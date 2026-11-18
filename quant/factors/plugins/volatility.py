"""Wilder range and directional strength."""
import pandas as pd

from ..registry import factor
from ..spec import ParamSpec
from ..smoothing import wilder_average

WINDOW = ParamSpec('window', 'int', 14, 2, 2000, description='Wilder 平滑周期（K 线根数）')
PRICE_FIELDS = ('high', 'low', 'close')


def average_true_range(df, window):
    previous = df.close.shift()
    true_range = pd.concat([df.high - df.low, (df.high - previous).abs(),
                            (df.low - previous).abs()], axis=1).max(axis=1)
    return wilder_average(true_range.where(previous.notna()), window)


@factor(id='volatility.atr', name='平均真实波幅 ATR', family='波动',
        description='用 Wilder 平滑衡量每根 K 线的真实波动幅度。', params=(WINDOW,), requires=PRICE_FIELDS,
        default_note='TR 取 H−L、|H−上根收盘|、|L−上根收盘| 三者最大值，再做 Wilder 平滑。'
                     '输出与价格同单位。前 N 个 TR 均值初始化，计算 N 个 TR 需要 N+1 根 K 线。')
def atr(df, params):
    return average_true_range(df, params['window'])


@factor(id='volatility.relative_atr', name='相对 ATR', family='波动',
        description='ATR 占当前收盘价的比例。', params=(WINDOW,), requires=PRICE_FIELDS,
        default_note='ATR ÷ 当前收盘价，输出小数比例。例如 0.005 表示波幅约为价格的 0.5%。'
                     'ATR 用 Wilder 平滑，热身值留空。')
def relative_atr(df, params):
    return average_true_range(df, params['window']) / df.close


@factor(id='trend.adx', name='ADX 趋势强度', family='趋势',
        description='用 Wilder 的方向运动衡量趋势强弱。', params=(WINDOW,), requires=PRICE_FIELDS,
        default_note='根据高低价变化计算 +DM、−DM，再用 ATR 归一化为 +DI、−DI。'
                     '对两者差的绝对值占两者之和的比例平滑，输出 0–100。只衡量强度。'
                     '前 2N−1 个位置留空。热身后无方向运动时 DX 取 0。')
def adx(df, params):
    window = params['window']
    up, down = df.high.diff(), -df.low.diff()
    positive = up.where((up > down) & (up > 0), 0.).where(up.notna())
    negative = down.where((down > up) & (down > 0), 0.).where(down.notna())
    ranges = average_true_range(df, window)
    positive_di = 100 * wilder_average(positive, window) / ranges.where(ranges > 0)
    negative_di = 100 * wilder_average(negative, window) / ranges.where(ranges > 0)
    total = positive_di + negative_di
    dx = 100 * (positive_di - negative_di).abs() / total.where(total > 0)
    return wilder_average(dx.mask((total == 0) | (ranges == 0), 0.), window)
