"""Wilder RSI calculated from completed bars."""
import pandas as pd

from ..registry import factor
from ..spec import ParamSpec

WINDOW = ParamSpec('window', 'int', 14, 2, 250, description='RSI 周期（K 线根数）')


def wilder_average(series, window):
    seed = series.rolling(window).mean()
    first = seed.first_valid_index()
    if first is None:
        return seed
    updates = series.loc[first:].copy()
    updates.iloc[0] = seed.loc[first]
    return updates.ewm(alpha=1 / window, adjust=False).mean().reindex(series.index)


@factor(id='momentum.rsi', name='RSI 相对强弱指标', family='动量',
        description='按 Wilder 平滑计算收盘价的相对强弱。', params=(WINDOW,), requires=('close',))
def rsi(df, params):
    change = pd.Series(df.close.to_numpy(), dtype=float).diff()
    gain = wilder_average(change.clip(lower=0), params['window'])
    loss = wilder_average(-change.clip(upper=0), params['window'])
    total = gain + loss
    return (100 * gain / total).mask(total == 0, 50).set_axis(df.index)
