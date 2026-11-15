import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from quant import jobs, storage
from quant.worker import exclusive_worker, execute


class DurableJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(storage, 'ROOT', Path(self.temp.name))
        self.patch.start()
        jobs.initialize()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def enqueue(self, identifier='abc'):
        return jobs.enqueue({'id': identifier, 'status': 'queued', 'name': 'test'})

    def test_claim_exactly_once(self):
        self.enqueue()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(jobs.claim, ['a', 'b', 'c', 'd']))
        self.assertEqual(sum(job is not None for job in claimed), 1)

    def test_capacity_atomic(self):
        def submit(i):
            try:
                self.enqueue(str(i))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(submit, range(6)))
        self.assertEqual(sum(results), 4)
        self.assertEqual(len(storage.all_of('experiment')), 4)

    def test_restart_preserves_queue_and_recovers_interrupted(self):
        self.enqueue('running')
        jobs.claim('old')
        self.enqueue('queued')
        with exclusive_worker():
            jobs.recover_exclusive()
        self.assertEqual(storage.get('experiment', 'running')['status'], 'failed')
        self.assertEqual(storage.get('run', jobs.claim('new')['run_id'])['experiment_id'], 'queued')

    def test_exclusive_lock(self):
        with exclusive_worker():
            with self.assertRaises(RuntimeError):
                with exclusive_worker():
                    pass

    def test_execute_records_outcome(self):
        self.enqueue()
        job = jobs.claim('worker')
        def complete(identifier):
            record = storage.get('run', identifier)
            storage.save('run', {**record, 'status': 'completed'})
        with patch('quant.engine.run', side_effect=complete):
            execute(job, 'worker')
        with storage.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM research_jobs').fetchone()[0], 'succeeded')

    def test_legacy_queue_migration(self):
        storage.save('experiment', {'id': 'legacy', 'status': 'queued'})
        with exclusive_worker():
            jobs.recover_exclusive()
            jobs.recover_exclusive()
        self.assertEqual(storage.get('run', jobs.claim('new')['run_id'])['experiment_id'], 'legacy')
        self.assertIsNone(jobs.claim('new'))
