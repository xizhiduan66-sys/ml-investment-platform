"""Explicit backend registration. Importing this module does not import ML runtimes."""
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import Callable


@lru_cache(maxsize=None)
def dependency_available(name):
    if not name:
        return True
    try:
        if name in ('lightgbm', 'xgboost'):
            from .native_runtime import prepare_openmp
            try:
                prepare_openmp()
            except OSError:
                pass  # A separately installed system runtime may still work.
        import_module(name)
        return True
    except Exception:  # Optional native runtimes may raise their own load-error classes.
        return False


@dataclass(frozen=True)
class ModelAdapter:
    id: str
    input_layout: str
    tasks: tuple
    dependency: str
    trainer: Callable
    parameter_schema: Callable
    metadata: dict

    def available(self):
        return dependency_available(self.dependency)

    def catalog_entry(self):
        return {**self.metadata, 'id': self.id, 'input': self.input_layout,
                'tasks': list(self.tasks), 'available': self.available(),
                'parameters': {task: self.parameter_schema(task) for task in self.tasks}}

    def fit(self, task, xtrain, ytrain, xvalid, yvalid, epochs, progress,
            seed=42, model_params=None):
        from .. import model_config
        if task not in self.tasks:
            raise ValueError('模型不支持当前学习任务')
        if not self.available():
            raise ValueError('模型依赖不可用：' + self.id)
        expected = {'vector': 2, 'sequence': 3}[self.input_layout]
        if xtrain.ndim != expected or xvalid.ndim != expected or xtrain.shape[1:] != xvalid.shape[1:]:
            raise ValueError('模型输入布局或特征维度不一致')
        params = model_config.resolve(self.id, task, model_params)
        return self.trainer(self.id, task, xtrain, ytrain, xvalid, yvalid,
                            epochs, progress, seed, params)


_ADAPTERS = {}


def register(adapter):
    if not isinstance(adapter, ModelAdapter) or adapter.input_layout not in ('vector', 'sequence'):
        raise ValueError('无效的模型适配器')
    if not adapter.tasks or not set(adapter.tasks) <= {'regression', 'binary'}:
        raise ValueError('不支持的学习任务')
    if adapter.id in _ADAPTERS:
        raise ValueError('模型已注册：' + adapter.id)
    _ADAPTERS[adapter.id] = adapter


def get_adapter(kind):
    if kind not in _ADAPTERS:
        raise ValueError('未知模型：' + kind)
    return _ADAPTERS[kind]


def adapters():
    return tuple(_ADAPTERS.values())


def _trainer(module):
    def train(*args):
        return import_module('.' + module, __name__).fit(*args)
    return train


def _schema(kind):
    def schema(task):
        from .parameters import schema as builtin_schema
        return builtin_schema(kind, task)
    return schema


def _register_builtins():
    from .catalog import entries
    for item in entries():
        kind, layout = item['id'], item['input']
        metadata = {key: value for key, value in item.items() if key not in ('id', 'input', 'tasks')}
        metadata.update(group='sequence' if layout == 'sequence' else 'tree', recommended=kind == 'lightgbm')
        register(ModelAdapter(kind, layout, tuple(item['tasks']),
                              'torch' if layout == 'sequence' else kind,
                              _trainer('recurrent' if layout == 'sequence' else kind),
                              _schema(kind), metadata))


_register_builtins()
