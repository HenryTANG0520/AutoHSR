"""Version evidence and account continuity, without a live process or account."""
import json
import tempfile
import unittest
from pathlib import Path

import cv2

from autohsr.currency_wars_identity import account_key, installed_client, bind_account, refresh_client
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_replay import save_sample
from autohsr.models import AutomationError, Scene, Token
from autohsr.tests.test_currency_wars_standard import rank_page


def account(uid='100000000',confidence=.99):
    state=rank_page(40,(40,39,38))
    state.tokens.append(Token('UID:'+uid,confidence,(.01,.96,.10,.99)))
    return state


class IdentityTests(unittest.TestCase):
    def test_uid_requires_full_unique_trusted_footer_and_only_returns_digest(self):
        result=account_key(account())
        self.assertEqual(len(result),64)
        self.assertNotIn('100000000',result)
        self.assertNotEqual(result,account_key(account('200000000')))
        for state in (Scene([]),account('1234'),account(confidence=.5)):
            with self.assertRaises(AutomationError):
                account_key(state)
        state=account()
        state.tokens.append(state.tokens[-1])
        with self.assertRaises(AutomationError):
            account_key(state)

    def install(self,folder,version='4.6.0'):
        root=Path(folder)
        executable=root/'StarRail.exe'
        executable.write_bytes(b'fake executable; never launched')
        (root/'config.ini').write_text('[General]\ngame_version='+version+'\nchannel=1\n',encoding='utf-8')
        return executable

    def test_game_version_comes_from_its_install_config_not_unity(self):
        with tempfile.TemporaryDirectory() as folder:
            exe=self.install(folder)
            result=installed_client(exe)
            self.assertEqual((result['version'],result['full_version']),('4.6','4.6.0'))
            self.assertEqual(result['kind'],'launcher_game_version')
            self.assertEqual(len(result['sha256']),64)
            for section in ('general','General','GENERAL'):
                for encoding in ('utf-8-sig','utf-16'):
                    (Path(folder)/'config.ini').write_text(f'[{section}]\nGAME_VERSION=4.6.0\n',encoding=encoding)
                    self.assertEqual(installed_client(exe)['version'],'4.6')
            for content in ('[General]\ngame_version=4.6.0\ngame_version=4.7.0',
                            '[General]\ngame_version=private-secret-value',
                            '[General]\ngame_version=4.6.0\n[general]\ngame_version=4.7.0',
                            '[DEFAULT]\ngame_version=4.6.0\n[General]\nchannel=1',
                            '[Other]\ngame_version=4.6.0'):
                (Path(folder)/'config.ini').write_text(content,encoding='utf-8')
                with self.assertRaises(AutomationError) as error:
                    installed_client(exe)
                self.assertNotIn('private-secret-value',str(error.exception))

    def store(self,folder,entry=None):
        store=StandardSession(Path(folder)/'currency-standard-session.json')
        store.begin(Path(folder)/'attempt',entry or dict(rank_verified=True))
        return store

    def test_new_bind_does_not_store_raw_uid_and_mismatch_keeps_file_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            bind_account(store,account(),'attempt',0)
            raw=store.path.read_text(encoding='utf-8')
            self.assertNotIn('100000000',raw)
            self.assertEqual(store.data['account_verified_epoch'],0)
            before=store.path.read_bytes()
            with self.assertRaises(AutomationError):
                bind_account(store,account('200000000'),'later',1)
            self.assertEqual(store.path.read_bytes(),before)

    def test_legacy_bind_requires_original_hash_checked_a8_40_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'entry.png'
            state=account()
            image.write_bytes(cv2.imencode('.png',state.image)[1].tobytes())
            save_sample(state,image,stage='entry')
            store=self.store(folder,dict(rank_verified=True,screenshot=str(image)))
            store.data.update(status='active',start_verified=True)
            store.persist()
            bind_account(store,account(),'resume',0)
            self.assertEqual(store.data['account_source'],'verified_original_entry')
            self.assertEqual(store.data['account_key'],account_key(account()))
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            store.data['status']='active'
            store.persist()
            with self.assertRaises(AutomationError):
                bind_account(store,account(),'resume',0)

    def test_client_unknown_preserved_and_changed_install_cannot_silently_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            exe=self.install(folder)
            refresh_client(store,exe,'run1',0)
            self.assertEqual(store.data['client']['version'],'4.6')
            self.assertEqual(store.data['rules_version'],'4.6')
            self.install(folder,'4.7.0')
            with self.assertRaises(AutomationError):
                refresh_client(store,exe,'run2',0)
            refresh_client(store,None,'run3',0)
            self.assertNotIn('client',store.data)
            self.assertNotIn('rules_version',store.data)


if __name__=='__main__':
    unittest.main()
