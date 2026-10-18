import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from autohsr.currency_wars_deployment import (require_distinct_front_pair, verify_front_swap,
    test_front_swap as run_probe, backend_layout, plan_bench_deployment, verify_bench_deployment,
    test_bench_deployment as run_deploy, _BENCH_FACE, _crop)
from autohsr.models import AutomationError, InputInterrupted, RunReport, Scene, Token
from autohsr.config import Settings


def frame(swapped=False, node='1-1'):
    root = Path(__file__).parent / 'fixtures/currency_wars_pages.json'
    tokens = [Token(**t) for t in json.loads(root.read_text(encoding='utf-8'))['pages']['preparation']['tokens']]
    tokens = [Token(node, t.score, t.box) if t.text == '1-1' else t for t in tokens]
    # Distinct visual identities independent of OCR names/deployment counters.
    image = np.zeros((1440, 2560, 3), dtype=np.uint8)
    texture1 = np.random.default_rng(41).integers(0, 256, (87, 90, 3), dtype=np.uint8)
    texture3 = np.random.default_rng(83).integers(0, 256, (87, 90, 3), dtype=np.uint8)
    image[475:562, 947:1037] = texture3 if swapped else texture1
    image[475:562, 1331:1421] = texture1 if swapped else texture3
    return Scene(tokens, image=image, captured_at=time.monotonic())


class SwapEvidenceTests(unittest.TestCase):
    def test_real_overflow_hatching_does_not_imitate_six_backend_slots(self):
        import cv2
        image=np.zeros((1440,2560,3),dtype=np.uint8)
        image[800:990,580:1940]=cv2.imread(str(Path(__file__).parent/'fixtures/currency_layout/overflow_backend.png'))
        self.assertEqual(backend_layout(image)[0],7)

    def test_crossed_visual_identity_verifies_but_same_count_does_not(self):
        before = frame()
        self.assertEqual(verify_front_swap(before, frame(True))['status'], 'verified')
        self.assertEqual(verify_front_swap(before, frame())['status'], 'unchanged')

    def test_changed_node_or_resolution_never_confirms_swap(self):
        self.assertEqual(verify_front_swap(frame(), frame(True, '1-2'))['status'], 'unknown')
        after = frame(True)
        after.image = after.image[::2, ::2]
        self.assertEqual(verify_front_swap(frame(), after)['status'], 'unknown')

    def test_partial_move_or_unrelated_portraits_never_confirms_both_identities(self):
        before, after = frame(), frame(True)
        after.image[475:562, 1331:1421] = 0
        self.assertNotEqual(verify_front_swap(before, after)['status'], 'verified')
        after.image[:] = np.random.default_rng(193).integers(0, 256, after.image.shape, dtype=np.uint8)
        self.assertEqual(verify_front_swap(before, after)['status'], 'unknown')

    def test_empty_slots_or_unrecognized_page_never_authorize_probe(self):
        for scene in (Scene([]), frame()):
            if scene.image is not None:
                scene.image[:] = 0
            with self.assertRaises(AutomationError):
                require_distinct_front_pair(scene)

    def test_probe_performs_one_drag_and_is_still_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            before, after = frame(), frame(True)
            c = SimpleNamespace(settings=Settings(), report=RunReport(run_dir=directory),
                runner=SimpleNamespace(input_epoch=0, emit=Mock()), scene_epoch=0, last_scene=None,
                checkpoint=Mock(), drag=Mock(), log=Mock())
            scenes = iter((before, after))
            def snapshot():
                c.last_scene = next(scenes)
                return c.last_scene
            c.snapshot = snapshot
            c.evidence = Mock(side_effect=lambda _, name: Path(directory) / (name + '.png'))
            result = run_probe(c)
            self.assertEqual(result.status, 'partial')
            c.drag.assert_called_once()
            data = json.loads((Path(directory) / 'currency-drag.json').read_text(encoding='utf-8'))
            self.assertEqual(data['action_status'], 'verified')
            self.assertFalse(data['completion_verified'])

    def test_interrupted_probe_preserves_pending_intent_and_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            before = frame()
            c = SimpleNamespace(settings=Settings(), report=RunReport(run_dir=directory),
                runner=SimpleNamespace(input_epoch=0, emit=Mock()), scene_epoch=0, last_scene=before,
                checkpoint=Mock(), drag=Mock(side_effect=InputInterrupted('paused')), log=Mock(),
                snapshot=Mock(return_value=before), evidence=Mock(return_value=Path(directory) / 'before.png'))
            with self.assertRaises(InputInterrupted):
                run_probe(c)
            c.drag.assert_called_once()
            self.assertEqual(c.report.currency_wars['action_status'], 'pending')
            self.assertEqual(json.loads((Path(directory) / 'currency-drag.json').read_text(encoding='utf-8'))['action_status'], 'pending')


def deployment_frame(count=7):
    import cv2
    scene = frame()
    scene.image[:] = (80, 35, 25)
    # Replace only the count field; preserve the real page's OCR anchors.
    import re
    from autohsr.models import normalize
    scene.tokens = [t for t in scene.tokens if not (t.within((.43,.18,.55,.36)) and re.fullmatch(r'[iIl|]?[0-9]+/[0-9]+', normalize(t.text)))]
    scene.tokens += [Token('5/6', .99, (.46,.20,.54,.25)), Token('17', .99, (.852,.84,.867,.86))]
    first = 710 if count == 7 else 805
    for i in range(count):
        cx = (first + 190*i) / 2560
        for side in (-1, 1):
            x = round((cx+side*.032)*2560)
            cv2.line(scene.image, (x, 800), (x, 990), (235, 235, 235), 2)
    portrait = _crop(scene.image, _BENCH_FACE)
    portrait[:] = np.random.default_rng(94).integers(0, 256, portrait.shape, dtype=np.uint8)
    return scene


