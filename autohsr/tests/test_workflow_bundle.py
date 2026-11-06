from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings
import wave
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image

from autohsr import workflow_bundle as bundles
from autohsr.config import Settings
from autohsr.models import Stopped
from autohsr.task_workflow import compile_recipe, read, task_spec


def task(identity, kind, **params):
    return dict(id=identity, type='task', task=kind, params=params)


def flow(*steps):
    return dict(version=1, name='测试素材', steps=list(steps))


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


@unittest.skipUnless(os.name == 'nt', 'Windows exclusive directory publication')
class WorkflowBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='ahsr-zip-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'drafts' / 'private-workflow.json'
        self.source.parent.mkdir()
        self.media = self.root / 'media'
        self.media.mkdir()
        self.png = self.media / 'private-image.png'
        self.jpg = self.media / 'private-template.JPEG'
        self.wav = self.media / 'private-prompt.wav'
        with Image.new('RGB', (32, 32), color='green') as image:
            image.save(self.png)
            image.save(self.jpg, format='JPEG')
        with wave.open(str(self.wav), 'wb') as audio:
            audio.setparams((1, 2, 8000, 800, 'NONE', 'not compressed'))
            audio.writeframes(bytes(1600))
        self.output = self.root / 'bundle.zip'
        self.destination = self.root / 'received'

    def save(self, definition):
        raw = encode(definition)
        self.source.write_bytes(raw)
        return raw

    def write_archive(self, definition, assets=(), *, changed_manifest=None, compressed=False):
        members = [('workflow.json', encode(definition)), *assets]
        manifest = {'schema': 1, 'files': {
            (name.filename if isinstance(name, ZipInfo) else name): dict(size=len(data), sha256=sha256(data).hexdigest())
            for name, data in members
        }}
        if changed_manifest is not None:
            changed_manifest(manifest)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='Duplicate name:')
            with ZipFile(self.output, 'w', **({'compression': ZIP_DEFLATED} if compressed else {})) as archive:
                for name, data in members:
                    archive.writestr(name, data)
                archive.writestr('manifest.json', encode(manifest))

    def assert_unpublished(self):
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('.autohsr-bundle-*')), [])

    def test_round_trip_copies_only_explicit_material_and_rewrites_every_branch(self):
        secret = self.source.parent / 'private-credentials.json'
        secret.write_text('private marker', encoding='utf-8')
        image = task('check_image', 'workflow_image', image='../media/private-image.png', template=str(self.jpg))
        audio = task('sound', 'workflow_audio', path=str(self.wav))
        alternate = dict(task('alternate', 'workflow_text', image=str(self.png), text='样本'), enabled=False)
        source_before = self.save(flow(
            task('check_text', 'workflow_text', image='../media/private-image.png', text='样本'),
            dict(id='decision', type='if', condition=dict(step='check_text', field='text_found', op='eq', value=True),
                 steps=[image, audio], else_steps=[alternate])))

        self.assertEqual(bundles.export_bundle(self.source, self.output), self.output)
        with ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {'workflow.json', 'manifest.json', 'assets/0001.png',
                                                     'assets/0002.jpeg', 'assets/0003.wav'})
            manifest = json.loads(archive.read('manifest.json'))
            self.assertNotIn(b'private-', archive.read('workflow.json'))
            for name, row in manifest['files'].items():
                raw = archive.read(name)
                self.assertEqual(row, {'size': len(raw), 'sha256': sha256(raw).hexdigest()})

        self.assertEqual(bundles.import_bundle(self.output, self.destination), self.destination / 'workflow.json')
        document = read(self.destination / 'workflow.json')
        recipe = compile_recipe(document, base_dir=self.destination)
        self.assertEqual(document['steps'][1]['else_steps'][0]['params']['image'], 'assets/0001.png')
        _, options = task_spec(Settings(), recipe.steps[1]['steps'][1], recipe.base_dir)
        self.assertEqual(Path(options['path']), self.destination / 'assets' / '0003.wav')
        for name, original in (('0001.png', self.png), ('0002.jpeg', self.jpg), ('0003.wav', self.wav)):
            self.assertEqual((self.destination / 'assets' / name).read_bytes(), original.read_bytes())
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(secret.read_text(encoding='utf-8'), 'private marker')

    def test_material_free_definition_can_be_imported(self):
        self.save(flow(dict(id='wait', type='wait', seconds=0)))
        bundles.export_bundle(self.source, self.output)
        result = bundles.import_bundle(self.output, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [result])

    def test_reject_external_nonmaterial_dependencies_even_when_disabled(self):
        for node, reason in (
                (task('warp', 'warp_analysis', imports=['private-record.json']), '跃迁记录'),
                (task('notify', 'workflow_notify', profile='saved', message='private message'), '本地通知方案'),
                (task('plan', 'plan', use_power_plan=True), '本地体力计划')):
            with self.subTest(reason=reason):
                self.save(flow(dict(node, enabled=False)))
                with self.assertRaisesRegex(bundles.BundleError, reason):
                    bundles.export_bundle(self.source, self.output)
                self.assertFalse(self.output.exists())
                self.write_archive(flow(dict(node, enabled=False)))
                with self.assertRaisesRegex(bundles.BundleError, reason):
                    bundles.import_bundle(self.output, self.destination)
                self.assert_unpublished()
                self.output.unlink()

    def test_missing_and_masquerading_media_cannot_publish(self):
        self.save(flow(task('check', 'workflow_text', image='private-missing.png', text='样本')))
        with self.assertRaises(bundles.BundleError) as missing:
            bundles.export_bundle(self.source, self.output)
        self.assertNotIn('private', str(missing.exception))
        self.assertFalse(self.output.exists())
        renamed = self.media / 'private-record.png'
        renamed.write_text('{"private":"test"}', encoding='utf-8')
        self.save(flow(task('check', 'workflow_text', image=str(renamed), text='样本')))
        with self.assertRaisesRegex(bundles.BundleError, '实际图片格式'):
            bundles.export_bundle(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_explicit_private_redemption_fields_cannot_be_exported_or_imported(self):
        overrides = (
            dict(redemption_codes=['PRIVATE-CODE']),
            dict(redemption_codes=[]),
            dict(redemption_catalog=str(self.root / 'private-catalog.json')),
            dict(redemption_catalog=''),
            dict(redemption_source='file'),
            dict(redemption_source='manual'),
            dict(redemption_source={'unexpected': 'PRIVATE-CODE'}),
            dict(redemption_server={'unexpected': 'PRIVATE-CODE'}),
            dict(redemption_claim_mail='PRIVATE-CODE'),
        )
        for params in overrides:
            with self.subTest(fields=tuple(params)):
                protected = dict(task('daily', 'daily', tasks=['redemption'], **params), enabled=False)
                document = flow(dict(id='gate', type='wait', seconds=0),
                                dict(id='branch', type='if', condition=dict(step='gate', field='status',
                                                                          op='eq', value='success'),
                                     steps=[dict(id='nothing', type='wait', seconds=0)], else_steps=[protected]))
                source = self.save(document)
                with self.assertRaisesRegex(bundles.BundleError, '在线兑换') as exported:
                    bundles.export_bundle(self.source, self.output)
                self.assertNotIn('PRIVATE-CODE', str(exported.exception))
                self.assertNotIn('private-catalog', str(exported.exception))
                self.assertFalse(self.output.exists())
                self.assertEqual(self.source.read_bytes(), source)
                self.write_archive(document)
                before = self.output.read_bytes()
                with self.assertRaisesRegex(bundles.BundleError, '在线兑换') as imported:
                    bundles.import_bundle(self.output, self.destination)
                self.assertNotIn('PRIVATE-CODE', str(imported.exception))
                self.assertNotIn('private-catalog', str(imported.exception))
                self.assertEqual(self.output.read_bytes(), before)
                self.assert_unpublished()
                self.output.unlink()

    def test_public_online_redemption_and_local_resume_flags_stay_portable(self):
        document = flow(task('daily', 'daily', tasks=['redemption'], redemption_source='online',
                             redemption_server='cn', redemption_claim_mail=False),
                        task('du', 'differential_universe', resume_active=True, periodic_rank=5),
                        task('cw', 'currency_wars_loop', resume=True))
        self.save(document)
        bundles.export_bundle(self.source, self.output)
        self.assertEqual(read(bundles.import_bundle(self.output, self.destination)), document)

    def test_duplicate_traversal_and_unknown_names_never_extract(self):
        definition = flow(task('check', 'workflow_text', image='assets/0001.png', text='样本'))
        good = ('assets/0001.png', self.png.read_bytes())
        for extra in (good, ('../escaped.png', good[1]), (r'assets\0001.png', good[1]),
                      ('assets/0001.png:stream', good[1]), ('C:/escape.png', good[1]),
                      ('Assets/0001.png', good[1]), ('profile.json', b'{}'), ('assets/0002.png', good[1])):
            with self.subTest(name=extra[0]):
                self.write_archive(definition, [good, extra])
                with self.assertRaises(bundles.BundleError):
                    bundles.import_bundle(self.output, self.destination)
                self.assert_unpublished()
        self.assertFalse((self.root / 'escaped.png').exists())

    def test_archive_symlink_metadata_cannot_publish(self):
        link = ZipInfo('assets/0001.png')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_archive(flow(task('check', 'workflow_text', image='assets/0001.png', text='样本')),
                           [(link, self.png.read_bytes())])
        with self.assertRaises(bundles.BundleError):
            bundles.import_bundle(self.output, self.destination)
        self.assert_unpublished()

    def test_manifest_hash_and_missing_or_absolute_references_fail_closed(self):
        valid = flow(task('check', 'workflow_text', image='assets/0001.png', text='样本'))
        data = [('assets/0001.png', self.png.read_bytes())]
        self.write_archive(valid, data, changed_manifest=lambda manifest: manifest['files']['assets/0001.png'].update(
            sha256='0' * 64))
        with self.assertRaisesRegex(bundles.BundleError, '摘要'):
            bundles.import_bundle(self.output, self.destination)
        self.assert_unpublished()

        self.write_archive(valid)
        with self.assertRaisesRegex(bundles.BundleError, '缺少'):
            bundles.import_bundle(self.output, self.destination)
        self.assert_unpublished()

        self.write_archive(flow(task('check', 'workflow_text', image=str(self.png), text='样本')), data)
        with self.assertRaisesRegex(bundles.BundleError, '相对引用'):
            bundles.import_bundle(self.output, self.destination)
        self.assert_unpublished()

    def test_expanded_and_index_limits_precede_payload_extraction(self):
        definition = flow(task('audio', 'workflow_audio', path='assets/0001.wav'))
        self.write_archive(definition, [('assets/0001.wav', self.wav.read_bytes())], compressed=True)
        with patch.object(bundles, '_MAX_EXPANDED', 1000), patch.object(bundles, '_verify_media') as media:
            with self.assertRaisesRegex(bundles.BundleError, '展开'):
                bundles.import_bundle(self.output, self.destination)
            media.assert_not_called()
        self.assert_unpublished()
        with patch.object(bundles, '_MAX_INDEX', 64), patch.object(bundles, 'ZipFile') as parser:
            with self.assertRaisesRegex(bundles.BundleError, '目录记录'):
                bundles.import_bundle(self.output, self.destination)
            parser.assert_not_called()
        self.assert_unpublished()

    def test_bounded_deflated_material_retains_exact_bytes(self):
        wav = self.wav.read_bytes()
        self.write_archive(flow(task('audio', 'workflow_audio', path='assets/0001.wav')),
                           [('assets/0001.wav', wav)], compressed=True)
        result = bundles.import_bundle(self.output, self.destination)
        self.assertEqual(result.parent.joinpath('assets', '0001.wav').read_bytes(), wav)

    def test_existing_outputs_and_late_racer_are_preserved(self):
        self.save(flow(dict(id='wait', type='wait', seconds=0)))
        self.output.write_bytes(b'old zip')
        with self.assertRaisesRegex(bundles.BundleError, '已经存在'):
            bundles.export_bundle(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'old zip')
        self.output.unlink()
        bundles.export_bundle(self.source, self.output)
        replace = bundles.replace_file

        def race(staged, target, **kwargs):
            target.mkdir()
            (target / 'original.txt').write_bytes(b'older data')
            return replace(staged, target, **kwargs)

        with patch.object(bundles, 'replace_file', side_effect=race), self.assertRaises(bundles.BundleError):
            bundles.import_bundle(self.output, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [self.destination / 'original.txt'])
        self.assertEqual((self.destination / 'original.txt').read_bytes(), b'older data')

    def test_stop_at_publication_and_staged_replacement_leave_no_directory(self):
        self.save(flow(dict(id='wait', type='wait', seconds=0)))
        bundles.export_bundle(self.source, self.output)
        replace = bundles.replace_file
        cancelled = False

        def checkpoint():
            if cancelled:
                raise Stopped('用户停止导入')

        def stop(staged, target, **kwargs):
            nonlocal cancelled
            cancelled = True
            return replace(staged, target, **kwargs)

        with patch.object(bundles, 'replace_file', side_effect=stop), self.assertRaises(Stopped):
            bundles.import_bundle(self.output, self.destination, checkpoint=checkpoint)
        self.assert_unpublished()

        def mutate(staged, target, **kwargs):
            (staged / 'workflow.json').write_bytes(b'{"changed":true}')
            return replace(staged, target, **kwargs)

        with patch.object(bundles, 'replace_file', side_effect=mutate), self.assertRaisesRegex(bundles.BundleError, '改变'):
            bundles.import_bundle(self.output, self.destination)
        self.assert_unpublished()

    def test_stop_after_exclusive_publication_keeps_committed_result(self):
        self.save(flow(dict(id='wait', type='wait', seconds=0)))
        bundles.export_bundle(self.source, self.output)
        replace = bundles.replace_file
        cancelled = False

        def checkpoint():
            if cancelled:
                raise Stopped('用户停止导入')

        def commit(staged, target, **kwargs):
            nonlocal cancelled
            replace(staged, target, **kwargs)
            cancelled = True

        with patch.object(bundles, 'replace_file', side_effect=commit):
            result = bundles.import_bundle(self.output, self.destination, checkpoint=checkpoint)
        self.assertTrue(cancelled)
        self.assertTrue(result.is_file())


if __name__ == '__main__':
    unittest.main()
