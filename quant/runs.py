"""Frozen experiment definitions and separately persisted executions."""
import json
import uuid
from datetime import datetime, timezone
from . import storage


def insert(db, kind, record):
    db.execute('INSERT INTO objects VALUES (?,?,?)',
               (record['id'], kind, json.dumps(record, ensure_ascii=False, allow_nan=False)))


def create(db, experiment, run_id=None):
    record = {'id': run_id or uuid.uuid4().hex, 'experiment_id': experiment['id'],
              'status': 'queued', 'message': '等待运行',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'seed': experiment.get('snapshot', {}).get('seed', 42)}
    insert(db, 'run', record)
    return record


_RUN_FIELDS = ('status', 'message', 'summary', 'job_id')


def list_for(experiment_id):
    """只取属于该实验的运行记录，不再把整张 run 表捞出来过滤。"""
    with storage.connect() as db:
        rows = db.execute("SELECT body FROM objects WHERE kind='run' "
                          "AND json_extract(body,'$.experiment_id')=? ORDER BY rowid DESC",
                          (experiment_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def definition(experiment_id):
    with storage.connect() as db:
        row = db.execute("SELECT body FROM objects WHERE kind='experiment' AND id=?", (experiment_id,)).fetchone()
    if not row:
        raise ValueError('实验不存在')
    return json.loads(row[0])


def merge(record, latest):
    """把最新一次运行的状态投影到实验定义上（含删除中保护）。"""
    if latest is None or record.get('status') == 'deleting':
        return record
    return {**record, **{k: latest[k] for k in _RUN_FIELDS if k in latest},
            'latest_run_id': latest['id']}


def project(record):
    executions = list_for(record['id'])
    return merge(record, executions[0] if executions else None)


def projected_all():
    """列出全部实验（含最新运行状态）用两次查询，而不是每条实验扫一遍 run 表。"""
    with storage.connect() as db:
        experiments = [json.loads(row[0]) for row in
                       db.execute("SELECT body FROM objects WHERE kind='experiment' ORDER BY rowid DESC")]
        latest = {}
        for body in db.execute("SELECT body FROM objects WHERE kind='run' ORDER BY rowid DESC"):
            run = json.loads(body[0])
            latest.setdefault(run['experiment_id'], run)
    return [merge(record, latest.get(record['id'])) for record in experiments]


def execution(run_id):
    run = storage.get('run', run_id)
    return {**definition(run['experiment_id']), **run}


def save_execution(record):
    storage.save('run', {k: v for k, v in record.items() if k not in ('snapshot', 'name')})


def migrate(db):
    for identifier, body in db.execute("SELECT id,body FROM objects WHERE kind='experiment'").fetchall():
        record = json.loads(body)
        if 'status' not in record or record['status'] == 'deleting':
            continue
        # The objects table has a global primary key: migrated runs need distinct IDs.
        run_id = uuid.uuid4().hex
        run = {k: record[k] for k in ('status', 'message', 'summary', 'created_at', 'job_id') if k in record}
        run.update(id=run_id, experiment_id=identifier, artifact_id=identifier)
        insert(db, 'run', run)
        db.execute('UPDATE research_jobs SET run_id=? WHERE run_id=?', (run_id, identifier))
        frozen = {k: v for k, v in record.items() if k not in ('status', 'message', 'summary', 'job_id')}
        db.execute('UPDATE objects SET body=? WHERE id=?', (json.dumps(frozen, ensure_ascii=False), identifier))
