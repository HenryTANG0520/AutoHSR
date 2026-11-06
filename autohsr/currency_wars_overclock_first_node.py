"""Current-run receipts before the ordinary legacy A0 entrance can start 1-1."""
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time

from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_deployment import _crop
from .currency_wars_initial import evidence_ref
from .currency_wars_match import read_match
from .currency_wars_node import loot_centers, start_target
from .currency_wars_overclock import (
    MAX_FRAME_AGE, MAX_JOURNAL_BYTES, _Evidence, _check_evidence, _freeze_scene_pixels, _hold_history_names,
    _pixels, _read_bytes, _require_frozen_scene, _require_stable_source,
)
from .currency_wars_overclock_first_node_pages import opening_crystal_target, read_first_node_board, same_crystals
from .currency_wars_overclock_preparation_pages import PHASES, read_preparation
from .currency_wars_sale import FieldIdentity, validate_field_image
from .currency_wars_state import strict_json
from .models import AutomationError, InputInterrupted, Stopped
from .storage import hold_read_sources
from .windows import Geometry


@dataclass(frozen=True, repr=False)
class _NativeFrame:
    window: object
    geometry: Geometry
    image: object
    tokens: tuple
    captured_at: float
    occlusions: int
    pixels: str


class LegacyFirstNode:
    def __init__(self, context, flow):
        self.c = context
        self.flow = flow
        self.session = context.overclock_session
        self.epoch = context.runner.input_epoch
        self.confidence = context.settings.ocr_confidence
        self.guard = CurrencyWarsWorkflow(context)
        self.arrival = None
        self.opening_crystals = ()
        self.ground_verified = False
        self.roles = {}
        self.drops = []
        self.pickups_sent = 0
        self.battery_placed = False
        self.sources = []
        self.armed = None
        self.pending = None
        self.sent = False
        self.flow['first_node_preflight'] = dict(status='pending', node='1-1')

    def applies(self, scene):
        state = read_match(scene, self.confidence)
        return state is not None and state.node == '1-1'

    def _current(self, scene):
        self.c.checkpoint()
        self.guard._require_current_scene(scene)
        if self.c.runner.input_epoch != self.epoch:
            raise InputInterrupted('1-1 当前证据的输入代次已改变。')

    def _proof(self, scene, path):
        ref = evidence_ref(scene, path, self.session.run_dir)
        return _Evidence(ref['path'], ref['sha256'], scene.captured_at, 'preparation')

    def _require_origin(self):
        if self.c.runner.input_epoch != self.epoch:
            raise InputInterrupted('1-1 当前证据的输入代次已改变。')
        if self.arrival is None:
            raise AutomationError('1-1 缺少本次同窗的环境确认与初始备战回执。')

    def record_arrival(self, scene):
        actions = self.flow['actions']
        route = tuple(action.get('action') for action in actions)
        if (scene is None or not self.session.data.get('window_key')
                or route not in (('advance_boss_preview', 'advance_plane', 'confirm_environment'),
                                 ('advance_boss_preview', 'advance_plane', 'select_environment', 'confirm_environment'))
                or actions[1].get('origin_node') != 1 or any(action.get('status') != 'verified' for action in actions)
                or read_preparation(scene, self.confidence).state != PHASES[-1]):
            return
        self._current(scene)
        self.arrival = self._proof(scene, actions[-1]['after'])
        self.sources.append(self.arrival)
        self.opening_crystals = loot_centers(scene)

    def observe_initial_ground(self, scene, state):
        if (self.ground_verified or state.deployment != (0, 3)
                or not self.arrival.captured_at < scene.captured_at
                or read_preparation(scene, self.confidence).state != PHASES[-1]):
            return
        self._current(scene)
        current = loot_centers(scene)
        if (opening_crystal_target(scene, current, 'gray') is None
                or not same_crystals(self.opening_crystals, current)):
            return
        proof = self._proof(scene, self.c.evidence(scene, 'currency_first_node_initial_ground'))
        self.sources.append(proof)
        self.ground_verified = True

    def record_deployment(self, before, after, action, plan, profile):
        if self.sent or not self.applies(after) or self.arrival is None:
            return
        self._current(after)
        feedback = action.get('feedback', {})
        key = plan.zone, plan.target_slot
        expected = len(self.roles)
        if (action.get('status') != 'verified' or feedback.get('status') != 'verified'
                or feedback.get('deployment_before') != (expected, 3)
                or feedback.get('deployment_after') != (expected + 1, 3)
                or not self.arrival.captured_at < before.captured_at < after.captured_at
                or key in self.roles or plan.zone not in profile.zones or profile.node != '1-1'):
            return
        try:
            board = read_first_node_board(after, self.confidence)
            occupied = {(cell.zone, cell.slot): cell for cell in board.cells
                        if cell.zone != 'bench' and cell.state == 'occupied'}
            if set(occupied) != {*self.roles, key}:
                return
            cell = occupied[key]
            field = FieldIdentity(cell.zone, cell.slot, cell.point, cell.node, _crop(after.image, cell.roi).copy())
            for _, previous in self.roles.values():
                validate_field_image(after, previous, self.confidence)
            proofs = (self._proof(before, action['before']), self._proof(after, action['after']))
        except AutomationError:
            return
        self.roles[key] = profile.name, field
        self.sources.extend(proofs)

    def _formation(self, scene, board):
        placed = {(cell.zone, cell.slot) for cell in board.cells
                  if cell.zone != 'bench' and cell.state == 'occupied'}
        if board.match.deployment[1] != 3 or placed != set(self.roles):
            raise AutomationError('1-1 的本次部署回执与当前阵容或前台槽不一致。')
        for _, field in self.roles.values():
            validate_field_image(scene, field, self.confidence)
        return placed

    def require_formation(self, scene):
        self._require_origin()
        self._current(scene)
        board = read_first_node_board(scene, self.confidence)
        self._formation(scene, board)

    def _team(self, scene, board):
        placed = self._formation(scene, board)
        if board.match.deployment != (3, 3) or not any(zone == 'front' for zone, _ in placed):
            raise AutomationError('1-1 的满员阵容或前台槽尚未核实。')
        return [dict(name=name, zone=zone, slot=slot) for (zone, slot), (name, _) in sorted(self.roles.items())]

    def require_pickup(self, scene, target):
        if self.sent or self.pickups_sent != len(self.drops):
            raise AutomationError('1-1 上一笔拾取或出战已提交，原回执保留。')
        self._require_origin()
        self._current(scene)
        board = read_first_node_board(scene, self.confidence)
        self._team(scene, board)
        expected = self.drops[-1]['remaining'] if self.drops else self.opening_crystals
        kind = 'gray' if not self.drops else 'blue'
        selected = opening_crystal_target(scene, board.crystals, kind)
        if (not self.ground_verified or not same_crystals(board.crystals, expected)
                or selected != target or any(cell.state == 'reward' for cell in board.cells)):
            raise AutomationError('1-1 的当前晶矿与本次开场掉落回执不一致。')

    def record_drop(self, before, first, after, delivery, action):
        self._require_origin()
        self._current(after)
        board = read_first_node_board(after, self.confidence)
        self._team(after, board)
        expected = 'gold' if not self.drops else 'battery'
        if (delivery.kind != expected or action.get('status') != 'verified' or self.pickups_sent != len(self.drops) + 1
                or not before.captured_at < first.captured_at < after.captured_at <= first.captured_at + MAX_FRAME_AGE):
            raise AutomationError('1-1 晶矿消失后的同场到账回执不完整。')
        first_path = self.c.evidence(first, 'currency_first_node_drop_feedback_first')
        proofs = (self._proof(before, action['before']), self._proof(first, first_path),
                  self._proof(after, action['after']))
        self.sources.extend(proofs)
        receipt = dict(kind=delivery.kind, value=delivery.value, remaining=delivery.remaining,
                       gold=board.match.gold, feedback=[asdict(proof) for proof in proofs[1:]])
        self.drops.append(receipt)
        action['first_node_delivery'] = receipt

    def require_equipment(self, scene, item_name, item):
        self._require_origin()
        self._current(scene)
        self._team(scene, read_first_node_board(scene, self.confidence))
        if (self.battery_placed or item_name != 'battery' or len(self.drops) != 2
                or item != self.drops[-1]['value']):
            raise AutomationError('1-1 当前装备没有可绑定的本次开场交付回执。')

    def record_equipped_battery(self, before, panel, after, actions, field, item, profile):
        if not self.applies(after) or self.sent:
            return
        self._current(after)
        equip, verify, close = actions
        source = self.roles.get((field.zone, field.slot))
        if (len(self.drops) != 2 or item != self.drops[-1]['value'] or source is None or source[0] != profile.name
                or any(action.get('status') != 'verified' for action in actions)):
            return
        try:
            self._team(after, read_first_node_board(after, self.confidence))
            proofs = (self._proof(before, equip['before']), self._proof(panel, verify['after']),
                      self._proof(after, close['after']))
        except AutomationError:
            return
        self.sources.extend(proofs)
        self.battery_placed = True

    def _before_start(self, scene):
        self._require_origin()
        self._current(scene)
        board = read_first_node_board(scene, self.confidence)
        team = self._team(scene, board)
        if (len(self.drops) != 2 or board.crystals or board.match.gold != self.drops[-1]['gold']
                or any(cell.state == 'reward' for cell in board.cells)):
            raise AutomationError('1-1 的开场掉落或交付仍待核对。')
        if self.drops[-1]['value'] not in board.batteries and not self.battery_placed:
            raise AutomationError('1-1 的本次光能电池去向待核对。')
        if board.target is None or start_target(scene, self.confidence) != board.target:
            raise AutomationError('1-1 的唯一出战控件未核实。')
        return board, team

    def prepare_start(self, first):
        if any(action.get('status') != 'verified' for action in self.flow['actions']):
            raise AutomationError('1-1 仍有本次旧动作待核对。')
        original, team = self._before_start(first)
        before = self._proof(first, self.c.evidence(first, 'currency_first_node_start_first'))
        self.c.sleep(.3)
        second = self.c.snapshot()
        current, _ = self._before_start(second)
        if (not first.captured_at < second.captured_at <= first.captured_at + MAX_FRAME_AGE
                or first.geometry != second.geometry or original.match != current.match
                or original.target.box != current.target.box
                or tuple(cell.state for cell in original.cells) != tuple(cell.state for cell in current.cells)):
            raise AutomationError('1-1 出战前的两帧读数或目标不一致。')
        after = self._proof(second, self.c.evidence(second, 'currency_first_node_start_second'))
        self.sources.extend((before, after))
        self.armed = second, current.target, before.captured_at, after.captured_at
        self.flow['first_node_preflight'] = dict(status='verified', node='1-1', team=team,
                                                opening_drops=list(self.drops), target=list(current.target.box),
                                                battery_equipped=self.battery_placed,
                                                feedback=[asdict(before), asdict(after)])
        return second

    def bind_pending(self, path, data, scene):
        actions = self.flow['actions']
        outer = actions[-1] if actions else {}
        if (self.sent or self.armed is None or self.armed[0] is not scene
                or outer.get('action') != 'run_current_node' or outer.get('status') != 'pending'
                or data.get('action') != 'start_node' or data.get('action_status') != 'pending'
                or data.get('origin_node') != '1-1'):
            raise AutomationError('1-1 没有本次双帧出战前置回执。')
        self.sources.extend((self._proof(scene, outer['before']), self._proof(scene, data['before'])))
        self.pending = path, dict(data)

    @staticmethod
    def _check_journal(path, expected, hold):
        hold(path)
        actual = strict_json(_read_bytes(path, MAX_JOURNAL_BYTES).decode('utf-8'))
        if actual != json.loads(json.dumps(expected, ensure_ascii=False)):
            raise AutomationError('1-1 当前待核对账本已改变。')

    def _freeze_input(self, scene):
        geometry = scene.geometry
        image = _freeze_scene_pixels(scene, geometry)
        return _NativeFrame(self.c.window, geometry, image, tuple(scene.tokens), scene.captured_at,
                            self.c.capture_occlusion_count, _pixels(image, geometry))

    def _hold_input_sources(self, stack, *additional, frame=None):
        from .currency_wars_identity import installed_client

        revisions = {}

        def hold(path):
            if path not in revisions:
                _require_stable_source(path, revisions)
                stack.enter_context(hold_read_sources((path,)))
            _require_stable_source(path, revisions)

        unchanged = _hold_history_names(self.session.path.parent, stack)
        self.session.require_active(hold)
        self.session.require_history(hold)
        client = installed_client(self.c.window.current_executable())
        hold(Path(client['source']))
        self._check_journal(self.session.run_dir / 'currency-flow.json', self.flow, hold)
        proofs = (*self.sources, *additional)
        for proof in proofs:
            expected = ((frame.geometry, frame.pixels)
                        if frame is not None and proof.captured_at == frame.captured_at else None)
            _check_evidence(proof, self.session.run_dir, check_source=hold, expected_pixels=expected)
        if len({revisions[Path(proof.screenshot)][:2] for proof in proofs}) != len(proofs):
            raise AutomationError('1-1 回执需要各自独立的原始截图。')
        return hold, unchanged

    def _finish_native_check(self, scene, unchanged, frame, *, earliest=None):
        unchanged()
        window = frame.window
        if self.c.window is not window or window.current_window_key() != self.session.data['window_key']:
            raise InputInterrupted('1-1 的原生发送窗口已改变。')
        window.guard(frame.geometry)
        if window.emergency_pressed() or self.c.runner.stop_requested:
            raise Stopped('1-1 本次操作已停止，原意图保留。')
        if (self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch
                or self.c.last_scene is not scene):
            raise InputInterrupted('1-1 当前证据的输入代次已改变。')
        now = time.monotonic()
        if (scene.captured_at != frame.captured_at or self.c.capture_occlusion_count != frame.occlusions
                or not 0 <= now - frame.captured_at <= MAX_FRAME_AGE
                or earliest is not None and not 0 <= now - earliest <= MAX_FRAME_AGE):
            raise AutomationError('1-1 的原生发送画面已改变或过期，原意图保留。')
        _require_frozen_scene(scene, frame.image, frame.tokens, frame.geometry)
        self.c.last_scene, self.c._scroll_anchor = None, None

    def click_pickup(self, scene, target):
        actions = self.flow['actions']
        action = actions[-1] if actions else {}
        if (action.get('action') != 'collect_loot' or action.get('status') != 'pending'
                or action.get('target') != list(target)):
            raise AutomationError('1-1 缺少本次晶矿的待核对拾取意图。')
        frame = self._freeze_input(scene)
        proof = self._proof(scene, action['before'])
        with ExitStack() as stack:
            def before_send():
                _, unchanged = self._hold_input_sources(stack, proof, frame=frame)
                self.require_pickup(scene, target)
                self._finish_native_check(scene, unchanged, frame)
                self.pickups_sent += 1

            frame.window.click(*target[:2], frame.geometry, before_send=before_send)

    def click(self, scene, target):
        if self.sent or self.armed is None or self.armed[0] is not scene or self.armed[1] != target or self.pending is None:
            raise AutomationError('1-1 缺本次唯一已核实的出战与落盘意图。')
        if scene.captured_at != self.armed[3]:
            raise AutomationError('1-1 的出战前置画面已改变。')
        frame = self._freeze_input(scene)
        with ExitStack() as stack:
            def before_send():
                hold, unchanged = self._hold_input_sources(stack, frame=frame)
                self._check_journal(*self.pending, hold)
                board, _ = self._before_start(scene)
                if board.target != target:
                    raise AutomationError('1-1 发送前出战目标已改变。')
                self._finish_native_check(scene, unchanged, frame, earliest=self.armed[2])
                self.sent = True

            frame.window.click(*target.center, frame.geometry, before_send=before_send)
