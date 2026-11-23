import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from quant import data, event_inputs, factors, jobs, models, sampling, storage, triggers
from quant.app import (PreflightIn, create_experiment, experiment, preview_event_feature,
                       research_preflight)
from quant.research_inputs import EventFeatureIn, ExperimentIn
from quant.worker import execute
from test_factor_causality import bars


class EventInputsTest(unittest.TestCase):
    def test_chan_mark_matches_first_observation_and_survives_truncation(self):
        frame = bars(1200)
        feature, = event_inputs.freeze([EventFeatureIn(rule_id='chan', params={'types': ['2:buy']})])
        snapshot = {'config': {}, 'event_features': [feature], 'chan': triggers.chan_snapshot()}

        def mark(df):
            batch = triggers.collect(df, snapshot, lambda _: None)
            inputs = event_inputs.add_columns(factors.matrix(df, []), df, snapshot, batch, lambda _: None)
            return inputs[feature['id']].to_numpy()

        full = mark(frame)
        events = triggers.replay(frame, feature)['events']
        self.assertTrue(events)
        self.assertEqual(set(np.flatnonzero(full)), {event['observed_at'] for event in events})
        np.testing.assert_array_equal(full[:900], mark(frame.iloc[:900]))
        report = {'events': [{'observed_at': 3, 'anchor': 1}, {'observed_at': 3, 'anchor': 2}]}
        np.testing.assert_array_equal(event_inputs.mark_bars(5, report), [0, 0, 0, 1, 0])

    def test_configured_event_only_inputs_reach_model_and_preview(self):
        if not any(m['id'] == 'lightgbm' and m['available'] for m in models.registry()):
            self.skipTest('LightGBM 不可用')
        inputs = [EventFeatureIn(rule_id='rsi_cross', params={'window': 8, 'direction': '上穿'}),
                  EventFeatureIn(rule_id='rsi_cross', params={'window': 12, 'direction': '下穿'})]
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            dataset = data.persist(bars(1200), '测试行情', 'synthetic')
            request = {'model': 'lightgbm', 'target_id': 'forward_return', 'event_features': inputs}
            preflight = research_preflight(PreflightIn(**request))
            self.assertEqual(len(preflight['manifest']['features']), 2)
            queued = create_experiment(ExperimentIn(name='事件输入', dataset_id=dataset['id'], **request))
            snapshot = queued['snapshot']
            self.assertEqual(snapshot['manifest'], preflight['manifest'])
            self.assertEqual(snapshot['event_features'][0]['params']['window'], 8)
            self.assertEqual(len(set(item['id'] for item in snapshot['event_features'])), 2)
            _, matrix, _, _ = sampling.prepare(data.load(snapshot['dataset']), snapshot,
                                                snapshot['target'], 1, lambda _: None)
            preview = preview_event_feature(dataset['id'], inputs[0])
            self.assertEqual(preview['count'], int(matrix.iloc[:, 0].sum()))
            self.assertGreater(preview['count'], 0)
            execute(jobs.claim('demo'), 'demo')
            completed = experiment(queued['id'])
            self.assertEqual(completed['status'], 'completed', completed.get('message'))
            self.assertEqual(completed['result']['feature_manifest'], preflight['manifest'])
