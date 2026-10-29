"""Small visual noise retains a read identity only through its own close receipt."""
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_appearance import appearance,same_appearance
from autohsr.currency_wars_collector import collected_snapshot,first_unit_probe,record_matches,roster_cells
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_collection import board_feedback,retained
from autohsr.currency_wars_standard_deployment import standard_deployment
from autohsr.currency_wars_standard_flow import _preparation_probe,run_standard
from autohsr.models import Stopped
from autohsr.tests import test_currency_wars_standard_collection as sources
from autohsr.tests import test_currency_wars_standard_deployment as deployment
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_trading as trading


def changed(scene, cells=None, *, amount=1):
    result=deepcopy(scene)
    for cell in cells or roster_cells(result):
        if cell.state=='occupied':
            crop=_crop(result.image,cell.roi)
            crop[:]=np.clip(crop.astype(int)+amount,0,255).astype(np.uint8)
    return result


def collect(folder, *, all_units=False, after=None, states=None):
    board,session=deployment.frame_and_session() if not all_units else trading.full_board_fixture()
    sources.uid(board)
    original=deepcopy(session['collection']['units'])
    cells=sorted((c for c in roster_cells(board) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot))
    if not all_units:cells=cells[:1]
    frames=[board];current=board
    for cell in cells:
        unit=original[cell.zone+':'+str(cell.slot)]['unit']
        panel=sources.uid(equipment.panel(unit,unit.get('equipment') or ()))
        current=changed(board,amount=1 if len(frames)%2 else -1) if after is None else after
        frames.append(panel)
        if cell.zone!='bench':frames.append(equipment.recommend(panel))
        frames.extend([current,current])
    session['collection']['units']={};session['collection']['complete']=False
    session['actions']=[];session.pop('strategy',None)
    c=trading.StandardTradingTests().context(folder,board,session,states or frames)
    reads=0;snapshot=c.snapshot
    def bounded():
        nonlocal reads
        reads+=1
        if reads>len(states or frames)+12:raise AssertionError('collection fixture exhausted: '+repr([
            (a['action'],a['status']) for a in c.currency_standard_session.data['actions']]))
        return snapshot()
    c.snapshot=bounded
    def stop():
        actions=getattr(getattr(c,'currency_standard_session',None),'data',{}).get('actions',[])
        if sum(a['action']=='close_standard_unit' and a['status']=='verified' for a in actions)==len(cells):raise Stopped('collection checked')
    c.checkpoint=stop
    with patch('autohsr.currency_wars_replay.save_sample'):
        try:run_standard(c)
        except Stopped:pass
        else:raise AssertionError('collection did not reach its close boundary')
    return board,current,StandardSession(c.currency_standard_session.path).data,c,original


class CollectionAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            cls.before,cls.after,cls.session,_,cls.original=collect(folder)
        cls.cell=next(c for c in roster_cells(cls.after) if c.state=='occupied')
        cls.key=cls.cell.zone+':'+str(cls.cell.slot)

    def test_formal_close_keeps_raw_hash_and_binds_current_signature(self):
        data=self.session;record=data['collection']['units'][self.key]
        self.assertNotEqual(record['signature'],record['inspection_signature'])
        self.assertEqual(record['inspection_signature'],data['actions'][0]['target'][3])
        self.assertEqual(record['signature'],self.cell.signature)
        self.assertEqual(record['signature_source'],data['actions'][1]['after'])
        self.assertTrue(retained(self.after,self.cell,record,data))

    def test_full_formal_sweep_does_not_reinspect_previous_noisy_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            before,after,data,c,original=collect(folder,all_units=True)
        self.assertEqual(c.window.click.call_count,2*len(original)+sum(not k.startswith('bench:') for k in original))
        self.assertEqual(len(data['collection']['units']),len(original))
        self.assertIsNone(_preparation_probe(after,.65,data['collection']['units'],data))
        data['collection']['complete']=True
        final=changed(before,amount=1)
        saved=deepcopy(data)
        result=collected_snapshot(final,data,0,'latest')
        self.assertTrue(result.roster_complete)
        self.assertEqual({u.name for u in result.roster},{r['unit']['name'] for r in original.values()})
        self.assertEqual(data,saved)
        self.assertNotIn('appearance',str(result.public_state()))
        self.assertNotIn('collection_receipt',str(result.public_state()))

    def test_probe_and_deployment_use_the_fresh_source_hash(self):
        data=deepcopy(self.session)
        for key,value in self.original.items():data['collection']['units'].setdefault(key,value)
        data['collection']['complete']=True
        latest=deepcopy(self.before)
        cell=next(c for c in roster_cells(latest) if c.zone+':'+str(c.slot)==self.key)
        crop=_crop(latest.image,cell.roi);crop[::7,::11]=np.clip(crop[::7,::11].astype(int)+1,0,255).astype(np.uint8)
        cells={c.zone+':'+str(c.slot):c for c in roster_cells(latest)}
        self.assertIsNone(first_unit_probe(latest,.65,data['collection']['units'],session=data))
        proposal=standard_deployment(latest,data)
        self.assertIsNotNone(proposal)
        plan,unit,_,payload=proposal
        self.assertEqual(payload[7],cells['bench:'+str(plan.source_slot)].signature)
        self.assertNotEqual(payload[7],data['collection']['units']['bench:'+str(plan.source_slot)]['signature'])

    def test_similar_crop_without_linked_receipt_is_not_identity(self):
        record=deepcopy(self.session['collection']['units'][self.key])
        latest=changed(self.before,amount=2);cell=next(c for c in roster_cells(latest) if c.zone+':'+str(c.slot)==self.key)
        self.assertTrue(same_appearance(appearance(self.after,self.cell.roi),appearance(latest,cell.roi)))
        for missing in ('collection_close_action_id','inspection_action_id','inspection_signature','signature_source','run_dir','source'):
            broken=deepcopy(record);broken.pop(missing)
            with self.subTest(missing=missing):self.assertFalse(retained(latest,cell,broken,self.session))
        self.assertFalse(record_matches(latest,cell,record))
        legacy=dict(record,appearance=appearance(latest,cell.roi));legacy.pop('collection_close_action_id')
        self.assertFalse(record_matches(latest,cell,legacy,self.session))

    def test_close_receipt_rejects_different_identity_slot_sources_or_epoch(self):
        for case in ('name','star','tier','equipment','traits','slot','profile_source','close_source','inspect_run','epoch','close_epoch','close_target','unknown','appearance','basis','run','close_id','inspect_id','bool_epoch'):
            data=deepcopy(self.session);record=data['collection']['units'][self.key];close=data['actions'][1]
            if case in ('name','star','tier','equipment','traits','slot'):
                record['unit'][case]={'name':'另一个角色','star':4,'tier':5,'equipment':['armor'],'traits':['新羁绊'],'slot':9}[case]
            elif case=='profile_source':record['source']='unrelated.png'
            elif case=='close_source':record['signature_source']='unrelated.png'
            elif case=='inspect_run':data['actions'][0]['inspection_run_dir']='old-run'
            elif case=='epoch':record['input_epoch']=1
            elif case=='close_epoch':close['input_epoch']=1
            elif case=='close_target':close['target'][2]=9
            elif case=='unknown':close['status']='unknown'
            elif case=='appearance':close['collection_receipt']['appearance']='e30='
            elif case=='basis':close['collection_receipt']['basis']['gold']+=1
            elif case=='close_id':close['id']=True
            elif case=='inspect_id':data['actions'][0]['id']=False
            elif case=='bool_epoch':close['input_epoch']=False
            else:data['account_verified_run']='old-run'
            with self.subTest(case=case):self.assertFalse(retained(self.after,self.cell,record,data))

    def test_new_identity_changing_or_unknown_inputs_invalidate_visual_retention(self):
        for name,status in (('deploy_standard_owned','verified'),('buy_standard_offer','verified'),('stage_standard_consumable','verified'),
                            ('inspect_standard_unit','unknown'),('inspect_standard_unit','pending')):
            data=deepcopy(self.session)
            data['actions'].append(dict(id=2,action=name,status=status,input_epoch=0,before='later.png',after='later-after.png'))
            with self.subTest(name=name,status=status):self.assertFalse(retained(self.after,self.cell,data['collection']['units'][self.key],data))

    def test_current_account_node_and_actual_changed_portrait_are_rejected(self):
        for case in ('account','node','portrait','brightness'):
            latest=deepcopy(self.after)
            if case=='account':sources.uid(latest,'200000000')
            elif case=='node':rewards.node(latest,'1-2')
            else:
                crop=_crop(latest.image,self.cell.roi)
                if case=='portrait':crop[:]=np.random.default_rng(44).integers(0,256,crop.shape,dtype=np.uint8)
                else:crop[:]=np.clip(crop.astype(int)+20,0,255).astype(np.uint8)
            cell=next(c for c in roster_cells(latest) if c.zone+':'+str(c.slot)==self.key)
            with self.subTest(case=case):self.assertFalse(retained(latest,cell,self.session['collection']['units'][self.key],self.session))

    def test_close_requires_original_resources_in_addition_to_portrait(self):
        data=deepcopy(self.session);data['actions'].pop();data['actions'].append(deepcopy(self.session['actions'][1]))
        data['actions'][1]['status']='pending'
        first=data['actions'][0]
        data['inspecting']=dict(zone=self.cell.zone,slot=self.cell.slot,node=self.cell.node,signature=first['target'][3],
            inspection_action_id=0,run_dir=data['collection']['run_dir'],input_epoch=0,before=first['before'],after=first['after'])
        from autohsr.currency_wars_standard_flow import StandardAction
        choice=StandardAction('close_standard_unit','standard_collected_unit_board',None,payload=tuple(data['actions'][1]['target']))
        self.assertTrue(board_feedback(choice,self.after,session=data))
        for case in ('gold','hp','level','experience','deployment','shape'):
            broken=deepcopy(data);basis=broken['actions'][0]['collection_basis']
            basis[case]={'gold':99,'hp':1,'level':10,'experience':[3,7],'deployment':[0,9],'shape':[100,200,3]}[case]
            with self.subTest(case=case):self.assertFalse(board_feedback(choice,self.after,session=broken))

    def test_small_steps_cannot_accumulate_into_a_new_visual_identity(self):
        record=self.session['collection']['units'][self.key]
        for amount,expected in ((1,True),(2,True),(6,False)):
            latest=changed(self.before,amount=amount)
            cell=next(c for c in roster_cells(latest) if c.zone+':'+str(c.slot)==self.key)
            with self.subTest(amount=amount):self.assertEqual(retained(latest,cell,record,self.session),expected)
        self.assertEqual(record['signature'],self.cell.signature)

    def test_intent_read_and_receipt_write_failures_preserve_pending_without_replay(self):
        for boundary,clicks in (('inspect',0),('close',1),('receipt',2)):
            board,panel,session=sources.fixture();session['actions']=[];session.pop('inspecting')
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory() as folder:
                c=trading.StandardTradingTests().context(folder,board,session,[board,panel,board,board])
                persist=StandardSession.persist
                def fail(store):
                    actions=store.data.get('actions',[]);last=actions[-1] if actions else {}
                    if boundary=='inspect' and last.get('collection_appearance'):raise OSError('inspection source write failed')
                    if boundary=='close' and last.get('collection_read'):raise OSError('close source write failed')
                    if boundary=='receipt' and last.get('collection_receipt'):raise OSError('close receipt write failed')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',fail),self.assertRaises(OSError):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertNotIn('collection_receipt',saved['actions'][-1])
                self.assertFalse(saved['collection']['complete'])
                self.assertEqual(c.window.click.call_count,clicks)
                from autohsr.models import AutomationError
                with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual(c.window.click.call_count,clicks)


if __name__=='__main__':unittest.main()
