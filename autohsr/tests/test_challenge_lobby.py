"""Exercise the dedicated guide entry with real CLI dispatch and fake game I/O."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.challenge_lobby import MODES, OPERATION, next_action, observe
from autohsr.config import RESOURCE_ROOT, Settings
from autohsr.models import EmptyCapture, Scene, Token
from autohsr.vision import Vision
from autohsr.windows import Geometry


AP = 'apocalyptic_shadow'
MOC = 'memory_of_chaos'
FICTION = 'pure_fiction'
GEOMETRY = Geometry(0, 0, 1920, 1080)
UID = Token('UID:100000000', .99, (.01, .96, .11, .985))
GUIDE = Token('星际和平指南', .99, (.051,.033,.116,.062))


def field(text, x, y, width=.065, height=.027):
    return Token(text, .99, (x, y, x+width, y+height))


def frame(*tokens, image=None):
    if image is None:
        image = np.full((1080,1920,3), 62, np.uint8)
    return Scene([UID, *tokens], image, GEOMETRY)


def survival():
    scene = frame(GUIDE, field('生存索引', .052,.061))
    icon = cv2.imread(str(RESOURCE_ROOT/'assets/templates/high_guide_tab.png'))
    assert icon is not None
    h, w = icon.shape[:2]
    scene.image[204:204+h,703:703+w] = icon
    return scene


def high(mode=None, *, teleport=True):
    tokens = [GUIDE, field('逐光捡金', .052,.061), field('忘却之庭', .157,.526),
              field('虚构叙事', .157,.648), field('末日幻影', .157,.770)]
    if mode is not None:
        tokens.append(field(MODES[mode][1], .484,.313))
        if teleport:
            tokens.append(field('传送', .794,.599,.028))
    else:
        tokens.extend((field('异相仲裁', .48,.315), field('前往挑战', .711,.797)))
    return frame(*tokens)


def stellar():
    return frame(field('末日幻影', .052,.046), field('支配遗忘', .449,.503,.105,.043),
                 field('星启模式', .485,.674), field('更换编队', .877,.669,.046,.025),
                 field('节点一', .266,.749,.036), field('节点二', .466,.749,.036),
                 field('节点三', .666,.749,.036), field('重新挑战', .345,.813,.044))


def chaos_notice():
    return frame(field('物竞天择', .374,.361), field('已更新', .458,.364,.040),
                 field('记忆紊流', .374,.407,.048), field('我方目标施放终结技时获得5个笑点。', .374,.450,.203),
                 field('点击空白处关闭', .456,.787,.089,.025))


def chaos_map():
    return frame(field('忘却之庭', .052,.036,.044,.025), field('混沌回忆', .053,.060,.054,.028),
                 field('物竞天择', .064,.117,.082,.041), field('奇珍琳琅', .097,.870,.056,.034),
                 field('08', .097,.437,.040,.054), field('09', .295,.513,.038,.051),
                 field('10', .476,.585,.036,.050), field('12', .835,.368,.034,.049))


def fiction_notice():
    return frame(field('取象为文', .730,.284,.085,.037), field('已更新', .754,.344,.039,.026),
                 field('战意机制', .751,.400,.050,.026), field('施加负面效果', .739,.434,.075,.027),
                 field('战意效果', .748,.609,.052,.026), field('开启故事', .756,.815,.053,.029))


def fiction_map():
    return frame(field('虚构叙事', .085,.062,.048,.025), field('取象为文', .073,.102,.074,.031),
                 field('奇珍琳琅', .104,.872,.054,.031), field('02', .604,.314,.024,.033),
                 field('03', .683,.665,.024,.033), field('04', .810,.456,.024,.033),
                 field('未解锁', .81,.489,.052,.035))


def native_cli(root, scenes, *, mode=AP, stop_at_submit=False):
    config = root/'config.json'
    Settings(overlay_logs=True).save(config)
    saved = config.read_bytes()
    frames = iter(scenes)
    current = None
    real_template = Vision.__new__(Vision).template

    def capture():
        nonlocal current
        current = next(frames, None)
        if current is None:
            raise EmptyCapture('fixture transition')
        return current.image.copy(), GEOMETRY

    def read(image, geometry):
        return Scene(list(current.tokens), image, geometry)

    positions = []

    def send(x, y, geometry, *, before_submit):
        assert geometry == GEOMETRY
        before_submit()
        positions.append((x, y))

    window = Mock(hwnd=1, capture=Mock(side_effect=capture), click=Mock(side_effect=send))
    window.emergency_pressed.return_value = stop_at_submit
    kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
    clock = SimpleNamespace(monotonic=count(1000.,.01).__next__)
    vision = SimpleNamespace(read=read, template=real_template)
    output = io.StringIO()
    with ExitStack() as stack:
        for name, value in (('ROOT',root), ('find_game',Mock(return_value=window)),
                            ('Vision',Mock(return_value=vision)), ('is_elevated',Mock(return_value=False))):
            stack.enter_context(patch('autohsr.app.'+name, value))
        stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
        stack.enter_context(patch('autohsr.app.threading.Thread'))
        stack.enter_context(patch('autohsr.windows.kernel32', kernel))
        stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
        stack.enter_context(patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no launch')))
        stack.enter_context(patch('autohsr.overlay.OverlayService', side_effect=AssertionError('no overlay')))
        stack.enter_context(patch.object(Context, 'sleep', lambda ctx, seconds: ctx.checkpoint()))
        for module in ('app', 'challenge_lobby', 'challenge_pages'):
            stack.enter_context(patch(f'autohsr.{module}.time', clock))
        stack.enter_context(redirect_stdout(output))
        stack.enter_context(redirect_stderr(io.StringIO()))
        code = main(['--challenge-lobby',mode,'--config',str(config)])
    assert config.read_bytes() == saved
    for method in (window.focus,window.key,window.move,window.drag,window.send):
        method.assert_not_called()
    return code, json.loads(output.getvalue()), positions


class ChallengeLobbyTests(unittest.TestCase):
    def test_right_hand_title_only_authorizes_its_own_teleport(self):
        c = SimpleNamespace(settings=Settings())
        for mode, (label, _) in MODES.items():
            with self.subTest(mode=mode):
                self.assertEqual(next_action(c,high(),mode).target.text,label)
                self.assertEqual(next_action(c,high(mode),mode).intent,'enter_lobby')
                self.assertIsNone(next_action(c,high(mode,teleport=False),mode))
        self.assertEqual(next_action(c,high(FICTION),MOC).intent,'open_mode_card')
        mixed = high(AP)
        mixed.tokens.append(field('混沌回忆', .488,.316))
        self.assertIsNone(next_action(c,mixed,AP))
        duplicate = high(AP)
        duplicate.tokens.append(Token('传送', .74, (.801,.601,.831,.627)))
        self.assertIsNone(next_action(c,duplicate,AP))
        for token in (Token('末日幻影', .74, (.484,.315,.55,.34)),
                      Token('混沌回忆', .74, (.484,.315,.55,.34))):
            with self.subTest(token=token):
                mixed = high(AP)
                mixed.tokens.append(token)
                self.assertIsNone(next_action(c,mixed,AP))

    def test_native_cli_goes_from_survival_to_lobby_with_three_persisted_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            stages = [survival(),survival(),high(),high(),high(AP),high(AP),stellar(),stellar()]
            code, report, positions = native_cli(Path(directory), stages)
            data = report['challenge']
            self.assertEqual((code,report['status'],report['report_saved']),(0,'success',True))
            self.assertEqual(report['operation'],OPERATION)
            self.assertEqual([row['intent'] for row in data['actions']],
                             ['open_difficulty_guide','open_mode_card','enter_lobby'])
            self.assertTrue(all(row['status']=='verified' and len(row['after'])==2 for row in data['actions']))
            self.assertTrue(data['lobby_verified'])
            self.assertEqual(data['variant'],'stellar')
            self.assertFalse(data['battle_started'])
            self.assertEqual(len(positions),3)
            persisted = Path(report['run_dir'])/'challenge-lobby.json'
            self.assertEqual(json.loads(persisted.read_bytes()),data)
            self.assertNotIn(UID.text,persisted.read_text(encoding='utf-8'))

    def test_native_cli_keeps_unknown_input_and_refuses_a_different_lobby(self):
        for mode, frames, stop, expected in (
            (AP,[high(AP),high(AP),high(AP),high(AP)],False,1),
            (MOC,[stellar(),stellar()],False,0),
            (AP,[high(AP),high(AP)],True,0),
        ):
            with self.subTest(mode=mode, stop=stop), tempfile.TemporaryDirectory() as directory:
                code, report, positions = native_cli(Path(directory),frames,mode=mode,stop_at_submit=stop)
                self.assertNotEqual(code,0)
                self.assertFalse(report['challenge']['lobby_verified'])
                self.assertEqual(len(positions),expected)
                if report['challenge']['actions']:
                    self.assertEqual(report['challenge']['actions'][0]['status'],'unknown')

    def test_native_cli_closes_only_the_matched_update_notice_and_confirms_lobby(self):
        notice = chaos_notice()
        lobby = chaos_map()
        with tempfile.TemporaryDirectory() as directory:
            code, report, positions = native_cli(Path(directory),
                [high(MOC),high(MOC),notice,notice,lobby,lobby], mode=MOC)
            self.assertEqual((code,len(positions)),(0,2))
            self.assertEqual(report['challenge']['variant'],'level_map')
            self.assertEqual([(row['intent'],row['observed_page']) for row in report['challenge']['actions']],
                             [('enter_lobby','period_notice'),('dismiss_period_notice','lobby')])
        ctx = SimpleNamespace(settings=Settings())
        self.assertIsNone(next_action(ctx,notice,FICTION))
        notice.tokens.append(field('获得物品', .45,.21))
        self.assertIsNone(next_action(ctx,notice,MOC))
        notice.tokens = [token for token in notice.tokens if token.text not in ('获得物品','记忆紊流')]
        self.assertIsNone(next_action(ctx,notice,MOC))
        for removed in ('奇珍琳琅','09'):
            with self.subTest(removed=removed):
                lobby = chaos_map()
                lobby.tokens = [token for token in lobby.tokens if token.text != removed]
                self.assertIsNone(observe(lobby))

    def test_native_cli_fiction_story_then_unknown_unlock_never_selects_a_stage(self):
        notice = fiction_notice()
        lobby = fiction_map()
        unlock = frame(field('选择最高解锁关卡', .40,.27,.19), field('03', .67,.67,.03),
                       field('确认', .55,.80,.03))
        for arrival, expected in ((lobby,True),(unlock,False)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                code, report, positions = native_cli(Path(directory),
                    [high(FICTION),high(FICTION),notice,notice,arrival,arrival], mode=FICTION)
                self.assertEqual(code == 0,expected)
                self.assertEqual(len(positions),2)
                enter, story = report['challenge']['actions']
                self.assertEqual(enter['observed_page'],'period_notice')
                self.assertEqual(story['intent'],'open_fiction_overview')
                self.assertEqual(story['status'],'verified' if expected else 'unknown')
                self.assertEqual(report['challenge']['lobby_verified'],expected)

    def test_report_rejects_changed_arrival_image_and_preserves_original_receipt(self):
        save_report = Runner._save_run_report

        def replace_source(runner, directory, *args, **kwargs):
            source = runner.report.challenge['lobby_evidence'][0]['file']
            (directory/source).write_bytes(b'changed after navigation')
            save_report(runner, directory, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.object(Runner, '_save_run_report', replace_source):
            code, report, positions = native_cli(Path(directory), [stellar(),stellar()])
            self.assertEqual((code,report['status'],positions),(1,'partial',[]))
            self.assertFalse(report['challenge']['lobby_verified'])
            persisted = Path(report['run_dir'])/'challenge-lobby.json'
            self.assertTrue(json.loads(persisted.read_bytes())['lobby_verified'])

    def test_stellar_lobby_requires_distinct_nodes_and_current_mode_marker(self):
        for removed in ('节点三','星启模式','更换编队'):
            state = stellar()
            state.tokens = [token for token in state.tokens if token.text != removed]
            with self.subTest(removed=removed):
                self.assertIsNone(observe(state))
