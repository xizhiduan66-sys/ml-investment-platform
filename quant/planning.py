"""Compile an explicit, JSON-serializable execution contract before queueing."""
from . import models, model_config

VERSION = 1


def compile_plan(config, target):
    mode = config.get('sample_mode', 'bar')
    if mode not in ('bar', 'chan_event') or mode not in target['sample_modes']:
        raise ValueError('目标与采样方式不兼容')
    model = next((m for m in models.registry() if m['id'] == config['model']), None)
    if not model or not model['available'] or target['task'] not in model['tasks']:
        raise ValueError('模型不可用或不支持当前任务')
    if mode == 'chan_event' and model['input'] != 'vector':
        raise ValueError('事件样本当前需要向量输入模型')
    return {
        'version': VERSION, 'task': target['task'], 'sampling': mode,
        'representation': model['input'], 'model': model['id'],
        'model_params': model_config.resolve(model['id'], target['task'], config.get('model_params')),
        'target': {'id': target['id'], 'version': target['version'], 'params': target.get('params', {})},
        'output': 'probability' if target['task'] == 'binary' else 'value',
        'split': {'kind': 'chronological', 'train': .6, 'valid_end': .8, 'purge_label_boundaries': True},
    }
