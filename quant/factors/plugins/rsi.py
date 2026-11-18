"""Wilder RSI calculated from completed bars."""
import pandas as pd

from ..registry import factor
from ..smoothing import wilder_average
from ..spec import ParamSpec

WINDOW = ParamSpec('window', 'int', 14, 2, 250, description='RSI 周期（K 线根数）')


@factor(id='momentum.rsi', name='RSI 相对强弱指标', family='动量',
        description='按 Wilder 平滑计算收盘价的相对强弱。', params=(WINDOW,), requires=('close',),
        default_note='RSI = 100 × 平滑涨幅 /（平滑涨幅 + 平滑跌幅）。使用已收盘 K 线，范围 0–100，'
                     '平滑期内涨跌幅均为零时取 50。至少需要 N+1 根收盘价形成 N 个价差。')
def rsi(df, params):
    change = pd.Series(df.close.to_numpy(), dtype=float).diff()
    gain = wilder_average(change.clip(lower=0), params['window'])
    loss = wilder_average(-change.clip(upper=0), params['window'])
    total = gain + loss
    return (100 * gain / total).mask(total == 0, 50).set_axis(df.index)


@factor(id='momentum.rsi_change', name='RSI 变化量', family='动量',
        description='当前 RSI 相对若干根前的点数变化。',
        params=(WINDOW, ParamSpec('lag', 'int', 3, 1, 250, description='比较间隔（K 线根数）')),
        requires=('close',), default_note='RSI(t) − RSI(t−k)，单位为 RSI 点。正值表示 RSI 回升。'
                                          '两个时点的 RSI 都已热身才计算，默认用 RSI(14) 和 3 根间隔。')
def rsi_change(df, params):
    values = rsi(df, {'window': params['window']})
    return values - values.shift(params['lag'])
