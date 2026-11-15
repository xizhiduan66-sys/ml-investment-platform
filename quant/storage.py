import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get('QUANT_DATA_DIR', Path(__file__).resolve().parent.parent / 'data'))
ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect():
    con = sqlite3.connect(ROOT / 'research.db', timeout=30)
    try:
        with con:
            con.execute('CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, kind TEXT, body TEXT)')
            yield con
    finally:
        con.close()


def save(kind, body):
    body = dict(body)
    body.setdefault('id', uuid.uuid4().hex[:12])
    body.setdefault('created_at', datetime.now(timezone.utc).isoformat())
    with connect() as con:
        con.execute('INSERT INTO objects VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, body=excluded.body', (body['id'], kind, json.dumps(body, ensure_ascii=False, allow_nan=False)))
    return body


def get(kind, key):
    with connect() as con:
        row = con.execute('SELECT body FROM objects WHERE kind=? AND id=?', (kind, key)).fetchone()
    if not row:
        raise ValueError('记录不存在：' + key)
    record = json.loads(row[0])
    if kind == 'experiment':
        from .runs import project
        return project(record)
    return record


def all_of(kind):
    with connect() as con:
        rows = con.execute('SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
    records = [json.loads(r[0]) for r in rows]
    if kind == 'experiment':
        from .runs import project
        return [project(record) for record in records]
    return records
