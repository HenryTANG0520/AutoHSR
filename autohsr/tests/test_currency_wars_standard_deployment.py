"""Owned-team selection, standard drag authority and conservative fact transfer."""
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_identity import account_key
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_deployment import choose_deployment, standard_deployment, deployment_feedback, transfer_collection
from autohsr.currency_wars_standard_flow import next_action, transition_ready
from autohsr.currency_wars_state import StrategySnapshot, UnitState
from autohsr.models import AutomationError, InputInterrupted, Token
from autohsr.tests.test_currency_wars_deployment import deployment_frame


def units():
    return (UnitState('砂金','bench',1,2,2,('公司','追击','护盾'),(),('front',)),
            UnitState('翡翠','bench',2,1,1,('公司','群攻'),(),('back',)),
            UnitState('乱破','bench',3,1,1,('巡海游侠','击破'),(),('front',)),
            UnitState('不死途','bench',4,1,2,('巡海游侠','追击'),(),('front','back')),
            UnitState('不死途','bench',5,1,2,('巡海游侠','追击'),(),('front','back')))


def frame_and_session():
    scene = deployment_frame(6)
    scene.tokens = [Token('0/3',t.score,t.box) if t.text=='5/6' else t for t in scene.tokens]
    scene.tokens.append(Token('UID:100000000',.99,(.01,.96,.1,.99)))
    for slot in range(1,6):
        crop = _crop(scene.image,bench_face(slot))
        crop[:] = np.random.default_rng(slot).integers(0,256,crop.shape,dtype=np.uint8)
    cells = {(c.zone,c.slot):c for c in roster_cells(scene)}
    records = {'bench:'+str(u.slot):dict(unit=asdict(u),signature=cells[('bench',u.slot)].signature,
                                       node=cells[('bench',u.slot)].node,source='profile.png') for u in units()}
    return scene, dict(status='active',start_verified=True,entry=dict(rank_verified=True),actions=[],
        account_key=account_key(scene),account_verified_run='run',account_verified_epoch=0,
        client=dict(version='4.6',verified_run='run',input_epoch=0,sha256='a'*64),rules_version='4.6',
        shop_observed_nodes=[cells[('bench',1)].node],
        collection=dict(run_dir='run',input_epoch=0,complete=True,units=records))


class StandardDeploymentTests(unittest.TestCase):
    def test_unique_owned_team_uses_star_position_and_tag_overlap(self):
        snapshot = StrategySnapshot(page='preparation',capacity=3,roster=units(),roster_complete=True,bench_occupied=5)
        selected = []
        for slot in range(3):
            unit,zone,score = choose_deployment(snapshot)
            selected.append((unit.name,zone))
            snapshot = replace(snapshot,roster=tuple(replace(u,zone=zone,slot=10+slot) if u==unit else u for u in snapshot.roster),
                               bench_occupied=4-slot)
        self.assertEqual(selected,[('砂金','front'),('翡翠','back'),('不死途','back')])
        self.assertIsNone(choose_deployment(snapshot))

    def test_unknown_roles_duplicates_and_not_enough_distinct_units_stop(self):
        for roster in ((replace(units()[0],eligible_zones=None),)+units()[1:],
                       (units()[3],units()[4]),
                       (replace(units()[0],zone='back'),)+units()[1:]):
            with self.assertRaises(AutomationError):
                choose_deployment(StrategySnapshot(page='preparation',capacity=3,roster=roster,roster_complete=True,
                                                  bench_occupied=sum(u.zone=='bench' for u in roster)))
        # A new, stronger name is considered without a fixed character-name list.
        roster=(replace(units()[0],name='任意前台',star=3),)+units()[1:]
        self.assertEqual(choose_deployment(StrategySnapshot(capacity=3,roster=roster,roster_complete=True,bench_occupied=5))[0].name,'任意前台')

    def test_current_roster_version_and_ledger_are_required(self):
        scene,session = frame_and_session()
        plan,unit,_,_ = standard_deployment(scene,session)
        self.assertEqual((unit.name,plan.source_slot,plan.zone,plan.target_slot),('砂金',1,'front',1))
        for mutation in ('portrait','epoch','ledger','version'):
            current,data = frame_and_session()
            if mutation=='portrait':
                _crop(current.image,bench_face(1))[:] = 100
            elif mutation=='epoch':
                data['account_verified_epoch']=1
            elif mutation=='ledger':
                data['actions']=[dict(action='purchase_standard_unit',status='unknown')]
            else:
                data['client']['version']='4.7'
            with self.assertRaises(AutomationError):
                standard_deployment(current,data)

    def test_front_move_verifies_identity_count_source_money_and_life(self):
        from autohsr.models import Scene
        before,session = frame_and_session()
        plan,_,_,_ = standard_deployment(before,session)
        after = Scene(list(before.tokens),before.image.copy(),before.geometry,before.captured_at)
        face = _crop(before.image,bench_face(plan.source_slot))
        h,w = face.shape[:2]
        x,y = round(plan.end[0]*2560)-w//2,480
        after.image[y:y+h,x:x+w]=face
        _crop(after.image,bench_face(plan.source_slot))[:] = (80,35,25)
        after.tokens=[Token('1/3',t.score,t.box) if t.text=='0/3' else t for t in after.tokens]
        self.assertEqual(deployment_feedback(before,after,plan)['status'],'verified')
        transfer_collection(session,before,after,plan,'after.png')
        self.assertNotIn('bench:1',session['collection']['units'])
        self.assertEqual(session['collection']['units']['front:1']['unit']['name'],'砂金')
        self.assertEqual(len(session['collection']['units']),5)
        # Count changes alone cannot prove that the right unit moved.
        after.image[y:y+h,x:x+w] = 100
        self.assertEqual(deployment_feedback(before,after,plan)['status'],'unknown')
        with self.assertRaises(AutomationError):
            transfer_collection(session,before,after,plan,'bad.png')

    def test_drag_dispatch_rechecks_durable_payload_and_interrupts_held_mouse(self):
        scene,data = frame_and_session()
        choice = next_action(scene,session=data)
        with tempfile.TemporaryDirectory() as folder:
            store = StandardSession(Path(folder)/'session.json')
            store.begin(folder,dict(rank_verified=True))
            store.data.update(data)
            action=store.pending(choice.intent,0,'before.png',choice.expected)
            action['target']=list(choice.payload)
            store.persist()
            c=Context(Runner(Settings(),operation='currency_wars_standard'),Mock(),Mock())
            c.currency_standard_session=store
            c.checkpoint,c.sleep=Mock(),Mock()
            def fresh():
                scene.captured_at=time.monotonic()
                c.last_scene=scene
            fresh()
            forged=replace(choice,payload=choice.payload[:-1]+('forged',))
            with self.assertRaises(AutomationError):
                c.currency_standard_input(scene,forged)
            c.window.drag.assert_not_called()
            c.currency_standard_input(scene,choice)
            c.window.drag.assert_called_once()
            c.window.click.assert_not_called()
            fresh()
            c.runner._pause.set()
            with self.assertRaises(InputInterrupted):
                c.currency_standard_input(scene,choice)


if __name__ == '__main__':
    unittest.main()
