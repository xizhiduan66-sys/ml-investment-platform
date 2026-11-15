"""Persistent market queue, executed under the market worker lock."""
import json
import time
import uuid
from . import storage


def initialize():
    with storage.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS market_queue (id TEXT PRIMARY KEY, status TEXT, worker_id TEXT, heartbeat REAL)')
        db.execute("INSERT OR IGNORE INTO market_queue(id,status) SELECT id,'queued' FROM objects WHERE kind='market_job' AND json_extract(body,'$.status')='queued'")


def submit(symbol, mode):
    initialize()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT body FROM objects WHERE kind='market_job' ORDER BY rowid DESC").fetchall()
        previous = next((json.loads(r[0]) for r in rows if json.loads(r[0])['symbol'] == symbol), None)
        if previous and previous['status'] in ('queued', 'running'):
            return previous
        record = {'id': uuid.uuid4().hex, 'symbol': symbol, 'mode': mode, 'status': 'queued',
                  'message': '等待行情 Worker', 'created_at': time.time(),
                  'changed_from': previous.get('changed_from') if previous and previous['mode'] == mode and previous['status'] != 'completed' else None}
        db.execute('INSERT INTO objects VALUES (?,?,?)', (record['id'], 'market_job', json.dumps(record)))
        db.execute("INSERT INTO market_queue(id,status) VALUES (?,'queued')", (record['id'],))
    return record


def claim(worker_id):
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT id FROM market_queue WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not row:
            return None
        db.execute("UPDATE market_queue SET status='running',worker_id=?,heartbeat=? WHERE id=?", (worker_id,time.time(),row[0]))
        return {'id': row[0]}


def heartbeat(job_id, worker_id):
    with storage.connect() as db:
        db.execute("UPDATE market_queue SET heartbeat=? WHERE id=? AND worker_id=? AND status='running'", (time.time(), job_id, worker_id))


def finish(job, worker_id, error=None):
    record = storage.get('market_job', job['id'])
    if error:
        record.update(status='failed', message=error)
        storage.save('market_job', record)
    with storage.connect() as db:
        db.execute('UPDATE market_queue SET status=? WHERE id=? AND worker_id=?', (record['status'],job['id'],worker_id))


def recover_exclusive():
    initialize()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for identifier, body in db.execute("SELECT id,body FROM objects WHERE kind='market_job'").fetchall():
            record = json.loads(body)
            queued = db.execute('SELECT status FROM market_queue WHERE id=?', (identifier,)).fetchone()
            if record['status'] == 'running' or (queued and queued[0] == 'running'):
                if record['status'] in ('running', 'queued'):
                    record.update(status='failed', message='行情 Worker 中断，可继续同步')
                    db.execute('UPDATE objects SET body=? WHERE id=?', (json.dumps(record),identifier))
                db.execute('UPDATE market_queue SET status=? WHERE id=?', (record['status'],identifier))
