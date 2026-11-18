import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant import data, jobs, models, planning, prediction_artifacts, runs, sampling, storage, targets, triggers
from quant.app import (BacktestIn, EventRuleIn, ExperimentIn, TriggerIn, create_backtest,
                       create_experiment, experiment, preview_event_rule, save_event_rule)
from quant.worker import execute


def synthetic_market():
    rng = np.random.default_rng(101)
    close = 100 * np.exp(np.cumsum(rng.normal(.0001, .009, 4800)))
    opened = np.r_[close[0], close[:-1]] + rng.normal(0, .1, len(close))
    return pd.DataFrame({'date': pd.date_range('2025-01-01', periods=len(close), freq='h', tz='UTC'),
                         'open': opened, 'close': close, 'volume': 100.,
                         'high': np.maximum(opened, close) + .4, 'low': np.minimum(opened, close) - .4})


class PredictionTasksTest(unittest.TestCase):
    def test_crossings_are_point_in_time_and_do_not_repeat(self):
        frame = synthetic_market()
        rule = triggers.definition('rsi_oversold', {'window': 8, 'threshold': 40})
        full = triggers.replay(frame, rule)['events']
        prefix = triggers.replay(frame.iloc[:1400], rule)['events']
        self.assertGreater(len(prefix), 30)
        self.assertEqual(prefix, [event for event in full if event['observed_at'] < 1400])
        values = pd.Series([np.nan, 30., 29., 25., 34., 28.])
        with patch('quant.triggers.rsi', return_value=values):
            events = triggers.replay(frame.iloc[:6], triggers.definition('rsi_oversold'))['events']
        self.assertEqual([event['observed_at'] for event in events], [2, 5])

    def test_partitions_purge_labels_crossing_the_boundary(self):
        bars = np.array([55, 55, 60, 65, 77, 80])
        ends = np.array([58, 58, 64, 80, -1, 85])
        groups = sampling.partitions(np.arange(len(bars)), bars, ends, 100)
        self.assertEqual({key: ids.tolist() for key, ids in groups.items()},
                         {'train': [0, 1], 'valid': [2], 'test': [5]})

    def test_targets_and_event_features_validate_compatibility(self):
        with self.assertRaisesRegex(ValueError, '下界'):
            targets.get('forward_return_band', params={'lower': .01, 'upper': .005})
        target = targets.get('forward_return_band', params={'horizon': 1, 'lower': 0., 'upper': .5})
        returns = targets.calculate(pd.DataFrame({'open': [100, 100, 90, 90, 180, 180]}), target, [0, 1, 2, 4])
        np.testing.assert_allclose(returns.values, [0, 1, 2, np.nan], equal_nan=True)
        self.assertEqual(returns.ends.tolist(), [2, 3, 4, -1])
        trigger = {'kind': 'event', 'rule': triggers.definition('rsi_oversold')}
        with self.assertRaisesRegex(ValueError, '采样方式'):
            planning.compile_plan({'trigger': trigger}, targets.STRUCTURE_CONFIRMATION)
        with self.assertRaisesRegex(ValueError, '事件来源'):
            planning.validate_features([{'spec_id': 'chan.side', 'name': '买卖方向'}], trigger)

    def test_event_multiclass_and_bar_binary_run_with_real_models(self):
        if not any(model['id'] == 'lightgbm' and model['available'] for model in models.registry()):
            self.skipTest('LightGBM 不可用')
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            jobs.initialize()
            snapshot = data.persist(synthetic_market(), '合成测试行情', 'synthetic')
            rule = save_event_rule(EventRuleIn(name='RSI 回落', provider='rsi_oversold', version=1,
                                               params={'window': 8, 'threshold': 40}))
            preview = preview_event_rule(rule['id'], snapshot['id'])
            self.assertGreater(preview['count'], 150)
            self.assertEqual(len(preview['events']), 50)
            cases = [('forward_return_band', TriggerIn(kind='event', rule_id=rule['id'])),
                     ('forward_return_above', TriggerIn(kind='bar'))]
            for target, trigger in cases:
                with self.subTest(target=target):
                    job = create_experiment(ExperimentIn(name=target, dataset_id=snapshot['id'],
                                            factor_ids=['momentum.rsi'], model='lightgbm',
                                            model_params={'n_estimators': 10}, target_id=target, trigger=trigger))
                    execute(jobs.claim('test-worker'), 'test-worker')
                    finished = experiment(job['id'])
                    self.assertEqual(finished['status'], 'completed', finished['message'])
                    result = finished['result']
                    artifact = json.loads((storage.ROOT / result['prediction_artifact']['file']).read_text())
                    self.assertEqual(artifact['version'], 2)
                    if trigger.kind == 'event':
                        self.assertEqual(artifact['classes'], ['下跌', '横盘', '上涨'])
                        self.assertEqual(finished['snapshot']['config']['trigger']['rule'],
                                         {key: value for key, value in rule.items() if key != 'created_at'})
                        self.assertEqual(result['kind'], 'event')
                        self.assertTrue(result['backtest_available'])
                        split = result['diagnostics']['splits']['test']
                        self.assertEqual(sum(split['class_counts']), split['count'])
                        self.assertAlmostEqual(sum(artifact['rows'][0]['probabilities']), 1.)
                        replay = create_backtest(BacktestIn(name='事件交易', experiment_id=job['id'],
                                                            strategy='return_band', threshold=0, short_threshold=0))
                        ledger = replay['result']
                        self.assertEqual(len(ledger['event_log']), split['count'])
                        self.assertEqual(replay['config']['max_hold_bars'], 5)
                        self.assertGreater(len(ledger['trades']), 0)
                        self.assertTrue(all(trade['entry_events'] for trade in ledger['trades']))
                    else:
                        execution = runs.list_for(job['id'])[0]
                        self.assertEqual(len(artifact['rows'][0]['probabilities']), 2)
                        decoded = prediction_artifacts.load(result['prediction_artifact'], execution['id'],
                                                            finished['snapshot']['dataset'], 'binary')
                        self.assertEqual(decoded[0]['prediction'], decoded[0]['probabilities'][1])
                        replay = create_backtest(BacktestIn(name='交易', source='experiment', experiment_id=job['id']))
                        self.assertAlmostEqual(replay['metrics']['net_return'], result['metrics']['net_return'])
