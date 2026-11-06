"""Exercise both desktop tool panels without a real window or a real sender."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import desktop_services as services
from autohsr.config import Settings


class FakeVariable:
    def __init__(self, master=None, value=''):
        self.value = value
        self.callbacks = {}

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in tuple(self.callbacks.values()):
            callback()

    def trace_add(self, _mode, callback):
        handle = str(len(self.callbacks) + 1)
        self.callbacks[handle] = callback
        return handle

    def trace_remove(self, _mode, handle):
        del self.callbacks[handle]


class FakeWidget:
    def __init__(self, parent=None, **options):
        self.options = options
        self.visible = False
        self.focused = False

    def configure(self, **options):
        self.options.update(options)

    def grid(self, **_):
        self.visible = True

    pack = grid

    def grid_remove(self):
        self.visible = False

    def columnconfigure(self, *_args, **_options):
        pass

    def bind(self, *_args, **_options):
        pass

    def focus_set(self):
        self.focused = True


def report_fixture():
    rows = [
        dict(status=status, reused=False, entry_id=f'{i:032x}', private='never display this')
        for i, status in enumerate(('redeemed', 'expired', 'already_used', 'invalid'), 1)
    ]
    rows.append(dict(status='redeemed', reused=True))
    return dict(operation='redemption', report_saved=True, redemption=dict(
        schema=1, status='partial', submitted=4, redeemed=1, reused=1,
        codes=['private-code'] * 6, results=rows,
        pending_entry_id='private pending id',
        skipped=[dict(row=2, reason='expired'), dict(row=3, reason='duplicate')],
    ))


class DesktopServiceTests(TestCase):
    def setUp(self):
        for name in ('__init__', 'configure', 'grid', 'grid_remove', 'pack',
                     'columnconfigure', 'bind', 'focus_set'):
            self.enterContext(patch.object(services.ttk.Frame, name, getattr(FakeWidget, name)))
        for name in ('Label', 'Entry', 'Combobox', 'Button', 'Checkbutton'):
            self.enterContext(patch.object(services.ttk, name, FakeWidget))
        for name in ('StringVar', 'BooleanVar'):
            self.enterContext(patch.object(services.tk, name, FakeVariable))
        self.profile_store = self.enterContext(patch.object(services, 'ProfileStore')).return_value
        self.profile_store.list_public.return_value = [
            dict(id='alpha', provider='webhook', readable=True, credential='do not show this'),
            dict(id='beta', provider='smtp', readable=True),
            dict(id='damaged', readable=False),
            dict(id='../unexpected', readable=False),
        ]
        self.notification_service = self.enterContext(patch.object(services, 'NotificationService'))
        self.save_settings = self.enterContext(patch.object(Settings, 'save', side_effect=AssertionError('explicit shared save only')))
        self.ui = SimpleNamespace(root=object(), ui_scale=1, settings=Settings(), form_variables=[], busy=False,
                                  _start_service_redemption=Mock(return_value=True),
                                  _submit_tool_job=Mock(return_value=True), _tool_action_changed=Mock())

    def test_builders_use_paper_widgets_and_keep_drafts_across_rebuild(self):
        first = services.build_redemption_panel(None, self.ui)
        notes = services.build_notifications_panel(None, self.ui)
        first.draft['source'].set('本地码表')
        first.draft['catalog'].set('current.json')
        notes.draft['selected'].set('alpha')
        notes.replace_existing.set(True)
        original_fields = tuple(self.ui.form_variables)
        rebuilt = services.build_redemption_panel(None, self.ui)
        rebuilt_notes = services.build_notifications_panel(None, self.ui)
        self.assertEqual(tuple(self.ui.form_variables), original_fields)
        self.assertIs(first.draft, rebuilt.draft)
        self.assertIs(notes.draft, rebuilt_notes.draft)
        self.assertEqual(rebuilt.settings_values()['redemption_catalog'], 'current.json')
        self.assertEqual(rebuilt.options['style'], 'Card.TFrame')
        self.assertTrue(rebuilt.file.visible)
        self.assertFalse(rebuilt.manual.visible)
        self.assertEqual(rebuilt.source.options['state'], 'readonly')
        self.assertTrue(rebuilt_notes.replace_existing.get())
        self.assertTrue(rebuilt_notes.primary_action()[2])
        rebuilt.focus_entry()
        rebuilt_notes.focus_entry()
        self.assertTrue(rebuilt.source.focused and rebuilt_notes.profiles.focused)
        self.notification_service.assert_not_called()
        self.profile_store.save.assert_not_called()

    def test_redemption_executes_current_overrides_and_updates_rebuilt_panel(self):
        panel = services.build_redemption_panel(None, self.ui)
        panel.draft['source'].set('手动输入')
        panel.draft['server'].set('由当前客户端识别')
        panel.draft['codes'].set('aBc, 中文码\nABC，aBc')
        panel.draft['mail'].set(False)
        self.assertTrue(panel.primary_action()[1]())
        sent = self.ui._start_service_redemption.call_args
        self.assertEqual(sent.args[0], dict(redemption_enabled=True, redemption_source='manual',
            redemption_server='auto', redemption_codes=['aBc', '中文码', 'ABC', 'aBc'],
            redemption_catalog='', redemption_claim_mail=False))
        self.assertFalse(panel.settings_values()['redemption_enabled'])
        self.assertFalse(self.ui.settings.redemption_enabled)
        other = services.build_redemption_panel(None, self.ui)
        sent.kwargs['on_report'](report_fixture())
        text = other.draft['result'].get()
        for phrase in ('待核对', '本次成功 1', '服务端过期 1', '已使用 1', '无效 1', '旧回执复用 1',
                       '码表跳过', '批次重复 1'):
            self.assertIn(phrase, text)
        self.assertNotIn('private', text)
        self.save_settings.assert_not_called()

    def test_disabled_and_inactive_redemption_drafts_stay_out_of_runtime(self):
        from dataclasses import replace

        panel = services.build_redemption_panel(None, self.ui)
        panel.draft['codes'].set('invalid-code')
        panel.draft['catalog'].set('invalid\npath')
        self.assertIs(panel.daily_enabled, False)
        self.assertEqual(panel.runtime_values(), {'redemption_enabled': False})
        replace(self.ui.settings, **panel.runtime_values()).validate('daily')
        self.assertTrue(panel.start())
        request = self.ui._start_service_redemption.call_args.args[0]
        self.assertEqual((request['redemption_codes'], request['redemption_catalog']), ([], ''))
        self.assertEqual(panel.settings_values()['redemption_codes'], ['invalid-code'])
        self.assertEqual(panel.settings_values()['redemption_catalog'], 'invalid\npath')
        panel.draft['enabled'].set(True)
        panel.draft['source'].set('手动输入')
        self.assertIs(panel.daily_enabled, True)
        self.assertEqual(panel.runtime_values()['redemption_codes'], ['invalid-code'])
        self.assertFalse(panel.start())
        self.ui._start_service_redemption.assert_called_once()

    def test_redemption_validates_missing_manual_input_and_locks_controls_when_busy(self):
        panel = services.build_redemption_panel(None, self.ui)
        panel.draft['source'].set('手动输入')
        self.assertFalse(panel.start())
        self.assertIn('至少一个有效兑换码', panel.draft['result'].get())
        panel.draft['codes'].set('ValidExample')
        self.ui.busy = True
        panel.refresh()
        self.assertFalse(panel.primary_action()[2])
        self.assertFalse(panel.start())
        self.assertTrue(all(widget.options['state'] == 'disabled' for widget, _ in panel.controls))
        self.ui.busy = False
        panel.refresh()
        self.assertEqual(panel.source.options['state'], 'readonly')
        self.ui._start_service_redemption.assert_not_called()

    def test_redemption_feedback_distinguishes_history_and_unverified_report(self):
        report = report_fixture()
        report.update(operation='plan', weekly_plan={'daily_reused': True}, budget_scope='original_daily_run')
        text = services._redemption_feedback(report)
        self.assertIn('沿用日常记录', text)
        self.assertIn('原批次成功 1', text)
        self.assertNotIn('本次成功', text)
        report['redemption']['reused'] = 8
        self.assertEqual(services._redemption_feedback(report), '兑换反馈未核实')
        self.assertIsNone(services._redemption_feedback({'operation': 'daily'}))

    def test_redemption_partial_mail_keeps_all_verified_codes_and_counts(self):
        report = report_fixture()
        batch = report['redemption']
        batch.pop('pending_entry_id')
        batch['codes'] = [f'private{i}' for i in range(len(batch['results']))]
        for code, row in zip(batch['codes'], batch['results']):
            row['code'] = code
        batch['mail'] = dict(status='partial', detail='private mail detail')

        panel = services.build_redemption_panel(None, self.ui)
        panel.render_report(report)
        text = panel.draft['result'].get()
        for expected in ('逐码反馈已核实', '批次待核对', '本次成功 1', '服务端过期 1',
                         '已使用 1', '无效 1', '旧回执复用 1', '邮件附件 · 待核对'):
            self.assertIn(expected, text)
        self.assertNotIn('private', text)

        batch['pending_entry_id'] = 'private pending'
        panel.render_report(report)
        self.assertIn('逐码反馈尚未齐全', panel.draft['result'].get())
        batch.pop('pending_entry_id')
        batch['results'][-1]['code'] = batch['codes'][0]
        panel.render_report(report)
        self.assertIn('逐码反馈尚未齐全', panel.draft['result'].get())

    def test_redemption_attachment_receipts_keep_handoff_and_prior_summary_separate(self):
        report = report_fixture()
        batch = report['redemption']
        batch.pop('pending_entry_id')
        batch['codes'] = [f'private{i}' for i in range(len(batch['results']))]
        for code, row in zip(batch['codes'], batch['results']):
            row['code'] = code
        for mail, expected in (
            ('not_requested', '本批未处理'),
            ('deferred_to_daily_mail', '交由日常邮件核对'),
            (dict(status='ok', detail='private'), '已核对'),
            (dict(status='failed', detail='private'), '核对失败'),
            (dict(status='stopped', detail='private'), '核对已停止'),
            (dict(status='unrecognized', detail='private'), '待核对'),
        ):
            with self.subTest(state=expected):
                batch['mail'] = mail
                batch['status'] = 'partial' if isinstance(mail, dict) and mail['status'] != 'ok' else 'completed'
                text = services._redemption_feedback(report)
                self.assertIn('邮件附件 · ' + expected, text)
                self.assertNotIn('private', text)

        batch['mail'] = dict(status='ok', detail='private')
        batch['status'] = 'completed'
        summary = services.report_summary(report)
        workflow = dict(operation='task_workflow', workflow={'redemption_summary': summary},
                        redemption=batch)
        self.assertIn('邮件附件 · 状态未记录', services._redemption_feedback(workflow))

    def test_notifications_check_and_profile_import_stay_local(self):
        panel = services.build_notifications_panel(None, self.ui)
        panel.draft['selected'].set('alpha')
        self.profile_store.load_private.return_value = dict(id='alpha', provider='webhook', params={'secret': 'synthetic'})
        panel.check()
        self.assertIn('本地配置可读取', panel.draft['result'].get())
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            original = '{"id":"alpha","provider":"webhook","params":{"synthetic": "fixture"}}'
            path.write_text(original, encoding='utf-8')
            self.profile_store.save.return_value = dict(id='alpha', provider='webhook', credentials_saved=True)
            panel.replace_existing.set(True)
            with patch.object(services.filedialog, 'askopenfilename', return_value=str(path)):
                panel.import_profile()
            self.assertEqual(path.read_text(encoding='utf-8'), original)
        self.profile_store.save.assert_called_once_with(
            dict(id='alpha', provider='webhook', params={'synthetic': 'fixture'}), replace=True)
        self.assertFalse(panel.replace_existing.get())
        self.assertEqual(panel.settings_values()['notification_profiles'], [])
        self.assertFalse(panel.settings_values()['notification_enabled'])
        self.notification_service.assert_not_called()
        self.ui._submit_tool_job.assert_not_called()
        self.save_settings.assert_not_called()

    def test_notification_test_is_explicit_and_uses_saved_target_after_view_changes(self):
        panel = services.build_notifications_panel(None, self.ui)
        panel.draft['selected'].set('alpha')
        panel.draft['title'].set('Unsaved title')
        panel.draft['body'].set('Unsaved body')
        service = self.notification_service.return_value
        frozen = (dict(id='alpha', provider='webhook', params={'secret': 'synthetic'}), 'version')
        self.profile_store.load_version.return_value = frozen
        service.deliver.return_value = dict(status='accepted', raw='private provider result')
        self.assertTrue(panel.primary_action()[1]())
        self.notification_service.assert_not_called()
        title, work, done = self.ui._submit_tool_job.call_args.args
        self.assertEqual(title, '通知测试')
        rebuilt = services.build_notifications_panel(None, self.ui)
        rebuilt.draft['selected'].set('beta')
        done(work(Event()))
        self.profile_store.load_version.assert_called_once_with('alpha')
        args = service.deliver.call_args.args
        self.assertEqual(args[:2], (frozen, 'AutoHSR 通知测试'))
        self.assertNotIn('Unsaved', args[2])
        self.assertTrue(args[3].startswith('explicit-test-'))
        self.assertEqual(rebuilt.draft['result'].get(), '测试配置 alpha · 渠道已接收测试通知。')
        self.assertFalse(rebuilt.settings_values()['notification_enabled'])
        self.save_settings.assert_not_called()

    def test_runtime_notification_summaries_are_separate_and_allowlisted(self):
        panel = services.build_notifications_panel(None, self.ui)
        panel.draft['result'].set('现有测试结果')
        rebuilt = services.build_notifications_panel(None, self.ui)
        signature = tuple(var.get() for var in self.ui.form_variables)

        def render(status, **data):
            panel.render_run_result(dict(type='notification_summary', status=status,
                                         profile='private', reason='private', **data))
            text = rebuilt.draft['run_result'].get()
            self.assertNotIn('private', text)
            self.assertEqual(rebuilt.draft['result'].get(), '现有测试结果')
            return text

        self.assertIn('渠道已受理', render('accepted', profiles=2, requested_profiles=2, accepted=2))
        self.assertIn('部分完成 · 已记录配置 3/3 · 渠道受理 1',
                      render('partial', profiles=3, requested_profiles=3, accepted=1))
        self.assertIn('已停止 · 已记录配置 1/3 · 渠道受理 1',
                      render('cancelled', profiles=1, requested_profiles=3, accepted=1))
        self.assertIn('结果状态不在通知范围', render('filtered', profiles=0))
        self.assertIn('回执待核对', render('unknown'))
        self.assertIn('已停止 · 回执计数待核对', render('cancelled'))
        for data in (
            dict(profiles=True, requested_profiles=2, accepted=1),
            dict(profiles=2, requested_profiles=2, accepted=3),
            dict(profiles=2, requested_profiles=2, accepted=1),
            dict(profiles=33, requested_profiles=33, accepted=33),
        ):
            with self.subTest(counts=data):
                text = render('accepted', **data)
                self.assertIn('回执待核对', text)
                self.assertNotIn('渠道受理 1', text)
        previous = rebuilt.draft['run_result'].get()
        panel.render_run_result(dict(type='notification_result', status='accepted', profile='private'))
        self.assertEqual(rebuilt.draft['run_result'].get(), previous)
        self.assertEqual(tuple(var.get() for var in self.ui.form_variables), signature)
        self.notification_service.assert_not_called()
        self.save_settings.assert_not_called()

    def test_notifications_avoid_unreadable_cancelled_or_changed_profiles(self):
        panel = services.build_notifications_panel(None, self.ui)
        self.assertNotIn('../unexpected', panel.profiles.options['values'])
        panel.draft['selected'].set('damaged')
        self.assertFalse(panel.primary_action()[2])
        self.assertFalse(panel.test())
        self.ui._submit_tool_job.assert_not_called()
        panel.draft['selected'].set('alpha')
        self.profile_store.load_version.return_value = (dict(id='alpha', provider='webhook', params={}), 'version')
        self.assertTrue(panel.test())
        _, work, done = self.ui._submit_tool_job.call_args.args
        event = Event()
        event.set()
        done(work(event))
        self.assertEqual(panel.draft['result'].get(), '测试配置 alpha · 测试通知已停止。')
        self.notification_service.assert_not_called()
        self.profile_store.load_version.return_value = (dict(id='alpha', provider='smtp', params={}), 'changed')
        self.assertFalse(panel.test())
        self.ui._submit_tool_job.assert_called_once()
        self.notification_service.assert_not_called()
        self.assertIn('所选配置已改变', panel.draft['result'].get())
        self.profile_store.list_public.side_effect = OSError('private storage path')
        panel.refresh_profiles()
        self.assertFalse(panel.primary_action()[2])
        self.assertNotIn('private', panel.draft['result'].get())
