from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.configuration_profiles import ConfigurationProfiles, DEFAULT_LABEL, ProfileError
from autohsr.currency_wars_identity import account_key_from_uid
from autohsr.desktop_profiles import DesktopProfiles


class ConfigurationProfilesTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.default = self.root / 'config.json'
        self.catalog = ConfigurationProfiles(self.default)

    def test_copy_and_switch_keep_settings_files_independent(self):
        Settings(assignments=True, battle=False).save(self.default)
        original = self.default.read_bytes()
        first = self.catalog.copy('日常一', self.default)
        Settings(assignments=False, battle=False).save(first)
        second = self.catalog.copy('日常二', first)
        self.assertFalse(Settings.load(second).assignments)
        self.assertEqual(self.default.read_bytes(), original)
        self.assertEqual(self.catalog.read('日常一'), (first, Settings.load(first)))
        self.assertEqual(self.catalog.read(DEFAULT_LABEL), (self.default, Settings.load(self.default)))
        self.assertEqual(self.catalog.names(), (DEFAULT_LABEL, '日常一', '日常二'))
        self.assertEqual(ConfigurationProfiles(first).root, self.catalog.root)

    def test_initial_read_does_not_create_a_profile_or_default(self):
        self.assertEqual(self.catalog.names(), (DEFAULT_LABEL,))
        self.assertEqual(self.catalog.read(DEFAULT_LABEL), (self.default, Settings()))
        self.assertFalse(self.catalog.root.exists())
        self.assertFalse(self.default.exists())

    def test_copy_requires_its_own_binding_and_config_contains_no_raw_uid(self):
        key = account_key_from_uid('100000000')
        Settings(profile_account_key=key).save(self.default)
        original = self.default.read_bytes()
        target = self.catalog.copy('独立账号', self.default)
        self.assertEqual(self.catalog.read(DEFAULT_LABEL)[1].profile_account_key, key)
        self.assertEqual(self.catalog.read('独立账号')[1].profile_account_key, '')
        self.assertNotIn(b'100000000', original)
        self.assertEqual(self.default.read_bytes(), original)

    def test_refuses_unsafe_duplicate_and_corrupt_profiles(self):
        for label in ('../别处', r'C:\别处', 'CON', '默认配置', '结尾.', ' 方案'):
            with self.subTest(label=label), self.assertRaises(ProfileError):
                self.catalog.copy(label, self.default)
        path = self.catalog.copy('有效', self.default)
        original = path.read_bytes()
        with self.assertRaises(ProfileError):
            self.catalog.copy('有效', self.default)
        self.assertEqual(path.read_bytes(), original)
        path.write_text('{', encoding='utf8')
        with self.assertRaises(ProfileError):
            self.catalog.read('有效')

    def test_linked_profile_cannot_read_or_write_outside_the_catalog(self):
        outside = self.root / 'outside'
        outside.mkdir()
        Settings().save(outside / 'config.json')
        self.catalog.root.mkdir()
        try:
            (self.catalog.root / '链接').symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'Windows symlink permission unavailable ({error.winerror})')
        self.assertEqual(self.catalog.names(), (DEFAULT_LABEL,))
        with self.assertRaises(ProfileError):
            self.catalog.read('链接')
        with self.assertRaises(ProfileError):
            self.catalog.copy('链接', self.default)

    def test_switch_requires_idle_clean_ui_and_no_armed_schedule(self):
        path = self.catalog.copy('备用', self.default)
        runtime = SimpleNamespace(snapshot=Mock(return_value={'enabled_ids': []}), wait_idle=Mock(return_value=True))
        ui = SimpleNamespace(config_path=self.default, busy=False, closing=False, worker=None, book_editor=None,
                             dirty=False, workflow_panel=SimpleNamespace(dirty=False),
                             schedule_panel=SimpleNamespace(dirty=False),
                             desktop_schedule=SimpleNamespace(runtime=runtime))
        control = DesktopProfiles.__new__(DesktopProfiles)
        control.ui, control.catalog = ui, self.catalog
        control.choice, control.feedback, control.activate = Mock(), Mock(), Mock()
        control.choice.get.return_value = '备用'
        for attribute in ('busy', 'dirty'):
            setattr(ui, attribute, True)
            control.switch()
            setattr(ui, attribute, False)
        ui.workflow_panel.dirty = True
        control.switch()
        ui.workflow_panel.dirty = False
        runtime.snapshot.return_value = {'enabled_ids': ['daily']}
        control.switch()
        control.activate.assert_not_called()
        runtime.snapshot.return_value = {'enabled_ids': []}
        control.switch()
        control.activate.assert_called_once_with(path, Settings.load(path))
