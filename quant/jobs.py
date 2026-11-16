"""Durable research queue. All state transitions use SQLite transactions."""
import json
import time
import uuid
from datetime import datetime, timezone
from . import storage, runs

SCHEMA = '''CREATE TABLE IF NOT EXISTS research_jobs (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL, worker_id TEXT, heartbeat REAL,
 created_at REAL NOT NULL, finished_at REAL, error TEXT
)'''

# 数据模型版本。2 = 实验定义与运行记录已拆分（experiment 行冻结，status 移到 run）。
SCHEMA_VERSION = 2

# 旧格式实验的特征：定义行里还带着 status。迁移后该字段消失，
# 所以这个 LIKE 探测只在“还没迁移”或“又出现旧格式行”时为真。
_LEGACY_PROBE = 'SELECT 1 FROM objects WHERE kind=? AND body LIKE ? LIMIT 1'


def initialize():
    with storage.connect() as db:
        db.execute(SCHEMA)
        db.execute('CREATE TABLE IF NOT EXISTS submission_keys (key TEXT PRIMARY KEY, experiment_id TEXT NOT NULL)')
        if 'experiment_id' in [r[1] for r in db.execute('PRAGMA table_info(research_jobs)')]:
            db.execute('ALTER TABLE research_jobs RENAME COLUMN experiment_id TO run_id')
        db.execute('CREATE INDEX IF NOT EXISTS research_jobs_queue ON research_jobs(status, created_at)')
        db.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)')
        version = db.execute('SELECT max(version) FROM schema_version').fetchone()[0] or 0
        # 迁移会把所有实验行的快照 json.loads 一遍再改写。initialize() 在每次
        # enqueue/retry/delete 都会被调用，所以先做两个廉价判定：版本已到位、
        # 且库里没有旧格式实验行，就直接跳过 —— 既不丢“调用即补迁移”的语义，
        # 也不再每次提交都整表重写。
        if version >= SCHEMA_VERSION and db.execute(_LEGACY_PROBE, ('experiment', '%"status"%')).fetchone() is None:
            return
        db.execute('BEGIN IMMEDIATE')
        runs.migrate(db)
        db.execute('INSERT OR REPLACE INTO schema_version VALUES (?)', (SCHEMA_VERSION,))


def enqueue(experiment):
    initialize()
    record = dict(experiment)
    record.setdefault('created_at', datetime.now(timezone.utc).isoformat())
    job_id = uuid.uuid4().hex
    record['job_id'] = job_id
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        key = record.get('snapshot', {}).get('config', {}).get('submission_key')
        if key:
            prior = db.execute('SELECT experiment_id FROM submission_keys WHERE key=?', (key,)).fetchone()
            if prior:
                return storage.get('experiment', prior[0])
        count = db.execute("SELECT count(*) FROM research_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if count >= 4:
            raise ValueError('运行队列已满，请等待当前任务完成')
        frozen = {k: v for k, v in record.items() if k not in ('status', 'message', 'summary', 'job_id')}
        runs.insert(db, 'experiment', frozen)
        if key:
            db.execute('INSERT INTO submission_keys VALUES (?,?)', (key, frozen['id']))
        execution = runs.create(db, frozen)
        db.execute('INSERT INTO research_jobs(id,run_id,status,created_at) VALUES (?,?,?,?)',
                   (job_id, execution['id'], 'queued', time.time()))

    return runs.project(frozen)


def claim(worker_id):
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT id,run_id FROM research_jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if row is None:
            return None
        db.execute("UPDATE research_jobs SET status='running',worker_id=?,heartbeat=? WHERE id=?",
                   (worker_id, time.time(), row[0]))
        return {'id': row[0], 'run_id': row[1]}


def heartbeat(job_id, worker_id):
    with storage.connect() as db:
        db.execute("UPDATE research_jobs SET heartbeat=? WHERE id=? AND worker_id=? AND status='running'",
                   (time.time(), job_id, worker_id))


def finish(job, worker_id, error=None):
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT body FROM objects WHERE kind='run' AND id=?", (job['run_id'],)).fetchone()
        record = json.loads(row[0]) if row else None
        succeeded = record is not None and record['status'] == 'completed' and error is None
        message = None if succeeded else error or (record or {}).get('message', '实验记录不存在')
        if record and not succeeded:
            record.update(status='failed', message=message)
            db.execute('UPDATE objects SET body=? WHERE id=?', (json.dumps(record, ensure_ascii=False), record['id']))
        db.execute("UPDATE research_jobs SET status=?,finished_at=?,error=? WHERE id=? AND worker_id=? AND status='running'",
                   ('succeeded' if succeeded else 'failed', time.time(), message, job['id'], worker_id))


def recover_exclusive():
    """Only call while holding the worker process lock; never steal a live worker's job."""
    initialize()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT id,body FROM objects WHERE kind='run'").fetchall()
        for experiment_id, body in rows:
            record = json.loads(body)
            job = db.execute('SELECT id,status FROM research_jobs WHERE run_id=?', (experiment_id,)).fetchone()
            if job and job[1] == 'running':
                succeeded = record['status'] == 'completed'
                message = None if succeeded else 'Worker 中断，可复制配置重新运行'
                db.execute('UPDATE research_jobs SET status=?,finished_at=?,error=? WHERE id=?',
                           ('succeeded' if succeeded else 'failed', time.time(), message, job[0]))
                if not succeeded:
                    record.update(status='failed', message=message)
            elif not job and record['status'] == 'queued':
                job_id = uuid.uuid4().hex
                record['job_id'] = job_id
                db.execute('INSERT INTO research_jobs(id,run_id,status,created_at) VALUES (?,?,?,?)',
                           (job_id, experiment_id, 'queued', time.time()))
            elif not job and record['status'] == 'running':
                record.update(status='failed', message='旧版进程内任务已中断，可复制配置重新运行')
            else:
                continue
            db.execute('UPDATE objects SET body=? WHERE id=?', (json.dumps(record, ensure_ascii=False), experiment_id))


def retry(experiment_id):
    initialize()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT body FROM objects WHERE kind='experiment' AND id=?", (experiment_id,)).fetchone()
        if not row:
            raise ValueError('实验不存在')
        definition = json.loads(row[0])
        if definition.get('status') == 'deleting':
            raise ValueError('实验正在删除')
        if db.execute("SELECT count(*) FROM research_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 4:
            raise ValueError('运行队列已满')
        run = runs.create(db, definition)
        db.execute('INSERT INTO research_jobs(id,run_id,status,created_at) VALUES (?,?,?,?)',
                   (uuid.uuid4().hex, run['id'], 'queued', time.time()))
    return run


def counts():
    """队列各状态的条数，供 /api/status 轮询使用。"""
    with storage.connect() as db:
        return {status: n for status, n in
                db.execute('SELECT status, count(*) FROM research_jobs GROUP BY status')}


def forget(run_ids, experiment_id):
    """删除实验时清掉队列状态与幂等键（归档模块调用）。"""
    initialize()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for run_id in run_ids:
            db.execute('DELETE FROM research_jobs WHERE run_id=?', (run_id,))
        db.execute('DELETE FROM submission_keys WHERE experiment_id=?', (experiment_id,))
