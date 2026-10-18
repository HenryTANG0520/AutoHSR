import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_experience import experience_target,buy_experience
from autohsr.currency_wars_flow import run_flow
from autohsr.models import AutomationError,InputInterrupted,Token
from autohsr.tests import test_currency_wars_node as node_helpers
from autohsr.tests.test_currency_wars_node import prepared


def xp(level=3,gold=12,experience=(0,4),price=4):
    s=prepared()
    rois=((.125,.815,.185,.87),(.13,.865,.18,.9),(.851,.829,.87,.868))
    s.tokens=[t for t in s.tokens if not any(t.within(r) for r in rois)]
    s.tokens += [Token(f'Lv.{level}',.99,(.13,.82,.17,.85)),
                 Token(f'{experience[0]}/{experience[1]}',.99,(.14,.87,.17,.89)),
                 Token(str(gold),.99,(.855,.84,.865,.86)),Token(str(price),.99,(.16,.91,.17,.93))]
    return s


class ExperienceTests(TestCase):
    def test_animation_frame_is_observed_again_without_another_purchase(self):
        with tempfile.TemporaryDirectory() as directory:
            before=xp()
            flash=xp(0,8,(0,6))
            final=xp(4,8,(0,6))
            c=node_helpers.NodeWorkflowTests().context(directory,[flash,final])
            c.last_scene=before
            c.currency_buy_experience=Mock()
            data=dict(actions=[])
            self.assertTrue(buy_experience(c,before,data,lambda:None))
            c.currency_buy_experience.assert_called_once()
            self.assertEqual([o['status'] for o in data['actions'][0]['observations']],['unknown','verified'])

    def test_purchase_requires_current_price_funds_and_unobscured_fields(self):
        experience_target(xp())
        for s in (xp(gold=3),xp(price=3),xp(price=5)):
            with self.assertRaises(AutomationError):
                experience_target(s)
        s=xp()
        s.tokens += [Token('5',.99,(.16,.91,.17,.93))]
        with self.assertRaises(AutomationError):
            experience_target(s)

    def test_exact_spend_and_gain_required_and_ambiguous_result_not_retried(self):
        for after,expected in ((xp(4,8,(0,6)),True),(xp(4,7,(0,6)),False),(xp(),False)):
            with tempfile.TemporaryDirectory() as directory:
                before=xp()
                c=node_helpers.NodeWorkflowTests().context(directory,[after])
                c.last_scene=before
                c.currency_buy_experience=Mock()
                data=dict(actions=[])
                with patch('autohsr.currency_wars_experience.time',SimpleNamespace(monotonic=Mock(side_effect=[0,9]))):
                    self.assertEqual(buy_experience(c,before,data,lambda:None),expected)
                c.currency_buy_experience.assert_called_once()
                self.assertEqual(data['actions'][0]['gold_before'],12)

    def test_flow_stops_buying_at_target_and_default_target_does_not_spend(self):
        for target,expected in ((4,1),(0,0),(3,0)):
            with tempfile.TemporaryDirectory() as directory:
                before=xp();before.image[:]=0
                after=xp(4,8,(0,6));after.image[:]=0
                c=node_helpers.NodeWorkflowTests().context(directory,[before,after,after])
                c.runner.currency_target_level=target
                def purchase(scene):
                    data=json.loads((Path(directory)/'currency-flow.json').read_text(encoding='utf-8'))
                    self.assertEqual(data['actions'][-1]['status'],'pending')
                c.currency_buy_experience=Mock(side_effect=purchase)
                run_flow(c)
                self.assertEqual(c.currency_buy_experience.call_count,expected)
                c.currency_start_node.assert_not_called()

    def test_interrupted_purchase_keeps_pending_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            before=xp()
            c=node_helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=before
            c.currency_buy_experience=Mock(side_effect=InputInterrupted('paused'))
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                buy_experience(c,before,data,lambda:None)
            c.currency_buy_experience.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'pending')

    def test_context_requires_explicit_higher_target_and_scoped_operation(self):
        window=Mock()
        for operation,target in (('daily',4),('currency_wars',4),('currency_wars_flow_test',0),('currency_wars_flow_test',3)):
            c=Context(Runner(Settings(),operation=operation,currency_target_level=target),window,Mock())
            c.last_scene=xp()
            with self.assertRaises(AutomationError):
                c.currency_buy_experience(c.last_scene)
        window.click.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test',currency_target_level=4),window,Mock())
        c.last_scene=xp();c.sleep=Mock()
        c.currency_buy_experience(c.last_scene)
        self.assertIsNone(c.last_scene)
        window.click.assert_called_once()
