import unittest

import numpy as np
import pandas as pd

from quant.backtest import BacktestConfig, run
from quant.policies import DirectionalPolicy


class DirectionalBacktestTest(unittest.TestCase):
    def test_signal_boundaries_missing_and_class_ties(self):
        for task, upper, lower in [('binary', .6, .4), ('regression', .01, -.01)]:
            policy = DirectionalPolicy(task, upper, lower)
            np.testing.assert_equal(policy.weights([lower-.001, lower, None, upper, upper+.001]),
                                    [-1, 0, 0, 0, 1])
            with self.assertRaises(ValueError):
                DirectionalPolicy(task, lower, upper)
        policy = DirectionalPolicy('multiclass', .45, .45)
        self.assertEqual(policy.weights([[.5, .5, 0], [.5, .3, .2], [.1, .3, .6], None]).tolist(),
                         [0, -1, 1, 0])

    def test_reversal_and_signed_cash_flows(self):
        prices = [110., 100., 90., 99.]
        frame = pd.DataFrame({key: prices for key in ('open', 'high', 'low', 'close')})
        result = run(frame, [-1, 1, 0, 0], BacktestConfig(initial_cash=100, fee_bps=0, slippage_bps=0))
        self.assertEqual([t['direction'] for t in result['trades']], ['short', 'long'])
        self.assertEqual([o['side'] for o in result['orders']], ['sell', 'buy', 'buy', 'sell'])
        self.assertAlmostEqual(result['metrics']['final_equity'], 121)

    def test_short_stop_gap_with_costs(self):
        prices = [100., 100., 110.]
        frame = pd.DataFrame({key: prices for key in ('open', 'high', 'low', 'close')})
        result = run(frame, [-1, -1, 0], BacktestConfig(initial_cash=100, fee_bps=10,
                                                        slippage_bps=10, stop_loss_pct=.04))
        trade, = result['trades']
        self.assertEqual(trade['exit_reason'], '止损')
        self.assertAlmostEqual(trade['entry_price'], 99.9)
        self.assertAlmostEqual(trade['exit_price'], 110.11)
        self.assertAlmostEqual(result['metrics']['final_equity'], 100 + trade['pnl'])
        self.assertGreater(trade['fee'], 0)

    def test_sparse_events_hold_through_gaps_and_record_skips(self):
        frame = pd.DataFrame({key: [100.] * 9 for key in ('open', 'high', 'low', 'close')})
        entries = {
            0: [{'event_id': 'a', 'direction': 1}, {'event_id': 'b', 'direction': 1}],
            2: [{'event_id': 'c', 'direction': -1}],
            4: [{'event_id': 'd', 'direction': 1}, {'event_id': 'e', 'direction': -1}],
            6: [{'event_id': 'f', 'direction': -1}],
            8: [{'event_id': 'g', 'direction': 1}],
        }
        result = run(frame, [0.] * len(frame), BacktestConfig(max_hold_bars=3), event_entries=entries)
        first, last = result['trades']
        self.assertEqual((first['entry_time'], first['exit_time'], first['hold_bars']), ('1', '4', 3))
        self.assertEqual([event['event_id'] for event in first['entry_events']], ['a', 'b'])
        self.assertEqual(first['exit_reason'], '达到最大持有')
        self.assertEqual(last['direction'], 'short')
        self.assertEqual(last['exit_reason'], '期末平仓')
        self.assertEqual([event['status'] for event in result['event_log']],
                         ['entered', 'entered', 'position_open', 'direction_conflict',
                          'direction_conflict', 'entered', 'end_of_test'])

    def test_structure_probability_filters_events_without_reversing_their_side(self):
        from quant.policies import ThresholdPolicy, event_entries

        rows = [{'sample_id': key, 'bar_index': 2, 'observed_at': 'bar 2', 'prediction': value}
                for key, value in [('sell_high', .8), ('buy_low', .2)]]
        events = {'sell_high': {'side': 'sell', 'observed_at': 2},
                  'buy_low': {'side': 'buy', 'observed_at': 2}}
        entries = event_entries(rows, ThresholdPolicy('binary', .6), 0, 4, events)
        self.assertEqual([event['direction'] for event in entries[2]], [-1, 0])
