from dataclasses import dataclass
import hashlib
from typing import Any, Dict, Tuple

from .library import resolve, event_value_key
from .spec import canonical_json, feature_id


@dataclass(frozen=True)
class FeatureEntry:
    id: str
    spec_id: str
    instance_id: str
    name: str
    version: int
    index: int
    dtype: str
    missing: str
    params: Dict[str, Any]

    def to_dict(self):
        return {
            "id": self.id,
            "spec_id": self.spec_id,
            "instance_id": self.instance_id,
            "name": self.name,
            "version": self.version,
            "index": self.index,
            "dtype": self.dtype,
            "missing": self.missing,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class FeatureManifest:
    version: int
    features: Tuple[FeatureEntry, ...]

    @property
    def hash(self):
        payload = [
            {
                "id": f.id,
                "version": f.version,
                "index": f.index,
                "dtype": f.dtype,
                "missing": f.missing,
            }
            for f in self.features
        ]
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()

    def to_dict(self):
        return {
            "version": self.version,
            "hash": self.hash,
            "features": [f.to_dict() for f in self.features],
        }


def build_manifest(instances):
    entries = []
    seen = set()
    for index, record in enumerate(instances):
        factor_spec, params, name, _, version = resolve(record)
        # Keep the existing identity for saved Chan experiment manifests.
        stable = feature_id(factor_spec.id, params)
        if factor_spec.scope == 'event':
            stable = event_value_key(factor_spec, params) if params else f'{factor_spec.id}:v{version}'
        if stable in seen:
            raise ValueError("因子重复：%s（%s）" % (name, stable))
        seen.add(stable)
        entries.append(FeatureEntry(
            id=stable,
            spec_id=factor_spec.id,
            instance_id=record.get("id") or stable,
            name=name,
            version=version,
            index=index,
            dtype="float64",
            missing=factor_spec.missing,
            params=params,
        ))
    return FeatureManifest(version=1, features=tuple(entries))
