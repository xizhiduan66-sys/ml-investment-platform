from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class ParamSpec:
    """一个因子参数的声明：类型、默认值、范围与说明。"""

    name: str
    kind: str = "int"  # int / float / bool / str / enum
    default: Any = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    options: Tuple[str, ...] = ()
    description: str = ""

    def validate(self, value):
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("参数 %s 必须是整数" % self.name)
            value = int(value)
        elif self.kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("参数 %s 必须是数值" % self.name)
            value = float(value)
        elif self.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError("参数 %s 必须是布尔值" % self.name)
        elif self.kind == "str":
            if not isinstance(value, str):
                raise ValueError("参数 %s 必须是字符串" % self.name)
        elif self.kind == "enum":
            if value not in self.options:
                raise ValueError("参数 %s 必须是 %s 之一" % (self.name, list(self.options)))
        else:
            raise ValueError("参数 %s 的类型 %s 不受支持" % (self.name, self.kind))
        if self.kind in ('int', 'float') and not math.isfinite(value):
            raise ValueError('参数 %s 必须是有限数值' % self.name)
        if self.minimum is not None and value < self.minimum:
            raise ValueError("参数 %s 不能小于 %s" % (self.name, self.minimum))
        if self.maximum is not None and value > self.maximum:
            raise ValueError("参数 %s 不能大于 %s" % (self.name, self.maximum))
        return value


@dataclass(frozen=True)
class FactorSpec:
    """因子的稳定声明。id 与参数共同决定特征身份。"""

    id: str
    name: str
    family: str
    description: str
    version: int = 1
    params: Tuple[ParamSpec, ...] = ()
    scope: str = "series"  # series / sample
    output: str = "float"
    missing: str = "nan"  # nan / neutral / drop
    requires: Tuple[str, ...] = ()
    compute: Optional[Callable[..., Any]] = field(default=None, compare=False, repr=False)

    def param_schema(self):
        return param_schema(self.params)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "family": self.family,
            "description": self.description,
            "version": self.version,
            "scope": self.scope,
            "output": self.output,
            "missing": self.missing,
            "requires": list(self.requires),
            "params": param_schema(self.params),
        }


def param_schema(params):
    return [
        {
            "name": p.name,
            "kind": p.kind,
            "default": p.default,
            "minimum": p.minimum,
            "maximum": p.maximum,
            "options": list(p.options),
            "description": p.description,
        }
        for p in params
    ]


def canonical_params(spec, params):
    """合并默认值、拒绝未知参数、按声明范围校验。"""
    params = dict(params or {})
    known = {p.name for p in spec.params}
    unknown = set(params) - known
    if unknown:
        raise ValueError("因子 %s 不支持参数：%s" % (spec.id, ", ".join(sorted(unknown))))
    merged = {}
    for p in spec.params:
        value = params.get(p.name, p.default)
        if value is None:
            raise ValueError("因子 %s 缺少参数 %s" % (spec.id, p.name))
        merged[p.name] = p.validate(value)
    return merged


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def feature_id(spec_id, params):
    """稳定特征 ID：算法 + 规范化参数，与实例 id、显示名无关。"""
    digest = hashlib.sha256(canonical_json({"spec": spec_id, "params": params}).encode()).hexdigest()[:8]
    return "%s:%s" % (spec_id, digest)
