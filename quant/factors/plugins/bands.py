"""Price location and width for Donchian and Bollinger bands."""
from ..registry import factor
from ..spec import ParamSpec

WINDOW = ParamSpec('window', 'int', 20, 2, 2000, description='窗口（K 线根数）')
DEVIATIONS = ParamSpec('deviations', 'float', 2., .1, 10., description='标准差倍数')


def donchian(df, window):
    upper = df.high.shift(1).rolling(window).max()
    lower = df.low.shift(1).rolling(window).min()
    return upper, lower


@factor(id='channel.donchian_position', name='唐奇安通道位置', family='区间',
        description='收盘价相对历史通道的归一化位置。', params=(WINDOW,), requires=('high', 'low', 'close'),
        default_note='（收盘 − 下轨）÷（上轨 − 下轨）。上下轨来自当前根之前 N 根的最高价和最低价。'
                     '0 和 1 对应下轨和上轨，允许超出区间。历史不足或上下轨重合时留空。')
def donchian_position(df, params):
    upper, lower = donchian(df, params['window'])
    width = upper - lower
    return (df.close - lower) / width.where(width > 0)


@factor(id='channel.donchian_width', name='唐奇安相对通道宽度', family='区间',
        description='历史高低价区间宽度占当前收盘价的比例。', params=(WINDOW,), requires=('high', 'low', 'close'),
        default_note='（上轨 − 下轨）÷ 当前收盘价，输出小数比例。上下轨排除当前根。'
                     '需要完整的 N 根历史，轨道重合时宽度为 0。')
def donchian_width(df, params):
    upper, lower = donchian(df, params['window'])
    return (upper - lower) / df.close


@factor(id='mean_reversion.bollinger_z', name='布林 Z-score', family='均值回归',
        description='当前收盘偏离布林中轨的标准差倍数。', params=(WINDOW,), requires=('close',),
        default_note='（收盘 − SMA）÷ 总体标准差（除以 N）。窗口包含当前已收盘根。'
                     '正负分别表示中轨上方和下方，标准差为零或热身不足时留空。')
def bollinger_z(df, params):
    window = df.close.rolling(params['window'])
    sigma = window.std(ddof=0)
    return (df.close - window.mean()) / sigma.where(sigma > 0)


@factor(id='mean_reversion.bollinger_width', name='布林相对带宽', family='均值回归',
        description='布林带上下轨间距占中轨的比例。', params=(WINDOW, DEVIATIONS), requires=('close',),
        default_note='2 × 标准差倍数 × 总体标准差 ÷ SMA。窗口包含当前已收盘根，输出小数比例。'
                     '标准差为零时带宽为 0，历史不足时留空。')
def bollinger_width(df, params):
    window = df.close.rolling(params['window'])
    return 2 * params['deviations'] * window.std(ddof=0) / window.mean()
