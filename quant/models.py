"""Public model facade. Backends are registered adapters, independent of research tasks."""
from .model_adapters import get_adapter, register, adapters


def dependency_status():
    return {a.dependency: a.available() for a in adapters()}


def is_sequence(kind):
    return get_adapter(kind).input_layout == 'sequence'


def registry():
    return [adapter.catalog_entry() for adapter in adapters()]


def fit(kind, task, xtrain, ytrain, xvalid, yvalid, epochs, progress,
        seed=42, model_params=None):
    adapter = get_adapter(kind)
    return adapter.fit(task, xtrain, ytrain, xvalid, yvalid, epochs, progress,
                       seed=seed, model_params=model_params)


def fit_predict(kind, task, xtrain, ytrain, xvalid, yvalid, xtest, epochs, progress,
                diagnostics=False, seed=42, model_params=None):
    """Compatibility facade for callers using the historical tuple contract."""
    fitted = fit(kind, task, xtrain, ytrain, xvalid, yvalid, epochs, progress,
                 seed=seed, model_params=model_params)
    predictions = {name: fitted.predict(x) for name, x in
                   [('train', xtrain), ('valid', xvalid), ('test', xtest)]}
    result = (predictions['test'], fitted.artifact, fitted.history)
    return (*result, {'predictions': predictions, 'model': fitted.diagnostics}) if diagnostics else result
