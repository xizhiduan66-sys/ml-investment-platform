"""Prediction-to-position policies. No training, persistence or execution logic."""
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ThresholdPolicy:
    task: str
    threshold: float

    def weights(self, predictions):
        if self.task not in ('regression', 'binary'):
            raise ValueError('阈值策略不支持当前预测语义')
        if not math.isfinite(self.threshold):
            raise ValueError('阈值必须为有限数值')
        if self.task == 'binary' and not 0 <= self.threshold <= 1:
            raise ValueError('二分类阈值必须在 0 到 1 之间')
        values = np.asarray(predictions, dtype=float)
        if np.isinf(values).any():
            raise ValueError('预测不能为无穷大')
        if self.task == 'binary' and np.any(np.isfinite(values) & ((values < 0) | (values > 1))):
            raise ValueError('二分类预测必须为概率')
        return (np.isfinite(values) & (values > self.threshold)).astype(float)

    def definition(self):
        return {'id': 'threshold_long_flat', 'version': 1, 'task': self.task,
                'threshold': self.threshold, 'missing': 'flat', 'execution': 'next_open'}


def bar_positions(df, rows, policy):
    if not rows:
        raise ValueError('实验没有样本外预测')
    indices, predictions = [], []
    for row in rows:
        index = row.get('bar_index')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(df) - 1:
            raise ValueError('预测索引无效或之后没有可成交 K 线')
        indices.append(index)
        predictions.append(row.get('prediction') if row.get('valid_prediction', True) else None)
    if len(set(indices)) != len(indices):
        raise ValueError('预测 K 线索引重复')
    signal = pd.Series(0., index=df.index, dtype='float64')
    signal.iloc[indices] = policy.weights(predictions)
    return signal, min(indices), max(indices) + 1
