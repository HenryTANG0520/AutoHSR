"""Supply text custody in the existing band; synthetic multi-item grammar only."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from autohsr.currency_wars_supply_fields import CENTERS, equipment_names, rows
from autohsr.models import AutomationError, Scene, Token
from autohsr.tests import test_currency_wars_supply_refresh as fixtures


class SupplyFieldTests(unittest.TestCase):
    def test_single_and_explicit_pair_keep_duplicate_names(self):
        for text, expected in (('光能电池', ('光能电池',)),
                ('量产型装甲、光能电池', ('量产型装甲', '光能电池')),
                ('光能电池 + 光能电池', ('光能电池', '光能电池')),
                ('光能电池＋未校准装备', ('光能电池', '未校准装备'))):
            with self.subTest(text=text):
                self.assertEqual(equipment_names(Token(text, .99, (.1,.62,.17,.66))), expected)
        for text in ('光能电池、', '、光能电池', '光能电池+2', '光能电池×2',
                '光能电池、量产型装甲、轮滑鞋', '光能电池/量产型装甲', '光能电池，量产型装甲',
                '光能电池\n量产型装甲', '光能电池；量产型装甲', '光能电池?', '光能电池(已选)', ''):
            with self.subTest(text=text), self.assertRaises(AutomationError):
                equipment_names(Token(text, .99, (.1,.62,.17,.66)))

    def replace_items(self, page, count, forms):
        page.tokens=[t for t in page.tokens if not t.within((.03,.61,.97,.67))]
        for x, form in zip(CENTERS[count], forms):
            if form=='whole':
                page.tokens.append(Token('量产型装甲、光能电池', .99, (x-.06,.62,x+.06,.66)))
            elif form=='horizontal':
                page.tokens.extend((Token('量产型装甲', .99, (x-.06,.62,x-.002,.66)),
                                    Token('光能电池', .99, (x+.002,.62,x+.06,.66))))
            elif form=='vertical':
                page.tokens.extend((Token('量产型装甲', .99, (x-.05,.612,x+.05,.634)),
                                    Token('光能电池', .99, (x-.05,.642,x+.05,.665))))
            else:
                page.tokens.append(Token('光能电池', .99, (x-.05,.62,x+.05,.66)))

    def test_four_and_five_columns_keep_all_visible_names(self):
        for count in (4,5):
            _,page,_=fixtures.fixture(count)
            self.replace_items(page,count,('whole','horizontal','vertical','single','whole'))
            fields=rows(page)
            self.assertEqual(len(fields),count)
            for i,_,item in fields:
                self.assertEqual(equipment_names(item),('光能电池',) if i==3 else ('量产型装甲','光能电池'))

    def test_missing_overlapping_low_confidence_and_cross_column_items_stop(self):
        _,page,_=fixtures.fixture(5)
        self.replace_items(page,5,('single',)*5)
        for case in ('missing','duplicate','overlap','cross','low','edge','outside_band','extra'):
            changed=deepcopy(page)
            t=next(t for t in changed.tokens if t.within((.03,.61,.22,.67)))
            if case=='missing': changed.tokens.remove(t)
            elif case=='duplicate': changed.tokens.append(t)
            elif case=='overlap': changed.tokens.append(Token('轮滑鞋',.99,(.11,.63,.18,.66)))
            elif case=='cross':
                changed.tokens.remove(t);changed.tokens.append(Token(t.text,.99,(.02,.62,.24,.66)))
            elif case=='low':
                changed.tokens.remove(t);changed.tokens.append(Token(t.text,.4,t.box))
            elif case=='edge':
                changed.tokens.remove(t);changed.tokens.append(Token(t.text,.99,(.01,.62,.25,.66)))
            elif case=='outside_band':
                changed.tokens.remove(t);changed.tokens.append(Token(t.text,.99,(.08,.60,.18,.66)))
            else: changed.tokens.append(Token('未知装备',.99,(.96,.62,.98,.66)))
            with self.subTest(case=case),self.assertRaises(AutomationError): rows(changed)

    def test_legacy_real_anonymous_ocr_retains_unknown_equipment_names(self):
        path=Path(__file__).parent/'fixtures/currency_wars_supply_plane3.json'
        value=json.loads(path.read_text(encoding='utf8'))
        scene=Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in value['tokens']])
        actual=[equipment_names(t) for _,_,t in rows(scene)]
        self.assertEqual(actual,[('步步生花',),('流星飞翼',),('信心注入器',),('天基轨道炮',),('蓄能帆',)])

    def test_extra_equipment_outside_calibrated_band_never_becomes_one_item(self):
        _,page,_=fixtures.fixture(5)
        for name in ('光能电池','未校准装备'):
            for score in (.99,.4):
                changed=deepcopy(page)
                changed.tokens.append(Token(name,score,(.08,.70,.18,.73)))
                with self.subTest(name=name,score=score),self.assertRaises(AutomationError):rows(changed)


if __name__=='__main__':
    unittest.main()
