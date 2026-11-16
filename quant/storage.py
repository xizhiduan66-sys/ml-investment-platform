"""研究库的 SQLite 访问：连接治理、文档表、修订号。

对象仍然以 objects(kind, body JSON) 存储。schema 只在每个数据目录首次使用时建立一次
（并切到 WAL），普通连接不再重复执行 DDL —— 之前每次 connect 都跑 CREATE TABLE，
在 Worker 写 + API 读并发的场景下会额外抢锁。
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get('QUANT_DATA_DIR', Path(__file__).resolve().parent.parent / 'data'))
ROOT.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, kind TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS objects_kind ON objects(kind, id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('revision', 0);
-- 任何一条对象写入都会自增修订号。触发器让 /api/catalog 的 ETag 失效成为
-- 结构保证：不依赖每个写点记得调用某个函数（jobs/runs/app 里都有直接写 SQL 的地方）。
CREATE TRIGGER IF NOT EXISTS objects_revision_insert AFTER INSERT ON objects
BEGIN UPDATE meta SET value=value+1 WHERE key='revision'; END;
CREATE TRIGGER IF NOT EXISTS objects_revision_update AFTER UPDATE ON objects
BEGIN UPDATE meta SET value=value+1 WHERE key='revision'; END;
CREATE TRIGGER IF NOT EXISTS objects_revision_delete AFTER DELETE ON objects
BEGIN UPDATE meta SET value=value+1 WHERE key='revision'; END;
"""

# 已建过表的数据目录。按 ROOT 记录，测试可以随时把 ROOT 指到新的临时目录。
_ready = set()


def database():
    return ROOT / 'research.db'


def _connect():
    return sqlite3.connect(database(), timeout=30)


def ensure_schema():
    """幂等建表 + 切 WAL。放在 connect() 里调用，所有入口都不必记得初始化。"""
    key = str(ROOT)
    if key in _ready:
        return
    con = _connect()
    try:
        try:
            con.execute('PRAGMA journal_mode=WAL')
        except sqlite3.OperationalError:
            pass  # 另一个进程正在首次初始化时保持原模式，不影响一致性
        con.executescript(SCHEMA)
    finally:
        con.close()
    _ready.add(key)


@contextmanager
def connect():
    ensure_schema()
    con = _connect()
    try:
        with con:
            yield con
    finally:
        con.close()




def revision():
    ensure_schema()
    con = _connect()
    try:
        row = con.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
    finally:
        con.close()
    return row[0] if row else 0


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
    if kind == 'experiment':
        # 投影需要“实验 + 最新运行”两组数据，交给 runs 一次查完（原来是每条实验扫一遍 run 表）。
        from .runs import projected_all
        return projected_all()
    with connect() as con:
        rows = con.execute('SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
    return [json.loads(row[0]) for row in rows]
