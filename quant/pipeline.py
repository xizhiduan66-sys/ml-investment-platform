"""Shared model execution for bar and event research; no persistence or HTTP."""
import numpy as np
from . import models
from .contracts import PreparedDataset, PredictionSet


def train_and_predict(config, task, partitions, progress, seed=42):
    if set(partitions) != {'train', 'valid', 'test'}:
        raise ValueError('必须提供训练、验证和测试分区')
    ids = [set(partitions[name].sample_ids) for name in ('train', 'valid', 'test')]
    if ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2]:
        raise ValueError('样本不能跨分区重复')
    expected = 3 if models.is_sequence(config['model']) else 2
    train, valid = partitions['train'], partitions['valid']
    for dataset in partitions.values():
        if dataset.values.ndim != expected or dataset.values.shape[1:] != train.values.shape[1:]:
            raise ValueError('模型输入布局或特征维度不一致')
        if task == 'binary' and not np.isin(dataset.labels, [0, 1]).all():
            raise ValueError('二分类标签必须为 0 或 1')
    fitted = models.fit(config['model'], task, train.values, train.labels,
                        valid.values, valid.labels, config['epochs'], progress,
                        seed=seed, model_params=config.get('model_params'))
    output = {name: PredictionSet(dataset.sample_ids, np.asarray(fitted.predict(dataset.values)),
                                 'probability' if task == 'binary' else 'value',
                                 1 if task == 'binary' else None)
              for name, dataset in partitions.items()}
    return fitted, output
