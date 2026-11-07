"""Single-item synthesis, card binding and durable no-replay regressions."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import daily_synthesis as synthesis
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, RunReport, Scene, Token
from autohsr.recovery import reward_only_settings
from autohsr.workflows import DailyWorkflow
from autohsr.vision import Vision
from autohsr.tests.test_core import FakeContext, token


def card(progress='0/1'):
    # Card-only OCR geometry from 20261025_224808_077674/225211_030039_daily_partial.png.
    return Scene([token('星际和平指南', .09, .04), token('每日实训', .09, .08),
        Token('进度'+progress, .9968, (.50469, .38889, .55885, .41389)),
        Token('使用1次「万能合成', .9918, (.50781, .44537, .62604, .47315)),
        Token('机」', .8950, (.50625, .47500, .53021, .50463)),
        Token('+100', .9988, (.55729, .63704, .59948, .67037)),
        Token('前往', .9999, (.56250, .75185, .59062, .77963)),
        token('UID:101688852', .1, .97)], captured_at=time.monotonic())


def snack(holding=299, quantity=1, materials=(301, 397), name=synthesis.RECIPE):
    return Scene([token('合成', .065, .048), token('消耗品合成', .08, .072),
        token(name, .572, .17), token('所需材料', .617, .537),
        token('当前持有：'+str(holding), .44, .477), token('合成数量：'+str(quantity), .616, .784),
        token(str(materials[0])+'/1', .57, .685), token(str(materials[1])+'/1', .66, .685),
        token('合成', .617, .911), token('UID:101688852', .1, .97)])


def confirm(quantity=1, name=synthesis.RECIPE):
    return Scene([token('确认合成', .5, .357),
        token(f'确认消耗以上物品进行合成{name}×{quantity}吗？', .5, .567),
        token('取消', .4, .649), token('确认', .61, .649), token('UID:101688852', .1, .97)])


class SynthesisContext(FakeContext):
    def click(self, scene, target, *, du_intent):
        synthesis.guard_click(scene, target, du_intent, self.report.daily_synthesis)
        return super().click(scene, target)


class DailySynthesisCliTests(TestCase):
    def test_daily_and_plan_pass_temporary_switch_to_runner(self):
        from autohsr.__main__ import main

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for mode, factory_name in (('--run', 'autohsr.app.Runner'), ('--plan', 'autohsr.plan_runner.PlanRunner')):
                for saved, flag, expected in ((True, None, True), (False, None, False),
                                              (True, '--no-daily-synthesis', False), (False, '--daily-synthesis', True)):
                    with self.subTest(mode=mode, saved=saved, flag=flag):
                        Settings(daily_synthesis=saved, assignments=False, battle=False, daily=True).save(path)
                        before = path.read_bytes()
                        args = [mode, '--config', str(path)] + ([flag] if flag else [])
                        with patch(factory_name) as runner, redirect_stdout(io.StringIO()):
                            runner.return_value.run.return_value = RunReport(status='success')
                            self.assertEqual(main(args), 0)
                        selected = runner.call_args.args[0]
                        self.assertIs(selected.daily_synthesis, expected)
                        self.assertFalse(selected.battle)
                        self.assertFalse(selected.assignments)
                        self.assertEqual(path.read_bytes(), before)

    def test_out_of_scope_and_conflicting_flags_fail_before_config_or_game_access(self):
        from autohsr.__main__ import main

        for flags in (['--daily-synthesis'], ['--check', '--no-daily-synthesis'],
                      ['--run', '--reward-only', '--daily-synthesis'], ['--run', '--reward-only', '--no-daily-synthesis'],
                      ['--plan', '--resume-weekly-currency', '--daily-synthesis'],
                      ['--run', '--daily-synthesis', '--no-daily-synthesis']):
            with self.subTest(flags=flags), patch.object(Settings, 'load') as load, \
                    patch('autohsr.app.Runner') as runner, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(flags)
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()
                runner.assert_not_called()

    def test_enabling_synthesis_cannot_select_daily_training(self):
        from autohsr.__main__ import main

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            Settings(daily=False).save(path)
            before = path.read_bytes()
            error = io.StringIO()
            with patch('autohsr.app.Runner') as runner, redirect_stderr(error):
                self.assertEqual(main(['--run', '--config', str(path), '--daily-synthesis']), 2)
            self.assertIn('需要开启每日实训', error.getvalue())
            runner.assert_not_called()
            self.assertEqual(path.read_bytes(), before)


class DailySynthesisTests(TestCase):
    def test_task_is_bound_to_its_own_go_progress_and_points(self):
        self.assertIsNotNone(synthesis.task_target(card()))
        self.assertIsNone(synthesis.task_target(card('1/1')))
        wrong = card()
        wrong.tokens = [t for t in wrong.tokens if t.text != '+100']+[token('+100', .75, .65)]
        self.assertIsNone(synthesis.task_target(wrong))

    def test_similar_other_task_does_not_authorize_synthesis(self):
        scene = card()
        scene.tokens = [t for t in scene.tokens if '万能' not in t.text]+[token('使用1次「助燃券」', .566, .46)]
        self.assertIsNone(synthesis.task_target(scene))

    def test_task_progress_is_an_exact_field_and_wrap_order_comes_from_geometry(self):
        scene = card('：0 ／ 1')
        scene.tokens.reverse()
        self.assertEqual(synthesis.task_target(scene).text, '前往')
        for progress in ('0/10', '0/1/2', '0/1?'):
            with self.subTest(progress=progress):
                self.assertIsNone(synthesis.task_target(card(progress)))

    def test_split_progress_keeps_one_contiguous_card_row(self):
        label = Token('进度', .99, (.505, .389, .527, .413))
        fraction = Token('0/1', .99, (.530, .390, .559, .413))
        split_fraction = [
            Token('0', .99, (.530, .390, .541, .413)),
            Token('／', .99, (.543, .391, .550, .412)),
            Token('1', .99, (.552, .390, .561, .413)),
        ]
        for parts in ([label, fraction], [label, *split_fraction],
                      [label, Token('0/', .99, (.530, .390, .550, .413)), split_fraction[-1]]):
            with self.subTest(parts=[t.text for t in parts]):
                scene = card()
                scene.tokens[2:3] = reversed(parts)
                self.assertEqual(synthesis.task_target(scene), scene.find('前往', exact=True))
        for parts in (
            [label, fraction, Token('0', .99, (.565, .39, .577, .413))],
            [label, label, fraction],
            [label, Token('0/1', .99, (.530, .419, .559, .427))],
            [label, Token('0/1', .99, (.555, .389, .583, .413))],
            [label, Token('0/1', .99, (.489, .389, .506, .413))],
            [label, fraction, token('已领取', .58, .766, score=.66)],
        ):
            with self.subTest(parts=[t.text for t in parts]):
                scene = card()
                scene.tokens[2:3] = parts
                self.assertIsNone(synthesis.task_target(scene))

    def test_split_task_title_keeps_the_separate_required_quantity(self):
        scene = card()
        scene.tokens[3:4] = [Token('次「万能合成', .99, (.551, .445, .626, .473)),
                             Token('使用', .99, (.508, .445, .533, .473)),
                             Token('1', .99, (.536, .445, .548, .473))]
        self.assertEqual(synthesis.task_target(scene), scene.find('前往', exact=True))
        scene.tokens[5] = Token('2', .99, (.536, .445, .548, .473))
        self.assertIsNone(synthesis.task_target(scene))

    def test_competing_same_card_fields_or_boundary_ocr_cannot_authorize_synthesis(self):
        for candidate in (token('进度1/1', .57, .406), token('+200', .56, .657),
                          token('已领取', .58, .766, score=.66), token('前往', .56, .772),
                          Token('进度0/1', .99, (.482, .389, .54, .416))):
            with self.subTest(candidate=candidate.text):
                scene = card()
                scene.tokens.append(candidate)
                self.assertIsNone(synthesis.task_target(scene))

    def test_only_one_whitelisted_snack_with_two_single_materials_is_ready(self):
        self.assertTrue(synthesis.ready(snack()))
        self.assertFalse(synthesis.ready(snack(quantity=2)))
        self.assertFalse(synthesis.ready(snack(materials=(0, 397))))
        self.assertFalse(synthesis.ready(snack(name='其他消耗品')))
        scene = snack()
        scene.tokens.append(token('购买', .8, .8))
        self.assertFalse(synthesis.ready(scene))

    def test_commit_requires_pending_record_and_exact_current_balances(self):
        scene = snack()
        record = dict(task_verified=True, status='pending', recipe=synthesis.RECIPE, quantity=1,
                      before_holding=299, before_materials=[(301, 1), (397, 1)], game_day=synthesis.game_day())
        target = scene.find('合成', (.5, .86, .75, .96), exact=True)
        synthesis.guard_click(scene, target, 'daily_synthesis_commit', record)
        for field, value in (('status', 'complete'), ('quantity', 2), ('before_holding', 298),
                             ('task_verified', False), ('before_materials', [(300, 1), (397, 1)])):
            with self.subTest(field=field):
                with self.assertRaises(AutomationError):
                    synthesis.guard_click(scene, target, 'daily_synthesis_commit', {**record, field:value})

    def test_one_craft_is_reconciled_by_inventory_and_both_material_balances(self):
        receipt = Scene([token('获得物品', .5, .15), token('奇巧零食', .5, .5),
                         token('点击空白处关闭', .5, .9), token('UID:101688852', .1, .97)])
        context = SynthesisContext([card(), snack(), receipt, snack(300, materials=(300, 396))])
        workflow = DailyWorkflow(context)
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.daily_synthesis.ROOT', Path(folder)):
            synthesis.complete_once(workflow, context.snapshot())
            journal = next((Path(folder)/'runs/daily-synthesis').glob('*.json'))
            stored = json.loads(journal.read_text('utf8'))
            self.assertEqual(stored['status'], 'complete')
            self.assertEqual(stored['after_holding'], 300)
            self.assertEqual(context.clicks.count('合成'), 1)
            self.assertEqual(context.report.stamina_spent, 0)
            with self.assertRaisesRegex(AutomationError, '已有合成记录'):
                synthesis.complete_once(workflow, card())
            self.assertEqual(context.clicks.count('合成'), 1)

    def test_confirmation_binds_the_exact_recipe_single_quantity_and_dialog(self):
        self.assertIsNotNone(synthesis.confirmation(confirm()))
        self.assertIsNone(synthesis.confirmation(confirm(quantity=2)))
        self.assertIsNone(synthesis.confirmation(confirm(name='其他消耗品')))
        scene = confirm()
        scene.tokens.append(token('购买', .5, .5))
        self.assertIsNone(synthesis.confirmation(scene))

    def test_compact_receipt_close_is_bound_to_the_snack_name(self):
        scene = Scene([token('获得物品', .5, .16), token('奇巧零食', .5, .576),
                       token('点击空白处关闭', .5, .731)])
        self.assertIsNotNone(synthesis.reward_close(scene))
        scene.tokens = [t for t in scene.tokens if t.text != '奇巧零食']
        self.assertIsNone(synthesis.reward_close(scene))

    def test_full_flow_confirms_once_and_verifies_balances(self):
        context = SynthesisContext([card(), snack(), confirm(), snack(300, materials=(300, 396))])
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.daily_synthesis.ROOT', Path(folder)):
            synthesis.complete_once(DailyWorkflow(context), context.snapshot())
            stored = json.loads(next((Path(folder)/'runs/daily-synthesis').glob('*.json')).read_text('utf8'))
            self.assertEqual(stored['status'], 'complete')
            self.assertTrue(stored['confirmation_sent'])
            self.assertEqual(context.clicks, ['前往', '合成', '确认'])

    def test_game_day_rollover_blocks_commit_or_confirmation_after_evidence_and_writes(self):
        old_day, new_day = '2026-11-04', '2026-11-05'
        for boundary in ('before_evidence', 'commit_write', 'confirmation_write'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as folder:
                context = SynthesisContext([card(), snack(), confirm(), snack(300, materials=(300, 396))])
                day = old_day
                original_evidence, original_save, original_fsync = context.evidence, synthesis._save, os.fsync

                def evidence(scene, label):
                    nonlocal day
                    if boundary == 'before_evidence' and label == 'daily_synthesis_before':
                        day = new_day
                    return original_evidence(scene, label)

                def fsync(handle):
                    nonlocal day
                    original_fsync(handle)
                    if boundary == 'commit_write':
                        day = new_day

                def save(record, path):
                    nonlocal day
                    original_save(record, path)
                    if boundary == 'confirmation_write' and record.get('confirmation_sent') is True:
                        day = new_day

                context.evidence = evidence
                with patch.object(synthesis, 'ROOT', Path(folder)), patch.object(synthesis, 'game_day', lambda _now=None: day), \
                     patch.object(synthesis, '_save', save), patch('os.fsync', fsync):
                    with self.assertRaisesRegex(AutomationError, '跨游戏日'):
                        synthesis.complete_once(DailyWorkflow(context), context.snapshot())
                files = list((Path(folder)/'runs/daily-synthesis').glob('*.json'))
                if boundary == 'before_evidence':
                    self.assertEqual(files, [])
                else:
                    self.assertEqual(len(files), 1)
                    stored = json.loads(files[0].read_text('utf8'))
                    self.assertEqual((stored['game_day'], stored['status']), (old_day, 'pending'))
                self.assertEqual(context.clicks, ['前往', '合成'] if boundary == 'confirmation_write' else ['前往'])

    def test_sent_confirmation_can_settle_its_original_game_day_after_rollover(self):
        receipt = Scene([token('获得物品', .5, .15), token('奇巧零食', .5, .5),
                         token('点击空白处关闭', .5, .9), token('UID:101688852', .1, .97)])
        context = SynthesisContext([card(), snack(), confirm(), receipt, snack(300, materials=(300, 396))])
        old_day = day = '2026-11-04'
        original_click = context.click

        def click(scene, target, *, du_intent):
            nonlocal day
            original_click(scene, target, du_intent=du_intent)
            if du_intent == 'daily_synthesis_confirm':
                day = '2026-11-05'

        context.click = click
        with tempfile.TemporaryDirectory() as folder, patch.object(synthesis, 'ROOT', Path(folder)), \
             patch.object(synthesis, 'game_day', lambda _now=None: day):
            synthesis.complete_once(DailyWorkflow(context), context.snapshot())
            path, = (Path(folder)/'runs/daily-synthesis').glob('*.json')
            stored = json.loads(path.read_text('utf8'))
            self.assertEqual((stored['game_day'], stored['status']), (old_day, 'complete'))
            self.assertEqual(stored['after_holding'], 300)
            self.assertEqual(context.clicks, ['前往', '合成', '确认', '点击空白处关闭'])

    def test_context_rechecks_frozen_day_after_logging_before_resource_click(self):
        for intent in ('daily_synthesis_commit', 'daily_synthesis_confirm'):
            with self.subTest(intent=intent):
                old_day = day = '2026-11-04'
                scene = confirm() if intent.endswith('confirm') else snack()
                target = synthesis.confirmation(scene) if intent.endswith('confirm') else scene.find(
                    '合成', (.5, .86, .75, .96), exact=True)
                scene.captured_at = time.monotonic()
                report = RunReport(operation='daily')
                record = dict(task_verified=True, status='pending', recipe=synthesis.RECIPE, quantity=1,
                              before_holding=299, before_materials=[(301, 1), (397, 1)],
                              game_day=old_day, confirmation_sent=True)
                report.daily_synthesis = record.copy()

                def log(*args):
                    nonlocal day
                    day = '2026-11-05'

                runner = SimpleNamespace(settings=Settings(daily_synthesis=True), report=report,
                                         input_epoch=0, checkpoint=Mock(), log=log)
                window = Mock()
                context = Context(runner, window, Mock())
                context.last_scene = scene
                context.sleep = Mock()
                with patch.object(synthesis, 'game_day', lambda _now=None: day):
                    with self.assertRaisesRegex(AutomationError, '跨游戏日'):
                        context.click(scene, target, du_intent=intent)
                self.assertEqual(day, '2026-11-05')
                window.click.assert_not_called()
                self.assertEqual(report.daily_synthesis, record)

    def test_task_card_must_be_captured_in_the_current_game_day(self):
        now = datetime(2026, 11, 5, 4, 0, 1, tzinfo=timezone(timedelta(hours=8)))
        game_day = synthesis.game_day
        for captured_at in (998.0, 999.5):
            with self.subTest(captured_at=captured_at), tempfile.TemporaryDirectory() as folder:
                source = card()
                source.captured_at = captured_at
                context = SynthesisContext([source, snack(), confirm(), snack(300, materials=(300, 396))])
                with patch.object(synthesis, 'ROOT', Path(folder)), patch.object(synthesis, 'datetime', wraps=datetime) as wall, \
                     patch.object(synthesis, 'monotonic', return_value=1000.0, create=True), \
                     patch.object(synthesis, 'game_day', lambda instant=None: game_day(now if instant is None else instant)):
                    wall.now.return_value = now
                    if captured_at == 998.0:
                        with self.assertRaisesRegex(AutomationError, '任务画面跨游戏日'):
                            synthesis.complete_once(DailyWorkflow(context), source)
                    else:
                        synthesis.complete_once(DailyWorkflow(context), source)
                journals = list((Path(folder)/'runs/daily-synthesis').glob('*.json'))
                if captured_at == 998.0:
                    self.assertEqual(context.clicks, [])
                    self.assertEqual(journals, [])
                else:
                    self.assertEqual(context.clicks, ['前往', '合成', '确认'])
                    self.assertEqual(len(journals), 1)
                    self.assertEqual(json.loads(journals[0].read_text('utf8'))['game_day'], '2026-11-05')

    def test_pending_modal_resumes_without_replaying_recipe_or_commit(self):
        context = SynthesisContext([confirm(), snack(300, materials=(300, 396))])
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.daily_synthesis.ROOT', Path(folder)):
            path = Path(folder)/'runs/daily-synthesis'/f'{synthesis.game_day()}-{synthesis.account_key(card())}.json'
            path.parent.mkdir(parents=True)
            record = dict(task_verified=True, status='pending', recipe=synthesis.RECIPE, quantity=1,
                before_holding=299, before_materials=[[301, 1], [397, 1]],
                game_day=synthesis.game_day(), account_key=synthesis.account_key(card()))
            path.write_text(json.dumps(record), encoding='utf8')
            self.assertTrue(synthesis.resume_pending(DailyWorkflow(context), context.snapshot()))
            self.assertEqual(context.clicks, ['确认'])
            self.assertEqual(json.loads(path.read_text('utf8'))['status'], 'complete')

    def test_pending_confirm_already_sent_is_not_replayed(self):
        context = SynthesisContext([confirm()])
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.daily_synthesis.ROOT', Path(folder)):
            path = Path(folder)/'runs/daily-synthesis'/f'{synthesis.game_day()}-{synthesis.account_key(card())}.json'
            path.parent.mkdir(parents=True)
            record = dict(task_verified=True, status='pending', recipe=synthesis.RECIPE, quantity=1,
                before_holding=299, before_materials=[[301, 1], [397, 1]], confirmation_sent=True,
                game_day=synthesis.game_day(), account_key=synthesis.account_key(card()))
            path.write_text(json.dumps(record), encoding='utf8')
            with self.assertRaisesRegex(AutomationError, '不重复确认'):
                synthesis.resume_pending(DailyWorkflow(context), context.snapshot())
            self.assertEqual(context.clicks, [])

    def test_pending_completed_inventory_only_reconciles_without_clicking(self):
        context = SynthesisContext([snack(300, materials=(300, 396))])
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.daily_synthesis.ROOT', Path(folder)):
            path = Path(folder)/'runs/daily-synthesis'/f'{synthesis.game_day()}-{synthesis.account_key(card())}.json'
            path.parent.mkdir(parents=True)
            record = dict(task_verified=True, status='pending', recipe=synthesis.RECIPE, quantity=1,
                before_holding=299, before_materials=[[301, 1], [397, 1]], confirmation_sent=True,
                game_day=synthesis.game_day(), account_key=synthesis.account_key(card()))
            path.write_text(json.dumps(record), encoding='utf8')
            self.assertTrue(synthesis.resume_pending(DailyWorkflow(context), context.snapshot()))
            self.assertEqual(context.clicks, [])
            self.assertEqual(json.loads(path.read_text('utf8'))['status'], 'complete')

    def test_interruption_preserves_intent_and_cannot_craft_again(self):
        context = SynthesisContext([card(), snack()])
        original = context.click
        def interrupted(scene, target, *, du_intent):
            if du_intent == 'daily_synthesis_commit':
                raise InputInterrupted('paused')
            return original(scene, target, du_intent=du_intent)
        context.click = interrupted
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.daily_synthesis.ROOT', Path(folder)):
            with self.assertRaises(InputInterrupted):
                synthesis.complete_once(DailyWorkflow(context), context.snapshot())
            stored = json.loads(next((Path(folder)/'runs/daily-synthesis').glob('*.json')).read_text('utf8'))
            self.assertEqual(stored['status'], 'pending')
            with self.assertRaisesRegex(AutomationError, '已有合成记录'):
                synthesis.complete_once(DailyWorkflow(context), card())

    def test_reward_only_never_crafts_or_changes_saved_preference(self):
        settings = Settings(daily_synthesis=True)
        self.assertFalse(reward_only_settings(settings).daily_synthesis)
        self.assertTrue(settings.daily_synthesis)

    def test_missing_quantity_is_read_from_its_own_field_without_guessing_one(self):
        import numpy as np
        scene = snack()
        scene.image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        scene.tokens = [t for t in scene.tokens if '合成数量' not in t.text]
        scene.tokens.append(token('合成数量：', .61, .784))
        vision = Vision.__new__(Vision)
        vision._read_field = Mock(return_value=token('1 ', .5, .5, .99))
        self.assertFalse(synthesis.ready(scene))
        vision.refine_daily_synthesis(scene)
        self.assertEqual(synthesis.quantity(scene), 1)
        self.assertTrue(synthesis.ready(scene))

    def test_known_multiple_quantity_is_never_overridden_by_a_field_retry(self):
        import numpy as np
        scene = snack(quantity=3)
        scene.image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        vision = Vision.__new__(Vision)
        vision._read_field = Mock(return_value=token('1', .5, .5, .99))
        vision.refine_daily_synthesis(scene)
        vision._read_field.assert_not_called()
        self.assertEqual(synthesis.quantity(scene), 3)
        self.assertFalse(synthesis.ready(scene))

    def test_conflicting_numeric_crops_cannot_authorize_a_craft(self):
        import numpy as np
        scene = snack()
        scene.image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        scene.tokens = [t for t in scene.tokens if '合成数量' not in t.text]
        scene.tokens.append(token('合成数量：', .61, .784))
        vision = Vision.__new__(Vision)
        vision._read_field = Mock(side_effect=[token('1', .5, .5), token('3', .5, .5), None, None])
        vision.refine_daily_synthesis(scene)
        self.assertIsNone(synthesis.quantity(scene))
        self.assertFalse(synthesis.ready(scene))
