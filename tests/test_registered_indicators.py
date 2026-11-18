from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant import factors, storage
from quant.app import FeatureNoteIn, registered_features, save_feature_note


def compute(frame, spec, **params):
    return factors.compute(frame, {'id': spec, 'spec_id': spec, 'params': params})


def candles(values):
    frame = pd.DataFrame({'close': values, 'date': pd.date_range('2025-01-01', periods=len(values), tz='UTC')})
    return frame.assign(high=frame.close + 1., low=frame.close - 1.)


class RegisteredIndicatorsTest(unittest.TestCase):
    def test_ema_sma_seed_and_period_order(self):
        frame = candles([100., 102., 104., 108.])
        fast = 101. + (104. - 101.) * 2 / 3
        slow = 102.
        self.assertAlmostEqual(compute(frame, 'trend.ema_relative_spread', fast=2, slow=3).iloc[2], fast / slow - 1)
        slope = compute(frame, 'trend.ema_relative_slope', slow=3, lag=1)
        self.assertTrue(slope.iloc[:3].isna().all())
        self.assertAlmostEqual(slope.iloc[-1], 105. / 102. - 1)
        with self.assertRaisesRegex(ValueError, '快线周期'):
            compute(frame, 'trend.ema_relative_spread', fast=3, slow=3)

    def test_atr_and_adx(self):
        frame = candles([10., 13., 16., 19., 22., 25.])
        atr = compute(frame, 'volatility.atr', window=2)
        np.testing.assert_allclose(atr.iloc[2:], 4.)
        self.assertAlmostEqual(compute(frame, 'volatility.relative_atr', window=2).iloc[-1], .16)
        adx = compute(frame, 'trend.adx', window=2)
        self.assertTrue(adx.iloc[:3].isna().all())
        np.testing.assert_allclose(adx.iloc[3:], 100.)
        flat = frame.assign(close=10., high=10., low=10.)
        np.testing.assert_allclose(compute(flat, 'trend.adx', window=2).iloc[3:], 0.)

    def test_donchian_lags_bands_and_bollinger_uses_population_variance(self):
        frame = candles([10., 12., 16.])
        self.assertAlmostEqual(compute(frame, 'channel.donchian_position', window=2).iloc[-1], 1.75)
        self.assertAlmostEqual(compute(frame, 'channel.donchian_width', window=2).iloc[-1], .25)
        self.assertAlmostEqual(compute(frame, 'mean_reversion.bollinger_z', window=2).iloc[-1], 1.)
        self.assertAlmostEqual(compute(frame, 'mean_reversion.bollinger_width', window=2).iloc[-1], 8 / 14)
        flat = frame.assign(close=10., high=10., low=10.)
        self.assertTrue(compute(flat, 'channel.donchian_position', window=2).isna().all())
        self.assertTrue(compute(flat, 'mean_reversion.bollinger_z', window=2).isna().all())

    def test_rsi_change_uses_existing_rsi(self):
        frame = candles([10., 12., 11., 13., 14.])
        rsi = compute(frame, 'momentum.rsi', window=2)
        pd.testing.assert_series_equal(compute(frame, 'momentum.rsi_change', window=2, lag=1), rsi.diff())

    def test_calendar_windows_annualization_ties_and_gaps(self):
        frame = candles([100., 110., 88., 100., 90., 120.])
        self.assertAlmostEqual(compute(frame, 'momentum.trailing_return', days=2).iloc[2], -.12)
        self.assertAlmostEqual(compute(frame, 'volatility.realized', days=2).iloc[2],
                               np.std(np.log([1.1, .8])) * np.sqrt(365))
        flat = frame.assign(close=100.)
        ranks = compute(flat, 'volatility.realized_percentile', days=2, rank_days=2)
        self.assertTrue(ranks.iloc[:4].isna().all())
        np.testing.assert_allclose(ranks.iloc[4:], .5)
        gap = frame.drop(index=3)
        self.assertTrue(np.isnan(compute(gap, 'volatility.realized', days=2).loc[4]))
        self.assertTrue(np.isnan(compute(gap, 'momentum.trailing_return', days=2).loc[5]))

    def test_default_notes_and_overrides_do_not_change_the_manifest(self):
        with TemporaryDirectory() as directory, patch.object(storage, 'ROOT', Path(directory)):
            feature_id = 'trend.ema_relative_spread'
            original = registered_features()[feature_id]
            self.assertIn('快 EMA', original['note'])
            before = factors.build_manifest([original]).hash
            for note in ('我自己的备注', ''):
                save_feature_note(feature_id, FeatureNoteIn(note=note))
                updated = registered_features()[feature_id]
                self.assertEqual(updated['note'], note)
                self.assertEqual(factors.build_manifest([updated]).hash, before)
