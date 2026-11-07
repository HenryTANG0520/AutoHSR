"""Installation-local configuration copies without account or credential changes."""

from pathlib import Path
import re

from .config import Settings


DEFAULT_LABEL = '默认配置'
PROFILE_DIRECTORY = 'profiles.local'


class ProfileError(ValueError):
    pass


def _label(value):
    if (type(value) is not str or not 1 <= len(value) <= 32 or value != value.strip()
            or not value[0].isalnum() or any(not (char.isalnum() or char in ' -_') for char in value)
            or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])', value, re.IGNORECASE)
            or value == DEFAULT_LABEL):
        raise ProfileError('方案名须为 1～32 个字，使用文字、数字、空格、连字符或下划线。')
    return value


class ConfigurationProfiles:
    def __init__(self, config_path):
        config_path = Path(config_path).resolve()
        if config_path.name == 'config.json' and config_path.parent.parent.name == PROFILE_DIRECTORY:
            self.root = config_path.parent.parent
            self.default = self.root.parent / 'config.json'
        else:
            self.default = config_path
            self.root = config_path.parent / PROFILE_DIRECTORY

    def _check_root(self):
        if self.root.resolve() != self.root or (self.root.exists() and not self.root.is_dir()):
            raise ProfileError('配置方案目录来源无法核实。')

    def _path(self, label):
        self._check_root()
        path = self.root / _label(label) / 'config.json'
        if path.resolve() != path:
            raise ProfileError('配置方案须位于本机方案目录中。')
        return path

    def label_for(self, path):
        path = Path(path).resolve()
        if path == self.default:
            return DEFAULT_LABEL
        if path.name == 'config.json' and path.parent.parent == self.root:
            return path.parent.name
        raise ProfileError('当前配置不属于此方案目录。')

    def names(self):
        self._check_root()
        if not self.root.exists():
            return (DEFAULT_LABEL,)
        names = []
        for directory in self.root.iterdir():
            try:
                if directory.is_dir() and self._path(directory.name).is_file():
                    names.append(directory.name)
            except (OSError, ProfileError, RuntimeError):
                continue
        return (DEFAULT_LABEL, *sorted(names, key=str.casefold))

    def read(self, label):
        default = label == DEFAULT_LABEL
        path = self.default if default else self._path(label)
        try:
            settings = Settings.load(path, require_existing=not default)
        except (OSError, ValueError, TypeError):
            raise ProfileError('所选方案无法读取或设置无效。') from None
        return path, settings

    def copy(self, label, source):
        path = self._path(label)
        try:
            source = Path(source).resolve()
            self.label_for(source)
            settings = Settings.load(source, require_existing=source != self.default)
        except (OSError, ValueError, TypeError):
            raise ProfileError('当前已保存配置无法复制。') from None
        self.root.mkdir(exist_ok=True)
        self._check_root()
        try:
            path.parent.mkdir()
        except FileExistsError:
            raise ProfileError('已有同名方案。') from None
        try:
            settings.save(path)
        except BaseException:
            # Remove only an empty directory just created by this invocation.
            try:
                path.parent.rmdir()
            except OSError:
                pass
            raise
        return path
