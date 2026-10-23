"""All Win32 calls mocked; verifies holding semantics, never controls a window."""
import unittest
import time
from unittest.mock import Mock, patch

from autohsr.models import AutomationError, FocusLost, InputInterrupted, Scene, Stopped
from autohsr.windows import GameWindow, Geometry, INPUT
import ctypes as C


class HeldDragTests(unittest.TestCase):
    def run_drag(self, *, interrupt=None, send_error=None, release=1,waypoints=()):
        window = GameWindow(42)
        events, moves = [], []
        def send(items, expected):
            events.extend(item.mi.dwFlags for item in items)
            if send_error:
                raise send_error
        def move(x, y, expected):
            moves.append((x, y, tuple(events)))
        def up(count, items, size):
            events.append(C.cast(items, C.POINTER(INPUT)).contents.mi.dwFlags)
            return release
        checkpoint = Mock(side_effect=interrupt)
        with patch.object(window, 'move', side_effect=move), patch.object(window, 'send', side_effect=send), \
                patch('autohsr.windows.user32.SendInput', side_effect=up), patch('autohsr.windows.time.sleep'):
            try:
                window.drag((.4, .8), (.5, .4), Geometry(0, 0, 1920, 1080), checkpoint=checkpoint,waypoints=waypoints)
            finally:
                self.events, self.moves = events, moves

    def test_button_stays_down_for_all_intermediate_moves(self):
        self.run_drag()
        self.assertEqual(self.events, [2, 4])
        self.assertEqual(len(self.moves), 31)
        self.assertEqual(self.moves[0], (.4, .8, ()))
        self.assertEqual(self.moves[-1], (.5, .4, (2,)))
        self.assertTrue(all(state == (2,) for _, _, state in self.moves[1:]))

    def test_waypoints_keep_button_held_and_avoid_the_diagonal_between_roles(self):
        self.run_drag(waypoints=((.4,.735),(.5,.735)))
        self.assertEqual(self.events,[2,4])
        self.assertEqual(len(self.moves),91)
        self.assertTrue(all(state==(2,) for _,_,state in self.moves[1:]))
        self.assertTrue(all(abs(y-.735)<1e-9 for x,y,_ in self.moves if .4<x<.5))
        with self.assertRaises(Stopped):
            self.run_drag(waypoints=((.4,.735),(.5,.735)),interrupt=[None]*45+[Stopped('stop')])
        self.assertEqual(self.events,[2,4])

    def test_stop_or_focus_loss_during_hold_still_releases(self):
        for error in (Stopped('stop'), FocusLost('focus')):
            with self.subTest(error=error), self.assertRaises(type(error)):
                self.run_drag(interrupt=[None] * 12 + [error])
            self.assertEqual(self.events, [2, 4])
            self.assertLess(len(self.moves), 31)

    def test_rejected_down_still_attempts_cleanup(self):
        with self.assertRaises(AutomationError):
            self.run_drag(send_error=AutomationError('down rejected'))
        self.assertEqual(self.events, [2, 4])

    def test_failed_release_is_reported(self):
        with self.assertRaisesRegex(AutomationError, '释放失败'):
            self.run_drag(release=0)

    def test_invalid_coordinates_never_reach_win32(self):
        window = GameWindow(42)
        for point in ((float('nan'), .5), (-.1, .5), (1, .5), (.2,), (True, .3)):
            with patch.object(window, 'move') as move, patch('autohsr.windows.user32.SendInput') as send:
                with self.assertRaises(AutomationError):
                    window.drag(point, (.5, .5), Geometry(0, 0, 1920, 1080))
                move.assert_not_called()
                send.assert_not_called()


class HeldClickTests(unittest.TestCase):
    def click(self,interrupt=None,send_error=None):
        window=GameWindow(42)
        events=[]
        def send(items,expected):
            events.extend(item.mi.dwFlags for item in items)
            if send_error:
                raise send_error
        def release(count,items,size):
            events.append(C.cast(items,C.POINTER(INPUT)).contents.mi.dwFlags)
            return 1
        checkpoint=Mock(side_effect=interrupt)
        with patch.object(window,'move'),patch.object(window,'send',side_effect=send),patch('autohsr.windows.user32.SendInput',side_effect=release),patch('autohsr.windows.time.sleep') as sleep:
            try:
                window.click_held(.3,.8,Geometry(0,0,1920,1080),checkpoint=checkpoint)
            finally:
                self.events,self.sleeps=events,sleep.call_count

    def test_one_down_and_up_span_multiple_frames(self):
        self.click()
        self.assertEqual(self.events,[2,4])
        self.assertGreaterEqual(self.sleeps,3)

    def test_pause_focus_and_stop_release_without_another_down(self):
        for error in (InputInterrupted('pause'),FocusLost('focus'),Stopped('stop')):
            with self.assertRaises(type(error)):
                self.click(interrupt=[None,None,error])
            self.assertEqual(self.events,[2,4])
        with self.assertRaises(AutomationError):
            self.click(send_error=AutomationError('rejected'))
        self.assertEqual(self.events,[2,4])

    def test_invalid_point_has_no_input(self):
        window=GameWindow(42)
        with patch.object(window,'move') as move,patch('autohsr.windows.user32.SendInput') as send:
            for x in (float('nan'),True,-1,1):
                with self.assertRaises(AutomationError):
                    window.click_held(x,.5,Geometry(0,0,1920,1080))
            move.assert_not_called()
            send.assert_not_called()


