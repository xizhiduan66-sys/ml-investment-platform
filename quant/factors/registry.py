from typing import Dict

from .spec import FactorSpec

_SPECS: Dict[str, FactorSpec] = {}


def register(factor_spec):
    if not isinstance(factor_spec, FactorSpec):
        raise TypeError("register 需要 FactorSpec")
    if factor_spec.compute is None:
        raise ValueError("因子 %s 缺少 compute" % factor_spec.id)
    if factor_spec.scope not in ('series', 'sample', 'event'):
        raise ValueError('不支持的因子 scope')
    if factor_spec.missing not in ('nan', 'neutral', 'drop'):
        raise ValueError('不支持的缺失策略')
    if factor_spec.output != 'float':
        raise ValueError('当前因子输出仅支持 float')
    if factor_spec.id in _SPECS:
        raise ValueError("因子 %s 已注册" % factor_spec.id)
    _SPECS[factor_spec.id] = factor_spec
    return factor_spec


def factor(id, name, family, description, params=(), scope="series", output="float",
           missing="nan", requires=(), version=1, event_source=None, default_note="", validate_params=None):
    """注册装饰器：@factor(...) 后函数签名按要求实现。"""
    def decorator(fn):
        register(FactorSpec(
            id=id,
            name=name,
            family=family,
            description=description,
            version=version,
            params=tuple(params),
            scope=scope,
            output=output,
            missing=missing,
            requires=tuple(requires),
            compute=fn,
            event_source=event_source,
            default_note=default_note,
            validate_params=validate_params,
        ))
        return fn
    return decorator


def spec(spec_id):
    if spec_id not in _SPECS:
        raise ValueError("未知因子：%s" % spec_id)
    return _SPECS[spec_id]


def specs():
    return dict(_SPECS)


def families():
    return sorted({s.family for s in _SPECS.values()})


def spec_catalog():
    return [s.to_dict() for s in _SPECS.values()]
