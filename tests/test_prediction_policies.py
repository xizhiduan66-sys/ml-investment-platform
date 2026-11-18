import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from quant import policies, prediction_artifacts, storage, backtest, engine


class PredictionPolicyTest(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'date': pd.date_range('2020-01-01', periods=8).astype(str),
                             'open': np.arange(100., 108.), 'close': np.arange(101., 109.),
                             'high': np.arange(102., 110.), 'low': np.arange(99., 107.)})

    def test_reuse_and_legacy_ledger_parity(self):
        df = self.frame()
        rows = [{'bar_index': 2, 'prediction': .6}, {'bar_index': 3, 'prediction': None},
                {'bar_index': 4, 'prediction': .8}]
        original = json.dumps(rows)
        low, start, end = policies.bar_positions(df, rows, policies.ThresholdPolicy('binary', .55))
        high, _, _ = policies.bar_positions(df, rows, policies.ThresholdPolicy('binary', .7))
        self.assertEqual(low.iloc[2], 1)
        self.assertEqual(high.iloc[2], 0)
        self.assertEqual(low.iloc[3], 0)
        self.assertEqual(original, json.dumps(rows))
        legacy, a, b = backtest.experiment_signals(df, {'rows': rows}, 'binary', .55)
        pd.testing.assert_series_equal(low, legacy)
        self.assertEqual((start, end), (a, b))
        config = {'probability_threshold': .55, 'cost_bps': 5}
        report, _, metrics = engine.simulate(df, [2, 3, 4], [.6, np.nan, .8], 'binary', config)
        ledger = backtest.run(df, low, backtest.BacktestConfig(initial_cash=1, fee_bps=5, slippage_bps=0), start, end)
        self.assertEqual(metrics['net_return'], ledger['metrics']['net_return'])
        self.assertEqual([r['equity'] for r in report], [r['equity'] for r in ledger['rows'][1:]])

    def test_artifact_binding_and_integrity(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            dataset = {'sha256': 'data-hash'}
            rows = [{'split': 'train', 'bar_index': 0, 'prediction': .4},
                    {'split': 'test', 'bar_index': 4, 'prediction': .8}]
            ref = prediction_artifacts.publish('abc', dataset, 'binary', 'bar', rows)
            self.assertEqual(prediction_artifacts.load(ref, 'abc', dataset, 'binary'), rows[1:])
            with self.assertRaises(ValueError):
                prediction_artifacts.load(ref, 'abc', {'sha256': 'other'}, 'binary')
            path = Path(directory) / ref['file']
            path.write_text('{}')
            with self.assertRaises(ValueError):
                prediction_artifacts.load(ref, 'abc', dataset, 'binary')

    def test_api_reuses_artifact_without_training(self):
        from quant.app import create_backtest, BacktestIn, delete_experiment
        from quant import models
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            dataset = {'id': 'abc', 'sha256': 'data-hash', 'name': 'test'}
            rows = [{'split': 'test', 'bar_index': 2, 'prediction': .6},
                    {'split': 'test', 'bar_index': 4, 'prediction': .8}]
            ref = prediction_artifacts.publish('abc', dataset, 'binary', 'bar', rows)
            storage.save('experiment', {'id': 'abc', 'status': 'completed', 'name': 'test',
                'snapshot': {'dataset': dataset, 'target': {'task': 'binary'},
                             'config': {'sample_mode': 'bar', 'probability_threshold': .55}}})
            (Path(directory) / 'abc.json').write_text(json.dumps({'prediction_artifact': ref}))
            with patch('quant.data.load', return_value=self.frame()), patch.object(models, 'fit') as fit:
                first = create_backtest(BacktestIn(name='low', source='experiment', experiment_id='abc', threshold=.55))
                second = create_backtest(BacktestIn(name='high', source='experiment', experiment_id='abc', threshold=.7))
                fit.assert_not_called()
            self.assertEqual(first['source']['prediction_artifact'], second['source']['prediction_artifact'])
            self.assertNotEqual(first['metrics']['net_return'], second['metrics']['net_return'])
            delete_experiment('abc')
            self.assertFalse((Path(directory) / ref['file']).exists())

    def test_only_experiment_inputs_are_accepted(self):
        from pydantic import ValidationError
        from quant.research_inputs import BacktestIn
        for fields in ({'source': 'sma'}, {'dataset_id': 'd'}, {'fast': 10}, {'slow': 30}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                BacktestIn(name='test', experiment_id='experiment', **fields)

    def test_run_settings_match_execution(self):
        from quant import backtest_submission
        from quant.research_inputs import BacktestIn
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            storage.save('experiment', {'id': 'exp', 'snapshot': {
                'config': {'cost_bps': 5}, 'dataset': {'id': 'd'}, 'target': {'task': 'binary'}}})
            storage.save('run', {'id': 'r', 'experiment_id': 'exp', 'status': 'completed'})
            report = {'execution': {'fee_bps': 8, 'slippage_bps': 3, 'position_pct': .4},
                      'strategy': {'threshold': .7}, 'rows': [{'bar_index': 2, 'prediction': .8}]}
            (Path(directory) / 'r.json').write_text(json.dumps(report))
            defaults = backtest_submission.settings('exp', 'r')
            with patch('quant.data.load', return_value=self.frame()):
                record = backtest_submission.create(BacktestIn(name='test', experiment_id='exp', run_id='r'))
            self.assertEqual(defaults['threshold'], record['source']['threshold'])
            self.assertEqual(defaults['threshold'], .7)
            for key, value in report['execution'].items():
                self.assertEqual(defaults[key], value)
                self.assertEqual(record['config'][key], value)

    def test_invalid_predictions(self):
        for rows in ([{'bar_index': 7, 'prediction': .5}],
                     [{'bar_index': 1, 'prediction': .5}] * 2,
                     [{'bar_index': 1, 'prediction': 1.2}]):
            with self.assertRaises(ValueError):
                policies.bar_positions(self.frame(), rows, policies.ThresholdPolicy('binary', .5))


if __name__ == '__main__':
    unittest.main()
