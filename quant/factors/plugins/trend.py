"""Trend features from completed closing prices."""
from ..registry import factor
from ..smoothing import seeded_average
from ..spec import ParamSpec

FAST = ParamSpec('fast', 'int', 20, 2, 2000, description='快线周期（K 线根数）')
SLOW = ParamSpec('slow', 'int', 60, 2, 2000, description='慢线周期（K 线根数）')
LAG = ParamSpec('lag', 'int', 5, 1, 2000, description='比较间隔（K 线根数）')


def ema(close, window):
    return seeded_average(close, window, alpha=2 / (window + 1))


def validate_ema_periods(params):
    if params['fast'] >= params['slow']:
        raise ValueError('快线周期必须小于慢线周期')


@factor(id='trend.ema_relative_spread', name='EMA 相对价差', family='趋势',
        description='衡量快慢 EMA 的方向和相对分离程度。', params=(FAST, SLOW), requires=('close',),
        validate_params=validate_ema_periods,
        default_note='快 EMA ÷ 慢 EMA − 1，输出小数比例。正值表示快线在慢线上方。'
                     '两条 EMA 均用各自前 N 根收盘均值初始化，之后以 2/(N+1) 更新。慢线热身前留空。')
def ema_relative_spread(df, params):
    fast, slow = params['fast'], params['slow']
    return ema(df.close, fast) / ema(df.close, slow) - 1


@factor(id='trend.ema_relative_slope', name='慢线相对斜率', family='趋势',
        description='慢 EMA 在指定间隔内的累计相对变化。', params=(SLOW, LAG), requires=('close',),
        default_note='EMA(t) ÷ EMA(t−k) − 1，输出小数比例，保留正负方向。按 k 根累计，不除以 k。'
                     '当前和比较时点均已完成慢线热身才有值。')
def ema_relative_slope(df, params):
    values = ema(df.close, params['slow'])
    return values / values.shift(params['lag']) - 1
