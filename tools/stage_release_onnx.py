"""Redact the private dataset path in staged Ultralytics ONNX descriptions."""

from hashlib import sha256
import json
from pathlib import PureWindowsPath


_MODEL_NAMES = ('du_cards', 'du_enemies', 'du_enemies_fallback', 'du_enemies_recovery', 'du_target')
_DESCRIPTION_PREFIX = 'Ultralytics YOLO11n model trained on '
_REDACTED_DESCRIPTION = _DESCRIPTION_PREFIX + 'a local dataset'
_MODEL_METADATA = 14  # ModelProto.metadata_props, a repeated StringStringEntryProto.


def _read_varint(data, offset):
    value = 0
    for shift in range(0, 64, 7):
        if offset == len(data):
            break
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128 and value < (1 << 64):
            return value, offset
    raise ValueError('Invalid protobuf varint in staged ONNX model.')


def _fields(data):
    end = 0
    while end < len(data):
        start = end
        tag, payload = _read_varint(data, start)
        number, wire_type = divmod(tag, 8)
        if number == 0:
            raise ValueError('Invalid protobuf field number in staged ONNX model.')
        if wire_type == 0:
            _, end = _read_varint(data, payload)
        elif wire_type == 2:
            size, payload = _read_varint(data, payload)
            end = payload + size
        elif wire_type in (1, 5):
            end = payload + (8 if wire_type == 1 else 4)
        else:
            raise ValueError('Unsupported protobuf wire type in staged ONNX model.')
        if end > len(data):
            raise ValueError('Truncated protobuf field in staged ONNX model.')
        yield number, wire_type, start, payload, end


def _varint(value):
    data = bytearray()
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    data.append(value)
    return bytes(data)


def _string_field(number, value):
    return _varint(number * 8 + 2) + _varint(len(value)) + value


def _redact_description(model):
    updated = None
    for number, wire_type, start, payload, end in _fields(model):
        if (number, wire_type) != (_MODEL_METADATA, 2):
            continue
        entry = model[payload:end]
        fields = list(_fields(entry))
        keys = [entry[p:e] for n, t, _, p, e in fields if (n, t) == (1, 2)]
        if b'description' not in keys:
            continue
        values = [(s, p, e) for n, t, s, p, e in fields if (n, t) == (2, 2)]
        if len(keys) != 1 or len(values) != 1 or updated is not None:
            raise ValueError('Ambiguous description in staged ONNX model.')
        value_start, value_payload, value_end = values[0]
        value = entry[value_payload:value_end].decode('utf-8')
        if not value.startswith(_DESCRIPTION_PREFIX) or not PureWindowsPath(
                value.removeprefix(_DESCRIPTION_PREFIX)).is_absolute():
            raise ValueError('Expected an Ultralytics absolute dataset description in staged ONNX model.')
        replacement = (
            entry[:value_start] + _string_field(2, _REDACTED_DESCRIPTION.encode('utf-8')) + entry[value_end:]
        )
        updated = model[:start] + _string_field(_MODEL_METADATA, replacement) + model[end:]
    if updated is None:
        raise ValueError('Expected description is missing from staged ONNX model.')
    return updated


def _check_cpu_equivalence(original, sanitized):
    import numpy as np
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    before = ort.InferenceSession(original, sess_options=options, providers=['CPUExecutionProvider'])
    after = ort.InferenceSession(sanitized, sess_options=options, providers=['CPUExecutionProvider'])
    expected_metadata = dict(before.get_modelmeta().custom_metadata_map, description=_REDACTED_DESCRIPTION)
    if expected_metadata != after.get_modelmeta().custom_metadata_map:
        raise ValueError('Unexpected ONNX metadata change in staged model.')
    model_input, = before.get_inputs()
    frame = np.random.default_rng(0).random(model_input.shape, dtype=np.float32)
    expected = before.run(None, {model_input.name: frame})
    actual = after.run(None, {model_input.name: frame})
    if len(expected) != len(actual) or not all(
            a.dtype == b.dtype and np.array_equal(a, b, equal_nan=True) for a, b in zip(expected, actual)):
        raise ValueError('Staged ONNX model differs from the source on CPU.')


def stage_onnx_assets(bundle):
    """Check all staged model transformations before writing the release copies."""
    model_dir = bundle / '_internal' / 'assets' / 'models'
    updates = {}
    for name in _MODEL_NAMES:
        model_path = model_dir / f'{name}.onnx'
        sidecar = model_path.with_suffix('.json')
        original = model_path.read_bytes()
        source_sha256 = sha256(original).hexdigest()
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        if metadata.get('sha256') != source_sha256 or metadata.get('bytes', len(original)) != len(original):
            raise ValueError(f'Source model does not match the sidecar for {name}.')
        sanitized = _redact_description(original)
        _check_cpu_equivalence(original, sanitized)
        metadata['sha256'] = sha256(sanitized).hexdigest()
        if 'bytes' in metadata:
            metadata['bytes'] = len(sanitized)
        metadata['release_staging'] = {
            'source_sha256': source_sha256,
            'transformation': 'Redacted the local dataset path in ONNX description metadata.',
        }
        updates[name] = model_path, sanitized, metadata

    primary = updates['du_enemies'][2]
    fallback = updates['du_enemies_fallback'][2]
    reference = primary['fallback']
    if reference.get('file') != 'du_enemies_fallback.onnx' or (
            reference.get('sha256') != fallback['release_staging']['source_sha256']):
        raise ValueError('Source fallback model does not match the primary sidecar reference.')
    reference['sha256'] = fallback['sha256']
    for model_path, data, metadata in updates.values():
        model_path.write_bytes(data)
        model_path.with_suffix('.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
        )
