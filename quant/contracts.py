"""Versioned contracts shared by research planning and model execution."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
import numpy as np


@dataclass
class FittedModel:
    artifact: Any
    history: list
    diagnostics: dict
    predict: Callable


@dataclass(frozen=True)
class PreparedDataset:
    sample_ids: tuple
    values: np.ndarray
    labels: np.ndarray

    def __post_init__(self):
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError('样本 ID 不能重复')
        if len(self.sample_ids) != len(self.values) or len(self.labels) != len(self.values):
            raise ValueError('样本、输入和标签必须一一对应')
        if self.values.ndim not in (2, 3) or not len(self.values):
            raise ValueError('模型输入必须是非空向量或序列样本')
        if self.labels.ndim != 1 or not np.isfinite(self.values).all() or not np.isfinite(self.labels).all():
            raise ValueError('训练输入和标签必须是有限数值')


@dataclass(frozen=True)
class PredictionSet:
    sample_ids: tuple
    values: np.ndarray
    semantic: str
    positive_class: int | None = None

    def __post_init__(self):
        if self.values.shape != (len(self.sample_ids),) or not np.isfinite(self.values).all():
            raise ValueError('预测必须与样本对应且为有限数值')
        if self.semantic == 'probability' and (self.positive_class != 1 or
                np.any((self.values < 0) | (self.values > 1))):
            raise ValueError('二分类输出必须是类别 1 的概率')
