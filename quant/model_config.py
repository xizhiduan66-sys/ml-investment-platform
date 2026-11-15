"""Validated, task-specific public model hyperparameters."""
import math


def schema(kind, task):
    from .model_adapters import get_adapter
    adapter = get_adapter(kind)
    if task not in adapter.tasks:
        raise ValueError('模型不支持当前学习任务')
    return adapter.parameter_schema(task)


def resolve(kind, task, supplied=None):
    specs = schema(kind, task)
    supplied = {} if supplied is None else supplied
    if not isinstance(supplied, dict):
        raise ValueError('模型参数必须是对象')
    unknown = set(supplied) - {s['name'] for s in specs}
    if unknown:
        raise ValueError('当前模型/任务不支持参数：' + ', '.join(sorted(unknown)))
    result = {}
    for spec in specs:
        value = supplied.get(spec['name'], spec['default'])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(spec['label'] + '必须是有限数值')
        if spec['kind'] == 'int' and not float(value).is_integer():
            raise ValueError(spec['label'] + '必须是整数')
        if not spec['minimum'] <= value <= spec['maximum']:
            raise ValueError('%s必须在 %s 到 %s 之间' % (spec['label'], spec['minimum'], spec['maximum']))
        result[spec['name']] = int(value) if spec['kind'] == 'int' else float(value)
    if kind == 'lightgbm' and result['num_leaves'] > 2 ** result['max_depth']:
        raise ValueError('最大叶子数不能超过 2 的最大树深次方')
    return result
