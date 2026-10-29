"""Station settings and real DU dispatch, without a live game or new captures."""
from contextlib import redirect_stdout,redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Runner
from autohsr.config import Settings,SettingsError
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_station_policy import StationPreferences,LABELS,MANDATORY
from autohsr.models import AutomationError,RunReport,Scene,Token
from autohsr.policy import guard_differential_universe_click
from autohsr.plan_runner import PlanRunner


def token(text,x=.5,y=.7,score=.99):
    return Token(text,score,(x-.02,y-.01,x+.02,y+.01))


def route(*names):
    count=len(names)
    positions={1:(.5,),2:(.43,.57),3:(.36,.5,.64),4:(.29,.43,.57,.705)}[count]
    return Scene([token('选择下一站',.1,.05),token('选择一张站点卡',.5,.25)]+
                 [token(name,x) for name,x in zip(names,positions)]+[token('确定',.85,.88)])


def flow(config=None):
    ctx=Mock(settings=config or Settings(differential_universe_station_custom=True),report=RunReport())
    ctx.template.return_value=None
    ctx.click.side_effect=lambda page,target,*,du_intent:guard_differential_universe_click(page,target,intent=du_intent)
    return DifferentialUniverseWorkflow(ctx,1)


class StationPreferenceTests(unittest.TestCase):
    def test_disabled_feature_keeps_legacy_text_and_image_order(self):
        config=Settings(differential_universe_station_disabled=['战斗'])
        current=flow(config)
        self.assertEqual(current._station_target(route('奖励','战斗','精英'))[0].text,'战斗')
        current.ctx.template.return_value=(.5,.54,.99)
        self.assertEqual(current._station_target(route('精英'))[1],'station_icon_select')
        self.assertFalse(current.report['station_preferences']['enabled'])

    def test_one_to_four_cards_and_equal_priority_use_visible_order(self):
        config=Settings(differential_universe_station_custom=True,differential_universe_station_priority={'奖励':0,'事件':0,'战斗':5})
        for names,expected in ((('奖励',),'奖励'),(('战斗','奖励'),'奖励'),
                               (('事件','奖励','战斗'),'事件'),(('商店','奖励','奖励','战斗'),'奖励')):
            with self.subTest(names=names):
                current=flow(config);page=route(*names);target,intent=current._station_target(page)
                self.assertEqual(target.text,expected);self.assertEqual(intent,'station_select')
                self.assertEqual(target.center[0],min(t.center[0] for t in page.tokens if t.text==expected))
                guard_differential_universe_click(page,target,intent=intent)

    def test_disabled_combat_cannot_return_through_the_icon_fallback(self):
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_disabled=['战斗']))
        current.ctx.template.return_value=(.36,.54,.99)
        target,intent=current._station_target(route('战斗','奖励'))
        self.assertEqual((target.text,intent),('奖励','station_select'));current.ctx.template.assert_not_called()

    def test_all_disabled_stops_before_input_wait_or_redraw(self):
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_disabled=['战斗','商店']))
        with self.assertRaisesRegex(AutomationError,'均已禁用'):current._progress_run(route('商店','战斗'),'station_choice')
        current.ctx.click.assert_not_called();current.ctx.wait.assert_not_called()

    def test_preferred_text_is_not_overridden_by_a_lower_priority_combat_icon(self):
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_priority={'奖励':0,'战斗':9}))
        current.ctx.template.return_value=(.36,.54,.99)
        self.assertEqual(current._station_target(route('战斗','奖励'))[0].text,'奖励')
        current.ctx.template.assert_not_called()

    def test_icon_can_recover_a_missing_combat_label_but_cannot_conflict_with_a_known_card(self):
        current=flow();current.ctx.template.return_value=(.5,.54,.99)
        page=route('事件','斗','商店')
        target,intent=current._station_target(page)
        self.assertEqual(intent,'station_icon_select');guard_differential_universe_click(page,target,intent=intent)
        page=route('商店','事件');current.ctx.template.return_value=(page.find('商店',exact=True).center[0],.54,.99)
        self.assertEqual(current._station_target(page)[0].text,'事件')

    def test_mandatory_stations_precede_custom_zero_and_cannot_be_disabled(self):
        for name in MANDATORY:
            with self.subTest(name=name):
                current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_priority={'奖励':0}))
                page=route('奖励',name);target,intent=current._station_target(page)
                self.assertEqual(target.text,name);guard_differential_universe_click(page,target,intent=intent)
                with self.assertRaises(SettingsError):Settings(differential_universe_station_disabled=[name]).validate('save')
                with self.assertRaises(SettingsError):Settings(differential_universe_station_priority={name:1}).validate('save')

    def test_omitted_known_labels_still_have_a_defined_last_priority(self):
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_priority={}))
        for name in LABELS:
            with self.subTest(name=name):self.assertEqual(current._station_target(route(name))[0].text,name)

    def test_low_confidence_outside_card_area_and_unknown_labels_do_not_authorize_selection(self):
        current=flow();page=route('未知')
        page.tokens.extend((token('奖励',.5,.9),token('战斗',.5,.7,.4)))
        self.assertIsNone(current._station_target(page));current.ctx.click.assert_not_called()

    def test_real_progress_dispatch_selects_preferred_card_then_confirms_once(self):
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_priority={'奖励':0,'战斗':5}))
        page=route('战斗','奖励');field=Scene([token('(2/13) 第一位面-奖励',.2,.05)])
        frames=iter((page,field))
        def submit(scene,target,*,du_intent):
            guard_differential_universe_click(scene,target,intent=du_intent)
            current.ctx.last_scene=next(frames)
        current.ctx.click.side_effect=submit
        current._field_anomaly=Mock(side_effect=AutomationError('arrived at selected station'))
        with self.assertRaisesRegex(AutomationError,'arrived at selected station'):current._progress_run(page,'station_choice')
        calls=current.ctx.click.call_args_list
        self.assertEqual([(c.args[1].text,c.kwargs['du_intent']) for c in calls],[('奖励','station_select'),('确定','station_confirm')])
        self.assertEqual(current.report['station_decisions'][0]['station'],'奖励')

    def test_beacon_alternative_obeys_preferences_and_disabled_list(self):
        current=flow(Settings(differential_universe_station_custom=True,
            differential_universe_station_priority={'战斗':0,'财富':1,'奖励':2},differential_universe_station_disabled=['财富']))
        page=route('战斗','财富','奖励');hazard=token('跟你爆了：敌人被消灭时自爆，对我方全体造成伤害',.6,.2)
        page.tokens.append(hazard);safe=Scene([t for t in page.tokens if t is not hazard])
        current._click=Mock(return_value=(safe,'station_choice'))
        self.assertEqual(current._safer_station_preview(page,page.find('战斗',exact=True)),(safe,'station_choice'))
        self.assertEqual(current._click.call_args.args[1].text,'奖励');self.assertEqual(current._click.call_count,1)
        guard_differential_universe_click(safe,safe.find('确定',exact=True),intent='station_confirm')

    def test_no_allowed_safe_alternative_does_not_select_a_disabled_card(self):
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_disabled=['财富']))
        page=route('战斗','财富');page.tokens.append(token('跟你爆了：敌人被消灭时自爆，对我方全体造成伤害',.6,.2))
        current._click=Mock()
        with self.assertRaisesRegex(AutomationError,'危险信标'):current._safer_station_preview(page,page.find('战斗',exact=True))
        current._click.assert_not_called()

    def test_profile_and_runner_plan_snapshots_do_not_follow_later_mutation(self):
        config=Settings(differential_universe_station_custom=True,differential_universe_station_priority={'奖励':0,'战斗':5})
        current=flow(config);native=Runner(config);plan=PlanRunner(config)
        config.differential_universe_station_priority['战斗']=0;config.differential_universe_station_disabled.append('奖励')
        for saved in (native.settings,plan.settings,replace(native.settings)):
            self.assertEqual(saved.differential_universe_station_priority['战斗'],5)
            self.assertEqual(saved.differential_universe_station_disabled,[])
        self.assertEqual(current._station_target(route('战斗','奖励'))[0].text,'奖励')
        self.assertEqual(current.report['station_preferences']['priority']['战斗'],5)

    def test_legacy_load_explicit_save_and_independent_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text('{}',encoding='utf8')
            config=Settings.load(path);self.assertFalse(config.differential_universe_station_custom)
            config.differential_universe_station_disabled.append('财富')
            self.assertEqual(Settings().differential_universe_station_disabled,[])
            config.differential_universe_station_custom=True;config.save(path)
            loaded=Settings.load(path);self.assertEqual(loaded,config)
            self.assertEqual(json.loads(path.read_text('utf8'))['differential_universe_station_disabled'],['财富'])

    def test_invalid_profiles_reject_types_unknown_names_ranges_and_duplicates(self):
        bad=(('custom','true'),('priority',[]),('priority',{'战斗':True}),('priority',{'战斗':-1}),
             ('priority',{'战斗':101}),('priority',{'未知':1}),('disabled','战斗'),('disabled',['未知']),('disabled',['战斗','战斗']))
        for field,value in bad:
            with self.subTest(field=field,value=value),self.assertRaises(SettingsError):
                Settings(**{'differential_universe_station_'+field:value}).validate('save')

    def test_cli_overrides_are_scoped_and_do_not_save_settings(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path);before=path.read_bytes()
            result=RunReport(status='success');result.report_saved=True
            with patch('autohsr.app.Runner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=result
                self.assertEqual(main(['--differential-universe','--config',str(path),'--du-station-priority','奖励=0',
                    '--du-station-disabled','商店,财富']),0)
                config=factory.call_args.args[0]
                self.assertTrue(config.differential_universe_station_custom)
                self.assertEqual(config.differential_universe_station_disabled,['商店','财富'])
                self.assertEqual(config.differential_universe_station_priority['奖励'],0)
            self.assertEqual(path.read_bytes(),before)
            with patch('autohsr.app.Runner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):main(['--run','--config',str(path),'--du-custom-stations'])
                factory.assert_not_called()

    def test_cli_rejects_ambiguous_or_invalid_overrides_before_runner_creation(self):
        from autohsr.__main__ import main
        cases=(['--du-station-priority','战斗=2','--du-station-priority','战斗=1'],
               ['--du-station-disabled','首领'],['--du-station-priority','奖励=1.5'],
               ['--no-du-custom-stations','--du-station-disabled','商店'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path)
            for args in cases:
                with self.subTest(args=args),patch('autohsr.app.Runner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['--differential-universe','--config',str(path)]+args),2)
                    factory.assert_not_called()

    def test_cli_plan_inherits_profile_and_can_temporarily_disable_it(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            Settings(weekly_enabled=True,differential_universe_station_custom=True,
                     differential_universe_station_disabled=['战斗']).save(path)
            original=path.read_bytes();result=RunReport(status='success');result.report_saved=True
            with patch('autohsr.plan_runner.PlanRunner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=result
                self.assertEqual(main(['--plan','--config',str(path),'--no-du-custom-stations']),0)
                config=factory.call_args.args[0]
                self.assertFalse(config.differential_universe_station_custom)
                self.assertEqual(config.differential_universe_station_disabled,['战斗'])
            self.assertEqual(path.read_bytes(),original)
            Settings(weekly_enabled=True,weekly_mode='currency_wars').save(path)
            with patch('autohsr.plan_runner.PlanRunner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--plan','--config',str(path),'--du-custom-stations']),2)
                factory.assert_not_called()

    def test_existing_masked_station_replay_keeps_default_and_respects_disabled_label(self):
        path=Path(__file__).parent/'fixtures/du_runtime/station_explosion_beacon.json'
        data=json.loads(path.read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        original=flow(Settings());target,intent=original._station_target(page)
        self.assertEqual((target.text,intent),('战斗','station_select'))
        current=flow(Settings(differential_universe_station_custom=True,differential_universe_station_disabled=['战斗']))
        target,intent=current._station_target(page)
        self.assertNotEqual(target.text,'战斗');guard_differential_universe_click(page,target,intent=intent)
        self.assertEqual(current._station_hazard(page),'enemy_death_party_explosion')
        with self.assertRaises(AutomationError):guard_differential_universe_click(page,page.find('确定',exact=True),intent='station_confirm')
