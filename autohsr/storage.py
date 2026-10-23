"""Atomic publication with bounded tolerance for Windows sharing locks."""
from pathlib import Path
import time


REPLACE_RETRY_DELAYS=(.02,.04,.08,.16,.32,.50)


def replace_file(source, destination):
    """Retry only the final rename, never the write or a game action."""
    source,destination=Path(source),Path(destination)
    for attempt in range(len(REPLACE_RETRY_DELAYS)+1):
        try:
            source.replace(destination)
            return
        except OSError as error:
            sharing=isinstance(error,PermissionError) or getattr(error,'winerror',None) in (5,32,33)
            if not sharing or attempt==len(REPLACE_RETRY_DELAYS):
                raise
            time.sleep(REPLACE_RETRY_DELAYS[attempt])
