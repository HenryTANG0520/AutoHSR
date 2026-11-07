"""Read the installed game version from StarRail's launcher configuration."""

import configparser
import hashlib
from pathlib import Path
import re

from .models import AutomationError


def version_parts(value):
    if type(value) is not str or not re.fullmatch(r'[1-9][0-9]?\.[0-9]{1,2}\.[0-9]{1,4}', value):
        raise ValueError('invalid game version')
    return tuple(map(int, value.split('.')))


def installed_client(executable):
    """The launcher config describes game version; EXE FileVersion is Unity."""
    try:
        if not isinstance(executable, (str, Path)):
            raise ValueError('missing process path')
        executable = Path(executable).resolve(strict=True)
        if executable.name.casefold() != 'starrail.exe' or not executable.is_file():
            raise ValueError('unexpected executable')
        path = executable.parent / 'config.ini'
        with path.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('oversize config')
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        parser.read_string(raw.decode(encoding))
        sections = [section for section in parser.sections() if section.casefold() == 'general']
        if len(sections) != 1 or 'game_version' in parser.defaults():
            raise ValueError('ambiguous version section')
        full = parser.get(sections[0], 'game_version', raw=True).strip()
        major, minor, _ = version_parts(full)
        return dict(version=f'{major}.{minor}', full_version=full, executable=str(executable), source=str(path),
                    sha256=hashlib.sha256(raw).hexdigest(), kind='launcher_game_version')
    except (OSError, ValueError, configparser.Error):
        raise AutomationError('客户端安装版本未核实；不使用EXE引擎版本代替。') from None
