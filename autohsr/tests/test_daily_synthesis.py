"""Single-item synthesis, card binding and durable no-replay regressions."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import daily_synthesis as synthesis
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, Scene
from autohsr.recovery import reward_only_settings
from autohsr.workflows import DailyWorkflow
from autohsr.vision import Vision
from autohsr.tests.test_core import FakeContext, token


def card(progress='0/1'):
    return Scene([token('星际和平指南', .09, .04), token('每日实训', .09, .08),
        token('进度'+progress, .53, .40), token('使用1次「万能合成', .566, .46),
        token('机」', .518, .49), token('+100', .577, .65), token('前往', .576, .767),
        token('UID:101688852', .1, .97)])


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
                      before_holding=299, before_materials=[(301, 1), (397, 1)])
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