class DragContextTests(unittest.TestCase):
    def test_du_pan_requires_reward_opt_in_current_gallery_and_exact_horizontal_route(self):
        from autohsr.tests.test_du_team import fixture
        from autohsr.du_rewards import gallery_pan_plan
        ctx,runner,window=self.context()
        runner.report.operation='differential_universe'
        page=fixture('gallery_offscreen_notification')
        page.geometry=ctx.last_scene.geometry
        page.captured_at=time.monotonic()
        ctx.last_scene=page
        plan=gallery_pan_plan(page)
        with self.assertRaises(AutomationError):
            ctx.drag(page,*plan,du_intent='du_reward_gallery_pan')
        runner.settings.differential_universe_rewards=True
        with self.assertRaises(AutomationError):
            ctx.drag(page,*plan)
        with self.assertRaises(AutomationError):
            ctx.drag(page,plan[0],(.35,.20),du_intent='du_reward_gallery_pan')
        window.drag.assert_not_called()
        ctx.drag(page,*plan,du_intent='du_reward_gallery_pan')
        window.drag.assert_called_once()

    def test_successful_drag_moves_pointer_off_the_feedback_portrait(self):
        ctx,runner,window=self.context()
        before=ctx.last_scene
        ctx.drag(before,(.4,.8),(.5,.4))
        window.drag.assert_called_once()
        window.move.assert_called_once_with(.5,.5,before.geometry)

    def test_release_is_consumed_before_pointer_leaves_the_drop_target(self):
        ctx,runner,window=self.context()
        events=[]
        window.drag.side_effect=lambda *a,**kw:events.append('released')
        ctx.sleep.side_effect=lambda seconds:events.append(('wait',seconds))
        window.move.side_effect=lambda *a:events.append('clear_hover')
        ctx.drag(ctx.last_scene,(.4,.8),(.5,.4))
        self.assertEqual(events[:3],['released',('wait',.2),'clear_hover'])

    def test_pause_after_release_cancels_hover_clear_and_old_target(self):
        ctx,runner,window=self.context()
        def paused(seconds):
            runner.input_epoch+=1
        ctx.sleep.side_effect=paused
        with self.assertRaises(InputInterrupted):
            ctx.drag(ctx.last_scene,(.4,.8),(.5,.4))
        window.move.assert_not_called()
        self.assertIsNone(ctx.last_scene)

    def context(self):
        from autohsr.app import Context, Runner
        from autohsr.config import Settings
        runner = Runner(Settings())
        window = Mock()
        ctx = Context(runner, window, Mock())
        ctx.last_scene = Scene([], geometry=Geometry(0, 0, 1920, 1080), captured_at=time.monotonic())
        ctx.sleep = Mock()
        return ctx, runner, window

    def test_pause_during_hold_aborts_without_blocking_or_resuming_old_drag(self):
        ctx, runner, window = self.context()
        before = ctx.last_scene
        def drag(*_, checkpoint):
            runner._pause.set()
            checkpoint()
        window.drag.side_effect = drag
        with self.assertRaises(InputInterrupted):
            ctx.drag(before, (.4, .8), (.5, .4))
        self.assertIsNone(ctx.last_scene)
        ctx.sleep.assert_not_called()
        window.move.assert_not_called()

    def test_epoch_change_or_stop_during_hold_discards_scene(self):
        for change, error in ((lambda r: setattr(r, 'input_epoch', 1), InputInterrupted),
                              (lambda r: r._stop.set(), Stopped)):
            ctx, runner, window = self.context()
            def drag(*_, checkpoint):
                change(runner)
                checkpoint()
            window.drag.side_effect = drag
            with self.assertRaises(error):
                ctx.drag(ctx.last_scene, (.4, .8), (.5, .4))
            self.assertIsNone(ctx.last_scene)
            ctx.sleep.assert_not_called()
