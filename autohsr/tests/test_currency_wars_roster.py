import json
from pathlib import Path
import tempfile
import time
from unittest import TestCase
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_roster import (candidate_at,validate_candidate,already_deployed,
    next_candidate,read_character,eligible_plan,deploy_candidate,CharacterProfile)
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.models import AutomationError,InputInterrupted,Scene,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_deployment import deployment_frame


def panel():
    data=json.loads((Path(__file__).parent/'fixtures/currency_wars_characters.json').read_text(encoding='utf-8'))
    s=Scene([Token(**t) for k,v in data.items() if k.startswith('154') for t in v['tokens']],captured_at=time.monotonic())
    s.tokens=[Token('1-1',t.score,t.box) if t.text=='2-1' else t for t in s.tokens]
    return s


class RosterTests(TestCase):
    def test_observed_name_and_position_are_read_together(self):
        self.assertEqual(read_character(panel()),CharacterProfile('阮梅',('back',),'1-1'))
        data=json.loads((Path(__file__).parent/'fixtures/currency_wars_characters.json').read_text(encoding='utf-8'))
        for key,value in data.items():
            profile=read_character(Scene([Token(**t) for t in value['tokens']]))
            self.assertEqual(profile.zones,('front','back') if key.startswith('140') else ('back',))
        scene=panel()
        scene.tokens=[t for t in scene.tokens if t.text!='阮·梅']
        with self.assertRaises(AutomationError):
            read_character(scene)

    def test_candidate_binds_node_and_source_portrait_and_position(self):
        scene=deployment_frame()
        candidate=candidate_at(scene,3)
        self.assertEqual(eligible_plan(scene,candidate,read_character(panel())).zone,'back')
        for changed in (CharacterProfile('阮梅',('front',),'2-1'),CharacterProfile('阮梅',(),'1-1')):
            with self.assertRaises(AutomationError):
                eligible_plan(scene,candidate,changed)
        _crop(scene.image,bench_face(3))[:]=0
        with self.assertRaises(AutomationError):
            validate_candidate(scene,candidate)

    def test_duplicate_on_field_is_skipped_and_item_not_treated_as_character(self):
        scene=deployment_frame()
        candidate=candidate_at(scene,3)
        self.assertFalse(already_deployed(scene,candidate))
        scene.image[820:820+candidate.portrait.shape[0],675:675+candidate.portrait.shape[1]]=candidate.portrait
        self.assertTrue(already_deployed(scene,candidate))
        with self.assertRaises(AutomationError):
            next_candidate(scene)
        scene=deployment_frame()
        scene.tokens += [Token('开启',.99,(.34,.82,.37,.86))]
        with self.assertRaises(AutomationError):
            candidate_at(scene,3)

    def test_open_close_deploy_each_persist_before_input_and_verify_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            first=deployment_frame()
            candidate=candidate_at(first,3)
            c=helpers.NodeWorkflowTests().context(directory,[panel(),first,first])
            c.last_scene=first
            data=dict(actions=[])
            def persist():
                (Path(directory)/'flow.json').write_text(json.dumps(data),encoding='utf-8')
            def dispatch(*args):
                saved=json.loads((Path(directory)/'flow.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['actions'][-1]['status'],'pending')
            c.currency_open_bench=Mock(side_effect=dispatch)
            c.currency_close_character=Mock(side_effect=dispatch)
            c.currency_deploy_candidate=Mock(side_effect=dispatch)
            with patch('autohsr.currency_wars_roster.verify_bench_deployment',return_value=dict(status='verified')):
                self.assertTrue(deploy_candidate(c,first,candidate,data,persist))
            self.assertEqual([a['status'] for a in data['actions']],['verified']*3)
            c.currency_deploy_candidate.assert_called_once()

    def test_interruption_keeps_pending_without_close_or_drag(self):
        with tempfile.TemporaryDirectory() as directory:
            scene=deployment_frame()
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=scene
            c.currency_open_bench=Mock(side_effect=InputInterrupted('paused'))
            c.currency_close_character=Mock()
            c.currency_deploy_candidate=Mock()
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                deploy_candidate(c,scene,candidate_at(scene,3),data,lambda:None)
            self.assertEqual(data['actions'][0]['status'],'pending')
            c.currency_close_character.assert_not_called()
            c.currency_deploy_candidate.assert_not_called()

    def test_context_scope_and_one_use_drag_request(self):
        scene=deployment_frame()
        candidate=candidate_at(scene,3)
        profile=read_character(panel())
        window=Mock()
        for operation in ('daily','currency_wars','currency_wars_deploy_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=scene
            with self.assertRaises(AutomationError):
                c.currency_deploy_candidate(scene,candidate,profile)
        window.drag.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),window,Mock())
        c.last_scene=scene
        c.sleep=Mock()
        plan=eligible_plan(scene,candidate,profile)
        with self.assertRaises(AutomationError):
            c.drag(scene,plan.start,plan.end)
        c.currency_deploy_candidate(scene,candidate,profile)
        window.drag.assert_called_once()
        self.assertIsNone(c._currency_deploy_request)
        self.assertIsNone(c.last_scene)
