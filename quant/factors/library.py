import numpy as np
import pandas as pd

from .context import FactorContext
from .registry import spec as get_spec
from .spec import canonical_params, feature_id


def resolve(record):
    """把 DB 记录（新旧字段都行）解析成 (spec, params, name, category, version)。"""
    if not isinstance(record, dict):
        raise TypeError("因子实例必须是字典")
    spec_id = record.get("spec_id") or record.get("recipe")
    if not spec_id:
        raise ValueError("因子记录缺少 spec_id/recipe")
    factor_spec = get_spec(spec_id)
    params = record.get("params")
    if params is None:
        params = {}
        if record.get("window") is not None:
            params["window"] = record["window"]
    params = canonical_params(factor_spec, params)
    name = record.get("name") or factor_spec.name
    category = record.get("category") or factor_spec.family
    version = factor_spec.version
    stored_version = record.get("version")
    if stored_version is not None:
        try:
            stored_value = int(stored_version)
        except (TypeError, ValueError):
            raise ValueError("因子 %s 的实例版本无效：%s" % (name, stored_version))
        if stored_value != version:
            raise ValueError("因子 %s 的实例版本 %s 与当前算法版本 %s 不一致，请重新创建因子实例" % (name, stored_version, version))
    return factor_spec, params, name, category, version


def compute(df, instance, params=None):
    """计算一个因子序列。

    兼容旧调用 compute(df, "your_factor", 20) 与因子记录 compute(df, record)。
    """
    if isinstance(instance, str):
        factor_spec = get_spec(instance)
        if params is None:
            params = {}
        elif isinstance(params, int):
            params = {"window": params}
        params = canonical_params(factor_spec, params)
    else:
        factor_spec, params, _, _, _ = resolve(instance)

    if factor_spec.scope == 'event':
        raise ValueError(f'「{factor_spec.name}」需要缠论买卖点，请使用事件采样')

    missing_columns = set(factor_spec.requires) - set(df.columns)
    if missing_columns:
        raise ValueError('因子 %s 缺少输入列：%s' % (factor_spec.id, ', '.join(sorted(missing_columns))))
    if factor_spec.scope == "sample":
        values = []
        for t in range(len(df)):
            try:
                values.append(factor_spec.compute(FactorContext(df, t), params))
            except Exception as exc:
                raise ValueError("因子 %s 在样本 %s 失败：%s" % (factor_spec.id, t, exc))
        series = pd.Series(values, index=df.index, dtype="float64")
    else:
        series = factor_spec.compute(df.copy(), params)
        if not isinstance(series, pd.Series):
            raise ValueError("因子 %s 必须返回 pandas.Series" % factor_spec.id)
        if len(series) != len(df):
            raise ValueError("因子 %s 返回长度与行情不一致" % factor_spec.id)
        if not series.index.equals(df.index):
            raise ValueError('因子 %s 返回索引与行情不一致' % factor_spec.id)
        series = series.astype("float64")

    series = series.replace([np.inf, -np.inf], np.nan)
    # nan/drop both preserve alignment; the sample builder drops invalid rows.
    return series.fillna(0.) if factor_spec.missing == 'neutral' else series


def matrix(df, instances):
    """按实例 id 组装特征矩阵；实例 id 缺失时退回稳定特征 ID。"""
    columns = {}
    for record in instances:
        factor_spec, params, _, _, _ = resolve(record)
        key = record.get("id") or feature_id(factor_spec.id, params)
        if key in columns:
            raise ValueError("因子重复：%s" % key)
        columns[key] = compute(df, record)
    return pd.DataFrame(columns, index=df.index)


def event_value_key(factor_spec, params):
    """Keep unparameterized event keys readable in existing replay reports."""
    if not params:
        return factor_spec.id
    return f'{feature_id(factor_spec.id, params)}:v{factor_spec.version}'


def compute_event(instance, context):
    factor_spec, params, _, _, _ = resolve(instance)
    if factor_spec.scope != 'event':
        raise ValueError(f'「{factor_spec.name}」需要行情序列')
    value = factor_spec.compute(context, params)
    if value is None or not np.isfinite(value):
        return 0. if factor_spec.missing == 'neutral' else None
    return float(value)


def event_matrix(df, instances, events):
    """Align ordinary values and frozen event values to the same event rows."""
    columns = {}
    for record in instances:
        factor_spec, params, _, _, _ = resolve(record)
        key = record.get('id') or feature_id(factor_spec.id, params)
        if key in columns:
            raise ValueError('因子重复：%s' % key)
        if factor_spec.scope == 'event':
            value_key = event_value_key(factor_spec, params)
            columns[key] = [event['features'].get(value_key) for event in events]
        else:
            series = compute(df, record)
            columns[key] = series.iloc[[event['observed_at'] for event in events]].to_numpy()
    return pd.DataFrame(columns, index=range(len(events)), dtype='float64')
