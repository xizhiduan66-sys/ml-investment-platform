"""Calendar lookbacks for continuously traded OHLCV."""
import numpy as np
import pandas as pd

from ..registry import factor
from ..spec import ParamSpec

DAYS = ParamSpec('days', 'int', 30, 1, 730, description='窗口（自然日）')
RANK_DAYS = ParamSpec('rank_days', 'int', 90, 1, 730, description='历史排名窗口（自然日）')
FIELDS = ('date', 'close')
SECONDS_PER_YEAR = pd.Timedelta(days=365).total_seconds()


def dated_close(df):
    index = pd.DatetimeIndex(pd.to_datetime(df.date, utc=True))
    return pd.Series(df.close.to_numpy(), index=index, dtype=float)


def annualized_volatility(close, span):
    returns = np.log(close).diff().rolling(span, min_periods=2)
    steps = close.index.to_series().diff().dt.total_seconds().rolling(span, min_periods=2)
    cadence = steps.max()
    complete = (steps.min() == cadence) & (returns.count() * cadence == span.total_seconds())
    return (returns.std(ddof=0) * np.sqrt(SECONDS_PER_YEAR / cadence)).where(complete)


@factor(id='momentum.trailing_return', name='过去区间收益率', family='动量',
        description='当前收盘相对于指定自然日前收盘的变化。', params=(DAYS,), requires=FIELDS,
        default_note='当前收盘 ÷ N 个自然日前同一 UTC 时刻的收盘 − 1。输出小数比例。'
                     '时间点缺失时留空，默认 30 天，对 1h 行情等于 720 根。')
def trailing_return(df, params):
    close = dated_close(df)
    previous = close.reindex(close.index - pd.Timedelta(days=params['days']))
    return (close / previous.to_numpy() - 1).set_axis(df.index)


@factor(id='volatility.realized', name='年化已实现波动率', family='波动',
        description='对数收益的滚动总体标准差，按连续交易年化。', params=(DAYS,), requires=FIELDS,
        default_note='最近 N 天单根对数收益率的总体标准差 × √(365 天 ÷ K 线间隔)。输出小数比例。'
                     '需要至少两个收益观测及完整、等间隔的窗口，遇到缺口或期限无法整除 K 线间隔时留空。')
def realized_volatility(df, params):
    return annualized_volatility(dated_close(df), pd.Timedelta(days=params['days'])).set_axis(df.index)


@factor(id='volatility.realized_percentile', name='已实现波动率历史分位', family='波动',
        description='当前年化已实现波动率在历史窗口内的位置。', params=(DAYS, RANK_DAYS), requires=FIELDS,
        default_note='比较当前波动率与前 M 天各根波动率，排除当前值。历史值较低计 1，相等计 0.5，'
                     '除以历史观测数。输出 0–1。默认 30 天计算波动、90 天排名，约需 120 天完整行情。')
def realized_percentile(df, params):
    close = dated_close(df)
    volatility = annualized_volatility(close, pd.Timedelta(days=params['days']))
    span = pd.Timedelta(days=params['rank_days'])
    history = volatility.rolling(span, closed='both', min_periods=2)
    previous_count = history.count() - 1
    cadence = close.index.to_series().diff().dt.total_seconds()
    rank = (history.rank(method='average') - 1) / previous_count
    return rank.where(previous_count * cadence == span.total_seconds()).set_axis(df.index)
