"""Export explicitly selected local calendar crops to a new PNG."""

from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zlib import error as DeflateError

import cv2
import numpy as np
from PIL import Image

from .models import Stopped
from .reward_guide_stitch import _MAX_INPUT_EDGE, _MAX_INPUT_PIXELS, _MAX_PAGES, stitch_reward_guide
from .screenshot_tool import MAX_BYTES
from .storage import file_revision, hold_read_sources
from .workflow_bundle import _path as local_path


_PNG_END = b'\x00\x00\x00\x00IEND\xaeB\x60\x82'


class _Rejected(ValueError):
    pass


def _result(status, overlaps=(), size=(None, None)):
    width, height = size
    return dict(status=status, overlap_rows=list(overlaps), width=width, height=height)


def _png_path(value, *, new=False):
    path = Path(value)
    if path.suffix.casefold() != '.png':
        raise ValueError()
    return local_path(path, new=new)


def _target(value):
    try:
        path = _png_path(value, new=True)
        directory = path.parent.stat()
        if not directory.st_ino:
            raise OSError()
        return path, (directory.st_dev, directory.st_ino)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise _Rejected('invalid_target') from None


def _verify_sources(sources):
    try:
        if any(_png_path(path) != path or file_revision(path) != revision for path, revision in sources):
            raise OSError()
    except (OSError, RuntimeError, TypeError, ValueError):
        raise _Rejected('source_changed') from None


def _read_png(path, pages):
    with path.open('rb') as stream:
        stream.seek(-len(_PNG_END), os.SEEK_END)
        if stream.read(len(_PNG_END)) != _PNG_END:
            raise _Rejected('invalid_source')
        stream.seek(0)
        with Image.open(stream, formats=('PNG',)) as header:
            width, height = header.size
            if min(width, height) < 64 or getattr(header, 'n_frames', 1) != 1:
                raise _Rejected('invalid_source')
            if max(width, height) > _MAX_INPUT_EDGE or width * height * pages > _MAX_INPUT_PIXELS:
                raise _Rejected('limit')
            header.verify()
    with path.open('rb') as stream, Image.open(stream, formats=('PNG',)) as image:
        if 'A' in image.getbands() or 'transparency' in image.info:
            image = image.convert('RGBA')
            if image.getchannel('A').getextrema() != (255, 255):
                raise _Rejected('invalid_source')
        return np.asarray(image.convert('RGB'))[:, :, ::-1].copy()


def _publish(target, sources, image, checkpoint):
    path, _ = target
    encoded = BytesIO()
    Image.fromarray(image[:, :, ::-1]).save(encoded, format='PNG')
    payload = encoded.getvalue()
    if len(payload) > MAX_BYTES:
        raise _Rejected('limit')

    def check_destination():
        if _target(path) != target:
            raise _Rejected('invalid_target')

    checkpoint()
    check_destination()
    with TemporaryDirectory(dir=path.parent, prefix='.autohsr-reward-guide-', ignore_cleanup_errors=True) as temp:
        staged = Path(temp) / 'calendar.tmp'
        with staged.open('xb') as stream:
            check_destination()
            if stream.write(payload) != len(payload):
                raise OSError()
            stream.flush()
            os.fsync(stream.fileno())
            created = os.fstat(stream.fileno())
        checkpoint()
        if local_path(staged) != staged:
            raise OSError()
        with hold_read_sources((staged,)):
            if local_path(staged) != staged:
                raise OSError()
            current = staged.stat()
            if (not created.st_ino or not os.path.samestat(created, current) or current.st_nlink != 1
                    or current.st_size != len(payload) or staged.read_bytes() != payload):
                raise OSError()
            _verify_sources(sources)
            check_destination()
            checkpoint()
            # A hard link keeps the verified bytes locked through the exclusive
            # publication. Windows rename would require releasing that lock.
            try:
                os.link(staged, path)
            except FileExistsError:
                raise _Rejected('invalid_target') from None


def export_reward_guide(sources, destination, *, checkpoint=lambda: None):
    """Export ordered local PNGs and return an anonymous, JSON-ready receipt.

    Pixel overlap relates the supplied crops. Their game page, account, capture
    time and completeness are outside the scope of this offline operation.
    """
    overlaps, failure = (), 'invalid_source'
    try:
        checkpoint()
        if not isinstance(sources, (list, tuple)) or not sources:
            return _result('invalid_source')
        if len(sources) > _MAX_PAGES:
            return _result('limit')
        paths = tuple(_png_path(value) for value in sources)
        target = _target(destination)
        revisions = tuple((path, file_revision(path)) for path in paths)
        if sum(revision[2] for _, revision in revisions) > MAX_BYTES:
            return _result('limit')
        with hold_read_sources(paths):
            _verify_sources(revisions)
            frames = []
            for path in paths:
                checkpoint()
                frames.append(_read_png(path, len(paths)))
            checkpoint()
            joined = stitch_reward_guide(frames)
            overlaps = joined.overlap_rows
            if joined.image is None:
                return _result(joined.status, overlaps)
            failure = 'publish_failed'
            _publish(target, revisions, joined.image, checkpoint)
        height, width = joined.image.shape[:2]
        return _result('ok', overlaps, (width, height))
    except Stopped:
        return _result('stopped', overlaps)
    except _Rejected as error:
        return _result(str(error), overlaps)
    except (OSError, RuntimeError, SyntaxError, TypeError, ValueError, DeflateError,
            Image.DecompressionBombError, cv2.error):
        return _result(failure, overlaps)
