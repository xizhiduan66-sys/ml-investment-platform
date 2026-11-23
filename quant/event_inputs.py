"""Resolve event rules into frozen, point-in-time binary model inputs."""
import numpy as np

from . import chan_events, triggers
from .factors.spec import feature_id


def freeze(inputs):
    features = []
    for item in inputs:
        rule = triggers.rule(item.rule_id)
        params = {**rule['params'], **item.params}
        definition = triggers.definition(rule['provider'], params, item.version or rule['version'])
        identifier = feature_id('event.occurred', definition)
        features.append({'id': identifier, 'name': item.name or rule['name'],
                         'rule_id': item.rule_id, **definition})
    return features


def validate_count(records, event_features):
    if not 1 <= len(records) + len(event_features) <= 30:
        raise ValueError('请选择 1–30 个特征（包含事件特征）')


def mark_bars(size, report):
    values = np.zeros(size, dtype=float)
    for event in report['events']:
        values[event['observed_at']] = 1.
    return values


def add_columns(matrix, df, snapshot, observations, progress):
    features = snapshot.get('event_features', ())
    if not features:
        return matrix
    if any(item['provider'] == 'chan' for item in features) and snapshot.get('chan') != triggers.chan_snapshot():
        raise ValueError('缠论计算配置已变化，请重新创建实验')

    # Multiple type selections can share the same Chan replay.
    chan_report = None
    trigger = triggers.for_config(snapshot['config'])
    for feature in features:
        if trigger.get('rule') and all(feature[k] == trigger['rule'][k]
                                       for k in ('provider', 'version', 'params')):
            report = observations.report
        elif feature['provider'] == 'chan':
            rule = triggers.definition('chan', feature['params'], feature['version'])
            if chan_report is None:
                progress('计算缠论事件输入')
                chan_report = triggers.replay(df, triggers.definition('chan', version=rule['version']),
                                             progress=progress)
            report = chan_events.filter_report(chan_report, rule['params']['types'])
        else:
            report = triggers.replay(df, feature)
        matrix[feature['id']] = mark_bars(len(df), report)[observations.bars]
    return matrix
