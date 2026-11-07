"""Hidden Tk coverage for carrying one verified capture into the workflow draft."""
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import ANY, Mock, patch

from PIL import Image

from autohsr import theme
from autohsr.config import Settings
from autohsr.desktop_workflow_template import WorkflowTemplateDialog
from autohsr.desktop_workflow_tree import WorkflowTreeDialog
from autohsr.desktop_workflows import _TASK_NAMES, build_workflow_panel
from autohsr.gui import AutoHSRWindow
from autohsr.task_workflow import read
from autohsr.workflow_yaml import load_march7th_yaml


def document(task='workflow_image'):
    params = dict(template='旧模板.png', region=[.1, .2, .8, .9], threshold=.92)
    if task == 'workflow_image':
        params['image'] = '手填来源.png'
    return dict(version=1, name='模板流程', steps=[
        dict(id='observe', type='task', task=task, params=params, enabled=False, on_failure='stop'),
        dict(id='wait', type='wait', seconds=2),
    ])


def live_image_document():
    query = dict(task='workflow_game_image', params=dict(template='旧模板.png', region=[.1, .2, .8, .9], threshold=.92),
                 value=False)
    return dict(version=1, name='实时条件', steps=[
        dict(id='observe', type='if', enabled=False, screen_condition=query, steps=[dict(id='yes', type='wait', seconds=0)],
             else_steps=[dict(id='no', type='wait', seconds=1)]),
    ])


