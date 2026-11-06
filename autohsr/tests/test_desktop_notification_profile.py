"""Verify notification form saves with synthetic credentials and no transport."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from autohsr.desktop_notification_profile import _NotificationProfileDialog
from autohsr.notify_profiles import MAGIC, PROVIDERS, ProfileStore
from autohsr.tests.test_notifications import PARAMS, SECRET


def _dialog(store, provider, fields, identity='form-fixture'):
    return SimpleNamespace(
        ui=SimpleNamespace(busy=False, closing=False), store=store,
        provider=Mock(get=Mock(return_value=provider)), active_provider=provider,
        identity=Mock(get=Mock(return_value=identity)),
        fields={key: Mock(get=Mock(return_value=value)) for key, value in fields.items()},
        feedback=Mock(), saved_id=None, destroy=Mock(),
    )


class NotificationProfileDialogTests(TestCase):
    def test_all_channels_save_with_profile_validation_and_dpapi(self):
        typed = {
            'telegram': dict(thread_id=1),
            'smtp': dict(To=['offline@example.test'], port=465, ssl=True, starttls=False),
            'custom': dict(datatype='json', data={'items': [1, {'message': '{message}'}]}),
            'webhook': dict(body='{content}'),
        }
        with TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            for provider in PROVIDERS:
                with self.subTest(provider=provider):
                    params = dict(PARAMS[provider], **typed.get(provider, {}))
                    if provider == 'winotify':
                        params = {}
                    identity = 'form-' + provider
                    fields = {key: json.dumps(value) if type(value) is not str or key in ('body', 'data')
                              else value for key, value in params.items()}
                    fields['allow_insecure'] = ''
                    dialog = _dialog(store, provider, fields, identity)
                    _NotificationProfileDialog._save(dialog)
                    dialog.feedback.configure.assert_not_called()
                    dialog.destroy.assert_called_once()
                    self.assertEqual(dialog.saved_id, identity)
                    self.assertEqual(store.load_private(identity), dict(id=identity, provider=provider, params=params))
                    encoded = store.path(identity).read_bytes()
                    self.assertTrue(encoded.startswith(MAGIC))
                    self.assertNotIn(SECRET.encode('utf-8'), encoded)
            self.assertEqual({p.suffix for p in (Path(temporary) / 'profiles').iterdir()}, {'.dpapi'})

    def test_existing_alias_is_never_replaced_and_invalid_values_remain_local(self):
        with TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            prior = dict(id='form-fixture', provider='winotify', params={})
            store.save(prior)
            original = store.path(prior['id']).read_bytes()
            for fields, error in (
                ({'url': 'https://example.test/' + SECRET}, '已存在'),
                ({'url': 'https://example.test/hook', 'headers': '{"Authorization":"' + SECRET}, 'JSON'),
                ({'url': 'https://user:' + SECRET + '@example.test/hook'}, '不接受地址中的用户名与密码'),
            ):
                with self.subTest(error=error):
                    dialog = _dialog(store, 'webhook', fields)
                    _NotificationProfileDialog._save(dialog)
                    dialog.destroy.assert_not_called()
                    self.assertIsNone(dialog.saved_id)
                    feedback = dialog.feedback.configure.call_args.kwargs['text']
                    self.assertIn(error, feedback)
                    self.assertNotIn(SECRET, feedback)
                    self.assertEqual(store.path(prior['id']).read_bytes(), original)
            self.assertEqual(list((Path(temporary) / 'profiles').iterdir()), [store.path(prior['id'])])

    def test_busy_or_unsynchronized_provider_cannot_write(self):
        for mode in ('busy', 'closing', 'provider'):
            with self.subTest(mode=mode):
                dialog = _dialog(Mock(), 'winotify', {})
                if mode == 'provider':
                    dialog.active_provider = 'webhook'
                else:
                    setattr(dialog.ui, mode, True)
                _NotificationProfileDialog._save(dialog)
                dialog.store.save.assert_not_called()
                dialog.destroy.assert_not_called()
