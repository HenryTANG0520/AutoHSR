"""Notification protocol contracts use synthetic calls without any transport."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from autohsr.notify_http import Reply
from autohsr.notify_profiles import NotifyError, profile
from autohsr.notify_providers import _call, acknowledgement, calls


class GoCqNotificationTests(unittest.TestCase):
    def params(self, **extra):
        return dict(endpoint='http://127.0.0.1:18080', token='synthetic-not-real',
                    user_id='123456', group_id='654321', **extra)

    def requests(self, params):
        return calls('gocqhttp', params, 'title', 'body', 'synthetic-report')

    def test_explicit_private_uses_only_selected_user_despite_group_id(self):
        built = self.requests(self.params(message_type='private'))
        self.assertEqual(len(built), 1)
        query = parse_qs(urlsplit(built[0].url).query)
        self.assertEqual(query['message_type'], ['private'])
        self.assertEqual(query['user_id'], ['123456'])
        self.assertNotIn('group_id', query)

    def test_explicit_group_uses_only_selected_group_despite_user_id(self):
        built = self.requests(self.params(message_type='group'))
        self.assertEqual(len(built), 1)
        query = parse_qs(urlsplit(built[0].url).query)
        self.assertEqual(query['message_type'], ['group'])
        self.assertEqual(query['group_id'], ['654321'])
        self.assertNotIn('user_id', query)

    def test_unspecified_mode_preserves_both_explicit_targets(self):
        built = self.requests(self.params())
        self.assertEqual(len(built), 2)
        self.assertEqual([parse_qs(urlsplit(call.url).query)['message_type'][0]
                          for call in built], ['private', 'group'])

    def test_invalid_mode_is_rejected_by_calls_and_profile_validation(self):
        for mode in ('both', 'channel', '', 1):
            params = self.params(message_type=mode)
            with self.subTest(mode=mode):
                with self.assertRaises(NotifyError):
                    self.requests(params)
                with self.assertRaises(NotifyError):
                    profile(dict(id='synthetic', provider='gocqhttp', params=params))

    def test_selected_mode_requires_corresponding_target_even_with_other_id(self):
        for mode, name in (('private', 'user_id'), ('group', 'group_id')):
            params = self.params(message_type=mode)
            del params[name]
            with self.subTest(mode=mode):
                with self.assertRaises(NotifyError):
                    self.requests(params)
                with self.assertRaises(NotifyError):
                    profile(dict(id='synthetic', provider='gocqhttp', params=params))


class KookNotificationTests(unittest.TestCase):
    def params(self, **extra):
        return dict(token='synthetic-not-real', target_id='123456', **extra)

    def test_default_and_explicit_private_route_user_to_direct_message(self):
        for params in (self.params(), self.params(chat_type='1')):
            with self.subTest(params=params):
                built = calls('kook', params, 'title', 'body', 'synthetic-report')
                self.assertEqual(len(built), 1)
                self.assertEqual(built[0].url, 'https://www.kookapp.cn/api/v3/direct-message/create')
                self.assertEqual(json.loads(built[0].data),
                                 dict(type=1, target_id='123456', content='title\nbody'))
                self.assertEqual(built[0].headers['Authorization'], 'Bot synthetic-not-real')

    def test_channel_route_uses_channel_endpoint_and_kmarkdown(self):
        built = calls('kook', self.params(chat_type='9'), 'title', 'body', 'synthetic-report')
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].url, 'https://www.kookapp.cn/api/v3/message/create')
        self.assertEqual(json.loads(built[0].data),
                         dict(type=9, target_id='123456', content='**title**\nbody'))

    def test_other_modes_and_numeric_values_are_rejected(self):
        for mode in ('2', '10', 'private', '', 1, 9):
            params = self.params(chat_type=mode)
            with self.subTest(mode=mode):
                with self.assertRaises(NotifyError):
                    calls('kook', params, 'title', 'body', 'synthetic-report')
                with self.assertRaises(NotifyError):
                    profile(dict(id='synthetic', provider='kook', params=params))


class HttpNotificationContractTests(unittest.TestCase):
    def test_onebot_and_gocq_success_requires_consistent_ok_and_zero(self):
        for provider in ('onebot', 'gocqhttp'):
            with self.subTest(provider=provider):
                self.assertEqual(acknowledgement(provider, Reply(200, b'{"status":"ok","retcode":0}')),
                                 'accepted')
                self.assertEqual(acknowledgement(provider, Reply(200, b'{"status":"failed","retcode":100}')),
                                 'rejected')

    def test_async_and_conflicting_onebot_results_stay_unknown(self):
        replies = [dict(status='async', retcode=1), dict(status='async', retcode=0),
                   dict(status='ok', retcode=1), dict(status='ok', retcode=100),
                   dict(status='failed', retcode=0), dict(status='failed', retcode=1),
                   dict(status='unrecognized', retcode=100), dict(retcode=100),
                   dict(status='ok', retcode=False), dict(status='failed', retcode=True),
                   dict(status='ok', retcode='0')]
        for provider in ('onebot', 'gocqhttp'):
            for data in replies:
                with self.subTest(provider=provider, data=data):
                    self.assertEqual(acknowledgement(provider, Reply(200, json.dumps(data).encode())),
                                     'unknown')

    def test_webhook_explicit_json_media_type_survives_header_case_normalization(self):
        for name in ('content-type', 'Content-Type', 'CoNtEnT-tYpE'):
            call = calls('webhook', dict(url='https://example.test/notify',
                         headers={name: 'application/vnd.example+json'}), 'title', 'body', 'id')[0]
            request = Request(call.url, call.data, call.headers, method=call.method)
            with self.subTest(header=name):
                self.assertEqual(request.get_header('Content-type'), 'application/vnd.example+json')
                self.assertEqual(sum(key.lower() == 'content-type' for key in call.headers), 1)

    def test_form_explicit_media_type_survives_header_case_normalization(self):
        for name in ('content-type', 'Content-Type', 'CoNtEnT-tYpE'):
            call = _call('https://example.test/notify', {}, form=dict(text='body'),
                         extra_headers={name: 'application/vnd.example.form'})
            request = Request(call.url, call.data, call.headers, method=call.method)
            with self.subTest(header=name):
                self.assertEqual(request.get_header('Content-type'), 'application/vnd.example.form')
                self.assertEqual(sum(key.lower() == 'content-type' for key in call.headers), 1)


if __name__ == '__main__':
    unittest.main()
