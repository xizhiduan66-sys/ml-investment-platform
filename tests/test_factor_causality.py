"""因子因果性守门。

研究台最危险的一类错误是“因子偷看未来”：它在 t 时刻用了 t 之后的数据，
指标会异常漂亮，而实盘根本复现不了。这里用截断对照把这条约定变成测试：

    compute(前 k 根) 必须与 compute(全部) 的前 k 根逐点一致

事件型因子从首次可见时冻结的上下文取值。逐 K 线因子及逐样本因子都纳入截断对照。
"""
import unittest

import numpy as np
import pandas as pd

from quant import factors


def bars(n=400, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .01, n)))
    opened = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        'date': pd.date_range('2025-01-01', periods=n, freq='h', tz='UTC'),
        'open': opened,
        'high': np.maximum(opened, close) + .5,
        'low': np.minimum(opened, close) - .5,
        'close': close,
        'volume': rng.integers(100, 500, n),
    })


def mismatches(compute, df, k):
    """返回“只看前 k 根”与“看全量”结果不一致的位置；空列表表示通过。"""
    full = np.asarray(compute(df), dtype=float)[:k]
    prefix = np.asarray(compute(df.iloc[:k]), dtype=float)
    return np.flatnonzero(~np.isclose(full, prefix, equal_nan=True)).tolist()


NON_EVENT = [spec for spec in factors.specs().values() if spec.scope != 'event']
EVENT = [spec for spec in factors.specs().values() if spec.scope == 'event']


class CausalityHarnessTest(unittest.TestCase):
    """先证明守门器本身有效，否则后面的“通过”没有意义。"""

    def test_detects_lookahead(self):
        df = bars()

        def leaks(frame):  # 典型错误：shift(-1) 偷看下一根收盘
            return pd.Series(frame['close'].shift(-1).to_numpy(), index=frame.index)

        found = mismatches(leaks, df, len(df) - 1)
        self.assertTrue(found, '守门器没有抓到 shift(-1) 这类偷看未来的实现')

    def test_accepts_causal_implementation(self):
        df = bars()
        self.assertEqual(mismatches(lambda frame: frame['close'].rolling(5).mean(), df, 200), [])

    def test_detects_full_series_normalisation(self):
        df = bars()

        def normalises_on_whole_series(frame):  # 另一类常见污染：用全序列均值做标准化
            return (frame['close'] - frame['close'].mean()) / frame['close'].std()

        self.assertTrue(mismatches(normalises_on_whole_series, df, 200))


class RegisteredFactorTest(unittest.TestCase):
    @unittest.skipIf(not NON_EVENT, '当前没有 series/sample 因子，守门器只对待注册插件生效')
    def test_series_and_sample_factors_are_causal(self):
        df = bars(6000)
        for spec in NON_EVENT:
            params = {param.name: param.default for param in spec.params if param.default is not None}
            record = {'id': 'probe', 'spec_id': spec.id, 'params': params}
            self.assertTrue(np.isfinite(factors.compute(df, record)).any(), f'{spec.id} 无有效值')
            for k in (len(df) // 2, len(df) - 1):
                self.assertEqual(mismatches(lambda frame: factors.compute(frame, record), df, k), [],
                                 f'{spec.id} 在只看前 {k} 根时结果不同')

    def test_event_factors_refuse_bar_sampling(self):
        df = bars()
        for spec in EVENT:
            with self.assertRaises(ValueError):
                factors.compute(df, {'id': 'probe', 'spec_id': spec.id, 'params': {}})


class EventFactorTest(unittest.TestCase):
    """事件因子的取值只来自事件首次可见时冻结的上下文。"""

    class Bi:
        def __init__(self, value):
            self.value = value

        def cal_macd_metric(self, algorithm, is_second):
            return self.value

    class Bsp:
        is_buy = True

    def context(self, numerator, denominator):
        return {'bsp': self.Bsp(), 'kind': '1', 'lines': None,
                'pair': (self.Bi(denominator), self.Bi(numerator))}

    def test_peak_ratio_uses_frozen_pair(self):
        record = {'id': 'probe', 'spec_id': 'chan.peak_ratio', 'params': {}}
        self.assertEqual(factors.compute_event(record, self.context(4., 2.)), 2.)
        self.assertEqual(factors.compute_event(record, self.context(4., 2.)), 2.)

    def test_missing_structure_is_empty(self):
        record = {'id': 'probe', 'spec_id': 'chan.peak_ratio', 'params': {}}
        self.assertIsNone(factors.compute_event(record, {**self.context(4., 2.), 'pair': None}))

    def test_side_and_type_come_from_event(self):
        self.assertEqual(factors.compute_event(
            {'id': 'r', 'spec_id': 'chan.side', 'params': {}}, self.context(4., 2.)), 1.)
        self.assertEqual(factors.compute_event(
            {'id': 't', 'spec_id': 'chan.type', 'params': {}}, {**self.context(4., 2.), 'kind': '2'}), 2.)


if __name__ == '__main__':
    unittest.main()
