"""One-off, explicitly authorized publication of BTCUSDT staged data."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant import storage, market, market_jobs
from quant.worker import exclusive_worker

symbol = 'BTCUSDT'
job_id = '74fe3e02c3e7'
stage = storage.ROOT / 'market-stage-BTCUSDT.db'
pid_path = storage.ROOT / 'service-pids.json'
pids = json.loads(pid_path.read_text())
pid = pids['market']
info = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True)
if '-m quant.worker --queue market' not in info:
    raise RuntimeError('行情 Worker PID 不匹配')
if any(j['status'] in ('queued','running') for j in market_jobs.jobs()):
    raise RuntimeError('行情任务正在执行，不能手动发布')
os.kill(pid, signal.SIGTERM)
for _ in range(100):
    try: os.kill(pid, 0)
    except ProcessLookupError: break
    time.sleep(.1)
else: raise RuntimeError('行情 Worker 尚未退出')
try:
    with exclusive_worker('market'):
        with sqlite3.connect(stage) as db:
            base, mode = db.execute('SELECT version,mode FROM sync_base').fetchone()
            expected = db.execute("SELECT period,count(*),min(ts),max(ts) FROM bars WHERE symbol=? GROUP BY period", (symbol,)).fetchall()
        with market.connect() as db:
            if market._version(db, symbol) != base:
                raise RuntimeError('正式库版本已变化')
        backup = storage.ROOT / ('market-before-manual-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.db')
        with sqlite3.connect(storage.ROOT / 'market.db') as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        authorization = {'authorized_by': 'user', 'reason': '用户已了解价格和成交量差异，要求手动入库',
                         'published_at': datetime.now(timezone.utc).isoformat(), 'source_job_id': job_id,
                         'base_version': base, 'backup': backup.name, 'validation_overridden': True}
        # Write intent first so a failure after publication is still traceable.
        receipt = storage.ROOT / ('manual-publication-' + job_id + '.json')
        receipt.write_text(json.dumps({**authorization, 'status': 'publishing'}, ensure_ascii=False))
        counts = market_jobs._publish(symbol, stage, base)
        with market.connect() as db:
            actual = db.execute("SELECT period,count(*),min(ts),max(ts) FROM bars WHERE symbol=? GROUP BY period", (symbol,)).fetchall()
        if actual != expected:
            raise RuntimeError('发布后数据量或范围不一致')
        job = storage.get('market_job', job_id)
        job.update(status='completed', message='已按用户授权手动发布；原始校验差异与待校验项仍保留', manual_publication=authorization)
        for period, report in job['reports'].items():
            report.update(counts.get(period, {'added': 0, 'revised': 0}))
        storage.save('market_job', job)
        with storage.connect() as db:
            db.execute("UPDATE market_queue SET status='completed' WHERE id=?", (job_id,))
        receipt.write_text(json.dumps({**authorization, 'status':'completed', 'counts': counts, 'series': actual}, ensure_ascii=False, indent=2))
        print(json.dumps({'published': actual, 'receipt': str(receipt), 'backup': str(backup)}, ensure_ascii=False))
finally:
    with (storage.ROOT / 'market.log').open('ab') as log:
        child = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-B', '-m', 'quant.worker', '--queue', 'market'],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    pids['market'] = child.pid
    pid_path.write_text(json.dumps(pids))
    print('market worker', child.pid)
