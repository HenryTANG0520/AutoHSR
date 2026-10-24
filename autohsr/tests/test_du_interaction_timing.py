"""Field interactions must settle and await feedback without repeated travel."""
import unittest
from unittest.mock import Mock,patch

import numpy as np

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.models import AutomationError,InputInterrupted,RunReport,Scene,Token


def field(caption='事件'):
    return Scene([Token('(6/13) 第二位面-异常',.99,(.01,.01,.29,.06)),
                  Token(caption,.99,(.64,.55,.69,.59))],np.zeros((540,960,3),np.uint8))


class DuInteractionTimingTests(unittest.TestCase):
    def flow(self):
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._wait_known=Mock(side_effect=lambda p,k,*a,**kw:(p,k))
        event=Scene([Token('事件',.99,(.02,.02,.08,.08))])
        flow._observe=Mock(side_effect=lambda p,*a:'event' if p is event else 'field_anomaly')
        ctx.differential_universe_interact.return_value=event
        return flow,ctx,event

    def test_changed_caption_is_reacquired_before_any_input(self):
        flow,ctx,event=self.flow()
        initial,fresh=field(),field('调查')
        flow._snapshot=Mock(return_value=(fresh,'field_anomaly'))
        with patch('autohsr.du_navigation.interaction_hint',return_value=True):
            self.assertEqual(flow._field_anomaly_visual(initial),(event,'event'))
        ctx.differential_universe_interact.assert_called_once_with(fresh,fresh.tokens[-1])
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_caption_without_live_f_stops_without_replaying_input(self):
        flow,ctx,event=self.flow()
        page=field()
        flow._snapshot=Mock(return_value=(page,'field_anomaly'))
        with patch('autohsr.du_navigation.interaction_hint',return_value=False), \
             self.assertRaisesRegex(AutomationError,'交互提示未稳定'):
            flow._field_anomaly_visual(page)
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_delayed_entry_finishes_while_character_remains_stationary(self):
        flow,ctx,event=self.flow()
        page=field()
        ctx.differential_universe_interact.return_value=page
        flow._snapshot=Mock(side_effect=[(page,'field_anomaly')]*3+[(event,'event')])
        with patch('autohsr.du_navigation.interaction_hint',return_value=True):
            self.assertEqual(flow._field_anomaly_visual(page),(event,'event'))
        ctx.differential_universe_interact.assert_called_once_with(page,page.tokens[-1])
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_entry_completed_during_settle_needs_no_more_f(self):
        flow,ctx,event=self.flow()
        flow._snapshot=Mock(return_value=(event,'event'))
        self.assertEqual(flow._field_anomaly_visual(field()),(event,'event'))
        ctx.differential_universe_interact.assert_not_called()

    def test_single_f_is_released_on_success_interruption_and_send_failure(self):
        from autohsr.windows import GameWindow
        for failure in ('none','pause','send'):
            with self.subTest(failure=failure):
                window=Mock();check=Mock();geometry=object()
                if failure=='pause':check.side_effect=[None,InputInterrupted('pause')]
                if failure=='send':window.send.side_effect=AutomationError('send')
                with patch('autohsr.windows.user32.MapVirtualKeyW',return_value=0x21), \
                     patch('autohsr.windows.user32.SendInput',return_value=1) as release, \
                     patch('autohsr.windows.time.sleep') as sleep:
                    if failure=='none':GameWindow.field_interact(window,geometry,checkpoint=check)
                    else:
                        with self.assertRaises(AutomationError):
                            GameWindow.field_interact(window,geometry,checkpoint=check)
                    window.send.assert_called_once()
                    self.assertIs(window.send.call_args.args[1],geometry)
                    down=window.send.call_args.args[0][0].ki
                    self.assertEqual((down.wScan,down.dwFlags),(0x21,0x8))
                    release.assert_called_once()
                    up=release.call_args.args[1]._obj.ki
                    self.assertEqual((up.wScan,up.dwFlags),(0x21,0xA))
                    window.move.assert_not_called()
                    if failure=='none':
                        duration=sum(c.args[0] for c in sleep.call_args_list)
                        self.assertGreaterEqual(duration,.15)
                        self.assertLess(duration,.25)

    def test_failed_f_release_is_reported(self):
        from autohsr.windows import GameWindow
        with patch('autohsr.windows.user32.SendInput',return_value=0), \
             patch('autohsr.windows.time.sleep'), self.assertRaisesRegex(AutomationError,'交互键释放失败'):
            GameWindow.field_interact(Mock(),None)
