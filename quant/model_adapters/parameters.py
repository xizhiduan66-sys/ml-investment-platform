"""Built-in model parameter schemas."""
def parameter(name, label, default, minimum, maximum, kind='float'):
    return {'name': name, 'label': label, 'default': default, 'minimum': minimum, 'maximum': maximum, 'kind': kind}


def schema(kind, task):
    if task not in ('regression', 'binary', 'multiclass'):
        raise ValueError('不支持的学习任务')
    if kind == 'lightgbm':
        return [parameter('n_estimators', '最大迭代轮数', 100, 10, 1000, 'int'),
                parameter('max_depth', '最大树深', 4, 2, 16, 'int'),
                parameter('num_leaves', '最大叶子数', 15, 2, 256, 'int'),
                parameter('learning_rate', '学习率', .03, .0001, 1.)]
    if kind == 'xgboost':
        return [parameter('n_estimators', '迭代轮数', 100, 10, 1000, 'int'),
                parameter('max_depth', '最大树深', 4, 2, 16, 'int'),
                parameter('learning_rate', '学习率', .03, .0001, 1.),
                parameter('subsample', '训练样本采样比例', 1., .1, 1.),
                parameter('colsample_bytree', '每棵树特征采样比例', 1., .1, 1.)]
    if kind in ('lstm', 'gru'):
        return [parameter('learning_rate', '学习率', .001, .00001, .1),
                parameter('batch_size', '批大小', 64, 8, 256, 'int'),
                parameter('hidden_size', kind.upper() + ' 隐藏维度', 24, 4, 128, 'int')]
    raise ValueError('未知模型')


