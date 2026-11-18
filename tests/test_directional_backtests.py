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
