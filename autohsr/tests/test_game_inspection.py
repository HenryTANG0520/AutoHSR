"""CLI inspection with fake window/OCR and temporary synthetic installs only."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.__main__ import main
from autohsr.config import Settings
from autohsr.models import AutomationError, Scene, Token


class GameInspectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture()

    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.install=self.root/'private-current-install';self.install.mkdir()
        self.executable=self.install/'StarRail.exe';self.executable.write_bytes(b'synthetic executable; never run')
        self.ini=self.install/'config.ini'
        self.ini.write_text('[General]\ngame_version=4.6.0\n',encoding='utf-8')
        self.output=self.root/'inspection';self.output.mkdir()
        self.config=self.output/'settings.json'
        self.config.write_text(json.dumps(asdict(Settings(game_path=str(self.root/'stale-cache'/'StarRail.exe')))),encoding='utf-8')
        self.config_before=self.config.read_bytes()
        self.image=np.full((540,960,3),63,np.uint8)
        self.geometry=SimpleNamespace(width=960,height=540)
        self.scene=Scene([Token('合成检测画面',.99,(.2,.2,.4,.3))],self.image,self.geometry)
        self.window=SimpleNamespace(hwnd=123,title='synthetic game',path='private-stale-cached-executable',
            focus=Mock(),capture=Mock(return_value=(self.image,self.geometry)),
            current_executable=Mock(return_value=str(self.executable)),click=Mock(),key=Mock())

    def check(self):
        stdout,stderr=io.StringIO(),io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch('autohsr.app.ROOT',self.output))
            finder=stack.enter_context(patch('autohsr.app.find_game',return_value=self.window))
            vision=stack.enter_context(patch('autohsr.app.Vision'))
            vision.return_value.read.return_value=self.scene
            stack.enter_context(patch('autohsr.app.is_admin',return_value=True))
            stack.enter_context(patch('autohsr.app.is_elevated',return_value=False))
            runner=stack.enter_context(patch('autohsr.app.Runner'))
            launch=stack.enter_context(patch('autohsr.app.launch_game'))
            stack.enter_context(redirect_stdout(stdout));stack.enter_context(redirect_stderr(stderr))
            code=main(['--check','--config',str(self.config)])
        self.assertEqual(code,0,stderr.getvalue())
        self.assertEqual(stderr.getvalue(),'')
        runner.assert_not_called();launch.assert_not_called()
        self.window.focus.assert_called_once();self.window.capture.assert_called_once()
        self.window.click.assert_not_called();self.window.key.assert_not_called()
        finder.assert_called_once_with(str(self.root/'stale-cache'/'StarRail.exe'))
        self.assertEqual(self.config.read_bytes(),self.config_before)
        data=json.loads(stdout.getvalue())
        self.assertEqual(json.loads(Path(data['screenshot']).with_name('check.json').read_text(encoding='utf-8')),data)
        self.assertEqual(Path(data['screenshot']).with_suffix('.txt').read_text(encoding='utf-8'),self.scene.text)
        for private in (str(self.executable),str(self.ini),'private-current-install','private-stale-cached-executable'):
            self.assertNotIn(private,stdout.getvalue())
        return data

    def test_cli_uses_current_executable_and_only_exposes_the_game_version_fields(self):
        data=self.check()
        self.window.current_executable.assert_called_once_with()
        self.assertEqual(data['game_client'],dict(status='verified',version='4.6',full_version='4.6.0',
            kind='launcher_game_version',sha256=hashlib.sha256(self.ini.read_bytes()).hexdigest()))

    def test_newer_game_version_does_not_block_read_only_inspection(self):
        self.ini.write_text('[General]\ngame_version=5.7.12\n',encoding='utf-8')
        self.assertEqual(self.check()['game_client']['full_version'],'5.7.12')

    def test_missing_or_unreadable_current_metadata_stays_unknown_without_cached_fallback(self):
        for change in ('missing','empty','error'):
            with self.subTest(change=change):
                self.fixture()
                if change=='missing':del self.window.current_executable
                elif change=='empty':self.window.current_executable.return_value=None
                else:self.window.current_executable.side_effect=AutomationError('private-current-install secret-metadata-error')
                data=self.check()
                self.assertEqual(set(data['game_client']),{'status','reason'})
                self.assertEqual(data['game_client']['status'],'unknown')
                self.assertNotIn('secret-metadata-error',json.dumps(data))

    def test_unity_missing_or_ambiguous_install_metadata_cannot_become_a_game_version(self):
        variants=(None,'[General]\nFileVersion=2019.4.40.11437\n',
            '[General]\ngame_version=4.6.0\n[general]\ngame_version=4.7.0\n',
            '[Other]\ngame_version=4.6.0\n',
            '[General]\ngame_version=private-current-install secret-metadata-error\n')
        for content in variants:
            with self.subTest(content=content):
                self.fixture()
                if content is None:self.ini.unlink()
                else:self.ini.write_text(content,encoding='utf-8')
                data=self.check()
                self.assertEqual(set(data['game_client']),{'status','reason'})
                self.assertEqual(data['game_client']['status'],'unknown')
                self.assertNotIn('2019.4.40.11437',json.dumps(data))
                self.assertNotIn('secret-metadata-error',json.dumps(data))
