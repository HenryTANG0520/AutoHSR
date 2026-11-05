from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time as wall_time
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow,classify_page
from autohsr.du_curio_discard_store import CurioDiscardStore
from autohsr.du_strategy import curio_card_selected
from autohsr.models import AutomationError,EmptyCapture,InputInterrupted,RunReport,Scene,Token
from autohsr.policy import du_curio_discard_page,du_tutorial_close_prompt,guard_differential_universe_click


class CurioDiscardTests(unittest.TestCase):
    ACCOUNT_A = 'a' * 64
    ACCOUNT_B = 'b' * 64
    SYNTHETIC_ACCOUNT = 'UID: 000000001'
    SYNTHETIC_OTHER = 'UID: 000000002'

    @staticmethod
    def native():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('curio_discard_generic_prompt')

    def test_discard_heading_and_controls_outrank_incidental_blessing_text(self):
        page=self.native()
        self.assertTrue(du_curio_discard_page(page))
        self.assertEqual(classify_page(page),'curio_discard')
        for label in ('请舍弃奇物','丢弃'):
            changed=Scene([t for t in page.tokens if t.text!=label],page.image)
            self.assertFalse(du_curio_discard_page(changed))
            self.assertEqual(classify_page(changed),'unknown')

    def test_native_damaged_curio_is_preferred_and_both_guarded_actions_are_supported(self):
        page=self.native();ctx=Mock(settings=Settings(),report=RunReport())
        target=DifferentialUniverseWorkflow(ctx,1)._choice_target(page,'curio_discard')
        self.assertEqual(target.text,'降维骰子')
        guard_differential_universe_click(page,target,intent='curio_discard_select')
        button=page.find('丢弃',(.78,.85,.99,.96),exact=True)
        guard_differential_universe_click(page,button,intent='curio_discard_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,Token('不存在的奇物',.99,target.box),intent='curio_discard_select')

    def test_white_selection_border_belongs_only_to_the_current_card(self):
        page=self.native()
        for name,expected in (('智识火漆',True),('星际漂流鱼',False),('降维骰子',False)):
            target=page.find(name,(.14,.35,.87,.54),exact=True)
            self.assertEqual(curio_card_selected(page,target),expected)

    def test_failed_selection_does_not_discard_the_previously_selected_other_card(self):
        page=self.native();ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._require_curio_discard_access=Mock()
        flow._click=Mock(return_value=(page,'curio_discard'))
        with self.assertRaisesRegex(AutomationError,'选中边框'):
            flow._progress_run(page,'curio_discard')
        self.assertEqual(flow._click.call_count,1)
        self.assertEqual(flow._click.call_args.kwargs['intent'],'curio_discard_select')

    def selected_frame(self):
        page=self.native()
        # Retain the recorded left-card white border. Suppress only the OCR
        # damaged-card marker so the normal preference also chooses that card.
        return Scene([token for token in page.tokens if token.text!='已损毁'],page.image)

    @contextmanager
    def captured_flow(self,pages, *, directory=None, seed_run=True, account_for=None):
        import numpy as np
        from autohsr import differential_universe as du
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        with TemporaryDirectory(prefix='AutoHSR-du-curio-test-') as temporary:
            directory=Path(directory) if directory is not None else Path(temporary)/'current'
            directory.mkdir()
            with DuRuntimeTests().captured_du_flow(pages) as (flow,window):
                du.time.time=wall_time
                flow.report['run_dir']=flow.ctx.report.run_dir=str(directory)
                window.hwnd=123
                if seed_run:
                    flow.report['current_run']=1
                    flow.report['run_results']=[dict(run=1,run_id='synthetic-current',origin='resumed_trial',status='resuming')]
                native_account=flow._curio_account
                if account_for is None:
                    # Page/clock tests use a known account for each frame. The
                    # account-specific tests opt into the real local parser.
                    account_for=lambda _: self.ACCOUNT_A

                def account(scene, *, required=True):
                    fake=account_for(scene)
                    return fake if fake is not None else native_account(scene, required=required)

                def evidence(scene, label):
                    if scene.image is None:
                        scene=Scene(scene.tokens,np.zeros((64,96,3),np.uint8))
                    return Context.evidence(flow.ctx,scene,label)

                flow._curio_account=account
                flow.ctx.evidence=evidence
                yield flow,window

    def confirm_clicks(self,window,page):
        button=page.find('丢弃',exact=True).center
        return sum(call.args[:2]==button for call in window.click.call_args_list)

    @staticmethod
    def requests(flow):
        return [row for row in flow.report['actions'] if row.get('intent')=='curio_discard_confirm']

    @staticmethod
    def departed():
        return Scene([Token('战斗失败',.99,(.44,.19,.56,.23))])

    @staticmethod
    def account_frame(page, *, drawn, read):
        import cv2
        import numpy as np

        image=page.image.copy() if page.image is not None else np.full((540,960,3),19,np.uint8)
        height,width=image.shape[:2]
        if drawn is not None:
            cv2.putText(image,drawn,(round(.02*width),round(.98*height)),
                        cv2.FONT_HERSHEY_SIMPLEX,.6,(220,220,220),1,cv2.LINE_AA)
        tokens=list(page.tokens)
        if read is not None:
            tokens.append(Token(read,.99,(.015,.95,.18,.988)))
        return Scene(tokens,image,page.geometry)

    @staticmethod
    def copies(page, count):
        return [Scene(list(page.tokens),page.image,page.geometry) for _ in range(count)]

    def test_interruption_after_discard_does_not_send_a_second_confirmation(self):
        page=self.selected_frame()
        frames=[Scene(page.tokens,page.image) for _ in range(4)]
        frames.append(self.departed())
        with self.captured_flow(frames) as (flow,window):
            sleep=flow.ctx.sleep
            interrupted=False

            def interrupt_after_send(seconds):
                nonlocal interrupted
                if window.click.call_count==2 and not interrupted:
                    interrupted=True
                    raise InputInterrupted('test interruption after raw discard click')
                sleep(seconds)

            flow.ctx.sleep=interrupt_after_send
            with self.assertRaises(AutomationError) as failure:
                flow._progress_run(flow.ctx.snapshot(),'curio_discard')
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(window.click.call_count,2)
            self.assertIn('待核对',str(failure.exception))
            self.assertEqual([row['feedback_status'] for row in self.requests(flow)],['unverified'])

    def test_unknown_then_old_discard_page_does_not_send_a_second_confirmation(self):
        page=self.selected_frame()
        frames=[Scene(page.tokens,page.image) for _ in range(3)]
        frames.extend([Scene([]),*[Scene(page.tokens,page.image) for _ in range(28)]])
        with self.captured_flow(frames) as (flow,window):
            with self.assertRaises(AutomationError) as failure:
                flow._progress_run(flow.ctx.snapshot(),'curio_discard')
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(window.click.call_count,2)
            self.assertIn('待核对',str(failure.exception))
            self.assertEqual([row['feedback_status'] for row in self.requests(flow)],['unverified'])

    def test_discard_waits_through_loading_until_independent_known_departure(self):
        page=self.selected_frame()
        frames=[Scene(page.tokens,page.image) for _ in range(3)]
        frames.extend([Scene([]),self.departed(),EmptyCapture('test loading'),self.departed(),self.departed()])
        with self.captured_flow(frames) as (flow,window):
            with self.assertRaisesRegex(AutomationError,'差分宇宙已失败'):
                flow._progress_run(flow.ctx.snapshot(),'curio_discard')
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(window.click.call_count,2)
            self.assertEqual(flow.ctx.vision.read.call_count,7)
            self.assertEqual(self.requests(flow)[0]['feedback_status'],'verified')
            self.assertEqual(self.requests(flow)[0]['after_page'],'defeat')

    def test_missing_discard_controls_cannot_make_old_cards_prove_departure(self):
        page=self.selected_frame()
        partial=[Token('智识火柒',token.score,token.box) if token.text=='智识火漆' else token
                 for token in page.tokens if token.text not in ('丢弃奇物','请舍弃奇物','丢弃')]
        self.assertEqual(classify_page(Scene(partial,page.image)),'blessing_choice')
        frames=[page,Scene(page.tokens,page.image),Scene(partial,page.image),Scene(partial,page.image),
                self.departed(),self.departed()]
        with self.captured_flow(frames) as (flow,window):
            with self.assertRaisesRegex(AutomationError,'差分宇宙已失败'):
                flow._progress_run(flow.ctx.snapshot(),'curio_discard')
            self.assertEqual(window.click.call_count,2)
            self.assertEqual(flow.ctx.vision.read.call_count,6)

    def test_real_followup_heading_with_old_dialog_pixels_is_not_departure(self):
        import cv2
        import numpy as np
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        page=self.selected_frame()
        next_page=DuRuntimeTests.optional_device_fixture('blessing_two_choices')
        heading=next_page.find('选择祝福',(0,0,.32,.13),exact=True)
        self.assertIsNotNone(heading)
        old_tokens=[token for token in page.tokens if token.text not in ('丢弃奇物','请舍弃奇物','丢弃')]
        height,width=page.image.shape[:2]
        shifted=cv2.warpAffine(page.image,np.float32([[1,0,2],[0,1,1]]),(width,height))
        old_pixels=Scene([*old_tokens,heading],shifted)
        self.assertEqual(classify_page(old_pixels),'blessing_choice')
        last=Scene(next_page.tokens,next_page.image.copy())
        with self.captured_flow([page,old_pixels,Scene(old_pixels.tokens,old_pixels.image.copy()),next_page,last]) as (flow,window):
            before=flow.ctx.snapshot()
            after,kind=flow._confirm_curio_discard(before,before.find('丢弃',exact=True))
            self.assertIs(after,last)
            self.assertEqual(kind,'blessing_choice')
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(flow.ctx.vision.read.call_count,5)
            self.assertEqual(len(self.requests(flow)[0]['departure_evidence']),2)

    def test_discard_uses_one_fifteen_second_budget_after_sending(self):
        from autohsr import differential_universe as du

        page=self.selected_frame()
        button=page.find('丢弃',exact=True).center
        for blank in (False,True):
            with self.subTest(blank=blank):
                loading=[EmptyCapture('loading') if blank else Scene([]) for _ in range(100)]
                with self.captured_flow([page,Scene(page.tokens,page.image),*loading]) as (flow,window):
                    sent=[]
                    def capture_confirmation_time(*args):
                        if args[:2]==button:
                            sent.append(du.time.monotonic())
                    window.click.side_effect=capture_confirmation_time
                    with self.assertRaises(AutomationError) as failure:
                        flow._progress_run(flow.ctx.snapshot(),'curio_discard')
                    self.assertEqual(len(sent),1)
                    self.assertLessEqual(du.time.monotonic()-sent[0],15.001)
                    self.assertIn('待核对',str(failure.exception))
                    self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')

    def test_epoch_change_before_discard_refreshes_then_sends_only_once(self):
        page=self.selected_frame()
        frames=[Scene(page.tokens,page.image) for _ in range(4)]
        frames.extend([self.departed(),self.departed()])
        with self.captured_flow(frames) as (flow,window):
            runner=flow.ctx.runner

            def checkpoint():
                if runner.input_epoch==0 and self.requests(flow):
                    runner.input_epoch=1

            runner.checkpoint.side_effect=checkpoint
            with self.assertRaisesRegex(AutomationError,'差分宇宙已失败'):
                flow._progress_run(flow.ctx.snapshot(),'curio_discard')
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(window.click.call_count,3)
            self.assertEqual([row['status'] for row in self.requests(flow)],['not_sent','sent'])

    @staticmethod
    def tutorial_close_requests(flow):
        return [row for row in flow.report['actions'] if row.get('intent')=='du_tutorial_close']

    def test_real_reward_overlay_can_reveal_the_old_discard_page_without_reconfirming(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        page=self.selected_frame()
        tutorial=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        frames=[page,Scene(page.tokens,page.image),tutorial,Scene(tutorial.tokens,tutorial.image),
                Scene(page.tokens,page.image),Scene(page.tokens,page.image),self.departed(),self.departed()]
        with self.captured_flow(frames) as (flow,window):
            with self.assertRaisesRegex(AutomationError,'待核对'):
                flow._progress_run(flow.ctx.snapshot(),'curio_discard')
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(window.click.call_count,3)
            self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')
            self.assertEqual(self.tutorial_close_requests(flow)[0]['feedback_status'],'unverified')

    def test_real_reward_overlay_closes_once_before_two_fresh_continuation_frames(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        page=self.selected_frame()
        tutorial=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        prompt=du_tutorial_close_prompt(tutorial)
        reward_title=tutorial.find('获得物品',exact=True)
        height,width=tutorial.image.shape[:2]
        x1,y1,x2,y2=[round(value*size) for value,size in zip(reward_title.box,(width,height,width,height))]
        fading=tutorial.image.copy()
        fading[y1:y2,x1:x2]=0
        cases=((False,'event_star_choices','event'),(True,'event_f_blue_background','field_reward'))
        for prompt_only,fixture,expected in cases:
            with self.subTest(prompt_only=prompt_only):
                next_page=DuRuntimeTests.optional_device_fixture(fixture)
                overlay=Scene([prompt] if prompt_only else tutorial.tokens,tutorial.image)
                # Simulate the title fading first and then the OCR losing both
                # overlay anchors while the live close prompt is still visible.
                partial=Scene([*next_page.tokens,reward_title],tutorial.image)
                masked=[Scene(next_page.tokens,fading) for _ in range(2)]
                last=Scene(next_page.tokens,next_page.image)
                frames=[page,overlay,Scene(overlay.tokens,overlay.image),partial,*masked,next_page,
                        EmptyCapture('loading after close'),Scene(next_page.tokens,next_page.image),last]
                with self.captured_flow(frames) as (flow,window):
                    before=flow.ctx.snapshot()
                    after,kind=flow._confirm_curio_discard(before,before.find('丢弃',exact=True))
                    self.assertIs(after,last)
                    self.assertEqual(kind,expected)
                    self.assertEqual([call.args[:2] for call in window.click.call_args_list],
                                     [before.find('丢弃',exact=True).center,prompt.center])
                    discard=self.requests(flow)[0]
                    close=self.tutorial_close_requests(flow)[0]
                    self.assertEqual(discard['overlay_close_action'],close['index'])
                    self.assertEqual(len(discard['overlay_evidence']),2)
                    self.assertEqual([row['feedback_status'] for row in (discard,close)],['verified','verified'])
                    self.assertEqual(discard['departure_evidence'],close['departure_evidence'])
                    self.assertEqual([row['page_kind'] for row in flow.report['page_history']],
                                     ['tutorial_overlay','tutorial_overlay',expected,expected])

    def test_other_or_partially_read_overlays_cannot_verify_departure(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        page=self.selected_frame()
        tutorial=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        event=DuRuntimeTests.optional_device_fixture('event_star_choices')
        reward_title=tutorial.find('获得物品',exact=True)
        overlay_cases=(
            (Scene([*event.tokens,reward_title],tutorial.image),'event'),
            (Scene([*event.tokens,Token('敷衍面具',.97,(.4,.1,.6,.2)),
                    Token('获得愿力 +30',.96,(.4,.5,.6,.6))],tutorial.image),'mask_reward_overlay'),
        )
        for overlay,classification in overlay_cases:
            with self.subTest(classification=classification):
                self.assertEqual(classify_page(overlay),classification)
                frames=[page,*[Scene(overlay.tokens,overlay.image) for _ in range(32)]]
                with self.captured_flow(frames) as (flow,window):
                    before=flow.ctx.snapshot()
                    with self.assertRaisesRegex(AutomationError,'待核对'):
                        flow._confirm_curio_discard(before,before.find('丢弃',exact=True))
                    self.assertEqual(self.confirm_clicks(window,page),1)
                    self.assertEqual(window.click.call_count,1)
                    self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')

    def test_discard_overlay_close_interruption_never_reenters_selection(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        page=self.selected_frame()
        tutorial=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        for before_close in (True,False):
            with self.subTest(before_close=before_close):
                frames=[page,Scene(page.tokens,page.image),tutorial,Scene(tutorial.tokens,tutorial.image)]
                with self.captured_flow(frames) as (flow,window):
                    if before_close:
                        evidence=flow.ctx.evidence

                        def interrupt_before(scene,label):
                            if label=='du_before_点击空白处关闭':
                                flow.ctx.runner.input_epoch+=1
                            return evidence(scene,label)

                        flow.ctx.evidence=interrupt_before
                    else:
                        sleep=flow.ctx.sleep

                        def interrupt_after(seconds):
                            if window.click.call_count==3:
                                raise InputInterrupted('test interruption after raw overlay close')
                            sleep(seconds)

                        flow.ctx.sleep=interrupt_after
                    with self.assertRaisesRegex(AutomationError,'待核对'):
                        flow._progress_run(flow.ctx.snapshot(),'curio_discard')
                    self.assertEqual(self.confirm_clicks(window,page),1)
                    self.assertEqual(window.click.call_count,2 if before_close else 3)
                    self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')
                    close=self.tutorial_close_requests(flow)[0]
                    if before_close:
                        self.assertEqual(close['status'],'not_sent')
                    else:
                        self.assertEqual(close['feedback_status'],'unverified')

    def test_overlay_close_and_later_feedback_share_original_fifteen_seconds(self):
        from autohsr import differential_universe as du
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        page=self.selected_frame()
        tutorial=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        stacked=DuRuntimeTests.optional_device_fixture('reward_items_fifty')
        for feedback in ('blank','stacked_overlay','close_expired'):
            with self.subTest(feedback=feedback):
                frames=[page,tutorial,Scene(tutorial.tokens,tutorial.image)]
                if feedback=='stacked_overlay':
                    frames.extend(Scene(stacked.tokens,stacked.image) for _ in range(32))
                else:
                    frames.extend(EmptyCapture('blank after close') for _ in range(100))
                with self.captured_flow(frames) as (flow,window):
                    sent=[]
                    window.click.side_effect=lambda *_: sent.append(du.time.monotonic())
                    if feedback=='close_expired':
                        evidence=flow.ctx.evidence

                        def slow_close_evidence(scene,label):
                            if label=='du_before_点击空白处关闭':
                                flow.ctx.sleep(15)
                            return evidence(scene,label)

                        flow.ctx.evidence=slow_close_evidence
                    before=flow.ctx.snapshot()
                    with self.assertRaisesRegex(AutomationError,'待核对'):
                        flow._confirm_curio_discard(before,before.find('丢弃',exact=True))
                    self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')
                    closes=self.tutorial_close_requests(flow)
                    self.assertEqual(len(closes),1)
                    if feedback=='close_expired':
                        self.assertEqual(len(sent),1)
                        self.assertEqual(closes[0]['status'],'not_sent')
                    else:
                        self.assertEqual(len(sent),2)
                        self.assertAlmostEqual(du.time.monotonic()-sent[0],15,places=3)
                        self.assertEqual(closes[0]['feedback_status'],'unverified')

    def leave_unverified(self, directory):
        page=self.selected_frame()
        frames=[Scene(page.tokens,page.image) for _ in range(32)]
        with self.captured_flow(frames,directory=directory,seed_run=False) as (flow,window):
            flow.resume_active=True
            store=CurioDiscardStore(directory,self.ACCOUNT_A)
            button=page.find('丢弃',exact=True).center

            def check_custody(*args):
                if args[:2]==button:
                    self.assertIsNone(store.current()['resolution'])
                    ledger=json.loads((directory/'differential-universe-ledger.json').read_text(encoding='utf8'))
                    requested=[row for row in ledger['actions'] if row.get('intent')=='curio_discard_confirm']
                    self.assertEqual([row['status'] for row in requested],['requested'])

            window.click.side_effect=check_custody
            with self.assertRaisesRegex(AutomationError,'反馈待核对'):
                flow.run()
            self.assertEqual(self.confirm_clicks(window,page),1)
            self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')
        store=CurioDiscardStore(directory,self.ACCOUNT_A)
        state=store.current()
        self.assertIsNone(state['resolution'])
        original=Path(state['intent']['path'])
        before=Path(json.loads(original.read_text(encoding='utf8'))['before']['path'])
        ledger=directory/'differential-universe-ledger.json'
        return store, {path:path.read_bytes() for path in (original,before,ledger)}

    def test_separate_resume_blocks_same_account_before_selecting_and_preserves_originals(self):
        page=self.selected_frame()
        with TemporaryDirectory(prefix='AutoHSR-du-curio-resume-') as folder:
            root=Path(folder)
            store, originals=self.leave_unverified(root/'previous')
            with self.captured_flow([page],directory=root/'resume',seed_run=False) as (flow,window):
                flow.resume_active=True
                with self.assertRaisesRegex(AutomationError,'上次奇物舍弃反馈待核对'):
                    flow.run()
                window.click.assert_not_called()
                self.assertEqual(flow.report['completed_runs'],0)
            self.assertIsNone(store.current()['resolution'])
            for path,raw in originals.items():
                self.assertEqual(path.read_bytes(),raw)

    def test_abrupt_exit_at_raw_send_leaves_requested_intent_blocking_resume(self):
        page=self.selected_frame()
        with TemporaryDirectory(prefix='AutoHSR-du-curio-abrupt-') as folder:
            root=Path(folder)
            before=root/'previous'
            with self.captured_flow([page,Scene(page.tokens,page.image)],directory=before,
                                    seed_run=False) as (flow,window):
                flow.resume_active=True
                button=page.find('丢弃',exact=True).center

                def stop_process(*args):
                    if args[:2]==button:
                        raise KeyboardInterrupt('synthetic abrupt exit at raw send')

                window.click.side_effect=stop_process
                with self.assertRaises(KeyboardInterrupt):
                    flow.run()
                self.assertEqual(self.confirm_clicks(window,page),1)
            path=before/'differential-universe-ledger.json'
            original=path.read_bytes()
            actions=json.loads(original)['actions']
            self.assertEqual([row['status'] for row in actions if row.get('intent')=='curio_discard_confirm'],
                             ['requested'])
            with self.captured_flow([page],directory=root/'resume',seed_run=False) as (flow,window):
                flow.resume_active=True
                with self.assertRaisesRegex(AutomationError,'上次奇物舍弃反馈待核对'):
                    flow.run()
                window.click.assert_not_called()
            self.assertEqual(path.read_bytes(),original)

    def test_other_account_can_confirm_and_unclear_visible_account_cannot_select(self):
        page=self.selected_frame()
        with TemporaryDirectory(prefix='AutoHSR-du-curio-account-') as folder:
            root=Path(folder)
            store, originals=self.leave_unverified(root/'previous')
            unreadable=Scene([*page.tokens,Token('UID?',.80,(.04,.965,.09,.982))],page.image)
            with self.captured_flow([unreadable],directory=root/'unreadable',seed_run=False,
                                    account_for=lambda _:None) as (flow,window):
                flow.resume_active=True
                with self.assertRaisesRegex(AutomationError,'账号未完整核实'):
                    flow.run()
                window.click.assert_not_called()
            frames=[page,Scene(page.tokens,page.image),self.departed(),self.departed()]
            account=lambda _: self.ACCOUNT_B
            with self.captured_flow(frames,directory=root/'other',seed_run=False,account_for=account) as (flow,window):
                flow.resume_active=True
                with self.assertRaisesRegex(AutomationError,'差分宇宙已失败'):
                    flow.run()
                self.assertEqual(self.confirm_clicks(window,page),1)
            other=CurioDiscardStore(root/'other',self.ACCOUNT_B).current()
            result=json.loads(Path(other['resolution']['path']).read_text(encoding='utf8'))
            self.assertEqual(result['status'],'verified')
            self.assertIsNone(store.current()['resolution'])
            for path,raw in originals.items():
                self.assertEqual(path.read_bytes(),raw)

    def test_account_change_after_selection_or_after_send_cannot_clear_a_pending_source(self):
        page=self.selected_frame()
        for after_send in (False,True):
            with self.subTest(after_send=after_send):
                changed=self.departed() if after_send else Scene(page.tokens,page.image)
                frames=[page,Scene(page.tokens,page.image),changed] if after_send else [page,changed]
                account=lambda scene:self.ACCOUNT_B if scene is changed else self.ACCOUNT_A
                with self.captured_flow(frames,account_for=account) as (flow,window):
                    with self.assertRaisesRegex(AutomationError,'账号已改变'):
                        flow._progress_run(flow.ctx.snapshot(),'curio_discard')
                    self.assertEqual(self.confirm_clicks(window,page),int(after_send))
                    store=CurioDiscardStore(flow.ctx.report.run_dir,self.ACCOUNT_A)
                    if after_send:
                        self.assertIsNone(store.current()['resolution'])
                    else:
                        self.assertIsNone(store.current())

    def test_feedback_omission_in_either_phase_keeps_the_custody_pending(self):
        from autohsr import differential_universe as du
        from autohsr.currency_wars_identity import account_key
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        account=self.SYNTHETIC_ACCOUNT
        before=self.account_frame(self.selected_frame(),drawn=account,read=account)
        overlay=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        proved_overlay=self.account_frame(overlay,drawn=account,read=account)
        for phase in ('departure','overlay','after_close'):
            target=overlay if phase=='overlay' else self.departed()
            known=self.account_frame(target,drawn=account,read=account)
            # The rendered footer belongs to the other synthetic account, but
            # OCR dropped it. It cannot borrow the identity from earlier frames.
            missing=self.account_frame(target,drawn=self.SYNTHETIC_OTHER,read=None)
            for one_readable in (False,True):
                with self.subTest(phase=phase,one_readable=one_readable):
                    frames=[before]
                    if phase=='after_close':
                        frames.extend(self.copies(proved_overlay,2))
                    if one_readable:
                        frames.append(known)
                    frames.extend(self.copies(missing,30))
                    with self.captured_flow(frames,account_for=lambda _:None) as (flow,window):
                        scene=flow.ctx.snapshot()
                        sent=[]
                        window.click.side_effect=lambda *_: sent.append(du.time.monotonic())
                        with self.assertRaisesRegex(AutomationError,'限时内核实离页'):
                            flow._confirm_curio_discard(scene,scene.find('丢弃',exact=True))
                        self.assertEqual(self.confirm_clicks(window,before),1)
                        self.assertEqual(window.click.call_count,2 if phase=='after_close' else 1)
                        self.assertAlmostEqual(du.time.monotonic()-sent[0],15,places=3)
                        self.assertEqual(self.requests(flow)[0]['feedback_status'],'unverified')
                        state=CurioDiscardStore(flow.ctx.report.run_dir,account_key(before)).current()
                        self.assertIsNone(state['resolution'])

    def test_omission_breaks_each_pair_until_two_current_account_frames_reappear(self):
        from autohsr.currency_wars_identity import account_key
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        account=self.SYNTHETIC_ACCOUNT
        before=self.account_frame(self.selected_frame(),drawn=account,read=account)
        overlay=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        event=DuRuntimeTests.optional_device_fixture('event_star_choices')
        frames=[before]
        for page in (overlay,event):
            known=self.account_frame(page,drawn=account,read=account)
            missing=self.account_frame(page,drawn=account,read=None)
            frames.extend([known,missing,*self.copies(known,2)])
        with self.captured_flow(frames,account_for=lambda _:None) as (flow,window):
            scene=flow.ctx.snapshot()
            sent=[]
            window.click.side_effect=lambda *_: sent.append(flow.ctx.vision.read.call_count)
            after,kind=flow._confirm_curio_discard(scene,scene.find('丢弃',exact=True))
            self.assertIs(after,frames[-1])
            self.assertEqual(kind,'event')
            self.assertEqual(sent,[1,5])
            self.assertEqual(flow.ctx.vision.read.call_count,9)
            self.assertEqual([row['page_kind'] for row in flow.report['page_history']],
                             ['tutorial_overlay','tutorial_overlay','event','event'])
            state=CurioDiscardStore(flow.ctx.report.run_dir,account_key(before)).current()
            receipt=json.loads(Path(state['resolution']['path']).read_text(encoding='utf8'))
            self.assertEqual(receipt['status'],'verified')

    def test_old_overlay_pixels_are_a_veto_even_if_its_account_was_unreadable(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        account=self.SYNTHETIC_ACCOUNT
        before=self.account_frame(self.selected_frame(),drawn=account,read=account)
        reward=DuRuntimeTests.optional_device_fixture('reward_items_twenty')
        event=DuRuntimeTests.optional_device_fixture('event_star_choices')
        missing=self.account_frame(reward,drawn=account,read=None)
        ghost=self.account_frame(Scene(event.tokens,reward.image),drawn=account,read=account)
        last=self.account_frame(event,drawn=account,read=account)
        frames=[before,missing,*self.copies(ghost,2),*self.copies(last,1),last]
        with self.captured_flow(frames,account_for=lambda _:None) as (flow,window):
            scene=flow.ctx.snapshot()
            after,kind=flow._confirm_curio_discard(scene,scene.find('丢弃',exact=True))
            self.assertIs(after,last)
            self.assertEqual(kind,'event')
            self.assertEqual(window.click.call_count,1)

    def test_replayed_account_frame_cannot_complete_a_pair(self):
        from autohsr.currency_wars_identity import account_key

        account=self.SYNTHETIC_ACCOUNT
        before=self.account_frame(self.selected_frame(),drawn=account,read=account)
        known=self.account_frame(self.departed(),drawn=account,read=account)
        replay=self.copies(known,1)[0]
        missing=self.account_frame(self.departed(),drawn=account,read=None)
        frames=[before,known,replay,*self.copies(missing,30)]
        with self.captured_flow(frames,account_for=lambda _:None) as (flow,window):
            snapshot=flow.ctx.snapshot

            def repeat_capture_time():
                scene=snapshot()
                if scene is replay:
                    scene.captured_at=known.captured_at
                return scene

            flow.ctx.snapshot=repeat_capture_time
            scene=flow.ctx.snapshot()
            with self.assertRaisesRegex(AutomationError,'限时内核实离页'):
                flow._confirm_curio_discard(scene,scene.find('丢弃',exact=True))
            self.assertEqual(self.confirm_clicks(window,before),1)
            state=CurioDiscardStore(flow.ctx.report.run_dir,account_key(before)).current()
            self.assertIsNone(state['resolution'])

    def test_custody_write_or_readback_failure_stops_before_raw_confirmation(self):
        from autohsr import du_curio_discard_store as storage

        page=self.selected_frame()
        for fail_readback in (False,True):
            with self.subTest(fail_readback=fail_readback):
                with self.captured_flow([page]) as (flow,window):
                    before=flow.ctx.snapshot()
                    read=CurioDiscardStore.current
                    def cannot_read(store):
                        if store.pointer.is_file():
                            raise AutomationError(storage.ERROR)
                        return read(store)
                    failure=(patch.object(CurioDiscardStore,'current',cannot_read) if fail_readback
                             else patch.object(storage,'_write',side_effect=OSError('synthetic write failure')))
                    with failure, self.assertRaises(AutomationError):
                        flow._confirm_curio_discard(before,before.find('丢弃',exact=True))
                    window.click.assert_not_called()
                    self.assertEqual(self.requests(flow)[0]['status'],'not_sent')
                    store=CurioDiscardStore(flow.ctx.report.run_dir,self.ACCOUNT_A)
                    if fail_readback:
                        self.assertIsNone(store.current()['resolution'])
                    else:
                        self.assertIsNone(store.current())

    def test_verified_native_start_retires_old_pointer_without_reclassifying_failure(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        setup=DuRuntimeTests.optional_device_fixture('periodic_setup')
        header=Token('(1/13)第一位面-战斗',.99,(.04,.021,.23,.047))
        field=Scene([header],setup.image)
        self.assertEqual(classify_page(setup),'periodic_setup')
        self.assertEqual(classify_page(field),'field_combat')
        for scenario in ('fresh','different_account','older_field','missing_old_source','missing_start_png'):
            with self.subTest(scenario=scenario), TemporaryDirectory(prefix='AutoHSR-du-curio-start-') as folder:
                root=Path(folder)
                store, originals=self.leave_unverified(root/'previous')
                if scenario=='missing_old_source':
                    old_ledger=root/'previous'/'differential-universe-ledger.json'
                    old_ledger.rename(root/'previous'/'missing-source.json')
                landing=field
                if scenario=='older_field':
                    landing=Scene([Token('(11/13)第三位面-战斗',.99,header.box)],setup.image)
                account=lambda scene:self.ACCOUNT_B if scene is landing and scenario=='different_account' else self.ACCOUNT_A
                with self.captured_flow([setup,landing],directory=root/'fresh',seed_run=False,
                                        account_for=account) as (flow,window):
                    flow._select_preset_team=Mock(return_value=(setup,'periodic_setup'))
                    flow._progress_run=Mock(side_effect=AutomationError('已到定向测试终点'))
                    if scenario=='missing_start_png':
                        evidence=flow.ctx.evidence

                        def remove_fake_start(scene,label):
                            path=evidence(scene,label)
                            if label.endswith('_periodic_run_started'):
                                path.unlink()
                            return path

                        flow.ctx.evidence=remove_fake_start
                    message={'missing_old_source':'原账本或证据无法核实',
                             'missing_start_png':'证据文件不可核实'}.get(scenario,'已到定向测试终点')
                    with self.assertRaisesRegex(AutomationError,message):
                        flow.run()
                    self.assertEqual(window.click.call_count,1)
                    self.assertEqual(flow.report['completed_runs'],0)
                if scenario=='missing_old_source':
                    with self.assertRaisesRegex(AutomationError,'原账本或证据无法核实'):
                        store.current()
                    old_ledger.with_name('missing-source.json').rename(old_ledger)
                state=store.current()
                if scenario=='fresh':
                    result=json.loads(Path(state['resolution']['path']).read_text(encoding='utf8'))
                    self.assertEqual(result['status'],'superseded_by_verified_start')
                    self.assertNotEqual(result['fresh']['session_id'],
                                        json.loads(Path(state['intent']['path']).read_text(encoding='utf8'))['session_id'])
                    page=self.selected_frame()
                    frames=[page,Scene(page.tokens,page.image),self.departed(),self.departed()]
                    with self.captured_flow(frames,directory=root/'later',seed_run=False) as (flow,window):
                        flow.resume_active=True
                        with self.assertRaisesRegex(AutomationError,'差分宇宙已失败'):
                            flow.run()
                        self.assertEqual(self.confirm_clicks(window,page),1)
                else:
                    self.assertIsNone(state['resolution'])
                for path,raw in originals.items():
                    self.assertEqual(path.read_bytes(),raw)
