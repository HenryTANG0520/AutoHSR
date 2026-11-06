"""Translate March7thAssistant's normalized XYWH geometry to native XYXY."""
from decimal import Decimal
from fractions import Fraction
import re

from .task_workflow import WorkflowError


_MAX_EXPRESSION = 512
_MAX_LITERAL = 64
_MAX_EXPONENT = 64
_DECIMAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE]([+-]?[0-9]+))?')
_FORMAT = '选区须填写四个归一化数值，或使用每项至多一次除法的四项选区算式。'


def _decimal(text):
    text = text.strip()
    match = _DECIMAL.fullmatch(text) if len(text) <= _MAX_LITERAL else None
    if match is None or (match[1] is not None and abs(int(match[1])) > _MAX_EXPONENT):
        raise WorkflowError('选区只支持有限十进制数，数值长度或指数不可超限。')
    return Fraction(text)


def _ratio(value, allow_division):
    if type(value) not in (str, int, float, Decimal) or (
            type(value) is int and value.bit_length() > 4 * _MAX_LITERAL):
        raise WorkflowError(_FORMAT)
    text = str(value)
    if not allow_division:
        return _decimal(text)
    parts = text.split('/', maxsplit=2)
    if len(parts) == 1:
        return _decimal(parts[0])
    if len(parts) != 2:
        raise WorkflowError(_FORMAT)
    numerator, denominator = map(_decimal, parts)
    if not denominator:
        raise WorkflowError('选区算式的分母不能为零。')
    return numerator / denominator


def parse_march7th_crop(value) -> list[float]:
    """Parse a small numeric grammar. Return [left, top, right, bottom]."""
    if value is None:
        return [0., 0., 1., 1.]
    from_expression = isinstance(value, str)
    if from_expression:
        if not value:
            return [0., 0., 1., 1.]
        if len(value) > _MAX_EXPRESSION:
            raise WorkflowError('选区算式过长。')
        text = value.strip()
        if text.startswith('(') and text.endswith(')'):
            text = text[1:-1]
        values = text.split(',')
    elif isinstance(value, (list, tuple)):
        if not value:
            return [0., 0., 1., 1.]
        values = value
    else:
        raise WorkflowError(_FORMAT)
    if len(values) != 4:
        raise WorkflowError(_FORMAT)
    left, top, width, height = (_ratio(item, from_expression) for item in values)
    right, bottom = left + width, top + height
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise WorkflowError('选区须有正面积，且左、上及相加后的右、下边界均须在 0～1。')
    region = [float(item) for item in (left, top, right, bottom)]
    if region[0] >= region[2] or region[1] >= region[3]:
        raise WorkflowError('选区精度超过原生边界可表示范围。')
    return region
