"""Stage public documentation and dependency notices before copying a Windows build."""

from hashlib import sha256
from importlib.metadata import distribution
import json
from pathlib import Path
import re
from shutil import copyfile
import sys


ROOT = Path(__file__).resolve().parents[1]
FALLBACK = Path(__file__).with_name('release-licenses')
DOCUMENTS = ('README.md', 'DAILY_FLOW.md', 'VALIDATION.md', 'CURRENCY_WARS.md',
             'CURRENCY_WARS_GUIDE.md', 'LICENSE_NOTICE.md')
# Runtime packages collected by this build, plus the PyInstaller bootloader.
DISTRIBUTIONS = (
    'colorama', 'et_xmlfile', 'flatbuffers', 'mss', 'numpy', 'onnxruntime',
    'opencv-python', 'openpyxl', 'packaging', 'Pillow', 'pyclipper',
    'PyInstaller', 'PyYAML', 'rapidocr-onnxruntime', 'Shapely', 'tqdm',
)
NOTICE_NAME = re.compile(r'^(?:licen[cs]e|notice|third.?party.?notices?|copying|copyright|authors)', re.I)
PROJECT_PATH = re.compile(r'(?<![A-Za-z0-9])[A-Z]:[/\\]+Projects[/\\]+AutoHSR(?=[/\\]|\b)', re.I)
PROFILE_PATH = re.compile(r'(?<![A-Za-z0-9])[A-Z]:[/\\]+Users[/\\]+[^/\\\s`"<>\])]+', re.I)


def public_paths(value):
    return PROFILE_PATH.sub('USER_HOME', PROJECT_PATH.sub('PROJECT_ROOT', value))


def stage_docs(bundle, revision):
    repository = 'https://github.com/HenryTANG0520/AutoHSR'
    source_url = f'{repository}/blob/{revision}/'
    (bundle / 'docs').mkdir()
    root_links = (('assets/', '_internal/assets/'), ('runs/', '../../runs/'),
                  ('dist/AutoHSR/runs/', 'runs/'), ('autohsr/', source_url + 'autohsr/'),
                  ('AGENTS.md', source_url + 'AGENTS.md'))
    docs_links = (('../assets/', '../_internal/assets/'), ('../runs/', '../../../runs/'),
                  ('../autohsr/', source_url + 'autohsr/'))
    paths = [(ROOT / name, bundle / name, root_links) for name in DOCUMENTS]
    paths += [(path, bundle / 'docs' / path.name, docs_links) for path in (ROOT / 'docs').glob('*.md')]
    for source, target, links in paths:
        if source.is_file():
            text = public_paths(source.read_text(encoding='utf-8-sig'))
            for before, after in links:
                text = text.replace('](' + before, '](' + after)
            if source.name == 'LICENSE_NOTICE.md':
                text = text.rstrip() + (
                    '\n\nSee the [packaged dependency notices](THIRD_PARTY_NOTICES/sources.json) '
                    f'and the [source revision for this build]({repository}/tree/{revision}).\n'
                )
            target.write_text(text, encoding='utf-8')

    provenance = bundle / '_internal/assets/templates/du_gallery_claimed.json'
    record = json.loads(provenance.read_text(encoding='utf-8-sig'))
    record['source'] = public_paths(record['source'])
    provenance.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_notice(source, target):
    if not source.is_file() or not source.stat().st_size:
        raise ValueError(f'Missing or empty license source for {target.name}.')
    target.parent.mkdir(parents=True, exist_ok=True)
    copyfile(source, target)


def stage_notices(bundle):
    output = bundle / 'THIRD_PARTY_NOTICES'
    output.mkdir()
    fallbacks = json.loads((FALLBACK / 'sources.json').read_text(encoding='utf-8'))
    used_fallbacks = []
    versions = {'CPython': sys.version.split()[0]}
    copy_notice(Path(sys.base_prefix) / 'LICENSE.txt', output / 'cpython/LICENSE.txt')
    for name in DISTRIBUTIONS:
        dist = distribution(name)
        key = re.sub(r'[-_.]+', '-', name.lower())
        folder = output / key
        versions[name] = dist.version
        installed_notices = []
        for file in dist.files or ():
            parts = file.parts
            if file.is_absolute() or '..' in parts:
                continue
            if parts[0].endswith(('.dist-info', '.egg-info')):
                relative = Path(*parts[1:])
            else:
                relative = Path(*parts)
            if NOTICE_NAME.match(file.name):
                copy_notice(Path(dist.locate_file(file)), folder / relative)
                installed_notices.append(file)
        if installed_notices:
            continue
        # Two known wheels omit the original license. Bind replacements to the
        # installed version and the recorded hash of the upstream release file.
        upstream = [item for item in fallbacks if item['file'].startswith(f'{key}/{dist.version}/')]
        if not upstream:
            raise ValueError(f'No complete license file for {name} {dist.version}.')
        for item in upstream:
            source = FALLBACK / item['file']
            if sha256(source.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError(f'Upstream license hash mismatch for {name} {dist.version}.')
            copy_notice(source, folder / source.name)
        used_fallbacks.extend(upstream)
    manifest = {'distribution_versions': versions, 'upstream_fallbacks': used_fallbacks}
    (output / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    from stage_release_onnx import stage_onnx_assets

    bundle, revision = Path(sys.argv[1]), sys.argv[2]
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not (bundle / 'AutoHSR.exe').is_file():
        raise SystemExit('Expected a newly built bundle and its source revision.')
    stage_docs(bundle, revision)
    stage_notices(bundle)
    stage_onnx_assets(bundle)
    copy_notice(ROOT / 'LICENSE', bundle / 'LICENSE')
