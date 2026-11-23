import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from quant import storage, jobs, runs
from quant.app import worker_status, research_preflight, label_preview, PreflightIn, ExperimentIn
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

    def test_legacy_trading_parameters_excluded_from_training(self):
        config = dict(name='test', model='lstm', target_id='forward_return')
        legacy = ExperimentIn(**config, auto_backtest=True, cost_bps=25, probability_threshold=.7)
        self.assertEqual(legacy.model_dump(), ExperimentIn(**config).model_dump())
        self.assertNotIn('auto_backtest', legacy.model_dump())

    def test_structure_label_preview_uses_loaded_snapshot(self):
        observed, confirmed = '2025-01-01T10:00:00Z', '2025-01-01T11:00:00Z'
        event = {'event_id': 'candidate', 'observed_at': 0, 'observed_time': observed,
                 'label': 1, 'label_end': 1, 'label_time': confirmed,
                 'eligible': True, 'status': 'confirmed'}
        frame = object()
        with patch('quant.app.storage.get', return_value={'rows': 2}), \
             patch('quant.app.data.load', return_value=frame), \
             patch('quant.app.chan_events.replay', return_value={'events': [event], 'counts': {'confirmed': 1}}) as replay:
            preview = label_preview('snapshot', 'chan_structure_v1')
        replay.assert_called_once_with(frame)
        self.assertEqual(preview['events'], [
            {'event_id': 'candidate', 'observed_time': observed, 'label_time': confirmed,
             'label': 1, 'status': 'confirmed'},
        ])
