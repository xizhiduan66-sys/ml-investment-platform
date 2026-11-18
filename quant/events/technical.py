"""Completed-bar events derived from registered technical features."""
import numpy as np
import pandas as pd

from ..factors.plugins.bands import donchian
from ..factors.plugins.returns import trailing_return
from ..factors.plugins.rsi import rsi
from ..factors.plugins.trend import ema


def crossings(values, reference):
    """Cross strictly beyond a boundary after being at or on its other side."""
    difference = values - reference
    ready = np.isfinite(difference) & np.isfinite(difference.shift())
    return {'up': ready & (difference.shift() <= 0) & (difference > 0),
            'down': ready & (difference.shift() >= 0) & (difference < 0)}


def event_rows(df, provider, values, reference, masks, direction='双向'):
    reference = pd.Series(reference, index=df.index, dtype=float)
    enabled = {'上穿': ('up',), '下穿': ('down',), '双向': ('up', 'down')}[direction]
    events = []
    for side in enabled:
        for i in np.flatnonzero(masks[side].to_numpy()):
            events.append({
                'event_id': f'{provider}:{side}:{i}',
                'observed_at': int(i), 'observed_time': str(df.date.iloc[i]), 'side': side,
                'value': float(values.iloc[i]), 'reference': float(reference.iloc[i]),
                'previous_value': float(values.iloc[i - 1]),
                'previous_reference': float(reference.iloc[i - 1]), 'features': {},
            })
    return {'events': sorted(events, key=lambda event: event['observed_at'])}


def ema_cross(df, params, feature_records, progress):
    fast, slow = ema(df.close, params['fast']), ema(df.close, params['slow'])
    return event_rows(df, 'ema_cross', fast, slow, crossings(fast, slow), params['direction'])


def donchian_breakout(df, params, feature_records, progress):
    upper, lower = donchian(df, params['window'])
    upper_masks, lower_masks = crossings(df.close, upper), crossings(df.close, lower)
    up = event_rows(df, 'donchian_breakout', df.close, upper,
                    {'up': upper_masks['up']}, '上穿')
    down = event_rows(df, 'donchian_breakout', df.close, lower,
                      {'down': lower_masks['down']}, '下穿')
    choices = {'上穿': up['events'], '下穿': down['events'], '双向': up['events'] + down['events']}
    return {'events': sorted(choices[params['direction']], key=lambda event: event['observed_at'])}


def bollinger_transition(df, params, feature_records, progress):
    window = df.close.rolling(params['window'])
    middle, deviation = window.mean(), window.std(ddof=0) * params['deviations']
    upper, lower = middle + deviation, middle - deviation
    mode = params['transition']
    if mode in ('上穿中轨', '下穿中轨'):
        reference = middle
        masks = crossings(df.close, reference)
    else:
        reference = upper if mode in ('进入上轨外', '从上轨回到带内') else lower
        masks = crossings(df.close, reference)
        difference = df.close - reference
        ready = np.isfinite(difference) & np.isfinite(difference.shift())
        if mode == '从上轨回到带内':
            masks['down'] = ready & (difference.shift() > 0) & (difference <= 0) & (df.close >= lower)
        elif mode == '从下轨回到带内':
            masks['up'] = ready & (difference.shift() < 0) & (difference >= 0) & (df.close <= upper)
    direction = {'进入上轨外': '上穿', '进入下轨外': '下穿', '从上轨回到带内': '下穿',
                 '从下轨回到带内': '上穿', '上穿中轨': '上穿', '下穿中轨': '下穿'}[mode]
    return event_rows(df, 'bollinger_transition', df.close, reference, masks, direction)


def rsi_cross(df, params, feature_records, progress):
    values = rsi(df, {'window': params['window']})
    return event_rows(df, 'rsi_cross', values, params['threshold'],
                      crossings(values, params['threshold']), params['direction'])


def momentum_flip(df, params, feature_records, progress):
    values = trailing_return(df, {'days': params['days']})
    return event_rows(df, 'momentum_flip', values, 0., crossings(values, 0.), params['direction'])


def price_cross(df, params, feature_records, progress):
    return event_rows(df, 'price_cross', df.close, params['level'],
                      crossings(df.close, params['level']), params['direction'])


def clock(df, params, feature_records, progress):
    if len(df) < 2:
        return {'events': []}
    timestamps = pd.DatetimeIndex(pd.to_datetime(df.date, utc=True))
    intervals = timestamps[1:] - timestamps[:-1]
    step = intervals[0]
    if step <= pd.Timedelta(0) or not (intervals == step).all():
        raise ValueError('定时观察需要等间隔、无缺口的 K 线')
    period = pd.Timedelta(days=1 if params['frequency'] == '每天' else 7)
    if period % step:
        raise ValueError('K 线周期须能整除定时观察周期，请选择更细的 K 线')
    weekdays = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')
    minute = pd.Timedelta(hours=params['hour'], minutes=params['minute'])
    first_close = timestamps[0] + step
    start = first_close.normalize()
    if params['frequency'] == '每周':
        start += pd.Timedelta(days=(weekdays.index(params['weekday']) - start.dayofweek) % 7)
    if (start + minute - first_close) % step:
        raise ValueError('UTC 定时时刻与 K 线收盘边界不对齐，请选择更细的 K 线或调整时间')
    closes = timestamps + step
    matches = (closes.hour == params['hour']) & (closes.minute == params['minute']) & (closes.second == 0)
    if params['frequency'] == '每周':
        matches &= closes.dayofweek == weekdays.index(params['weekday'])
    return {'events': [
        {'event_id': f'clock:{i}', 'observed_at': int(i), 'observed_time': str(df.date.iloc[i]),
         'available_at': closes[i].isoformat(), 'scheduled_time': closes[i].isoformat(), 'features': {}}
        for i in np.flatnonzero(matches)
    ]}
