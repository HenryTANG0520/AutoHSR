"""Exercise structural edits independently of desktop widgets and execution."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from autohsr.config import Settings
from autohsr.task_workflow import MAX_DEPTH, MAX_NODES, WorkflowError, compile_recipe, task_spec
from autohsr.workflow_tree_edit import WorkflowTreeDraft


def document(*steps):
    return dict(version=1, name='树编辑测试', steps=list(steps))


def wait(identity):
    return dict(id=identity, type='wait', seconds=0)


def condition(identity):
    return dict(step=identity, field='status', op='eq', value='success')


class WorkflowTreeEditTests(TestCase):
    def test_rows_match_formal_combined_paths_and_are_detached(self):
        source = document(wait('anchor'), dict(id='gate', type='if', condition=condition('anchor'),
            steps=[wait('first'), dict(id='loop', type='for', count=1, steps=[wait('inside')])],
            else_steps=[dict(id='other', type='if', condition=condition('anchor'), steps=[wait('fallback')])]),
            wait('tail'))
        draft = WorkflowTreeDraft(source)
        rows = draft.rows()
        self.assertEqual([(row.identity, row.parent_id, row.branch, row.path) for row in rows], [
            ('anchor', None, 'steps', (0,)), ('gate', None, 'steps', (1,)),
            ('first', 'gate', 'steps', (1, 0)), ('loop', 'gate', 'steps', (1, 1)),
            ('inside', 'loop', 'steps', (1, 1, 0)), ('other', 'gate', 'else_steps', (1, 2)),
            ('fallback', 'other', 'steps', (1, 2, 0)), ('tail', None, 'steps', (2,)),
        ])
        for row in rows:
            path = '/'.join(map(str, row.path))
            self.assertEqual(compile_recipe(source, selected_path=path).steps[0], row.node)
        source['steps'][1]['steps'].clear()
        rows[1].node['else_steps'].clear()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            recipe = draft.validate(base_dir=directory)
            self.assertEqual(recipe.base_dir, directory)
            recipe.document['steps'].clear()
        self.assertEqual(draft.validate().steps[1]['steps'][0]['id'], 'first')
        self.assertEqual(draft.validate().steps[1]['else_steps'][0]['id'], 'other')

    def test_add_both_branches_patch_and_move_keep_ids_and_children(self):
        draft = WorkflowTreeDraft(document())
        with self.assertRaises(WorkflowError):
            draft.validate()
        anchor = draft.add(dict(type='wait', seconds=0, name=None))
        gate = draft.add(dict(type='if', condition=condition(anchor), name='旧名称'), after=anchor)
        self.assertNotIn('name', draft.rows()[0].node)
        self.assertEqual(draft.rows()[1].node['steps'], [])
        fallback = draft.add(dict(type='wait', seconds=3), parent_id=gate, branch='else_steps')
        self.assertEqual(draft.rows()[-1].path, (1, 0))
        with self.assertRaises(WorkflowError):
            draft.validate()
        first = draft.add(dict(type='wait', seconds=1), parent_id=gate)
        final = draft.add(dict(type='wait', seconds=4), parent_id=gate)
        middle = draft.add(dict(type='wait', seconds=2), parent_id=gate, after=first)
        self.assertTrue(draft.move(final, -2))
        self.assertFalse(draft.move(fallback, -1))
        self.assertFalse(draft.move(first, 0))
        draft.update(gate, dict(type='if', name=None, enabled=False))
        draft.update(middle, dict(seconds=20))
        rows = draft.rows()
        edited = rows[1].node
        self.assertNotIn('name', edited)
        self.assertEqual(edited['condition'], condition(anchor))
        self.assertEqual([node['id'] for node in edited['steps']], [final, first, middle])
        self.assertEqual(edited['steps'][-1]['seconds'], 20)
        self.assertEqual([node['id'] for node in edited['else_steps']], [fallback])
        self.assertEqual(rows[-1].path, (1, 3))
        draft.validate()

    def test_nested_else_parent_is_editable_by_id_after_paths_change(self):
        source = document(wait('anchor'), dict(id='gate', type='if', condition=condition('anchor'),
            steps=[wait('first')], else_steps=[dict(id='loop', type='for', count=1, steps=[wait('inside')])]))
        draft = WorkflowTreeDraft(source)
        added = draft.add(dict(type='wait', seconds=1), parent_id='gate', after='first')
        nested = draft.add(dict(type='continue'), parent_id='loop', after='inside')
        draft.update('inside', dict(seconds=2))
        self.assertTrue(draft.move(nested, -1))
        draft.remove(added)
        self.assertEqual(next(row.path for row in draft.rows() if row.identity == nested), (1, 1, 0))
        self.assertEqual(draft.validate().steps[1]['else_steps'][0]['steps'], [
            dict(id=nested, type='continue'), dict(id='inside', type='wait', seconds=2),
        ])

    def test_dangling_references_remain_unbound_until_explicit_repair(self):
        draft = WorkflowTreeDraft(document(wait('step_1'), dict(id='gate', type='if',
            condition=condition('step_1'), steps=[wait('step_2')])))
        self.assertTrue(draft.move('gate', -1))
        with self.assertRaises(WorkflowError):
            draft.validate()
        self.assertTrue(draft.move('gate', 1))
        draft.remove('step_1')
        draft.remove('step_2')
        with self.assertRaises(WorkflowError):
            draft.validate()
        replacement = draft.add(dict(type='wait', seconds=0))
        self.assertNotIn(replacement, ('step_1', 'step_2'))
        child = draft.add(dict(type='wait', seconds=0), parent_id='gate')
        self.assertNotIn(child, ('step_1', 'step_2'))
        self.assertTrue(draft.move(replacement, -1))
        draft.update('gate', dict(condition=condition(replacement)))
        draft.validate()

        unsaved = WorkflowTreeDraft(document(dict(id='gate', type='if',
            condition=condition('step_2'), steps=[])))
        self.assertNotEqual(unsaved.add(dict(type='wait', seconds=0)), 'step_2')

    def test_budget_errors_are_draft_only_and_compile_after_repair(self):
        draft = WorkflowTreeDraft(document())
        fields = dict(type='task', task='daily', params=dict(tasks=['assignments']))
        first, second = draft.add(fields), draft.add(fields)
        fields['params']['tasks'].append('battle')
        with self.assertRaisesRegex(WorkflowError, '最多一份日常预算'):
            draft.validate()
        draft.update(second, dict(enabled=False))
        recipe = draft.validate()
        self.assertEqual(recipe.profile['daily_calls'], 1)
        self.assertEqual(recipe.steps[0]['id'], first)
        self.assertEqual(recipe.steps[0]['params'], {'tasks': ['assignments']})
        draft.name = '已校验名称'
        self.assertEqual(draft.validate().document['name'], '已校验名称')

    def test_invalid_addresses_and_fields_leave_current_draft_unchanged(self):
        source = document(wait('anchor'), dict(id='gate', type='if',
            condition=condition('anchor'), steps=[wait('first')], else_steps=[wait('fallback')]))
        draft = WorkflowTreeDraft(source)
        original = draft.rows()
        for change in (
            lambda: draft.add(dict(type='wait', seconds=0), branch='else_steps'),
            lambda: draft.add(dict(type='wait', seconds=0), parent_id='missing'),
            lambda: draft.add(dict(type='wait', seconds=0), parent_id='anchor'),
            lambda: draft.add(dict(type='wait', seconds=0), parent_id='gate', after='fallback'),
            lambda: draft.add(dict(type='wait', seconds=0), parent_id='gate', after='anchor'),
            lambda: draft.add(dict(type='continue'), parent_id='gate'),
            lambda: draft.add(dict(type='click', x=100, y=200)),
            lambda: draft.add(dict(type='task', task='daily', params=dict(script='unsafe'))),
            lambda: draft.add(dict(type='task', task='daily', params=dict(tasks=('assignments',)))),
            lambda: draft.add(dict(type='task', task='daily', params=dict(use_power_plan='true'))),
            lambda: draft.add(dict(type='wait', seconds=0, enabled=1)),
            lambda: draft.add(dict(type='wait', seconds=0, id='foreign')),
            lambda: draft.update('gate', dict(type='for')),
            lambda: draft.update('gate', dict(steps=[])),
            lambda: draft.update('gate', dict(condition=condition('1/0'))),
            lambda: draft.update('first', dict(seconds=True)),
            lambda: draft.update('first', dict(seconds=float('nan'))),
            lambda: draft.remove('unknown'),
            lambda: draft.move('first', True),
            lambda: setattr(draft, 'name', ''),
        ):
            with self.assertRaises(WorkflowError):
                change()
            self.assertEqual(draft.rows(), original)
            self.assertEqual(draft.name, '树编辑测试')
        fields = dict(type='wait', seconds=1)
        self.assertEqual(draft.add(fields), WorkflowTreeDraft(source).add(fields))

    def test_legacy_partial_task_settings_are_validated_by_the_existing_runtime_contract(self):
        source = document(dict(id='redeem', type='task', task='daily', params={
            'tasks': ['redemption'], 'redemption_source': 'manual',
        }))
        draft = WorkflowTreeDraft(source)
        draft.update('redeem', dict(name='手动批次'))
        recipe = draft.validate()
        settings, _ = task_spec(Settings(redemption_codes=['LOCALTESTONLY']), recipe.steps[0], recipe.base_dir)
        self.assertTrue(settings.redemption_enabled)
        self.assertEqual(settings.redemption_codes, ['LOCALTESTONLY'])
        self.assertNotIn('redemption_codes', recipe.steps[0]['params'])

    def test_bounds_duplicate_ids_and_wrong_branch_shapes_are_structural(self):
        for value in (
            document(wait('same'), wait('same')),
            document(dict(id='loop', type='for', count=1, steps=[], else_steps=[])),
            document(dict(id='loop', type='for', count=1, steps={})),
            document(dict(id='gate', type='if', condition=condition('@last'))),
        ):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                WorkflowTreeDraft(value)
        draft = WorkflowTreeDraft(document(*(wait(f'w{index}') for index in range(MAX_NODES))))
        with self.assertRaisesRegex(WorkflowError, '最多256个步骤'):
            draft.add(dict(type='wait', seconds=1))
        self.assertEqual(len(draft.rows()), MAX_NODES)

        node = wait('last')
        for index in range(MAX_DEPTH):
            node = dict(id=f'loop{index}', type='for', count=1, steps=[node])
        with self.assertRaisesRegex(WorkflowError, '嵌套过深'):
            WorkflowTreeDraft(document(node))
