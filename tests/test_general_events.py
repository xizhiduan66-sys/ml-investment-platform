import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant import data, jobs, models, sampling, storage, targets, triggers
from quant.app import (EventRuleIn, ExperimentIn, TriggerIn, create_experiment, experiment,
                       preview_event_rule, save_event_rule)
from quant.events import technical
from quant.worker import execute


PROVIDERS = ('ema_cross', 'donchian_breakout', 'bollinger_transition', 'rsi_cross',
             'momentum_flip', 'clock', 'price_cross')


def candles(values, dates=None):
    values = np.array(values, dtype=float)
    return pd.DataFrame({
        'date': pd.date_range('2025-01-01', periods=len(values), freq='h', tz='UTC') if dates is None else dates,
        'open': values, 'close': values, 'high': values + .1, 'low': values - .1, 'volume': 100.,
    })


def detect(provider, frame, **params):
    return triggers.replay(frame, triggers.definition(provider, params))['events']


class GeneralEventTest(unittest.TestCase):
    def test_all_providers_are_point_in_time_and_have_unique_chronological_ids(self):
        rng = np.random.default_rng(101)
        frame = candles(100 * np.exp(np.cumsum(rng.normal(0, .015, 4200))))
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                full = detect(provider, frame)
                prefix = detect(provider, frame.iloc[:3000])
                self.assertTrue(full, provider)
                self.assertEqual(prefix, [e for e in full if e['observed_at'] < 3000])
                self.assertEqual(len(full), len({e['event_id'] for e in full}))
                self.assertEqual([e['observed_at'] for e in full], sorted(e['observed_at'] for e in full))
                json.dumps(full, allow_nan=False)
                for event in full:
                    self.assertEqual(event['observed_time'], str(frame.date.iloc[event['observed_at']]))

    def test_rsi_equality_warmup_and_direction(self):
        frame = candles([100.] * 8)
        values = pd.Series([np.nan, 30., 29., 25., 30., 31., np.nan, 20.])
        with patch.object(technical, 'rsi', return_value=values):
            events = detect('rsi_cross', frame, threshold=30, direction='双向')
            upward = detect('rsi_cross', frame, threshold=30, direction='上穿')
        self.assertEqual([(e['observed_at'], e['side']) for e in events], [(2, 'down'), (5, 'up')])
        self.assertEqual([e['observed_at'] for e in upward], [5])
        self.assertEqual(events[0]['previous_value'], 30)
        self.assertEqual(events[0]['reference'], 30)
        self.assertEqual(detect('rsi_cross', frame), [])

    def test_ema_uses_the_same_seeded_series_as_features(self):
        frame = candles([10., 11., 12., 11., 9., 8., 10., 12., 13.])
        fast = technical.ema(frame.close, 2)
        slow = technical.ema(frame.close, 3)
        events = detect('ema_cross', frame, fast=2, slow=3)
        self.assertEqual([e['side'] for e in events], ['down', 'up'])
        for event in events:
            i = event['observed_at']
            self.assertEqual(event['value'], fast.iloc[i])
            self.assertEqual(event['reference'], slow.iloc[i])
        with self.assertRaisesRegex(ValueError, '快线周期'):
            triggers.definition('ema_cross', {'fast': 60, 'slow': 20})

    def test_donchian_excludes_current_bar_and_deduplicates_episodes(self):
        frame = candles([10., 10., 10., 12., 14., 16., 14., 20.])
        events = detect('donchian_breakout', frame, window=2, direction='上穿')
        self.assertEqual([e['observed_at'] for e in events], [3, 7])
        self.assertEqual(events[0]['reference'], 10.1)
        self.assertEqual(events[1]['previous_reference'], 16.1)
        flat = candles([10.] * 8).assign(high=10., low=10.)
        self.assertEqual(detect('donchian_breakout', flat, window=2), [])

    def test_bollinger_entry_reentry_and_middle_crossings(self):
        frame = candles([10., 10., 15., 16., 10., 5., 4., 10.])
        for mode, expected in (
            ('进入上轨外', [(2, 'up'), (7, 'up')]),
            ('从上轨回到带内', []),
            ('进入下轨外', [(4, 'down')]),
            ('从下轨回到带内', []),
            ('上穿中轨', [(2, 'up'), (7, 'up')]),
            ('下穿中轨', [(4, 'down')]),
        ):
            with self.subTest(mode=mode):
                events = detect('bollinger_transition', frame, window=2, deviations=.5, transition=mode)
                self.assertEqual([(e['observed_at'], e['side']) for e in events], expected)
        self.assertEqual(detect('bollinger_transition', candles([10.] * 10), window=2), [])
        returned = candles([10., 10., 15., 16., 15.5, 10., 9., 10.])
        for mode, expected in (('从上轨回到带内', [(4, 'down')]), ('从下轨回到带内', [(7, 'up')])):
            events = detect('bollinger_transition', returned, window=3, deviations=.8, transition=mode)
            self.assertEqual([(e['observed_at'], e['side']) for e in events], expected)

    def test_price_and_momentum_crossings(self):
        frame = candles([99., 100., 101., 102., 100., 99., 98.])
        events = detect('price_cross', frame, level=100)
        self.assertEqual([(e['observed_at'], e['side']) for e in events], [(2, 'up'), (5, 'down')])
        daily = candles([100., 100., 110., 120., 100., 100., 90., 80.],
                        pd.date_range('2025-01-01', periods=8, freq='D', tz='UTC'))
        events = detect('momentum_flip', daily, days=1)
        self.assertEqual([(e['observed_at'], e['side']) for e in events],
                         [(2, 'up'), (4, 'down'), (6, 'down')])

    def test_clock_uses_just_closed_bar_in_utc_and_validates_alignment(self):
        dates = pd.date_range('2025-01-05T00:00:00Z', periods=49, freq='h')
        events = detect('clock', candles([100.] * len(dates), dates))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['observed_at'], 23)
        self.assertEqual(pd.Timestamp(events[0]['available_at']), pd.Timestamp('2025-01-06T00:00:00Z'))
        daily = detect('clock', candles([100.] * len(dates), dates), frequency='每天')
        self.assertEqual([e['observed_at'] for e in daily], [23, 47])
        gaps = dates.delete(6)
        with self.assertRaisesRegex(ValueError, '无缺口'):
            detect('clock', candles([100.] * len(gaps), gaps))
        with self.assertRaisesRegex(ValueError, '不对齐'):
            detect('clock', candles([100.] * len(dates), dates), minute=30)

    def test_rule_api_preview_and_real_training(self):
        rng = np.random.default_rng(101)
        frame = candles(100 * np.exp(np.cumsum(rng.normal(.0001, .009, 4800))))
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            jobs.initialize()
            dataset = data.persist(frame, '合成事件测试', 'synthetic')
            for provider in PROVIDERS:
                with self.subTest(provider=provider):
                    definition = triggers.definition(provider)
                    rule = save_event_rule(EventRuleIn(name=provider, **definition))
                    result = preview_event_rule(rule['id'], dataset['id'])
                    self.assertGreater(result['count'], 0)
                    self.assertLessEqual(len(result['events']), 50)
                    trigger = triggers.request(TriggerIn(kind='event', rule_id=rule['id']))
                    snap = {'config': {'trigger': trigger}, 'factors': [{'id': 'momentum.rsi',
                            'spec_id': 'momentum.rsi', 'params': {'window': 14}}]}
                    observations = triggers.collect(frame, snap, lambda _: None)
                    self.assertEqual(len(observations.ids), result['count'])
            saved = save_event_rule(EventRuleIn(name='RSI 穿越 50', **triggers.definition('rsi_cross', {'window': 8})))
            if not any(m['id'] == 'lightgbm' and m['available'] for m in models.registry()):
                self.skipTest('LightGBM 不可用')
            submitted = create_experiment(ExperimentIn(
                name='通用事件训练', dataset_id=dataset['id'], trigger=TriggerIn(kind='event', rule_id=saved['id']),
                target_id='forward_return', factor_ids=['momentum.rsi'], model='lightgbm',
                model_params={'n_estimators': 10},
            ))
            execute(jobs.claim('event-test'), 'event-test')
            completed = experiment(submitted['id'])
            self.assertEqual(completed['status'], 'completed', completed['message'])
            self.assertEqual(completed['result']['kind'], 'event')
            self.assertGreater(completed['result']['splits']['test']['count'], 30)
