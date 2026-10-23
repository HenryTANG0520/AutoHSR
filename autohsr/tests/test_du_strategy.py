"""Replay the user-designated blessing recommendation marker and priority."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import cv2
from autohsr.models import Scene,Token,RunReport
from autohsr.config import Settings
from autohsr.du_strategy import blessing_recommendation,blessing_score
from autohsr.differential_universe import DifferentialUniverseWorkflow


def page(name):
    root=Path(__file__).parent/'fixtures/du_runtime'/('blessing_recommended_'+name)
    data=json.loads(root.with_suffix('.json').read_text('utf8'))
    return Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']],
                 cv2.imread(str(root.with_suffix('.png')))),data['marked_columns']


class BlessingRecommendationTests(unittest.TestCase):
    def test_native_markers_stay_in_their_own_columns_across_resolutions(self):
        for name in ('right','two','none'):
            source,expected=page(name)
            for width in (960,1280,1920,3840):
                resized=Scene(source.tokens,cv2.resize(source.image,(width,round(width*9/16))))
                with self.subTest(name=name,width=width):
                    self.assertEqual([bool(blessing_recommendation(resized,x)) for x in (.25,.5,.755)],expected)

    def test_recommendation_beats_unmarked_higher_rarity_and_equation_completion(self):
        marked,_=page('right')
        marked=Scene([t for t in marked.tokens if t.center[1]<.87],marked.image)
        other=Scene([*marked.tokens,Token('3→4/4',.99,(.2,.92,.3,.95))],marked.image)
        right=Token('带标记的一星祝福',.99,(.735,.46,.775,.48))
        left=Token('未标记的三星祝福',.99,(.23,.46,.27,.48))
        with patch('autohsr.du_strategy.rarity',side_effect=lambda scene,x:1 if x>.6 else 3):
            preferred,reason=blessing_score(marked,right,preview=True)
            alternative,unmarked=blessing_score(other,left,preview=True)
        self.assertGreater(preferred,alternative)
        self.assertTrue(reason['recommended'])
        self.assertGreater(reason['recommendation_confidence'],.82)
        self.assertFalse(unmarked['recommended'])
        self.assertEqual(unmarked['equations_completed'],1)

    def test_green_color_without_the_badge_and_badge_in_body_do_not_count(self):
        source,_=page('none')
        im=source.image.copy()
        cv2.circle(im,(round(.335*1920),round(.253*1080)),17,(145,230,100),-1)
        self.assertFalse(blessing_recommendation(Scene(source.tokens,im),.25))
        marked,_=page('right')
        im=source.image.copy()
        im[540:630,610:716]=marked.image[216:306,round(.815*1920):round(.815*1920)+106]
        self.assertEqual([blessing_recommendation(Scene(source.tokens,im),x) for x in (.25,.5,.755)],[0,0,0])
        self.assertEqual(blessing_recommendation(Scene(source.tokens),.25),0)

    def test_preview_logs_recommendation_and_no_marker_preserves_equation_strategy(self):
        marked,_=page('right')
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._settle_blessing_titles=Mock(return_value=marked)
        flow._click=Mock(return_value=(marked,'blessing_choice'))
        flow._persist_ledger=Mock()
        self.assertEqual(flow._select_blessing(marked),(marked,'blessing_choice'))
        decision=flow.report['reward_decisions'][-1]
        self.assertTrue(decision['reason']['recommended'])
        self.assertEqual([v['recommended'] for v in decision['candidates']],[False,False,True])
        unmarked,_=page('none')
        ordinary=Scene([t for t in unmarked.tokens if t.center[1]<.87],unmarked.image)
        advancing=Scene([*ordinary.tokens,Token('3→4/4',.99,(.2,.92,.3,.95))],ordinary.image)
        target=Token('祝福候选卡片',.99,(.23,.46,.27,.48))
        self.assertGreater(blessing_score(advancing,target,preview=True)[0],
                           blessing_score(ordinary,target,preview=True)[0])
