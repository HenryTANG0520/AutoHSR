import tempfile
from unittest import TestCase
from unittest.mock import Mock

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_equipment import (battery_items,equipment_fields,equipment_slots,
    equipment_template,battery_plan,equip_battery,equipment_items,equipment_plan,available_slots)
from autohsr.models import AutomationError,InputInterrupted,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_sale import duplicate,sale_panel


def board():
    scene=duplicate()
    battery=equipment_template('battery')
    scene.image[300:360,2430:2490]=battery
    scene.image[610:670,2430:2490]=battery
    return scene


def equipped_panel(scene,equipped=False):
    s=sale_panel(scene)
    empty=equipment_template('empty_equipment')
    battery=equipment_template('battery')
    for x in (2195,2310,2420):
        s.image[1040:1130,x-45:x+45]=0
        s.image[1060:1110,x-27:x+23]=empty
    if equipped:
        s.image[1040:1130,2150:2240]=0
        s.image[1055:1115,2165:2225]=battery
    return s


class EquipmentTests(TestCase):
    def test_advanced_armor_requires_exact_item_empty_slot_and_recommended_role(self):
        scene=board()
        armor=equipment_template('hard_armor')
        scene.image[505:565,2320:2380]=armor
        field=equipment_fields(scene)[0]
        item=equipment_items(scene,'hard_armor')[0]
        self.assertEqual(equipment_plan(scene,field,item,equipped_panel(scene),'hard_armor'),(item,field.point))
        with self.assertRaises(AutomationError):
            equipment_plan(scene,field,battery_items(scene)[0],equipped_panel(scene),'hard_armor')
        self.assertEqual(equipment_plan(scene,field,item,equipped_panel(scene,True),'hard_armor'),(item,field.point))
        panel=equipped_panel(scene)
        panel.image[1040:1130,2150:2240]=0
        panel.image[1055:1115,2165:2225]=armor
        self.assertEqual(equipment_slots(panel),('hard_armor','empty','empty'))
        with self.assertRaises(AutomationError):
            equipment_items(scene,'unobserved_item')

    def test_energy_sail_preserves_other_slots_and_cannot_duplicate_or_overwrite(self):
        from types import SimpleNamespace
        self.assertTrue(available_slots(SimpleNamespace(name='花火'),('battery','hard_armor','empty'),'energy_sail'))
        self.assertFalse(available_slots(SimpleNamespace(name='三月七'),('battery','empty','empty'),'energy_sail'))
        self.assertFalse(available_slots(SimpleNamespace(name='花火'),('battery','energy_sail','empty'),'energy_sail'))
        self.assertFalse(available_slots(SimpleNamespace(name='花火'),('battery','armor','hard_armor'),'energy_sail'))
        self.assertFalse(available_slots(SimpleNamespace(name='花火'),('other','empty','empty'),'energy_sail'))
        self.assertFalse(available_slots(SimpleNamespace(name='花火'),('armor','empty','empty'),'armor'))

    def test_energy_sail_feedback_requires_retaining_sparkles_battery(self):
        def sparkle(scene,with_sail=False):
            panel=equipped_panel(scene,True)
            panel.tokens=[Token('花火',t.score,t.box) if t.text=='阮·梅' else t for t in panel.tokens]
            if with_sail:
                panel.image[1040:1130,2265:2355]=0
                panel.image[1055:1115,2280:2340]=equipment_template('energy_sail')
            return panel
        with tempfile.TemporaryDirectory() as directory:
            first=board()
            first.image[715:775,2320:2380]=equipment_template('energy_sail')
            field=equipment_fields(first)[0]
            item=equipment_items(first,'energy_sail')[0]
            after=board()
            before_panel=sparkle(first)
            after_panel=sparkle(after,True)
            self.assertEqual(equipment_slots(after_panel),('battery','energy_sail','empty'))
            c=helpers.NodeWorkflowTests().context(directory,[before_panel,first,after,after_panel,after])
            c.last_scene=first
            c.currency_open_field=Mock()
            c.currency_close_character=Mock()
            c.currency_equip_item=Mock()
            data=dict(actions=[])
            self.assertTrue(equip_battery(c,first,field,item,data,lambda:None,item_name='energy_sail'))
            self.assertEqual(data['actions'][2]['original_slots'],['battery','empty','empty'])
            self.assertEqual(data['actions'][2]['name'],'花火')
            self.assertEqual([a['status'] for a in data['actions']],['verified']*5)

    def test_advanced_armor_consumption_and_same_profile_are_both_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            first=board()
            first.image[505:565,2320:2380]=equipment_template('hard_armor')
            field=equipment_fields(first)[0]
            item=equipment_items(first,'hard_armor')[0]
            after=board()
            panel=equipped_panel(after)
            panel.image[1040:1130,2150:2240]=0
            panel.image[1055:1115,2165:2225]=equipment_template('hard_armor')
            c=helpers.NodeWorkflowTests().context(directory,[equipped_panel(first),first,after,panel,after])
            c.last_scene=first
            c.currency_open_field=Mock()
            c.currency_close_character=Mock()
            c.currency_equip_item=Mock()
            data=dict(actions=[])
            self.assertTrue(equip_battery(c,first,field,item,data,lambda:None,item_name='hard_armor'))
            c.currency_equip_item.assert_called_once()
            self.assertEqual(c.currency_equip_item.call_args.args[:3],(first,field,item))
            self.assertEqual(c.currency_equip_item.call_args.args[-1],'hard_armor')
            self.assertEqual([a['status'] for a in data['actions']],['verified']*5)

    def test_inventory_and_empty_slots_are_required_before_wearing(self):
        scene=board()
        self.assertEqual(len(battery_items(scene)),2)
        field=equipment_fields(scene)[0]
        self.assertEqual(field.zone,'back')
        self.assertEqual(equipment_slots(equipped_panel(scene)),('empty',)*3)
        self.assertEqual(battery_plan(scene,field,battery_items(scene)[0],equipped_panel(scene))[1],field.point)
        with self.assertRaises(AutomationError):
            battery_plan(scene,field,battery_items(scene)[0],equipped_panel(scene,True))

    def test_one_wear_requires_inventory_consumption_and_named_profile_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            first=board()
            field=equipment_fields(first)[0]
            item=battery_items(first)[0]
            after=board()
            after.image[288:372,2418:2502]=0
            c=helpers.NodeWorkflowTests().context(directory,[equipped_panel(first),first,after,equipped_panel(after,True),after])
            c.last_scene=first
            data=dict(actions=[])
            def pending(*args):
                self.assertEqual(data['actions'][-1]['status'],'pending')
            c.currency_open_field=Mock(side_effect=pending)
            c.currency_close_character=Mock(side_effect=pending)
            c.currency_equip_battery=Mock(side_effect=pending)
            self.assertTrue(equip_battery(c,first,field,item,data,lambda:None))
            c.currency_equip_battery.assert_called_once()
            self.assertEqual([a['status'] for a in data['actions']],['verified']*5)

    def test_scoped_drag_cannot_repeat_or_enter_readonly(self):
        scene=board()
        field=equipment_fields(scene)[0]
        item=battery_items(scene)[0]
        profile=equipped_panel(scene)
        window=Mock()
        for operation in ('daily','currency_wars','currency_wars_deploy_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=scene
            with self.assertRaises(AutomationError):
                c.currency_equip_battery(scene,field,item,profile)
        window.drag.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),window,Mock())
        c.last_scene=scene
        c.sleep=Mock()
        c.currency_equip_battery(scene,field,item,profile)
        window.drag.assert_called_once()
        self.assertIsNone(c._currency_equipment_request)
        with self.assertRaises(AutomationError):
            c.drag(scene,item,field.point)

    def test_interrupted_inspection_never_wears(self):
        with tempfile.TemporaryDirectory() as directory:
            scene=board()
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=scene
            c.currency_open_field=Mock(side_effect=InputInterrupted('paused'))
            c.currency_equip_battery=Mock()
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                equip_battery(c,scene,equipment_fields(scene)[0],battery_items(scene)[0],data,lambda:None)
            self.assertEqual(data['actions'][0]['status'],'pending')
            c.currency_equip_battery.assert_not_called()
