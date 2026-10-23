"""Station-card regressions, including OCR segmentation and level bonuses."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.du_card_effects import REGIONS, station_card_effect
from autohsr.models import AutomationError, RunReport, Scene, Token
from autohsr.policy import du_miracle_target_labels, guard_differential_universe_click


def token(text, x=.3, y=.147):
    return Token(text, .99, (x-.02, y-.01, x+.02, y+.01))


def selector(instruction):
    return Scene([token('选择站点卡', .09, .07), token('抽牌区', .06, .20),
                  token(instruction), token('弃牌区', .06, .44),
                  token('铸造', .12, .48), token('确定', .85, .89)])


class StationCardEffectTests(unittest.TestCase):
    def test_native_growing_curio_beacon_uses_one_region_selection(self):
        data=json.loads((Path(__file__).parent/'fixtures/du_runtime/growing_beacon_target.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        effect=station_card_effect(page)
        self.assertEqual((effect.kind,effect.count,effect.reward_count,effect.growth_threshold),
                         ('growing_beacon',1,1,10))
        self.assertEqual(effect.growth_name,'武装考古铲高级')
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('战斗',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        done=Scene([token('信标已部署',.5,.15),token('点击空白处关闭',.5,.9)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(done,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(done,'tutorial_overlay'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'tutorial_overlay'))
        self.assertEqual(flow._click.call_count,2)

    def test_growing_beacon_quantities_thresholds_and_names_are_data_not_click_counts(self):
        for quantity,threshold,name in ((1,10,'武装考古铲'),(2,12,'示例成长奇物'),(3,20,'测试装置')):
            instruction=f'立即获得{quantity}个随机信标。进入区域后，若持有的信标数量大于等于{threshold}，则升级为【{name}（高级）】'
            page=selector(instruction)
            effect=station_card_effect(page)
            self.assertEqual((effect.count,effect.reward_count,effect.growth_threshold,effect.growth_name),
                             (1,quantity,threshold,name+'高级'))
            self.assertEqual(effect.target_labels,REGIONS)
            guard_differential_universe_click(page,page.find('铸造',exact=True),intent='miracle_target')
        valid='立即获得1个随机信标。进入区域后，若持有的信标数量大于等于10，则升级为【武装考古铲（高级）】'
        for altered in ('支付60宇宙碎片'+valid,valid+'并消耗60星琼',valid.replace('获得1个','获得0个'),
                        valid.replace('获得1个','获得1.5个'),valid.replace('等于10','等于0'),
                        valid.replace('随机信标','随机负面信标')):
            with self.subTest(altered=altered):
                self.assertIsNone(station_card_effect(selector(altered)))

    def test_native_snow_owl_optimization_reuses_single_loss_receipt(self):
        data=json.loads((Path(__file__).parent/'fixtures/du_runtime/snow_owl_optimization.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        effect=station_card_effect(page)
        self.assertEqual((effect.kind,effect.count),('delete',1))
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('冒险',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        loss=Scene([token('失去站点卡',.5,.15),token('失去数量：1',.5,.21),
                    token('点击空白处关闭',.5,.9)])
        done=Scene([token('(3/13) 第一位面-战斗',.1,.04)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(loss,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(loss,'tutorial_overlay'))
        flow._close_tutorial=Mock(return_value=(done,'field_combat'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'field_combat'))
        self.assertEqual(flow._click.call_args_list[0].args[1],card)
        self.assertEqual(flow._click.call_count,2)
        for text in ('优化阶段，请删除2个指定区域','优化阶段，请删除1个指定区域并消耗60星琼',
                     '支付60宇宙碎片优化阶段，请删除1个指定区域'):
            self.assertIsNone(station_card_effect(selector(text)))

    def test_native_delete_instruction_uses_sequential_single_card_receipts(self):
        data=json.loads((Path(__file__).parent/'fixtures/du_runtime/delete_two_regions.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        effect=station_card_effect(page)
        self.assertEqual((effect.kind,effect.count,effect.target_labels[:2]),('delete',2,('冒险','商店')))
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('冒险',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        loss=Scene([token('失去站点卡',.5,.15),token('失去数量：1',.5,.21),
                    token('点击空白处关闭',.5,.9)])
        second=Scene([t for t in page.tokens if t is not card])
        done=Scene([token('选择下一站',.1,.05)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(loss,'tutorial_overlay'),
                                     (second,'miracle_target'),(loss,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(loss,'tutorial_overlay'))
        flow._close_tutorial=Mock(side_effect=[(second,'miracle_target'),(done,'station_choice')])
        self.assertEqual(flow._apply_miracle_target(page),(done,'station_choice'))
        self.assertEqual([c.args[1].text for c in flow._click.call_args_list][::2],['冒险','商店'])
        self.assertEqual(flow._close_tutorial.call_count,2)

    def test_delete_can_resume_remaining_card_but_never_repeats_without_loss_receipt(self):
        page=selector('立即删除2个指定区域');page.tokens.append(token('商店',.3,.5))
        loss=Scene([token('失去站点卡',.5,.15),token('失去数量：1',.5,.21),
                    token('点击空白处关闭',.5,.9)])
        done=Scene([token('选择下一站',.1,.05)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(loss,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(loss,'tutorial_overlay'))
        flow._close_tutorial=Mock(return_value=(done,'station_choice'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'station_choice'))
        self.assertEqual(flow._click.call_count,2)
        wrong=Scene([token('失去站点卡',.5,.15),token('失去数量：2',.5,.21)])
        flow._click=Mock(side_effect=[(page,'miracle_target'),(wrong,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(wrong,'tutorial_overlay'))
        flow._close_tutorial=Mock()
        with self.assertRaisesRegex(AutomationError,'逐张失去1张'):
            flow._apply_miracle_target(page)
        flow._close_tutorial.assert_not_called()
        self.assertEqual(flow._click.call_count,2)

    def test_delete_count_is_data_and_instruction_must_be_free_and_complete(self):
        # Larger values exercise parsing, not a claim about the game's cap.
        for count in (1,2,3,20):
            page=selector(f'立即删除{count}个指定区域')
            self.assertEqual(station_card_effect(page).count,count)
        for text in ('立即删除0个指定区域','立即删除-2个指定区域','立即删除2.5个指定区域',
                     '支付60星琼立即删除2个指定区域','立即删除2个指定区域并消耗60宇宙碎片'):
            self.assertIsNone(station_card_effect(selector(text)))

    def test_native_region_copies_are_one_target_with_separate_output_quantity(self):
        data=json.loads((Path(__file__).parent/'fixtures/du_runtime/copy_region_target.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        effect=station_card_effect(page)
        self.assertEqual((effect.kind,effect.count,effect.copies,effect.target_labels[0]),('copy',1,2,'战斗'))
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('战斗',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        done=Scene([token('获得站点卡',.5,.15),token('获得数量：2',.5,.21),token('点击空白处关闭',.5,.9)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(done,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(done,'tutorial_overlay'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'tutorial_overlay'))
        self.assertEqual(flow._click.call_count,2)
        for body in ('获得0个该区域的复制','获得-2个该区域的复制','获得2.5个该区域的复制',
                     '获得2个该区域的复制并消耗60星琼'):
            self.assertIsNone(station_card_effect(selector('指定1个区域，'+body)))

    def test_copy_quantity_change_after_selection_blocks_confirmation(self):
        page=selector('指定1个区域，获得2个该区域的复制')
        page.tokens.append(token('战斗',.3,.5))
        changed=selector('指定1个区域，获得3个该区域的复制')
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(return_value=(changed,'miracle_target'))
        with self.assertRaisesRegex(AutomationError,'选中后指令改变'):
            flow._apply_miracle_target(page)
        self.assertEqual(flow._click.call_count,1)

    def test_native_single_target_conversion_and_reward_forms(self):
        fixtures=Path(__file__).parent/'fixtures/du_runtime'
        expected={
            'random_single_target':('randomize','',0,()),
            'beacon_postfix_name':('beacon','',0,()),
            'blank_currency_150':('transform','cosmic_fragments',150,()),
            'blank_currency_275':('transform','cosmic_fragments',275,()),
            'blank_random_blessings':('transform','random_blessings',2,(1,2)),
            'blank_equation_blessings':('transform','equation_blessings',3,()),
        }
        for name,details in expected.items():
            with self.subTest(name=name):
                data=json.loads((fixtures/f'{name}.json').read_text('utf8'))
                page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
                effect=station_card_effect(page)
                self.assertIsNotNone(effect)
                self.assertEqual((effect.kind,effect.reward_kind,effect.reward_count,effect.reward_star_range),details)
                self.assertEqual(effect.count,1)
                self.assertEqual(classify_page(page),'miracle_target')
                if name=='beacon_postfix_name':
                    self.assertEqual(effect.beacons,('必吃榜',))
                card=next(t for label in effect.target_labels for t in page.tokens
                          if t.text==label and t.within((.03,.24,.64,.78)))
                guard_differential_universe_click(page,card,intent='miracle_target')
                done=Scene([token('点击空白处关闭',.5,.9)])
                flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
                flow._click=Mock(side_effect=[(page,'miracle_target'),(done,'tutorial_overlay')])
                flow._snapshot=Mock(return_value=(done,'tutorial_overlay'))
                self.assertEqual(flow._apply_miracle_target(page),(done,'tutorial_overlay'))
                self.assertEqual(flow._click.call_count,2)

    def test_blank_rewards_require_complete_positive_effect_and_remain_bound_after_selection(self):
        text='指定1个区域，使其变为【空白】区域。然后获得150宇宙碎片'
        for altered in (text+'并消耗60星琼',text.replace('150','-150'),text.replace('150','1.5'),
                        text.replace('1个区域','2个区域'),text.replace('150宇宙碎片','2个随机3-1星祝福')):
            self.assertIsNone(station_card_effect(selector(altered)),altered)
        page=selector(text);page.tokens.append(token('事件',.3,.5))
        changed=selector(text.replace('150','275'))
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(return_value=(changed,'miracle_target'))
        with self.assertRaisesRegex(AutomationError,'选中后指令改变'):
            flow._apply_miracle_target(page)
        self.assertEqual(flow._click.call_count,1)

    def test_native_upgrade_with_negative_beacon_is_one_card_effect(self):
        data=json.loads((Path(__file__).parent/'fixtures/du_runtime/upgrade_negative_beacon.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        effect=station_card_effect(page)
        self.assertEqual((effect.kind,effect.count,effect.level_delta,effect.beacons,effect.beacon_polarity),
                         ('upgrade',1,2,('随机',),'负面'))
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('战斗',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        done=Scene([token('站点卡升级',.5,.15),token('点击空白处关闭',.5,.9)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(done,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(done,'tutorial_overlay'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'tutorial_overlay'))
        self.assertEqual(flow._click.call_count,2)

    def test_upgrade_and_beacon_bonus_are_parsed_independently(self):
        for delta in (1,2,3,20):
            for source in ('','【战斗】'):
                for polarity in ('','正面','负面'):
                    text=f'指定1个{source}区域，使其等级+{delta}，但为其附加1个随机{polarity}信标'
                    effect=station_card_effect(selector(text))
                    self.assertEqual((effect.level_delta,effect.beacon_polarity),(delta,polarity))
                    self.assertEqual(effect.target_labels[0],'战斗')
        text='指定1个区域，使其等级+2，但为其附加1个随机负面信标'
        for altered in (text+'并消耗60星琼',text.replace('附加1个','附加2个'),text.replace('信标','奇物')):
            self.assertIsNone(station_card_effect(selector(altered)))

    def test_beacon_polarity_change_after_selection_stops_confirmation(self):
        text='指定1个区域，使其等级+2，但为其附加1个随机负面信标'
        page=selector(text);page.tokens.append(token('战斗',.3,.5))
        changed=selector(text.replace('负面','正面'))
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(return_value=(changed,'miracle_target'))
        with self.assertRaisesRegex(AutomationError,'选中后指令改变'):
            flow._apply_miracle_target(page)
        self.assertEqual(flow._click.call_count,1)

    def test_unrestricted_and_alternative_source_upgrades_share_numeric_parser(self):
        for sources in ('', '【事件】或【异常】'):
            for delta in (1, 2, 3, 4, 20):
                page=selector(f'指定1个{sources}区域，使其等级+{delta}')
                effect=station_card_effect(page)
                self.assertEqual(effect.level_delta, delta)
                self.assertEqual(effect.source_regions, ('事件','异常') if sources else ())
                self.assertEqual(effect.target_labels[0], '事件' if sources else '战斗')
                self.assertEqual(classify_page(page), 'miracle_target')
                guard_differential_universe_click(page, token(effect.target_labels[0],.12,.48),intent='miracle_target')

    def test_native_any_region_upgrade_selects_combat_and_confirms_once(self):
        data=json.loads((Path(__file__).parent/'fixtures/du_runtime/any_region_upgrade.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        effect=station_card_effect(page)
        self.assertEqual((effect.kind,effect.source_regions,effect.level_delta),('upgrade',(),2))
        self.assertEqual(classify_page(page),'miracle_target')
        self.assertTrue(page.has('等级3'))  # Preview's existing level is not the bonus.
        done=Scene([token('点击空白处关闭',.5,.9)])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(done,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(done,'tutorial_overlay'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'tutorial_overlay'))
        card=flow._click.call_args_list[0].args[1]
        self.assertEqual(card.text,'战斗')
        self.assertEqual(flow._click.call_count,2)
        guard_differential_universe_click(page,card,intent='miracle_target')

    def test_level_bonus_is_numeric_for_every_known_region(self):
        # 4 and 20 test parser generality, not a claim about the client's cap.
        for name in REGIONS:
            for delta in (1, 2, 3, 4, 20):
                with self.subTest(region=name, delta=delta):
                    page=selector(f'指定1个【{name}】区域，使其等级+{delta}')
                    effect=station_card_effect(page)
                    self.assertEqual((effect.kind, effect.count, effect.level_delta), ('upgrade', 1, delta))
                    self.assertEqual(effect.target_labels, (name,))
                    self.assertEqual(classify_page(page), 'miracle_target')
                    guard_differential_universe_click(page, token(name, .12, .48), intent='miracle_target')

    def test_fullwidth_numbers_plus_and_spacing_share_numeric_parser(self):
        for delta in (1, 2, 3):
            fullwidth=chr(ord('０')+delta)
            page=selector(f'指定 １ 个【铸造】区域，使其等级 ＋ {fullwidth}。')
            self.assertEqual(station_card_effect(page).level_delta, delta)
        self.assertEqual(station_card_effect(selector('指定一个【铸造】区域，使其等级+一')).level_delta, 1)

    def test_split_ocr_is_joined_in_visual_reading_order(self):
        page=selector('unused')
        page.tokens.pop(2)
        page.tokens.extend([token('＋ ３', .57, .147), token('区域，使其等级', .40, .148),
                            token('指定1个【铸造】', .17, .146)])
        self.assertEqual(station_card_effect(page).level_delta, 3)
        page.tokens.append(token('并消耗60星琼', .34, .17))
        self.assertIsNone(station_card_effect(page))

    def test_level_and_conversion_bonuses_preserve_source_vs_output(self):
        for delta in (1, 2, 3, 20):
            page=selector(f'指定1个【事件】或【异常】区域，使其变为+{delta}等级的【战斗】区域')
            effect=station_card_effect(page)
            self.assertEqual((effect.source_regions, effect.output_regions, effect.level_delta),
                             (('事件', '异常'), ('战斗',), delta))
            for source in effect.source_regions:
                guard_differential_universe_click(page, token(source, .12, .48), intent='miracle_target')
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page, token('战斗', .12, .48), intent='miracle_target')

    def test_bad_numbers_costs_and_unsupported_counts_do_not_authorize_clicks(self):
        for body in ('使其等级+0', '使其等级-3', '使其等级+3.5', '使其等级+3/5',
                     '使其等级+3%', '使其等级+I', '使其等级+3并消耗60宇宙碎片',
                     '花费60星琼使其等级+3', '使其等级+3然后移除1个区域'):
            self.assertIsNone(station_card_effect(selector('指定1个【铸造】区域，'+body)), body)
        for text in ('指定2个【铸造】区域，使其等级+3', '指定1个【未知】区域，使其等级+3',
                     '指定2个区域，获得2个该区域的复制', '支付60星琼指定1个【铸造】区域，使其等级+3'):
            self.assertIsNone(station_card_effect(selector(text)), text)

    def test_body_preview_and_other_instruction_cannot_supply_missing_bonus(self):
        page=selector('指定1个【铸造】区域，使其等级+')
        page.tokens.extend([token('3', .80, .70), token('指定1个【铸造】区域，使其等级+3', .80, .60)])
        self.assertIsNone(station_card_effect(page))
        page=selector('指定1个【铸造】区域，使其等级+1')
        page.tokens.append(token('指定1个【战斗】区域，使其等级+3', .30, .17))
        self.assertIsNone(station_card_effect(page))

    def test_instruction_is_required_in_the_observed_header_strip(self):
        for x, y in ((.3, .06), (.3, .55), (.8, .2)):
            page=selector('指定1个【铸造】区域，使其等级+3')
            page.tokens[2]=token(page.tokens[2].text, x, y)
            self.assertIsNone(station_card_effect(page))
        page=selector('指定1个【铸造】区域，使其等级+3')
        page.tokens.pop(0)
        self.assertIsNone(station_card_effect(page))

    def test_native_instructions_separate_upgrade_transform_and_beacon(self):
        for name, expected in (('forge_plus_three', ('upgrade', 3)), ('station_transform', ('transform', 1)),
                               ('station_beacon_target', ('beacon', 0)), ('any_region_beacon', ('beacon', 0)),
                               ('random_two_target', ('randomize', 0))):
            data=json.loads((Path(__file__).parent/'fixtures/du_runtime'/f'{name}.json').read_text('utf8'))
            page=Scene([Token(v['text'], v['score'], tuple(v['box'])) for v in data['tokens']])
            effect=station_card_effect(page)
            self.assertEqual((effect.kind, effect.level_delta), expected, name)
            if name=='station_beacon_target':
                self.assertEqual((effect.source_regions, effect.beacons, effect.removed_region),
                                 (('战斗',), ('奇物扑满', '祝福扑满'), '精英'))

    def test_discard_card_is_selectable_without_using_right_hand_preview(self):
        page=selector('指定1个【铸造】区域，使其等级+3')
        preview=token('铸造', .80, .35)
        page.tokens.append(preview)
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(), report=RunReport()), 1)
        self.assertEqual(flow._find(page, du_miracle_target_labels(page), (.03,.24,.64,.78)), page.tokens[4])
        guard_differential_universe_click(page, page.tokens[4], intent='miracle_target')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page, preview, intent='miracle_target')

    def test_confirm_is_not_sent_if_effect_changes_after_selection(self):
        page=selector('指定1个【铸造】区域，使其等级+3')
        changed=selector('指定1个【铸造】区域，使其等级+2')
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(), report=RunReport()), 1)
        flow._click=Mock(return_value=(changed, 'miracle_target'))
        with self.assertRaisesRegex(AutomationError, '选中后指令改变'):
            flow._apply_miracle_target(page)
        self.assertEqual(flow._click.call_count, 1)

    def test_beacon_quantity_is_distinct_from_card_level_increment(self):
        for count in (2, 3):
            self.assertIsNone(station_card_effect(selector(f'指定1个【铸造】区域，为其附加{count}个【基石】信标')))
        effect=station_card_effect(selector('指定一个区域，为其附加【基石】信标'))
        self.assertEqual((effect.kind, effect.level_delta, effect.target_labels[0]), ('beacon', 0, '战斗'))
