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


@dataclass(frozen=True)
class DirectionalPolicy:
    task: str
    threshold: float
    short_threshold: float

    def __post_init__(self):
        if self.task in ('binary', 'multiclass') and not (
                0 <= self.threshold <= 1 and 0 <= self.short_threshold <= 1):
            raise ValueError('概率阈值必须在 0 到 1 之间')
        if self.task != 'multiclass' and self.short_threshold > self.threshold:
            raise ValueError('做空阈值不能高于做多阈值')

    def weights(self, predictions):
        if self.task == 'multiclass':
            weights = []
            for value in predictions:
                if value is None:
                    weights.append(0)
                    continue
                probs = np.asarray(value, dtype=float)
                if probs.shape != (3,) or np.any(probs < 0) or not np.isclose(probs.sum(), 1):
                    raise ValueError('收益分档预测需要下跌、横盘、上涨的有效概率')
                down, flat, up = probs
                if up > max(flat, down, self.threshold):
                    weights.append(1)
                elif down > max(flat, up, self.short_threshold):
                    weights.append(-1)
                else:
                    weights.append(0)
            return np.asarray(weights)
        longs = ThresholdPolicy(self.task, self.threshold).weights(predictions)
        values = np.asarray(predictions, dtype=float)
        return longs - (values < self.short_threshold).astype(float)

    def definition(self):
        return {'id': 'return_band' if self.task == 'multiclass' else 'long_short',
                'task': self.task, 'threshold': self.threshold, 'short_threshold': self.short_threshold,
                'missing': 'flat', 'execution': 'next_open', 'version': 1}


def supports_backtest(sample_mode, task):
    return sample_mode == 'bar' and task in ('regression', 'binary')


def threshold_policy(task, config, threshold=None):
    if threshold is None:
        key = 'entry_threshold' if task == 'regression' else 'probability_threshold'
        threshold = config.get(key)
    if threshold is None:
        threshold = 0.0 if task == 'regression' else 0.55
    return ThresholdPolicy(task, float(threshold))


def bar_positions(df, rows, policy):
    if not rows:
        raise ValueError('实验没有样本外预测')
    indices, predictions = [], []
    for row in rows:
        index = row.get('bar_index')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(df) - 1:
            raise ValueError('预测索引无效或之后没有可成交 K 线')
        indices.append(index)
        key = 'probabilities' if policy.task == 'multiclass' else 'prediction'
        predictions.append(row.get(key) if row.get('valid_prediction', True) else None)
    if len(set(indices)) != len(indices):
        raise ValueError('预测 K 线索引重复')
    signal = pd.Series(0., index=df.index, dtype='float64')
    signal.iloc[indices] = policy.weights(predictions)
    return signal, min(indices), max(indices) + 1