class WorkflowTemplateBindingTests(TestCase):
    def setUp(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        self.addCleanup(root.destroy)
        self.addCleanup(root.update_idletasks)
        theme.apply_theme(root, 1)
        self.ui = SimpleNamespace(root=root, ui_scale=1, busy=False, closing=False,
                                  _workflow_action_changed=Mock(), _start_task_workflow=Mock(return_value=True))
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name).resolve()
        self.base, self.other = self.home / '原目录', self.home / '其他目录'
        self.base.mkdir()
        self.other.mkdir()
        self.source = self.base / 'original.json'
        self.source.write_text(json.dumps(document(), ensure_ascii=False), encoding='utf8')
        self.receipt = self.make_capture(self.base)

    @staticmethod
    def make_capture(base, color='green'):
        path = base / '素材' / '选区.png'
        path.parent.mkdir(exist_ok=True)
        Image.new('RGB', (24, 18), color).save(path)
        return SimpleNamespace(path=path, relative_path='素材/选区.png', sha256=sha256(path.read_bytes()).hexdigest())

    def tree(self, draft=None, *, base=None, **options):
        dialog = WorkflowTreeDialog(self.ui, draft or document(), base_dir=self.base if base is None else base,
                                    task_names=_TASK_NAMES, **options)
        self.addCleanup(lambda: dialog.destroy() if dialog.winfo_exists() else None)
        dialog.tree.selection_set('node:observe')
        dialog._refresh()
        dialog._edit()
        return dialog

    @staticmethod
    def parameters(dialog):
        return json.loads(dialog.form.parameters.get('1.0', 'end-1c'))

    def test_both_image_forms_fill_only_template_before_two_explicit_apply_actions(self):
        for task in ('workflow_image', 'workflow_game_image'):
            with self.subTest(task=task):
                original = document(task)
                dialog = self.tree(original)
                with patch('autohsr.desktop_workflow_tree._ask_template', return_value=self.receipt) as capture:
                    dialog.form.template_button.invoke()
                capture.assert_called_once_with(self.ui, dialog, base_dir=self.base, capture_current=ANY)
                expected = dict(original['steps'][0]['params'], template=self.receipt.relative_path)
                self.assertEqual(self.parameters(dialog), expected)
                self.assertEqual(dialog.draft.rows()[0].node, original['steps'][0])
                self.assertIsNone(dialog.result)
                dialog.form.apply_button.invoke()
                self.assertEqual(dialog.draft.rows()[0].node['params'], expected)
                self.assertIsNone(dialog.result)
                dialog.apply_button.invoke()
                self.assertEqual(dialog.result[0]['steps'][0]['params'], expected)
                self.assertEqual(original, document(task))
        self.ui._start_task_workflow.assert_not_called()
        self.assertEqual(self.ui.root.state(), 'withdrawn')

    def test_no_destination_disables_only_capture_and_leaves_manual_parameters(self):
        dialog = WorkflowTreeDialog(self.ui, document(), base_dir=None, task_names=_TASK_NAMES)
        dialog.tree.selection_set('node:observe')
        dialog._edit()
        try:
            self.assertTrue(dialog.form.template_button.instate(('disabled',)))
            self.assertIn('另存', dialog.form.template_button.cget('text'))
            dialog.form.apply_button.invoke()
            self.assertEqual(dialog.draft.rows()[0].node['params']['template'], '旧模板.png')
        finally:
            dialog.destroy()

    def test_cancel_focus_loss_switching_selection_or_form_cannot_fill(self):
        for state in ('cancel', 'focus', 'selection', 'task', 'close'):
            with self.subTest(state=state):
                dialog = self.tree()
                old = self.parameters(dialog)

                def modal(*_args, **_kwargs):
                    if state == 'cancel':
                        return None
                    if state == 'selection':
                        dialog.tree.selection_set('node:wait')
                        dialog._refresh()
                        dialog.tree.selection_set('node:observe')
                        dialog._refresh()
                    elif state == 'task':
                        dialog.form.values['task'].set(_TASK_NAMES['workflow_text'])
                        dialog.form.values['task'].set(_TASK_NAMES['workflow_image'])
                    elif state == 'close':
                        dialog._close_form()
                    return self.receipt

                with (patch('autohsr.desktop_workflow_tree._ask_template', side_effect=modal) as capture,
                      patch.object(dialog, 'winfo_viewable', return_value=state == 'focus'),
                      patch('autohsr.desktop_workflow_tree.theme.focus_widget',
                            side_effect=[dialog.form.parameters, None])):
                    dialog.form.template_button.invoke()
                capture.assert_called_once()
                self.assertEqual(self.parameters(dialog), old)
                self.assertEqual(dialog.template_bindings, {})

    def test_changed_receipt_and_relative_mismatch_do_not_replace_manual_value(self):
        dialog = self.tree()
        old = self.parameters(dialog)
        invalid = SimpleNamespace(**vars(self.receipt))
        invalid.relative_path = 'another.png'
        for receipt in (invalid, self.receipt):
            if receipt is self.receipt:
                Image.new('RGB', (24, 18), 'red').save(receipt.path)
            with patch('autohsr.desktop_workflow_tree._ask_template', return_value=receipt):
                dialog.form.template_button.invoke()
            self.assertEqual(self.parameters(dialog), old)
            self.assertTrue(dialog.form.error.get())

    def panel(self):
        panel = self.ui.workflow_panel = build_workflow_panel(self.ui.root, self.ui)
        panel._load(self.source)
        return panel

    def edit_hidden(self, panel, modal=None, *, after_capture=None):
        def edit(ui, draft, *, template_bindings, **options):
            dialog = WorkflowTreeDialog(ui, draft, **options)
            try:
                dialog.tree.selection_set('node:observe')
                dialog._edit()
                with patch('autohsr.desktop_workflow_tree._ask_template',
                           side_effect=modal or (lambda *_args, **_kwargs: self.receipt)):
                    dialog.form.template_button.invoke()
                if after_capture is not None:
                    after_capture(dialog)
                dialog.form.apply_button.invoke()
                dialog.apply_button.invoke()
                if dialog.result is not None:
                    template_bindings.update(dialog.template_bindings)
                return dialog.result
            finally:
                if dialog.winfo_exists():
                    dialog.destroy()

        with patch('autohsr.desktop_workflow_tree.ask_workflow_tree', side_effect=edit):
            panel.edit_tree()

    def test_live_image_template_binding_survives_alias_and_verified_save(self):
        source = live_image_document()
        self.source.write_text(json.dumps(source, ensure_ascii=False), encoding='utf8')
        original = self.source.read_bytes()
        panel = self.panel()

        def add_alias(dialog):
            self.assertEqual(dialog.form.values['condition_source'].get(), '实时图像')
            self.assertEqual(dialog.form.values['screen_value'].get(), '未匹配')
            params = self.parameters(dialog)
            self.assertEqual(params['template'], self.receipt.relative_path)
            params['template'] = './' + params['template']
            dialog.form.parameters.replace('1.0', 'end-1c', json.dumps(params, ensure_ascii=False))

        self.edit_hidden(panel, after_capture=add_alias)
        expected = source['steps'][0]
        expected['screen_condition']['params']['template'] = './' + self.receipt.relative_path
        self.assertEqual(json.loads(panel._text())['steps'][0], expected)
        self.assertIn(('observe', Path(self.receipt.relative_path)), panel._template_bindings)
        self.assertEqual(self.source.read_bytes(), original)

        self.make_capture(self.other)
        different = panel.saved_target = self.other / 'elsewhere.json'
        panel.save_as()
        self.assertIn('绑定到原目录', panel.status.get())
        self.assertFalse(different.exists())

        target = panel.saved_target = self.base / 'verified.json'
        from autohsr.task_workflow_draft import publish_new

        def verify_locked(path, writer, *, limit):
            if os.name == 'nt':
                with self.assertRaises(PermissionError):
                    self.receipt.path.write_bytes(b'replacement')
            return publish_new(path, writer, limit=limit)

        with patch('autohsr.task_workflow_draft.publish_new', side_effect=verify_locked) as publish:
            panel.save_as()
        publish.assert_called_once()
        self.assertEqual(read(target)['steps'][0], expected)
        panel._load(target)
        self.assertEqual(panel._source_file, target)
        self.assertIn(('observe', Path(self.receipt.relative_path)), panel._template_bindings)
        self.ui._start_task_workflow.assert_not_called()

    def test_switching_live_source_during_capture_does_not_fill_the_restored_form(self):
        dialog = self.tree(live_image_document())
        original = self.parameters(dialog)

        def change_source(*_args, **_kwargs):
            dialog.form.values['condition_source'].set('实时文字')
            dialog.form.values['condition_source'].set('实时图像')
            return self.receipt

        with patch('autohsr.desktop_workflow_tree._ask_template', side_effect=change_source) as modal:
            dialog.form.template_button.invoke()
        modal.assert_called_once()
        self.assertEqual(self.parameters(dialog), original)
        dialog.form.apply_button.invoke()
        self.assertEqual(dialog.template_bindings, {})

    def test_live_properties_scroll_separately_from_json_tree_and_footer(self):
        dialog = self.tree(live_image_document())
        self.assertTrue(dialog._property_view.grid_info())
        self.assertTrue(dialog.apply_button.pack_info())
        canvas = dialog._property_canvas
        self.assertTrue(canvas.cget('yscrollcommand'))
        with patch.object(canvas, 'yview_scroll') as scroll:
            event = SimpleNamespace(widget=dialog.form.controls['condition_source'], delta=-120)
            self.assertEqual(dialog._scroll_properties(event), 'break')
            for widget in (dialog.form.parameters, dialog.tree, dialog.apply_button):
                self.assertIsNone(dialog._scroll_properties(SimpleNamespace(widget=widget, delta=-120)))
        scroll.assert_called_once_with(1, 'units')
        dialog.form.cancel_button.invoke()
        self.assertFalse(dialog._property_view.grid_info())
        self.assertEqual(self.ui.root.state(), 'withdrawn')

    def test_explicit_save_target_must_be_new_json_before_opening_capture(self):
        panel = self.panel()
        legacy_source = self.base / 'original.flow'
        self.source.rename(legacy_source)
        panel._load(legacy_source)
        self.assertEqual(panel._template_base(), self.base)
        original = panel._text()
        occupied = self.base / 'occupied.JSON'
        occupied.write_bytes(b'preserve-existing')
        modal = Mock(return_value=self.receipt)
        for target in (self.base / 'wrong.png', self.other / 'missing' / 'new.json', occupied,
                       occupied.with_suffix('.json') if os.name == 'nt' else occupied):
            with self.subTest(target=target):
                panel.saved_target = target
                self.edit_hidden(panel, modal)
                modal.assert_not_called()
                self.assertEqual(panel._text(), original)
        panel.saved_target = self.base / 'new.JSON'
        self.edit_hidden(panel, modal)
        modal.assert_called_once()
        self.assertEqual(json.loads(panel._text())['steps'][0]['params']['template'], self.receipt.relative_path)
        self.assertEqual(occupied.read_bytes(), b'preserve-existing')

    def test_yaml_draft_uses_only_a_destination_that_its_real_save_accepts(self):
        panel = self.panel()
        yaml_source = self.other / '旧流程.yaml'
        original = b'name: upstream\nsteps: [{type: wait}]\n'
        yaml_source.write_bytes(original)
        panel._install(load_march7th_yaml(yaml_source))
        panel._replace_draft_document(document())
        (self.base / 'nested').mkdir()
        modal = Mock(return_value=self.receipt)
        for target in (None, self.base / 'wrong.png', self.base / 'nested' / '..' / 'new.json'):
            with self.subTest(target=target):
                panel.saved_target = target
                self.edit_hidden(panel, modal)
                modal.assert_not_called()
        target = panel.saved_target = self.base / 'new.json'
        self.edit_hidden(panel, modal)
        modal.assert_called_once()
        panel.save_as()
        self.assertEqual(read(target)['steps'][0]['params']['template'], self.receipt.relative_path)
        self.assertEqual(yaml_source.read_bytes(), original)

    def test_occupied_json_during_png_picker_does_not_submit_a_save(self):
        panel = self.panel()
        target = panel.saved_target = self.base / 'new.json'
        candidate = self.base / 'late.png'
        self.ui._submit_tool_job = Mock()

        def modal(ui, owner, *, base_dir, capture_current):
            dialog = WorkflowTemplateDialog(ui, owner, base_dir=base_dir, capture_current=capture_current)
            try:
                self.assertTrue(capture_current())
                dialog._load_image(Image.new('RGB', (24, 18), 'green'), '本地图片')
                dialog.select_all()

                def occupy(*_args, **_kwargs):
                    target.write_bytes(b'other-owner')
                    return str(candidate)

                with patch('autohsr.desktop_workflow_template.filedialog.asksaveasfilename', side_effect=occupy):
                    dialog.save()
                self.assertIsNone(dialog.result)
                self.assertIn('另存位置或编辑状态已变化', dialog.message)
            finally:
                dialog.destroy()

        self.edit_hidden(panel, modal)
        self.ui._submit_tool_job.assert_not_called()
        self.assertFalse(candidate.exists())
        self.assertEqual(target.read_bytes(), b'other-owner')

    def test_switching_save_base_away_and_back_during_modal_invalidates_capture(self):
        panel = self.panel()
        original = panel._text()

        def change_base(*_args, **_kwargs):
            panel.saved_target = self.other / 'temporary.json'
            panel.saved_target = None
            return self.receipt

        self.edit_hidden(panel, change_base)
        self.assertEqual(panel._text(), original)
        self.assertEqual(panel._template_bindings, {})

    def test_current_draft_binding_survives_resize_and_same_folder_save(self):
        panel = self.panel()
        original = self.source.read_bytes()
        self.edit_hidden(panel)
        self.assertTrue(panel.dirty)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(list(self.base.glob('*.json')), [self.source])

        self.ui.ui_scale = 1.5
        restored = self.ui.workflow_panel = build_workflow_panel(self.ui.root, self.ui)
        restored.restore_draft(panel.snapshot_draft())
        panel.destroy()
        selected = self.base / '同目录.json'
        restored.saved_target = selected
        restored.save_as()
        self.assertEqual(read(selected)['steps'][0]['params']['template'], self.receipt.relative_path)
        self.assertEqual(self.source.read_bytes(), original)

        # Even an existing identically named asset in another folder cannot silently take over.
        self.make_capture(self.other, color='orange')
        target = self.other / '另存.json'
        restored.saved_target = target
        restored.save_as()
        self.assertFalse(target.exists())
        self.assertIn('绑定到原目录', restored.status.get())

    def test_manually_changed_template_keeps_existing_save_as_relative_semantics(self):
        panel = self.panel()
        self.edit_hidden(panel)
        edited = json.loads(panel._text())
        edited['steps'][0]['params']['template'] = '手填新模板.png'
        panel._replace_draft_document(edited)
        target = self.other / '另存.json'
        panel.saved_target = target
        panel.save_as()
        self.assertEqual(read(target), edited)
        self.assertEqual(panel.draft.validate().base_dir, self.other)

    def test_reloading_the_same_definition_does_not_rebind_a_captured_template(self):
        panel = self.panel()
        self.edit_hidden(panel)
        panel.saved_target = self.base / '保存.json'
        panel.save_as()
        panel.reload()
        self.make_capture(self.other, color='orange')
        target = self.other / '另存.json'
        panel.saved_target = target
        panel.save_as()
        self.assertFalse(target.exists())
        self.assertIn('绑定到原目录', panel.status.get())

    def test_recapture_in_new_directory_rebinds_the_same_relative_name(self):
        panel = self.panel()
        self.edit_hidden(panel)
        panel.saved_target = target = self.other / '另存.json'
        self.receipt = self.make_capture(self.other, color='red')
        self.edit_hidden(panel)
        panel.save_as()
        self.assertEqual(read(target)['steps'][0]['params']['template'], self.receipt.relative_path)
        self.assertEqual(panel.draft.validate().base_dir, self.other)

    def test_other_step_preview_still_works_but_save_checks_entire_tree(self):
        panel = self.panel()
        self.edit_hidden(panel)
        panel.saved_target = target = self.other / '另存.json'
        panel.scope.set('指定步骤')
        panel.step_path.set('1')
        panel.validate()
        self.assertIn('校验通过', panel.status.get())
        self.assertIn('步骤 1', panel.budget.get())
        panel.save_as()
        self.assertFalse(target.exists())
        self.assertIn('绑定到原目录', panel.status.get())

    def test_save_rechecks_hash_and_holds_capture_during_publication(self):
        panel = self.panel()
        self.edit_hidden(panel)
        target = self.base / '另存.json'
        panel.saved_target = target
        original = self.receipt.path.read_bytes()
        self.receipt.path.write_bytes(original + b'changed')
        panel.save_as()
        self.assertFalse(target.exists())
        self.assertIn('无法回读', panel.status.get())

        self.receipt = self.make_capture(self.base)
        self.edit_hidden(panel)
        if os.name == 'nt':
            replacement = self.base / 'candidate.png'
            replacement.write_bytes(original + b'other')
            save = panel.draft.save_as
            current_folder = self.receipt.path.parent.resolve(strict=True)
            moved_folder = (self.base / 'retargeted').resolve()
            self.assertTrue(current_folder.is_relative_to(self.base) and moved_folder.is_relative_to(self.base))

            def publishing(destination):
                with self.assertRaises(PermissionError):
                    os.replace(replacement, self.receipt.path)
                with self.assertRaises(PermissionError):
                    current_folder.rename(moved_folder)
                return save(destination)

            with patch.object(panel.draft, 'save_as', side_effect=publishing) as checked:
                panel.save_as()
            checked.assert_called_once_with(target)
            self.assertEqual(self.receipt.path.read_bytes(), original)
        else:
            panel.save_as()
        self.assertTrue(target.exists())

    def test_same_bytes_from_replaced_file_do_not_reuse_the_capture_receipt(self):
        panel = self.panel()
        self.edit_hidden(panel)
        replacement = self.base / 'candidate.png'
        replacement.write_bytes(self.receipt.path.read_bytes())
        os.replace(replacement, self.receipt.path)
        target = self.base / '另存.json'
        panel.saved_target = target
        panel.save_as()
        self.assertFalse(target.exists())
        self.assertIn('无法回读', panel.status.get())

    def saved_capture(self, name):
        panel = self.panel()
        self.edit_hidden(panel)
        document = json.loads(panel._text())
        document['steps'][0]['enabled'] = True
        panel._replace_draft_document(document)
        panel.saved_target = self.base / name
        panel.save_as()
        panel.scope.set('指定步骤')
        panel.step_path.set('0')
        panel.validate()
        self.assertTrue(panel._can_run_saved())
        return panel

    def test_run_rejects_changed_capture_and_identical_replacement_after_review(self):
        for same_bytes in (False, True):
            with self.subTest(same_bytes=same_bytes):
                self.receipt = self.make_capture(self.base)
                panel = self.saved_capture(f'check-{same_bytes}.json')
                identity = self.receipt.path.stat().st_ino
                if same_bytes:
                    replacement = self.base / 'replacement.png'
                    replacement.write_bytes(self.receipt.path.read_bytes())
                    os.replace(replacement, self.receipt.path)
                    self.assertNotEqual(self.receipt.path.stat().st_ino, identity)
                else:
                    Image.new('RGB', (24, 18), 'red').save(self.receipt.path)
                    self.assertEqual(self.receipt.path.stat().st_ino, identity)
                panel.run_saved()
                self.ui._start_task_workflow.assert_not_called()
                self.assertIn('无法回读', panel.status.get())
                self.assertFalse(panel._can_run_saved())

    def test_worker_rechecks_capture_and_holds_explicitly_reselected_source(self):
        panel = self.saved_capture('run.json')
        jobs = []
        ui = self.ui
        ui.events = Mock()
        ui._native_run = Mock()
        ui._read_settings = Mock(return_value=Settings())
        ui._start_desktop_job = Mock(side_effect=lambda _title, work, *_args, **_kw: jobs.append(work) or True)
        ui._start_task_workflow = AutoHSRWindow._start_task_workflow.__get__(ui)
        ui._start_scoped_runner = AutoHSRWindow._start_scoped_runner.__get__(ui)
        runner = self.enterContext(patch('autohsr.task_workflow_run.TaskWorkflowRunner'))
        panel.run_saved()
        replacement = self.base / 'replacement.png'
        replacement.write_bytes(self.receipt.path.read_bytes())
        os.replace(replacement, self.receipt.path)
        result = jobs[0](None)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('无法回读', result['error'])
        runner.assert_not_called()
        ui._native_run.run.assert_not_called()

        # Reapplying a new capture with the same relative name still invalidates review.
        self.receipt = self.make_capture(self.base, color='orange')
        self.edit_hidden(panel)
        self.assertFalse(panel._can_run_saved())
        panel.validate()
        panel.run_saved()
        self.assertEqual(len(jobs), 2)

        def run_native(_runner):
            if os.name == 'nt':
                with self.assertRaises(PermissionError), self.receipt.path.open('ab'):
                    pass
            return dict(status='success')

        ui._native_run.run.side_effect = run_native
        self.assertEqual(jobs[1](None), dict(status='success'))
        self.assertEqual(runner.call_args.kwargs['selected_path'], '0')
        ui._native_run.run.assert_called_once()
        with self.receipt.path.open('ab'):
            pass  # The worker released the read handle.

    def test_selected_leaf_does_not_require_ancestor_condition_template(self):
        self.source.write_text(json.dumps(live_image_document(), ensure_ascii=False), encoding='utf8')
        panel = self.saved_capture('condition.json')
        self.receipt.path.write_bytes(b'changed')
        panel.run_saved()
        self.ui._start_task_workflow.assert_not_called()
        self.assertIn('无法回读', panel.status.get())
        panel.step_path.set('0/0')
        panel.validate()
        panel.run_saved()
        self.ui._start_task_workflow.assert_called_once()
        self.assertEqual(self.ui._start_task_workflow.call_args.args[0].path, (0, 0))

    def test_save_uses_the_validated_directory_instead_of_resolving_a_path_twice(self):
        panel = self.panel()
        self.edit_hidden(panel)
        target = self.other / '另存.json'
        checked = self.base / target.name
        panel.saved_target = target
        validate = panel._draft_recipe
        # Model a selected directory alias that resolved to the capture directory at validation.
        with patch.object(panel, '_draft_recipe', side_effect=lambda **_: validate(destination=checked)):
            panel.save_as()
        self.assertFalse(target.exists())
        self.assertEqual(read(checked)['steps'][0]['params']['template'], self.receipt.relative_path)
