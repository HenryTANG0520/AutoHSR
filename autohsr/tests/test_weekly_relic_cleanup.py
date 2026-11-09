"""Offline gates for opt-in weekly relic cleanup. No game window is opened."""
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from autohsr.config import Settings, SettingsError
from autohsr.models import AutomationError, Scene, Token
from autohsr.tests.test_core import token
from autohsr.weekly_plan import CHINA
from autohsr.weekly_relic_cleanup import (
    BAG_BREAK, BATCH_CONFIRM, BATCH_TITLE, BREAK_TITLE, CANCEL_BAND, CLEAR_RULES,
    DECOMPOSE_BODY, DECOMPOSE_CONFIRM, DECOMPOSE_TITLE, DISCARDED_RULE, FOUR_STAR,
    PROTECT_LABEL, PROTECT_STATE, QUICK_BUTTON, QUICK_CONFIRM, QUICK_TITLE,
    REWARD_BODY, REWARD_CLOSE, REWARD_TITLE, SALVAGE_BREAK, SALVAGE_COUNT,
    SMART_BUTTON, SMART_CONFIRM, SMART_COUNT, SMART_TITLE, TAB_ROW, TITLE,
    UNMATCHED_RULE, ZERO_RULE, Cleanup, TimestampStore, bag_target, decision,
    guard_click, is_due, open_live_port, perform, unique_text,
)
from autohsr.weekly_relic_cleanup_cli import run as run_cli


NOW = datetime(2026, 11, 9, 10, 0, tzinfo=CHINA)


def at(text, roi, dx=0.0, dy=0.0, score=0.99):
    return token(text, (roi[0] + roi[2]) / 2 + dx, (roi[1] + roi[3]) / 2 + dy, score)


def salvage(count):
    return Scene([
        at('遗器分解', BREAK_TITLE), at('快速选择', QUICK_BUTTON),
        at(f'{count}/500', SALVAGE_COUNT), at('分解', SALVAGE_BREAK),
        at('智能弃置', SMART_BUTTON),
    ])


def quick():
    return Scene([
        at('快速选择', QUICK_TITLE), at('4星及以下', FOUR_STAR),
        at('5星及以下', FOUR_STAR, dx=0.08), at('全选已弃置', DISCARDED_RULE),
        at('确认', QUICK_CONFIRM), at('取消', CANCEL_BAND),
    ])


def smart_dialog(count='0/500', state='已开启'):
    return Scene([
        at('待弃置遗器', SMART_TITLE), at('全部清除', CLEAR_RULES),
        at('不匹配任意推荐角色', UNMATCHED_RULE), at('0次', ZERO_RULE),
        at('弃置保护', PROTECT_LABEL), at(state, PROTECT_STATE),
        at(count, SMART_COUNT), at('确认', SMART_CONFIRM), at('取消', CANCEL_BAND),
    ])


def batch(count):
    return Scene([
        at('批量弃置', BATCH_TITLE), at(f'已标记{count}件', (0.30, 0.45, 0.70, 0.60)),
        at('确认弃置', BATCH_CONFIRM), at('取消', CANCEL_BAND),
    ])


def preview(count):
    return Scene([
        at('确认分解', DECOMPOSE_TITLE),
        at(f'将分解{count}件遗器，获得遗器残骸', DECOMPOSE_BODY),
        at('取消', CANCEL_BAND), at('确认', DECOMPOSE_CONFIRM),
    ])


def reward():
    return Scene([
        at('获得物品', REWARD_TITLE), at('遗器残骸', REWARD_BODY),
        at('点击空白处关闭', REWARD_CLOSE),
    ])


def phone_grid():
    """Token boxes from the tracked 4.6 phone grid, without decoding its screenshot."""
    def box(text, left, top, right, bottom):
        return Token(text, 0.99, (left, top, right, bottom))
    return Scene([
        box('开拓等级70', 0.6697916666666667, 0.23055555555555557, 0.7359375, 0.25555555555555554),
        box('指南', 0.6875, 0.725, 0.7109375, 0.75),
        box('编队', 0.6869791666666667, 0.8453703703703703, 0.7104166666666667, 0.8694444444444445),
        box('背包', 0.7546875, 0.8444444444444444, 0.778125, 0.8694444444444445),
        box('任务', 0.8229166666666666, 0.8453703703703703, 0.8453125, 0.8703703703703703),
    ])


