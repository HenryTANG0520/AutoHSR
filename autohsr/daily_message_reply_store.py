"""Local, per-section SMS reply intent and confirmation."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import Lock
from uuid import uuid4
from weakref import ref

from .models import AutomationError
from .storage import file_revision, hold_read_sources, remove_owned_stage, replace_file


def _publish(path, payload, *, exclusive=False, before_replace=None):
    temporary = created = None

    def verify(source):
        if source.resolve(strict=True) != source:
            raise OSError('短信回复记录的文件来源已变化。')
        with source.open('rb') as stream:
            current = os.fstat(stream.fileno())
            if (not created.st_ino or not os.path.samestat(created, current) or current.st_nlink != 1
                    or stream.read(len(payload) + 1) != payload):
                raise OSError('短信回复记录的文件来源已变化。')

    def prepare():
        with hold_read_sources((temporary,)):
            verify(temporary)
        if before_replace is not None:
            before_replace()

    try:
        with NamedTemporaryFile(mode='wb', dir=path.parent, prefix='.sms-reply-', suffix='.tmp',
                                delete=False) as stream:
            temporary = Path(stream.name)
            created = os.fstat(stream.fileno())
            if stream.write(payload) != len(payload):
                raise OSError('短信回复记录写入不完整。')
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path, exclusive=exclusive, before_replace=prepare)
        with hold_read_sources((path,)):
            verify(path)
    finally:
        if created is not None:
            try:
                remove_owned_stage(temporary, created)
            except OSError:
                pass


class _Reservation:
    def __init__(self, path, section):
        self._path = path
        record = dict(schema=1, section=section, attempt=uuid4().hex, status='pending')
        self._pending = json.dumps(record, separators=(',', ':')).encode('ascii')
        record['status'] = 'confirmed'
        self._confirmed = json.dumps(record, separators=(',', ':')).encode('ascii')
        self._revision = None
        self._origin = ref(self)
        self._lock = Lock()

    def _verify_pending(self):
        if self._path.is_symlink() or file_revision(self._path) != self._revision:
            raise AutomationError('短信回复待核对记录的来源已变化。')
        with self._path.open('rb') as stream:
            if stream.read(len(self._pending) + 1) != self._pending:
                raise AutomationError('短信回复待核对记录的内容已变化。')

    @contextmanager
    def hold_pending(self):
        with hold_read_sources((self._path,)):
            self._verify_pending()
            yield

    def confirm(self, *, before_replace=None):
        """Confirm an observed reply using the original reservation."""
        with self._lock:
            if self._origin() is not self or self._revision is None:
                raise AutomationError('缺少本次短信回复的待核对记录。')

            def verify():
                self._verify_pending()
                if before_replace is not None:
                    before_replace()

            try:
                _publish(self._path, self._confirmed, before_replace=verify)
            except OSError as error:
                raise AutomationError('短信回复确认未保存，保留待核对状态。') from error
            self._revision = None


class ReplyStore:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()

    def _path(self, account_key, section):
        if (type(account_key) is not str or re.fullmatch(r'[0-9a-f]{64}', account_key) is None
                or type(section) is not int or not 0 < section <= 0xffffffff):
            raise AutomationError('短信回复缺少已核实的账号或段落。')
        scope = json.dumps((account_key, section), separators=(',', ':')).encode('ascii')
        digest = sha256(b'autohsr-sms-reply-v1\0' + scope).hexdigest()
        return self.directory / f'reply-{digest}.json'

    def status(self, account_key: str, section: int) -> str:
        """Read the local result without clearing an unreadable record."""
        path = self._path(account_key, section)
        try:
            if path.is_symlink():
                return 'pending'
            with path.open('rb') as stream:
                raw = stream.read(513)
            if len(raw) > 512:
                return 'pending'
            record = json.loads(raw)
        except FileNotFoundError:
            return 'none'
        except (OSError, ValueError):
            return 'pending'
        if (type(record) is dict and set(record) == {'schema', 'section', 'attempt', 'status'}
                and type(record['schema']) is int and record['schema'] == 1
                and type(record['section']) is int and record['section'] == section
                and type(record['attempt']) is str and re.fullmatch(r'[a-f0-9]{32}', record['attempt'])
                and record['status'] == 'confirmed'
                and json.dumps(record, separators=(',', ':')).encode('ascii') == raw):
            return 'confirmed'
        return 'pending'

    def reserve(self, account_key: str, section: int) -> _Reservation:
        """Persist one pending attempt before any reply input can be submitted."""
        path = self._path(account_key, section)
        reservation = _Reservation(path, section)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Every existing record blocks, including unreadable or partial records.
            _publish(path, reservation._pending, exclusive=True)
            reservation._revision = file_revision(path)
        except FileExistsError as error:
            raise AutomationError('本账号的短信段落已有回复记录，未重复提交。') from error
        except OSError as error:
            raise AutomationError('短信回复待核对记录无法保存，未提交。') from error
        return reservation
