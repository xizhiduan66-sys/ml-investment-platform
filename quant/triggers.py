"""Versioned observation sources. Event rules only decide when to sample."""
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import chan_events, storage
from .factors.plugins.rsi import WINDOW, rsi
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

    def catalog_entry(self):
        return {'id': self.id, 'name': self.name, 'description': self.description,
                'version': self.version, 'parameters': param_schema(self.params), 'types': self.types or {}}


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


SPECS = {
    'chan': EventSpec('chan', '缠论买卖点', '候选买卖点首次可见时触发。', (), detect_chan, types=chan_events.EVENT_TYPES),
    'rsi_oversold': EventSpec('rsi_oversold', 'RSI 进入超卖区',
                             '上一根 RSI 在阈值上方或等于阈值，本根收盘后跌破阈值时触发。',
                             (WINDOW, ParamSpec('threshold', 'float', 30, 1, 99, description='超卖阈值')), detect_rsi),
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
