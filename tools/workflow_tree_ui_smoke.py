"""Hidden Tk checks for the workflow tree editor and its saved-workflow handoff."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autohsr import theme
from autohsr.desktop_workflow_tree import WorkflowTreeDialog
from autohsr.desktop_workflows import _TASK_NAMES, build_workflow_panel
from autohsr.task_workflow import read


def workflow():
    return dict(version=1, name='示例流程', steps=[
        dict(id='seed', type='task', task='daily', params=dict(tasks=['assignments']), enabled=False),
        dict(id='check', type='if', condition=dict(step='seed', field='status', op='eq', value='success'),
             steps=[dict(id='first', type='wait', seconds=1)],
             else_steps=[dict(id='other', type='wait', seconds=2)]),
    ])


class WorkflowTreeSmoke(unittest.TestCase):
    def setUp(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        theme.apply_theme(root, 1)
        self.ui = SimpleNamespace(root=root, ui_scale=1, busy=False, closing=False,
                                  _workflow_action_changed=Mock(), _start_task_workflow=Mock(return_value=True))

    def select(self, dialog, item):
        dialog.tree.selection_set(item)
        dialog._refresh()

    def test_false_branch_paths_follow_sibling_order_and_can_transfer_to_runner_scope(self):
        original = workflow()
        dialog = WorkflowTreeDialog(self.ui, original, base_dir=None, task_names=_TASK_NAMES)
        self.select(dialog, 'branch:check:else_steps')
        self.assertTrue(dialog.actions[2].instate(('disabled',)))
        dialog.actions[0].invoke()
        dialog._store_node(dict(type='wait', seconds=3, name='第三秒'))
        inserted = dialog.tree.selection()[0]
        self.assertEqual(dialog.tree.item(inserted, 'values'), ('1/2',))
        dialog.actions[2].invoke()
        self.assertEqual(dialog.tree.item(inserted, 'values'), ('1/1',))
        dialog.actions[1].invoke()
        dialog._store_node(dict(type='wait', seconds=4, name=None))
        self.assertTrue(dialog.select_button.instate(('!disabled',)))
        dialog.select_button.invoke()
        edited, path = dialog.result
        self.assertEqual(path, '1/1')
        self.assertEqual(original, workflow())
        self.assertEqual([step['seconds'] for step in edited['steps'][1]['else_steps']], [4, 2])

    def test_empty_group_cannot_apply_and_cancel_preserves_original(self):
        original = workflow()
        dialog = WorkflowTreeDialog(self.ui, original, base_dir=None, task_names=_TASK_NAMES)
        self.select(dialog, 'node:check')
        dialog.actions[0].invoke()
        dialog._store_node(dict(type='for', count=2))
        loop = dialog.tree.selection()[0]
        dialog.apply_button.invoke()
        self.assertTrue(dialog.winfo_exists())
        self.assertIn('必须包含子步骤', dialog.feedback.get())
        self.assertEqual(original, workflow())
        self.select(dialog, 'branch:' + loop.split(':', 1)[1] + ':steps')
        dialog.actions[0].invoke()
        dialog._store_node(dict(type='continue'))
        self.assertTrue(dialog.select_button.instate(('disabled',)))
        dialog.destroy()
        self.assertIsNone(dialog.result)
        self.assertEqual(original, workflow())

    def test_modal_result_updates_only_draft_until_verified_new_file_and_run(self):
        panel = self.ui.workflow_panel = build_workflow_panel(self.ui.root, self.ui)
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'source.json'
            original = json.dumps(workflow(), ensure_ascii=False).encode('utf8')
            source.write_bytes(original)
            panel._load(source)
            panel.scope.set('指定步骤')
            panel.step_path.set('1/0')
            panel.validate()
            previous = panel.reviewed_step
            self.assertIsNotNone(previous)
            with patch('autohsr.desktop_workflow_tree.ask_workflow_tree', return_value=None):
                panel.edit_tree()
            self.assertEqual(panel.reviewed_step, previous)
            edited = workflow()
            edited['steps'][1]['else_steps'][0]['seconds'] = 9
            with patch('autohsr.desktop_workflow_tree.ask_workflow_tree', return_value=(edited, '1/1')):
                panel.edit_tree()
            self.assertTrue(panel.dirty)
            self.assertIsNone(panel.reviewed_step)
            self.assertEqual(panel.step_path.get(), '1/1')
            panel.run_saved()
            self.ui._start_task_workflow.assert_not_called()
            target = Path(folder) / 'next.json'
            panel.saved_target = target
            panel.save_as()
            self.assertEqual(read(target), edited)
            self.assertEqual(source.read_bytes(), original)
            self.assertIsNone(panel.reviewed_step)
            panel.validate()
            panel.run_saved()
            recipe = self.ui._start_task_workflow.call_args.args[0]
            self.assertEqual(recipe.path, (1, 1))
            self.assertEqual(recipe.steps[0]['seconds'], 9)

    def test_reordering_requires_fresh_step_without_widening_scope_and_busy_rejects_delivery(self):
        panel = self.ui.workflow_panel = build_workflow_panel(self.ui.root, self.ui)
        panel.new()
        panel.scope.set('指定步骤')
        panel.step_path.set('0')
        original = panel._text()
        updated = json.loads(original)
        updated['steps'].insert(0, dict(id='pause', type='wait', seconds=2))

        def busy_during_delivery(*_args, **_options):
            self.ui.busy = True
            return updated, None

        with patch('autohsr.desktop_workflow_tree.ask_workflow_tree', side_effect=busy_during_delivery):
            panel.edit_tree()
        self.assertEqual(panel._text(), original)
        self.assertEqual(panel.step_path.get(), '0')
        self.ui.busy = False
        with patch('autohsr.desktop_workflow_tree.ask_workflow_tree', return_value=(updated, None)):
            panel.edit_tree()
        self.assertEqual(panel.scope.get(), '指定步骤')
        self.assertEqual(panel.step_path.get(), '')
        self.assertTrue(panel.dirty)
        with TemporaryDirectory() as folder:
            panel.saved_target = Path(folder) / 'edited.json'
            panel.save_as()
            panel.run_saved()
        self.ui._start_task_workflow.assert_not_called()


if __name__ == '__main__':
    unittest.main()
