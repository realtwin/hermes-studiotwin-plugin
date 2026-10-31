"""Small atomic JSON stores, resolved under the requesting profile by callers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

STATE_LOCK = RLock()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.part', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, allow_nan=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class AssetIndex:
    def __init__(self, root: Path):
        self.path = root / 'asset-index.json'

    def rows(self):
        rows = read_json(self.path, [])
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get('path'), str)] if isinstance(rows, list) else []

    def record(self, path: Path, *, asset=None, task=None, kind=None):
        with STATE_LOCK:
            rows = self.rows()
            row = next((r for r in rows if r['path'] == str(path)), None)
            if row is None:
                row = {'path': str(path)}
                rows.append(row)
            st = path.stat()
            row.update(name=path.name, bytes=st.st_size, mtime=int(st.st_mtime * 1000))
            for key, value in [('uuid',asset),('task',task),('type',kind)]:
                if value is not None:
                    row[key] = value
            write_json(self.path, rows[-2000:])
            return dict(row)
