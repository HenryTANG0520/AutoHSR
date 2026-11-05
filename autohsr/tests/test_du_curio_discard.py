import unittest
from unittest.mock import Mock
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow,classify_page
from autohsr.du_strategy import curio_card_selected
from autohsr.models import AutomationError,EmptyCapture,InputInterrupted,RunReport,Scene,Token
from autohsr.policy import du_curio_discard_page,du_tutorial_close_prompt,guard_differential_universe_click


class CurioDiscardTests(unittest.TestCase):
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

    def captured_flow(self,pages):
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests().captured_du_flow(pages)

    def confirm_clicks(self,window,page):
        button=page.find('丢弃',exact=True).center
        return sum(call.args[:2]==button for call in window.click.call_args_list)

    @staticmethod
    def requests(flow):
        return [row for row in flow.report['actions'] if row.get('intent')=='curio_discard_confirm']

    @staticmethod
    def departed():
        return Scene([Token('战斗失败',.99,(.44,.19,.56,.23))])

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