def relic_bag():
    return Scene([
        at('背包', TITLE), at('遗器', TAB_ROW, dx=-0.10), at('光锥', TAB_ROW, dx=0.10),
        at('分解', BAG_BREAK),
    ])


def material_bag():
    return Scene([
        at('背包', TITLE), at('遗器', TAB_ROW, dx=-0.10), at('光锥', TAB_ROW, dx=0.10),
    ])


class ScriptedPort:
    def __init__(self, scenes):
        self.scenes = list(scenes)
        self.index = 0
        self.clicks = []
        self.keys = []
        self.homes = 0

    def scene(self):
        return self.scenes[self.index]

    def click(self, scene, target, intent):
        if scene is not self.scene():
            raise AssertionError('stale scene')
        self.clicks.append((intent, target.text))
        self.index = min(self.index + 1, len(self.scenes) - 1)

    def press_escape(self):
        self.keys.append('esc')
        self.index = min(self.index + 1, len(self.scenes) - 1)

    def return_home(self):
        self.homes += 1


def enabled(**changes):
    values = dict(break_down_level_four_relicset=True, weekly_relic_cleanup_day_of_week=1,
                  weekly_relic_smart_discard_enable=False)
    values.update(changes)
    return Settings(**values)


class ScheduleAndConfigTests(TestCase):
    def test_defaults_are_off_and_absent_from_the_completion_ledger(self):
        settings = Settings()
        self.assertFalse(settings.break_down_level_four_relicset)
        self.assertFalse(settings.weekly_relic_smart_discard_enable)
        self.assertEqual(settings.weekly_relic_cleanup_day_of_week, 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            settings.save(path)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertFalse(saved['break_down_level_four_relicset'])
            self.assertNotIn('weekly_relic_cleanup_timestamp', saved)
            loaded = Settings.load(path)
            self.assertFalse(loaded.weekly_relic_smart_discard_enable)

    def test_invalid_switches_and_weekday_fail_before_a_run(self):
        with self.assertRaises(SettingsError) as caught:
            Settings(break_down_level_four_relicset=1).validate('save')
        self.assertEqual(caught.exception.field, 'break_down_level_four_relicset')
        for day in (0, 8, True):
            with self.subTest(day=day):
                with self.assertRaises(SettingsError) as caught:
                    Settings(weekly_relic_cleanup_day_of_week=day).validate('save')
                self.assertEqual(caught.exception.field, 'weekly_relic_cleanup_day_of_week')

    def test_due_follows_the_game_week_refresh_and_previous_timestamp(self):
        self.assertTrue(is_due(NOW, 1, 0))
        self.assertFalse(is_due(NOW, 5, 0))
        same_week = int(datetime(2026, 11, 9, 5, tzinfo=CHINA).timestamp())
        self.assertFalse(is_due(NOW, 1, same_week))
        early = datetime(2026, 11, 9, 3, 30, tzinfo=CHINA)
        self.assertTrue(is_due(early, 1, 0))
        previous = int(datetime(2026, 11, 2, 12, tzinfo=CHINA).timestamp())
        self.assertFalse(is_due(early, 1, previous))
        self.assertFalse(is_due(datetime(2026, 11, 11, 10, tzinfo=CHINA), 5, 0))

    def test_disabled_not_due_and_not_invoked_skip_without_a_port_or_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimestampStore(Path(folder) / 'weekly-relic-cleanup.json')
            factory = Mock(side_effect=AssertionError('不应打开画面'))
            skipped = perform(enabled(), store, NOW, invoked=False, port_factory=factory)
            self.assertEqual(skipped['reason'], 'not_invoked')
            disabled = perform(Settings(), store, NOW, invoked=True, port_factory=factory)
            self.assertEqual(disabled['reason'], 'disabled')
            self.assertFalse(disabled['timestamp_written'])
            store.write(int(datetime(2026, 11, 9, 5, tzinfo=CHINA).timestamp()))
            before = store.write_count
            not_due = perform(enabled(), store, NOW, invoked=True, port_factory=factory)
            self.assertEqual(not_due['reason'], 'not_due')
            self.assertEqual(store.write_count, before)
            factory.assert_not_called()
            self.assertEqual(decision(enabled(), 0, NOW, invoked=False), 'not_invoked')


class RecognitionTests(TestCase):
    def test_daily_click_guard_rejects_the_bag_and_relic_page(self):
        from autohsr.policy import guard_click as daily_guard
        phone = phone_grid()
        bag = bag_target(phone)
        self.assertEqual(bag.text, '背包')
        with self.assertRaises(AutomationError):
            daily_guard(phone, bag)
        page = relic_bag()
        target = unique_text(page, '分解', BAG_BREAK)
        with self.assertRaises(AutomationError):
            daily_guard(page, target)
        guard_click(page, target, 'open_salvage', {})

    def test_bare_coordinate_and_generic_confirm_are_rejected(self):
        page = salvage(2)
        with self.assertRaisesRegex(AutomationError, '已识别的文字控件'):
            guard_click(page, (0.5, 0.9), 'request_decompose', {'pending_count': 2, 'marked': 0})
        confirm = unique_text(preview(9), '确认', DECOMPOSE_CONFIRM)
        with self.assertRaisesRegex(AutomationError, '未发送点击'):
            guard_click(preview(9), confirm, 'confirm_decompose', {'pending_count': 2, 'marked': 0})

    def test_loose_bag_word_is_not_an_entry(self):
        port = ScriptedPort([Scene([token('背包', 0.2, 0.2)])])
        cleanup = Cleanup(port, False)
        with self.assertRaisesRegex(AutomationError, '无法确认背包遗器入口'):
            cleanup.run()
        self.assertEqual(port.clicks, [])
        self.assertEqual(port.keys, [])
        self.assertEqual(port.homes, 1)


class FlowTests(TestCase):
    def test_four_star_selection_does_not_include_discarded_or_five_star(self):
        port = ScriptedPort([salvage(0), quick(), quick(), salvage(2)])
        cleanup = Cleanup(port, False)
        self.assertEqual(cleanup.select_for_salvage(False), 2)
        self.assertEqual([text for _, text in port.clicks], ['快速选择', '4星及以下', '确认'])
        self.assertNotIn('全选已弃置', [text for _, text in port.clicks])
        self.assertNotIn('5星及以下', [text for _, text in port.clicks])

    def test_smart_discard_order_confirms_protection_without_toggling_the_action(self):
        port = ScriptedPort([salvage(0), smart_dialog(), smart_dialog(), smart_dialog(),
                             smart_dialog(count='0/500'), salvage(0)])
        cleanup = Cleanup(port, True)
        self.assertEqual(cleanup.mark_smart_discard(), 0)
        self.assertEqual([text for _, text in port.clicks],
                         ['智能弃置', '全部清除', '不匹配任意推荐角色', '0次'])
        self.assertEqual(port.keys, ['esc'])

        marked = ScriptedPort([salvage(0), smart_dialog(count='2/500'), smart_dialog(count='2/500'),
                               smart_dialog(count='2/500'), smart_dialog(count='2/500'), batch(2), salvage(0)])
        self.assertEqual(Cleanup(marked, True).mark_smart_discard(), 2)
        self.assertEqual([text for _, text in marked.clicks],
                         ['智能弃置', '全部清除', '不匹配任意推荐角色', '0次', '确认', '确认弃置'])
        self.assertEqual(marked.keys, [])

    def test_protection_must_be_on_before_discard_and_aborts_after_one_toggle(self):
        scenes = [salvage(0)] + [smart_dialog(state='未开启')] * 5
        port = ScriptedPort(scenes)
        cleanup = Cleanup(port, True)
        with self.assertRaisesRegex(AutomationError, '弃置保护已开启'):
            cleanup.mark_smart_discard()
        self.assertEqual([text for _, text in port.clicks],
                         ['智能弃置', '全部清除', '不匹配任意推荐角色', '0次', '未开启'])
        self.assertNotIn('确认', [text for _, text in port.clicks])

    def test_smart_quick_select_adds_discarded_items_before_four_star(self):
        port = ScriptedPort([salvage(0), quick(), quick(), quick(), salvage(2)])
        self.assertEqual(Cleanup(port, True).select_for_salvage(True), 2)
        self.assertEqual([text for _, text in port.clicks],
                         ['快速选择', '全选已弃置', '4星及以下', '确认'])

    def test_four_star_run_from_the_relic_bag_decomposes_once(self):
        port = ScriptedPort([
            relic_bag(), salvage(0), quick(), quick(), salvage(2), preview(2), reward(), salvage(0),
        ])
        cleanup = Cleanup(port, False)
        cleanup.mark_smart_discard = Mock(side_effect=AssertionError('四星路径不应智能弃置'))
        self.assertTrue(cleanup.run())
        self.assertEqual([intent for intent, _ in port.clicks], [
            'open_salvage', 'open_quick_select', 'select_four_star', 'confirm_quick_select',
            'request_decompose', 'confirm_decompose', 'close_reward'])
        self.assertEqual(cleanup.decompose_confirmed, 1)
        self.assertEqual(port.homes, 1)
        self.assertEqual(port.keys, ['esc'])

    def test_phone_entry_reaches_the_relic_bag_before_an_empty_cleanup(self):
        port = ScriptedPort([
            phone_grid(), material_bag(), relic_bag(), salvage(0), quick(), quick(), salvage(0),
        ])
        cleanup = Cleanup(port, False)
        self.assertTrue(cleanup.run())
        self.assertEqual([text for _, text in port.clicks[:3]], ['背包', '遗器', '分解'])
        self.assertEqual(cleanup.decompose_confirmed, 0)
        self.assertEqual(port.homes, 1)

    def test_shortfall_aborts_before_decomposition_and_still_exits(self):
        port = ScriptedPort([
            salvage(0), smart_dialog(count='2/500'), smart_dialog(count='2/500'),
            smart_dialog(count='2/500'), smart_dialog(count='2/500'), batch(2), salvage(0),
            quick(), quick(), quick(), salvage(1),
        ])
        cleanup = Cleanup(port, True)
        with self.assertRaisesRegex(AutomationError, '少于智能弃置数量：1 < 2'):
            cleanup.run()
        intents = [intent for intent, _ in port.clicks]
        self.assertNotIn('request_decompose', intents)
        self.assertNotIn('confirm_decompose', intents)
        self.assertEqual(cleanup.decompose_confirmed, 0)
        self.assertIn('esc', port.keys)
        self.assertEqual(port.homes, 1)

    def test_zero_selected_is_also_a_shortfall_when_items_were_marked(self):
        port = ScriptedPort([
            salvage(0), smart_dialog(count='2/500'), smart_dialog(count='2/500'),
            smart_dialog(count='2/500'), smart_dialog(count='2/500'), batch(2), salvage(0),
            quick(), quick(), quick(), salvage(0),
        ])
        with self.assertRaisesRegex(AutomationError, '少于智能弃置数量：0 < 2'):
            Cleanup(port, True).run()
        self.assertNotIn('confirm_decompose', [intent for intent, _ in port.clicks])
        self.assertEqual(port.homes, 1)

    def test_preview_mismatch_does_not_confirm_decomposition(self):
        port = ScriptedPort([salvage(0), quick(), quick(), salvage(2), preview(9)])
        cleanup = Cleanup(port, False)
        with self.assertRaisesRegex(AutomationError, '未分解'):
            cleanup.run()
        self.assertNotIn('confirm_decompose', [intent for intent, _ in port.clicks])
        self.assertEqual(cleanup.decompose_confirmed, 0)
        self.assertEqual(port.homes, 1)

    def test_ocr_failure_never_decomposes_and_still_returns_home(self):
        port = ScriptedPort([Scene([token('未知页面', 0.4, 0.4)])])
        cleanup = Cleanup(port, False)
        with self.assertRaisesRegex(AutomationError, '无法确认背包遗器入口'):
            cleanup.run()
        self.assertEqual(port.clicks, [])
        self.assertEqual(port.keys, [])
        self.assertEqual(cleanup.decompose_confirmed, 0)
        self.assertEqual(port.homes, 1)

    def test_existing_selection_and_unreadable_count_stop_before_decomposition(self):
        port = ScriptedPort([salvage(0)])
        cleanup = Cleanup(port, False)
        cleanup.enter = lambda: None
        cleanup.salvage_count = lambda: 3
        cleanup.decompose = Mock()
        with self.assertRaisesRegex(AutomationError, '已有其他选中的遗器'):
            cleanup.run()
        cleanup.decompose.assert_not_called()
        self.assertEqual(port.homes, 1)

    def test_full_batch_is_followed_by_an_empty_check(self):
        port = ScriptedPort([salvage(0)])
        cleanup = Cleanup(port, True)
        cleanup.enter = lambda: None
        cleanup.salvage_count = lambda: 0
        cleanup.mark_smart_discard = Mock(side_effect=[4, 0])
        cleanup.select_for_salvage = Mock(side_effect=[500, 0])
        cleanup.decompose = Mock()
        self.assertTrue(cleanup.run())
        cleanup.decompose.assert_called_once_with(500)
        self.assertEqual(cleanup.mark_smart_discard.call_count, 2)

    def test_seven_full_batches_do_not_count_as_completion(self):
        port = ScriptedPort([salvage(0)])
        cleanup = Cleanup(port, False)
        cleanup.enter = lambda: None
        cleanup.salvage_count = lambda: 0
        cleanup.select_for_salvage = Mock(return_value=500)
        cleanup.decompose = Mock()
        with self.assertRaisesRegex(AutomationError, '连续七批'):
            cleanup.run()
        self.assertEqual(cleanup.decompose.call_count, 7)


class TimestampTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TimestampStore(Path(self.tmp.name) / 'weekly-relic-cleanup.json')
        self.addCleanup(self.tmp.cleanup)

    def _perform(self, port, **changes):
        return perform(enabled(**changes), self.store, NOW, invoked=True, port_factory=lambda settings: port)

    def test_success_writes_the_timestamp_once_and_the_same_week_skips(self):
        port = ScriptedPort([
            relic_bag(), salvage(0), quick(), quick(), salvage(2), preview(2), reward(), salvage(0),
        ])
        result = self._perform(port)
        self.assertTrue(result['timestamp_written'])
        self.assertEqual(result['weekly_relic_cleanup_timestamp'], int(NOW.timestamp()))
        self.assertEqual(self.store.write_count, 1)
        self.assertEqual(self.store.read(), int(NOW.timestamp()))
        again = self._perform(ScriptedPort([salvage(0)]))
        self.assertEqual(again['reason'], 'not_due')
        self.assertFalse(again['timestamp_written'])
        self.assertEqual(self.store.write_count, 1)

    def test_empty_success_still_records_one_completion(self):
        port = ScriptedPort([salvage(0), quick(), quick(), salvage(0)])
        result = self._perform(port)
        self.assertEqual(result['decompose_confirmed'], 0)
        self.assertEqual(self.store.write_count, 1)

    def test_shortfall_ocr_and_preview_failures_do_not_write(self):
        cases = [
            ScriptedPort([
                salvage(0), smart_dialog(count='2/500'), smart_dialog(count='2/500'),
                smart_dialog(count='2/500'), smart_dialog(count='2/500'), batch(2), salvage(0),
                quick(), quick(), quick(), salvage(1),
            ]),
            ScriptedPort([Scene([token('未知页面', 0.4, 0.4)])]),
            ScriptedPort([salvage(0), quick(), quick(), salvage(2), preview(9)]),
        ]
        flags = [{}, {}, {}]
        flags[0] = dict(weekly_relic_smart_discard_enable=True)
        for port, changes in zip(cases, flags):
            with self.subTest(changes=changes):
                with self.assertRaises(AutomationError):
                    self._perform(port, **changes)
                self.assertFalse(self.store.path.exists())
                self.assertEqual(self.store.write_count, 0)

    def test_feedback_failure_after_confirm_does_not_write(self):
        port = ScriptedPort([salvage(0), quick(), quick(), salvage(2), preview(2), Scene([token('加载中', 0.5, 0.5)])])
        with self.assertRaisesRegex(AutomationError, '未核实'):
            self._perform(port)
        self.assertIn('confirm_decompose', [intent for intent, _ in port.clicks])
        self.assertFalse(self.store.path.exists())

    def test_corrupt_ledger_blocks_an_enabled_run_without_replacement(self):
        self.store.path.write_text('{', encoding='utf-8')
        original = self.store.path.read_bytes()
        with self.assertRaisesRegex(AutomationError, '无法核对'):
            self._perform(ScriptedPort([salvage(0)]))
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.write_count, 0)


