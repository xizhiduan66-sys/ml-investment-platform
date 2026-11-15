"""因子库：声明式因子、参数校验、特征清单与评价。"""
from .spec import FactorSpec, ParamSpec, canonical_params, feature_id
from .registry import factor, register, spec, specs, families, spec_catalog
from .context import FactorContext
from .plugins import load_plugins

load_plugins()

# 兼容旧前端：recipe -> 显示名/分类/描述/默认参数
RECIPES = {
    s.id: {
        "name": s.name,
        "family": s.family,
        "category": s.family,
        "description": s.description,
        "default": s.params[0].default if s.params else None,
    }
    for s in specs().values()
}

from .library import compute, matrix, resolve, compute_event, event_matrix, event_value_key  # noqa: E402
from .manifest import FeatureEntry, FeatureManifest, build_manifest  # noqa: E402
from .analysis import correlation  # noqa: E402

__all__ = [
    "FactorSpec", "ParamSpec", "canonical_params", "feature_id",
    "factor", "register", "spec", "specs", "families", "spec_catalog",
    "FactorContext", "RECIPES", "compute", "matrix", "resolve",
    "FeatureEntry", "FeatureManifest", "build_manifest",
    "correlation", "compute_event", "event_matrix", "event_value_key",
]
