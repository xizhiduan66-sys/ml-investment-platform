"""Compile an explicit, JSON-serializable execution contract before queueing."""
from . import factors, models, model_config, triggers

VERSION = 1


def compile_plan(config, target):
    trigger = triggers.for_config(config)
    mode = triggers.sample_mode(trigger)
    required_source = target.get('event_source')
    if mode not in target['sample_modes'] or (required_source and required_source != triggers.source(trigger)):
        raise ValueError('目标与采样方式不兼容')
    model = next((m for m in models.registry() if m['id'] == config['model']), None)
    if not model or not model['available'] or target['task'] not in model['tasks']:
        raise ValueError('模型不可用或不支持当前任务')
    if trigger['kind'] == 'event' and model['input'] != 'vector':
        raise ValueError('事件样本当前需要向量输入模型')
    plan = {
        'version': VERSION, 'task': target['task'], 'sampling': mode,
        'representation': model['input'], 'model': model['id'],
        'model_params': model_config.resolve(model['id'], target['task'], config.get('model_params')),
        'target': {'id': target['id'], 'version': target['version'], 'params': target.get('params', {})},
        'output': 'probability' if target['task'] == 'binary' else 'value',
        'split': {'kind': 'chronological', 'train': .6, 'valid_end': .8, 'purge_label_boundaries': True},
    }
    if config.get('trigger'):
        plan.update(version=2, trigger=trigger,
                    output={'regression': 'value', 'binary': 'class_probabilities',
                            'multiclass': 'class_probabilities'}[target['task']])
    return plan


def validate_features(records, trigger):
    provider = triggers.source(trigger)
    for record in records:
        spec = factors.resolve(record)[0]
        if spec.scope == 'event' and (spec.event_source or 'chan') != provider:
            raise ValueError(f'「{record["name"]}」需要匹配的事件来源，请选择对应事件规则或更换特征')