class BenchDeploymentTests(unittest.TestCase):
    def test_selected_bench_slot_and_front_target_are_validated(self):
        from autohsr.currency_wars_deployment import bench_face
        scene = deployment_frame()
        plan = plan_bench_deployment(scene,source_slot=3,zone='front')
        self.assertEqual((plan.zone,plan.target_slot),('front',1))
        for slot,zone in ((0,'back'),(10,'front'),(True,'back'),(3,'invalid')):
            with self.assertRaises(AutomationError):
                plan_bench_deployment(scene,source_slot=slot,zone=zone)
        self.assertEqual(len(bench_face(9)),4)

    def test_front_deployment_requires_both_portrait_features(self):
        from autohsr.currency_wars_deployment import bench_face
        before,after=deployment_frame(),deployment_frame()
        plan=plan_bench_deployment(before,zone='front')
        face=_crop(before.image,bench_face(3))
        height,width=face.shape[:2]
        x,y=round(plan.end[0]*2560)-width//2,480
        after.image[y:y+height,x:x+width]=face
        _crop(after.image,bench_face(3))[:]=(80,35,25)
        after.tokens=[Token('6/6',t.score,t.box) if t.text=='5/6' else t for t in after.tokens]
        self.assertEqual(verify_bench_deployment(before,after,plan)['status'],'verified')
        after.image[y:y+round(.022*1440),x:x+width]=(80,35,25)
        self.assertEqual(verify_bench_deployment(before,after,plan)['status'],'unknown')

    def test_both_observed_layouts_and_flat_color_not_portrait(self):
        for count in (6, 7):
            scene = deployment_frame(count)
            self.assertEqual(backend_layout(scene.image)[0], count)
            self.assertEqual(plan_bench_deployment(scene).backend_slots, count)
            _crop(scene.image, _BENCH_FACE)[:] = (180, 20, 10)
            with self.assertRaises(AutomationError):
                plan_bench_deployment(scene)
        with self.assertRaises(AutomationError):
            backend_layout(np.zeros((1440,2560,3), dtype=np.uint8))

    def test_full_capacity_and_occupied_slots_reject_input(self):
        scene = deployment_frame()
        scene.tokens = [Token('6/6',t.score,t.box) if t.text=='5/6' else t for t in scene.tokens]
        with self.assertRaises(AutomationError):
            plan_bench_deployment(scene)
        scene = deployment_frame()
        for cx in backend_layout(scene.image)[1][:6]:
            patch = _crop(scene.image, (cx-.025,.58,cx+.025,.66))
            patch[:] = np.random.default_rng(19).integers(0,256,patch.shape,dtype=np.uint8)
        with self.assertRaises(AutomationError):
            plan_bench_deployment(scene)

    def moved(self):
        before, after = deployment_frame(), deployment_frame()
        plan = plan_bench_deployment(before)
        portrait = _crop(before.image, _BENCH_FACE)
        height, width = portrait.shape[:2]
        x, y = round(plan.end[0]*2560)-width//2, 850
        after.image[y:y+height,x:x+width] = portrait
        _crop(after.image, _BENCH_FACE)[:] = (80,35,25)
        after.tokens = [Token('6/6',t.score,t.box) if t.text=='5/6' else t for t in after.tokens]
        return before, after, plan

    def test_identity_source_empty_count_and_gold_required_together(self):
        before, after, plan = self.moved()
        self.assertEqual(verify_bench_deployment(before, after, plan)['status'], 'verified')
        self.assertEqual(verify_bench_deployment(before, before, plan)['status'], 'unchanged')
        # A count increase without a moved source is insufficient.
        _crop(after.image, _BENCH_FACE)[:] = _crop(before.image, _BENCH_FACE)
        self.assertEqual(verify_bench_deployment(before, after, plan)['status'], 'unknown')
        before, after, plan = self.moved()
        after.tokens = [Token('16',t.score,t.box) if t.text=='17' else t for t in after.tokens]
        self.assertEqual(verify_bench_deployment(before, after, plan)['status'], 'unknown')

    def test_single_action_and_pending_journal_survives_interruption(self):
        for interrupted in (False, True):
            before, after, _ = self.moved()
            with tempfile.TemporaryDirectory() as directory:
                c = SimpleNamespace(settings=Settings(), report=RunReport(run_dir=directory),
                    runner=SimpleNamespace(input_epoch=0,emit=Mock()), scene_epoch=0,last_scene=None,
                    checkpoint=Mock(),drag=Mock(side_effect=InputInterrupted('paused') if interrupted else None),log=Mock())
                scenes = iter((before, after))
                def snapshot():
                    c.last_scene = next(scenes)
                    return c.last_scene
                c.snapshot = snapshot
                c.evidence = Mock(side_effect=lambda _,name: Path(directory)/(name+'.png'))
                if interrupted:
                    with self.assertRaises(InputInterrupted):
                        run_deploy(c)
                else:
                    self.assertEqual(run_deploy(c).status, 'partial')
                c.drag.assert_called_once()
                journal = json.loads((Path(directory)/'currency-drag.json').read_text(encoding='utf-8'))
                self.assertEqual(journal['action_status'], 'pending' if interrupted else 'verified')
