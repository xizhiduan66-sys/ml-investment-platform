"""特征矩阵的相关性。输入由调用方按评价区间切好，本模块不读切分规则。"""
import pandas as pd


def _safe(value):
    return None if pd.isna(value) else float(value)


def correlation(features, method='spearman'):
    """特征间相关矩阵；单特征时返回 1×1 平凡矩阵。"""
    if not isinstance(features, pd.DataFrame):
        raise ValueError('相关性计算需要特征矩阵')
    if features.empty:
        raise ValueError('特征矩阵为空，无法计算相关性')
    corr = features.corr(method=method)
    return {
        'columns': [str(c) for c in corr.columns],
        'values': [[_safe(v) for v in row] for row in corr.values],
    }
