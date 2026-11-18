"""Versioned observation sources. Event rules only decide when to sample."""
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import chan_events, storage
from .events import technical
from .factors.plugins.bands import WINDOW as BAND_WINDOW, DEVIATIONS
from .factors.plugins.returns import DAYS
from .factors.plugins.rsi import WINDOW, rsi
from .factors.plugins.trend import FAST, SLOW, validate_ema_periods
from .factors.spec import ParamSpec, canonical_params, param_schema


@dataclass(frozen=True)
class EventSpec:
    id: str
    name: str
    description: str
    params: tuple
    detect: Callable
    version: int = 1
    types: dict = None
    validate_params: Callable = None
    preview_columns: tuple = ()

    def catalog_entry(self):
        return {'id': self.id, 'name': self.name, 'description': self.description,
                'version': self.version, 'parameters': param_schema(self.params), 'types': self.types or {},
                'preview_columns': [{'key': key, 'label': label} for key, label in self.preview_columns]}


def detect_chan(df, params, feature_records, progress):
    return chan_events.filter_report(chan_events.replay(df, progress, feature_records=feature_records), params['types'])


def detect_rsi(df, params, feature_records, progress):
    values = rsi(df, params)
    positions = np.flatnonzero(((values.shift() >= params['threshold']) & (values < params['threshold'])).to_numpy())
    return {'events': [
        {'event_id': f"rsi_oversold:{i}", 'observed_at': int(i), 'observed_time': str(df.date.iloc[i]),
         'value': float(values.iloc[i]), 'features': {}}
        for i in positions
    ]}


DIRECTION = ParamSpec('direction', 'enum', '双向', options=('上穿', '下穿', '双向'), description='触发方向')
CROSS_COLUMNS = (('side', '方向'), ('previous_value', '前一根观测值'), ('value', '本根观测值'),
                 ('previous_reference', '前一根参考值'), ('reference', '本根参考值'))


SPECS = {
    'chan': EventSpec('chan', '缠论买卖点', '候选买卖点首次可见时触发。', (), detect_chan, types=chan_events.EVENT_TYPES),
    'rsi_oversold': EventSpec('rsi_oversold', 'RSI 进入超卖区',
                             '上一根 RSI 在阈值上方或等于阈值，本根收盘后跌破阈值时触发。',
                             (WINDOW, ParamSpec('threshold', 'float', 30, 1, 99, description='超卖阈值')), detect_rsi,
                             preview_columns=(('value', '触发时 RSI'),)),
    'ema_cross': EventSpec('ema_cross', 'EMA 均线交叉',
                          '快线上穿或下穿慢线时触发。使用已收盘价格，首个有效值不追溯触发。',
                          (FAST, SLOW, DIRECTION), technical.ema_cross, validate_params=validate_ema_periods,
                          preview_columns=(('side', '方向'), ('value', '快线 EMA'), ('reference', '慢线 EMA'))),
    'donchian_breakout': EventSpec('donchian_breakout', '唐奇安通道突破',
                                  '收盘首次越过前 N 根的上轨或下轨时触发。轨道排除当前根，连续位于轨外期间不重复触发。',
                                  (BAND_WINDOW, DIRECTION), technical.donchian_breakout,
                                  preview_columns=(('side', '方向'), ('value', '收盘价'), ('reference', '通道边界'))),
    'bollinger_transition': EventSpec('bollinger_transition', '布林带进入与回归',
                                     '用含当前收盘的 SMA 和总体标准差计算轨道。进入轨外、回到带内或穿越中轨时取样。回到轨道边界计入带内。',
                                     (BAND_WINDOW, DEVIATIONS, ParamSpec('transition', 'enum', '进入下轨外',
                                      options=('进入上轨外', '进入下轨外', '从上轨回到带内', '从下轨回到带内', '上穿中轨', '下穿中轨'),
                                      description='状态变化')), technical.bollinger_transition,
                                     preview_columns=(('side', '方向'), ('value', '收盘价'), ('reference', '布林参考轨道'))),
    'rsi_cross': EventSpec('rsi_cross', 'RSI 阈值穿越',
                          '已热身的 RSI 从阈值另一侧（含相等）穿到指定方向时触发一次。可配置超买、超卖或回穿 50。',
                          (WINDOW, ParamSpec('threshold', 'float', 50, 0, 100, description='RSI 阈值'), DIRECTION),
                          technical.rsi_cross, preview_columns=CROSS_COLUMNS),
    'momentum_flip': EventSpec('momentum_flip', '动量符号翻转',
                              '过去 N 个自然日的收盘收益率穿过零时触发。所需历史时间点缺失时不触发。',
                              (DAYS, DIRECTION), technical.momentum_flip, preview_columns=CROSS_COLUMNS),
    'clock': EventSpec('clock', 'UTC 定时观察',
                      '每天或每周在指定 UTC 时刻取样，使用该时刻刚刚收盘的 K 线。时刻须与收盘边界对齐，行情须等间隔、无缺口。',
                      (ParamSpec('frequency', 'enum', '每周', options=('每天', '每周'), description='观察频率'),
                       ParamSpec('weekday', 'enum', '周一',
                                 options=('周一', '周二', '周三', '周四', '周五', '周六', '周日'),
                                 description='星期（仅每周生效）'),
                       ParamSpec('hour', 'int', 0, 0, 23, description='UTC 小时'),
                       ParamSpec('minute', 'int', 0, 0, 59, description='UTC 分钟')),
                      technical.clock, preview_columns=(('scheduled_time', '定时 / 可用时间（UTC）'),)),
    'price_cross': EventSpec('price_cross', '指定价位穿越',
                            '收盘价首次穿过固定价位时触发一次。价位使用行情的价格单位，默认 100，使用前可另存为所需价位。',
                            (ParamSpec('level', 'float', 100., .00000001, 1e12, description='固定价位'), DIRECTION),
                            technical.price_cross, preview_columns=CROSS_COLUMNS),
}


