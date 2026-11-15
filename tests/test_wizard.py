import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from quant import storage, jobs, runs
from quant.app import worker_status, research_preflight, PreflightIn, ExperimentIn
from quant.worker import exclusive_worker


class WizardTest(unittest.TestCase):
    def test_worker_readiness_uses_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            self.assertFalse(worker_status()['research']['online'])
            with exclusive_worker():
                self.assertTrue(worker_status()['research']['online'])
                self.assertFalse(worker_status()['market']['online'])

    def test_submission_key_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            definition = {'name': 'test', 'status': 'queued', 'snapshot': {'config': {'submission_key': 'same'}}}
            first = jobs.enqueue({**definition, 'id': 'first'})
            second = jobs.enqueue({**definition, 'id': 'second'})
            self.assertEqual(first['id'], second['id'])
            self.assertEqual(len(runs.list_for('first')), 1)
            self.assertEqual(len(storage.all_of('experiment')), 1)

    def test_preflight_rejects_incompatible_task(self):
        with patch('quant.app.feature_records', return_value=[]), patch('quant.models.registry', return_value=[{'id': 'lstm', 'available': True, 'input': 'sequence', 'tasks': ['binary']}]), patch('quant.factors.build_manifest'):
            with self.assertRaisesRegex(ValueError, '向量'):
                research_preflight(PreflightIn(model='lstm', sample_mode='chan_event', target_id='chan_structure_v1', factor_ids=['example']))

    def test_auto_backtest_backward_compatible(self):
        config = dict(name='test', model='lstm', target_id='forward_return')
        self.assertTrue(ExperimentIn(**config).auto_backtest)
        self.assertFalse(ExperimentIn(**config, auto_backtest=False).auto_backtest)
