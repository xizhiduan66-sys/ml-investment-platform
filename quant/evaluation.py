"""Model-only diagnostics. Baselines are fitted on training labels, never on test data."""
import numpy as np
import pandas as pd
from sklearn.metrics import (mean_absolute_error, mean_squared_error, r2_score,
                             roc_auc_score, average_precision_score, log_loss,
                             brier_score_loss, confusion_matrix, roc_curve,
                             precision_recall_curve)

VERSION = 'model-diagnostics-v1'
CLASSIFICATION_THRESHOLD = .5


def number(value):
    return float(value) if value is not None and np.isfinite(value) else None


def pairs(y, pred, task):
    y, pred = np.asarray(y, dtype=float), np.asarray(pred, dtype=float)
    if y.ndim != 1 or pred.shape != y.shape or not len(y):
        raise ValueError('模型评价需要非空且一一对应的标签与预测')
    if not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise ValueError('模型评价不接受非有限标签或预测')
    if task not in ('regression', 'binary'):
        raise ValueError('不支持的评价任务')
    if task == 'binary' and (not np.isin(y, [0, 1]).all() or ((pred < 0) | (pred > 1)).any()):
        raise ValueError('二分类标签必须为 0/1，预测必须为 [0,1] 概率')
    return y, pred


def metrics(y, pred, task, threshold=CLASSIFICATION_THRESHOLD):
    y, pred = pairs(y, pred, task)
    if task == 'regression':
        varying = len(y) > 1 and np.ptp(y) > 0
        correlated = varying and np.ptp(pred) > 0
        return {
            'mae': number(mean_absolute_error(y, pred)),
            'rmse': number(np.sqrt(mean_squared_error(y, pred))),
            'r2': number(r2_score(y, pred)) if varying else None,
            'pearson': number(np.corrcoef(y, pred)[0, 1]) if correlated else None,
            'spearman': number(pd.Series(y).corr(pd.Series(pred), method='spearman')) if correlated else None,
            'direction_accuracy': float(np.mean(np.sign(y) == np.sign(pred))),
            'bias': number(np.mean(pred - y)),
        }
    if not 0 <= threshold <= 1:
        raise ValueError('分类评价阈值必须在 [0,1] 内')
    negative, positive = int((y == 0).sum()), int((y == 1).sum())
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(y, pred >= threshold, labels=[0, 1]).ravel()]
    return {
        'auc': number(roc_auc_score(y, pred)) if negative and positive else None,
        'average_precision': number(average_precision_score(y, pred)) if negative and positive else None,
        'log_loss': number(log_loss(y, np.clip(pred, 1e-7, 1 - 1e-7), labels=[0, 1])),
        'brier': number(brier_score_loss(y, pred)),
        'accuracy': (tn + tp) / len(y),
        'precision': tp / (tp + fp) if tp + fp else None,
        'recall': tp / (tp + fn) if tp + fn else None,
        'specificity': tn / (tn + fp) if tn + fp else None,
        'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        'positive_rate': positive / len(y),
        'predicted_positive_rate': (tp + fp) / len(y),
        'confusion': {'tn': tn, 'fp': fp, 'fn': fn, 'tp': tp},
    }


def sampled_points(x, y, limit=200):
    ids = np.unique(np.linspace(0, len(x) - 1, min(limit, len(x)), dtype=int))
    return [{'x': float(x[i]), 'y': float(y[i])} for i in ids]


def calibration(y, pred):
    bins = []
    assignments = np.minimum((pred * 10).astype(int), 9)
    for i in range(10):
        mask = assignments == i
        if not mask.any():
            continue
        bins.append({'lower': i / 10, 'upper': (i + 1) / 10, 'count': int(mask.sum()),
                     'prediction_mean': float(pred[mask].mean()), 'actual_rate': float(y[mask].mean())})
    return bins


def charts(y, pred, task):
    if task == 'binary':
        bins = calibration(y, pred)
        out = {'calibration': bins, 'ece': sum(b['count'] * abs(b['actual_rate'] - b['prediction_mean']) for b in bins) / len(y),
               'roc': [], 'pr': []}
        if len(np.unique(y)) == 2:
            fpr, tpr, _ = roc_curve(y, pred)
            precision, recall, _ = precision_recall_curve(y, pred)
            out.update(roc=sampled_points(fpr, tpr), pr=sampled_points(recall, precision))
        return out
    residual = pred - y
    count, edges = np.histogram(residual, bins=12)
    return {'scatter': sampled_points(y, pred, 300),
            'residual_histogram': [{'lower': float(edges[i]), 'upper': float(edges[i + 1]), 'count': int(n)} for i, n in enumerate(count)],
            'residual_quantiles': {str(q): number(np.quantile(residual, q)) for q in [.05, .25, .5, .75, .95]},
            'absolute_error_p95': number(np.quantile(np.abs(residual), .95))}


def report(task, samples, model_diagnostics):
    """samples maps train/valid/test to y, pred and decision-time dates."""
    train_y, _ = pairs(samples['train']['y'], samples['train']['pred'], task)
    constant = float(train_y.mean())
    baselines = {'train_mean': constant, 'zero': 0.} if task == 'regression' else {'train_prevalence': constant}
    result = {'version': VERSION, 'task': task, 'classification_threshold': CLASSIFICATION_THRESHOLD,
              'baselines': baselines, 'splits': {}, 'model': model_diagnostics,
              'notes': ['基线只使用训练标签估计；各分区使用同一批有效样本进行模型与基线对照。',
                        '时间分段是固定模型的分段诊断，不是滚动重训练；相邻多步标签可能重叠，未提供独立样本显著性结论。',
                        '验证集用于诊断和方案选择；测试集用于最终评价，反复据此修改方案会影响其独立性。']}
    if task == 'binary':
        result['notes'].append('分类阈值固定为 0.5，与交易开仓门槛无关；AP 为 Average Precision，不是梯形积分 PR-AUC。')
    for split, sample in samples.items():
        y, pred = pairs(sample['y'], sample['pred'], task)
        dates = list(map(str, sample['dates']))
        if len(dates) != len(y):
            raise ValueError('评价日期与样本数量不一致')
        score = metrics(y, pred, task)
        base_scores = {name: metrics(y, np.full(len(y), value), task) for name, value in baselines.items()}
        key, base_key = ('rmse', 'train_mean') if task == 'regression' else ('log_loss', 'train_prevalence')
        denominator = base_scores[base_key][key]
        improvement = 1 - score[key] / denominator if denominator and score[key] is not None else None
        segments = []
        for ids in np.array_split(np.arange(len(y)), min(4, max(1, len(y) // 20))):
            segments.append({'start': dates[ids[0]], 'end': dates[ids[-1]], 'count': len(ids),
                             'metrics': metrics(y[ids], pred[ids], task)})
        result['splits'][split] = {'count': len(y), 'start': dates[0], 'end': dates[-1],
                                  'metrics': score, 'baseline_metrics': base_scores,
                                  'baseline_improvement': number(improvement), 'primary_metric': key,
                                  'charts': charts(y, pred, task), 'segments': segments,
                                  'warnings': (['标签只有一个类别，AUC/AP 不定义。'] if task == 'binary' and len(np.unique(y)) < 2 else [])}
    return result
