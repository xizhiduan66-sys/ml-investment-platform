"""Common point-in-time feature, label and chronological split pipeline."""
import numpy as np

from . import factors, splits, targets, triggers


def partitions(indices, bars, ends, n):
    indices = np.asarray(indices, dtype=int)
    observed, ready = bars[indices], ends[indices]
    result = {}
    for name in ('train', 'valid', 'test'):
        lo, hi = splits.bounds(n, name)
        result[name] = indices[(observed >= lo) & (observed < hi) & (ready >= observed) & (ready < hi)]
    return result


def prepare(df, snapshot, target, window, progress):
    observations = triggers.collect(df, snapshot, progress)
    events = None if observations.report is None else observations.report['events']
    records = snapshot['factors']
    matrix = factors.matrix(df, records) if events is None else factors.event_matrix(df, records, events)
    array = matrix.to_numpy()
    labels = targets.calculate(df, target, observations.bars, events=events)
    valid = np.isfinite(array).all(axis=1)
    if window > 1:
        cumulative = np.r_[0, np.cumsum(~valid)]
        mask = np.zeros(len(valid), dtype=bool)
        if len(valid) >= window:
            mask[window - 1:] = (cumulative[window:] - cumulative[:-window]) == 0
        valid = mask
    indices = np.flatnonzero(valid & (labels.ends >= 0) & np.isfinite(labels.values))
    if window > 1 and len(indices) * window * len(records) > 8000000:
        raise ValueError('序列样本超过初版内存预算，请减少行情长度、窗口或因子数')
    groups = partitions(indices, observations.bars, labels.ends, len(df))
    counts = {name: len(ids) for name, ids in groups.items()}
    if counts['train'] < 80 or min(counts.values()) < 30:
        raise ValueError(f'有效样本不足（训练至少 80，验证和测试各至少 30）：{counts}。')
    return observations, matrix, labels, groups
