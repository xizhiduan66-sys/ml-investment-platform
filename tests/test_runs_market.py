import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from quant import jobs, runs, storage, market_queue, market_jobs
from quant.worker import execute, exclusive_worker


class RunsMarketTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(storage, 'ROOT', Path(self.temp.name))
        self.patch.start()
        jobs.initialize()
        market_queue.initialize()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_repeated_runs_preserve_definition(self):
        jobs.enqueue({'id': 'abc', 'name': 'frozen', 'snapshot': {'seed': 42}, 'status': 'queued'})
        original = runs.definition('abc')
        first = runs.list_for('abc')[0]
        storage.save('run', {**first, 'status': 'completed', 'summary': {'score': 1}})
        second = jobs.retry('abc')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(runs.definition('abc'), original)
        self.assertNotIn('status', original)
        self.assertEqual(storage.get('run', first['id'])['summary'], {'score': 1})
        self.assertEqual(runs.latest('abc')['latest_run_id'], second['id'])

    def test_market_atomic_dedup_and_dispatch(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            submitted = list(pool.map(lambda _: market_jobs.submit('BTCUSDT', 'full'), range(4)))
        self.assertEqual(len({r['id'] for r in submitted}), 1)
        job = market_queue.claim('worker')
        self.assertIsNone(market_queue.claim('other'))
        def complete(identifier):
            record = storage.get('market_job', identifier)
            storage.save('market_job', {**record, 'status': 'completed'})
        with patch.object(market_jobs, 'run', side_effect=complete):
            execute(job, 'worker', 'market')
        with storage.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM market_queue').fetchone()[0], 'completed')

    def test_market_interruption_and_independent_locks(self):
        record = market_jobs.submit('BTCUSDT', 'full')
        market_queue.claim('old')
        with exclusive_worker('research'), exclusive_worker('market'):
            market_queue.recover_exclusive()
        self.assertEqual(storage.get('market_job', record['id'])['status'], 'failed')
        self.assertNotEqual(market_jobs.submit('BTCUSDT', 'full')['id'], record['id'])

    def test_legacy_artifact_migration_idempotent(self):
        storage.save('experiment', {'id': 'old', 'status': 'completed', 'snapshot': {}, 'summary': {'score': 2}})
        jobs.initialize()
        jobs.initialize()
        executions = runs.list_for('old')
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]['artifact_id'], 'old')
        self.assertEqual(runs.latest('old')['summary'], {'score': 2})

    def test_run_detail_and_delete_all_artifacts(self):
        from quant.app import run_detail, delete_experiment
        jobs.enqueue({'id': 'abc', 'name': 'frozen', 'snapshot': {}, 'status': 'queued'})
        first = runs.list_for('abc')[0]
        second = jobs.retry('abc')
        for execution in (first, second):
            storage.save('run', {**execution, 'status': 'completed'})
            for suffix in ('.json', '.pkl', '.predictions.json'):
                (storage.ROOT / (execution['id'] + suffix)).write_text('{}')
            self.assertEqual(run_detail(execution['id'])['result'], {})
        delete_experiment('abc')
        self.assertEqual(runs.list_for('abc'), [])
        for execution in (first, second):
            self.assertFalse((storage.ROOT / (execution['id'] + '.json')).exists())
