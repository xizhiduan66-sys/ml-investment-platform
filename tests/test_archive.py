import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant import archive, jobs, runs, storage


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(storage, 'ROOT', Path(self.temp.name))
        self.patch.start()
        jobs.initialize()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def artifact(self, identifier, suffix):
        path = storage.ROOT / (identifier + suffix)
        path.write_text('{}')
        return path

    def test_purge_removes_rows_queue_state_and_files(self):
        jobs.enqueue({'id': 'abc', 'name': 'exp', 'snapshot': {}, 'status': 'queued'})
        run = runs.list_for('abc')[0]
        storage.save('run', {**run, 'status': 'completed'})
        files = [self.artifact('abc', suffix) for suffix in ('.csv', '.json', '.pkl', '.predictions.json')]
        result = archive.purge('abc')
        self.assertEqual(runs.list_for('abc'), [])
        self.assertFalse(any(path.exists() for path in files))
        self.assertTrue(all(name.endswith(('.csv', '.json', '.pkl')) for name in result['files']))
        with storage.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM objects WHERE kind='experiment'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM research_jobs").fetchone()[0], 0)

    def test_gc_only_removes_unreferenced(self):
        storage.save('dataset', {'name': '快照', 'file': 'a' * 32 + '.csv'})
        referenced = self.artifact('a' * 32, '.csv')
        orphan = self.artifact('b' * 32, '.csv')
        log = storage.ROOT / 'api.log'
        log.write_text('x')
        dry = archive.gc()
        self.assertEqual(dry['orphans'], ['b' * 32 + '.csv'])
        self.assertEqual(dry['removed'], [])
        self.assertTrue(orphan.exists() and referenced.exists())
        applied = archive.gc(apply=True)
        self.assertEqual(applied['removed'], ['b' * 32 + '.csv'])
        self.assertFalse(orphan.exists())
        self.assertTrue(referenced.exists() and log.exists())
        self.assertEqual(archive.orphans(), [])

    def test_orphans_ignore_manual_files(self):
        (storage.ROOT / 'manual-publication-abcdef123456.json').write_text('{}')
        (storage.ROOT / 'service-pids.json').write_text('{}')
        self.assertEqual(archive.orphans(), [])


if __name__ == '__main__':
    unittest.main()