class EntryTests(TestCase):
    def test_command_is_exclusive_and_daily_plan_never_reference_it(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('app.py', 'workflows.py', 'plan_runner.py'):
            text = (root / name).read_text(encoding='utf-8')
            self.assertNotIn('weekly_relic', text)
            self.assertNotIn('break_down_level_four', text)
        source = (root / '__main__.py').read_text(encoding='utf-8')
        flag = source.index("mode.add_argument('--weekly-relic-cleanup'")
        self.assertLess(flag, source.index('mode.add_argument("--run"'))
        self.assertLess(flag, source.index('mode.add_argument("--plan"'))
        self.assertLess(source.index('if args.weekly_relic_cleanup:'), source.index('runner = Runner'))
        self.assertIn('不随 --run 或 --plan', source)
        def reject(message):
            raise SystemExit(2)
        with self.assertRaises(SystemExit) as caught:
            run_cli(SimpleNamespace(config=None, game_path=None),
                    ['--weekly-relic-cleanup', '--run'], SimpleNamespace(error=reject))
        self.assertEqual(caught.exception.code, 2)

    def test_cli_skips_when_disabled_and_refuses_to_open_the_game_when_due(self):
        import inspect
        from autohsr import weekly_relic_cleanup as cleanup
        self.assertNotIn('find_game', inspect.getsource(cleanup.open_live_port))
        self.assertNotIn('launch', inspect.getsource(cleanup.open_live_port))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            Settings(assignments=False, battle=False, daily=False).save(path)
            with redirect_stdout(io.StringIO()) as output:
                code = run_cli(SimpleNamespace(config=path, game_path=None),
                               ['--weekly-relic-cleanup', '--config', str(path)],
                               SimpleNamespace(error=self.fail),
                               store_path=Path(folder) / 'weekly-relic-cleanup.json')
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())['reason'], 'disabled')
            enabled().save(path)
            with redirect_stdout(io.StringIO()) as output:
                code = run_cli(SimpleNamespace(config=path, game_path=None),
                               ['--weekly-relic-cleanup', '--config', str(path)],
                               SimpleNamespace(error=self.fail), now=NOW,
                               store_path=Path(folder) / 'weekly-relic-cleanup.json')
            self.assertEqual(code, 1)
            body = json.loads(output.getvalue())
            self.assertFalse(body['timestamp_written'])
            self.assertIn('未启动游戏', body['error'])
            self.assertFalse((Path(folder) / 'weekly-relic-cleanup.json').exists())
            with self.assertRaisesRegex(AutomationError, '未启动游戏'):
                open_live_port(enabled())

    def test_cli_success_uses_the_injected_port_and_writes_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            enabled().save(path)
            ledger = Path(folder) / 'weekly-relic-cleanup.json'
            port = ScriptedPort([salvage(0), quick(), quick(), salvage(0)])
            with redirect_stdout(io.StringIO()) as output:
                code = run_cli(SimpleNamespace(config=path, game_path=None),
                               ['--weekly-relic-cleanup', '--config', str(path)],
                               SimpleNamespace(error=self.fail), now=NOW, store_path=ledger,
                               port_factory=lambda settings: port)
            self.assertEqual(code, 0)
            body = json.loads(output.getvalue())
            self.assertTrue(body['timestamp_written'])
            self.assertEqual(json.loads(ledger.read_text(encoding='utf-8'))['weekly_relic_cleanup_timestamp'],
                             int(NOW.timestamp()))
            self.assertEqual(port.homes, 1)
