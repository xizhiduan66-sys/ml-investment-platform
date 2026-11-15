"""Unified target definitions and their label calculations."""
from dataclasses import dataclass
from typing import Callable, Tuple

import numpy as np

from . import storage
from .factors.spec import ParamSpec, canonical_params, param_schema


def forward_labels(df, target):
    h = target['horizon']
    raw = df.open.shift(-(h + 1)) / df.open.shift(-1) - 1
    return raw if target['task'] == 'regression' else (raw > target['threshold']).astype(float).where(raw.notna())


def settle_structure_label(retained, bar, time):
    return {'label': int(retained), 'label_end': bar, 'label_time': str(time),
            'status': 'confirmed' if retained else 'invalidated'}


def event_label(event):
    """The event tracker supplies the first settled outcome and its availability time."""
    return event['label'], event['label_end'], event['label_time']


@dataclass(frozen=True)
class SampleLabels:
    """One value and maturity bar per input sample. Unavailable labels use NaN / -1."""

    values: np.ndarray
    ends: np.ndarray


def _forward_samples(df, target, observations, events):
    ends = observations + target['horizon'] + 1
    values = forward_labels(df, target).to_numpy(dtype=float)[observations]
    return SampleLabels(values, np.where((ends < len(df)) & np.isfinite(values), ends, -1))


def _structure_samples(df, target, observations, events):
    if events is None:
        raise ValueError('结构确认目标需要缠论事件样本')
    labels = [event_label(event) for event in events]
    values = np.array([value if event['eligible'] and value is not None and end is not None else np.nan
                       for event, (value, end, _) in zip(events, labels)], dtype=float)
    ends = np.array([end if np.isfinite(value) else -1
                     for value, (_, end, _) in zip(values, labels)], dtype=int)
    return SampleLabels(values, ends)


@dataclass(frozen=True)
class TargetSpec:
    id: str
    version: int
    name: str
    task: str
    kind: str
    sample_modes: Tuple[str, ...]
    description: str
    maturity: str
    parameters: Tuple[ParamSpec, ...]
    calculate: Callable

    def definition(self, supplied=None):
        params = canonical_params(self, supplied)
        return {
            'id': self.id, 'version': self.version, 'name': self.name, 'task': self.task,
            'kind': self.kind, 'sample_modes': list(self.sample_modes), 'description': self.description,
            'maturity': self.maturity, 'parameters': param_schema(self.parameters), 'params': params,
            **params,
        }

    @property
    def params(self):
        return self.parameters


_HORIZON = ParamSpec('horizon', 'int', 5, 1, 60, description='持有周期（K 线根数）')
_THRESHOLD = ParamSpec('threshold', 'float', .005, -.5, .5, description='收益门槛（0.005 = 0.5%）')
_RETURN_MODES = ('bar', 'chan_event')
_RETURN_MATURITY = '从下一根 K 线开盘开始，持有周期结束时确定。'
_REGISTERED = {
    (spec.id, spec.version): spec for spec in (
        TargetSpec('forward_return', 1, '未来区间收益率', 'regression', 'forward_return',
                   _RETURN_MODES, '计算从下一根开盘到持有期结束开盘的收益率。',
                   _RETURN_MATURITY, (_HORIZON,), _forward_samples),
        TargetSpec('forward_return_above', 1, '未来收益超过门槛', 'binary', 'forward_return',
                   _RETURN_MODES, '收益严格超过门槛记 1，其余记 0。',
                   _RETURN_MATURITY, (_HORIZON, _THRESHOLD), _forward_samples),
        TargetSpec('chan_structure_v1', 1, '一二类买卖点 · 结构确认', 'binary', 'chan_structure',
                   ('chan_event',), '候选点在结构冻结时保留记 1，撤销记 0。',
                   '结构冻结时确定，尚未判定的候选点留空。', (), _structure_samples),
    )
}
_CURRENT = {spec.id: spec for spec in _REGISTERED.values()}
STRUCTURE_CONFIRMATION = _CURRENT['chan_structure_v1'].definition()


def catalog():
    return [spec.definition() for spec in _CURRENT.values()]


def get(target_id, version=None, params=None):
    spec = _CURRENT.get(target_id) if version is None else _REGISTERED.get((target_id, version))
    if spec is not None:
        return spec.definition(params)
    if target_id in _CURRENT:
        raise ValueError('所选目标版本不可用，请重新选择目标')
    # Old clients can still submit IDs from existing database-backed definitions.
    legacy = storage.get('target', target_id)
    legacy_version = legacy.get('version', 1)
    legacy_params = {'horizon': legacy['horizon']}
    if legacy['task'] == 'binary':
        legacy_params['threshold'] = legacy['threshold']
    if (params and params != legacy_params) or (version is not None and version != legacy_version):
        raise ValueError('请从目标目录选择可配置的目标版本')
    return {'kind': 'forward_return', 'sample_modes': list(_RETURN_MODES), **legacy,
            'version': legacy_version, 'params': legacy_params}


def calculate(df, target, observations, *, events=None):
    """Return labels in sample order; events on the same bar remain separate rows."""
    spec = _REGISTERED.get((target.get('id'), target.get('version')))
    if spec is None and target.get('kind', 'forward_return') == 'forward_return':
        # Historical experiment snapshots have generated IDs and flat parameter values.
        if target.get('id') not in _CURRENT:
            spec = _CURRENT['forward_return_above' if target['task'] == 'binary' else 'forward_return']
    if spec is None:
        raise ValueError('目标计算版本不可用')
    if events is not None and len(events) != len(observations):
        raise ValueError('事件与样本位置数量不一致')
    return spec.calculate(df, target, np.asarray(observations, dtype=int), events)


def output(target):
    if target.get('kind') == 'chan_structure':
        return {'task': 'binary', 'meaning': '候选买卖点最终结构确认保留的概率',
                'unit': 'probability', 'horizon': None}
    regression = target['task'] == 'regression'
    return {'task': target['task'], 'horizon': target['horizon'],
            'meaning': '未来可交易区间收益率' if regression else '未来收益超过目标门槛的概率',
            'unit': 'return' if regression else 'probability'}