def definition(provider, params=None, version=None):
    spec = SPECS.get(provider)
    if spec is None or version not in (None, spec.version):
        raise ValueError('事件规则版本不可用')
    params = dict(params or {})
    if spec.types:
        selection = params.pop('types', None)
        selection = list(spec.types) if selection is None else selection
        if not isinstance(selection, list) or not selection or any(
                not isinstance(name, str) or name not in spec.types for name in selection):
            raise ValueError('请选择有效的事件类型')
        if len(set(selection)) != len(selection):
            raise ValueError('事件类型不能重复')
        params = {**canonical_params(spec, params), 'types': [name for name in spec.types if name in selection]}
    else:
        params = canonical_params(spec, params)
    return {'provider': provider, 'version': spec.version, 'params': params}


def rule(rule_id):
    if rule_id in SPECS:
        return {'id': rule_id, 'name': SPECS[rule_id].name, **definition(rule_id)}
    return storage.get('event_rule', rule_id)


def catalog():
    return {'providers': [spec.catalog_entry() for spec in SPECS.values()],
            'rules': [*(rule(provider) for provider in SPECS), *storage.all_of('event_rule')]}


def request(trigger, legacy_mode='bar', legacy_types=None):
    if trigger is None:
        if legacy_mode == 'bar' and legacy_types is None:
            return {'kind': 'bar'}
        if legacy_mode == 'chan_event':
            definition_ = definition('chan', {'types': legacy_types})
            return {'kind': 'event', 'rule': {'id': 'chan', 'name': SPECS['chan'].name, **definition_}}
        raise ValueError('未知采样方式，或 K 线触发带有事件配置')
    if trigger.kind == 'bar' and trigger.rule_id is None and legacy_types is None:
        return {'kind': 'bar'}
    if trigger.kind != 'event' or not trigger.rule_id:
        raise ValueError('事件触发需要选择事件规则')
    chosen = rule(trigger.rule_id)
    params = chosen['params']
    if legacy_types is not None:
        if chosen['provider'] != 'chan' or not set(legacy_types) <= set(params['types']):
            raise ValueError('所选事件类型与规则不兼容')
        params = {**params, 'types': legacy_types}
    return {'kind': 'event', 'rule': {'id': chosen['id'], 'name': chosen['name'],
            **definition(chosen['provider'], params, chosen['version'])}}


def for_config(config):
    return config.get('trigger') or request(None, config.get('sample_mode', 'bar'), config.get('event_types'))


def source(trigger):
    return trigger['rule']['provider'] if trigger['kind'] == 'event' else None


def sample_mode(trigger):
    return {'chan': 'chan_event', None: 'bar'}.get(source(trigger), 'event')


def chan_snapshot():
    return {'version': chan_events.VERSION, 'upstream': chan_events.UPSTREAM, 'config': dict(chan_events.CONFIG)}


def replay(df, rule, *, feature_records=(), progress=lambda _: None):
    spec = definition(rule['provider'], rule['params'], rule['version'])
    return SPECS[spec['provider']].detect(df, spec['params'], feature_records, progress)


@dataclass(frozen=True)
class Observations:
    bars: np.ndarray
    ids: tuple
    report: dict = None


def collect(df, snapshot, progress):
    trigger = for_config(snapshot['config'])
    if trigger['kind'] == 'bar':
        return Observations(np.arange(len(df)), tuple(map(str, range(len(df)))))
    if source(trigger) == 'chan' and snapshot.get('chan') != chan_snapshot():
        raise ValueError('缠论计算配置已变化，请重新创建实验')
    report = replay(df, trigger['rule'], feature_records=snapshot['factors'], progress=progress)
    events = report['events']
    return Observations(np.array([e['observed_at'] for e in events], dtype=int),
                        tuple(e['event_id'] for e in events), report)
