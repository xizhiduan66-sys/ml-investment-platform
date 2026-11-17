import warnings
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from ..contracts import FittedModel

def fit(kind, task, xtrain, ytrain, xvalid, yvalid, epochs, progress, seed, params):
    from lightgbm import LGBMRegressor, LGBMClassifier
    cls = LGBMRegressor if task == 'regression' else LGBMClassifier
    estimator = cls(**params, verbosity=-1, random_state=seed, n_jobs=2)
    scaler = StandardScaler().set_output(transform='pandas').fit(xtrain)
    (tx, vx) = [scaler.transform(x) for x in (xtrain, xvalid)]
    metric = {'regression': 'rmse', 'binary': 'binary_logloss', 'multiclass': 'multi_logloss'}[task]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        estimator.fit(tx, ytrain, eval_set=[(tx, ytrain), (vx, yvalid)], eval_names=['train', 'valid'], eval_metric=metric)
    model = make_pipeline(scaler, estimator)

    def infer(x):
        transformed = scaler.transform(x)
        if task == 'regression':
            return np.asarray(estimator.predict(transformed))
        probabilities = estimator.predict_proba(transformed)
        return probabilities[:, 1] if task == 'binary' else probabilities
    history = []
    detail = {'kind': kind, 'seed': seed, 'parameters': params, 'warnings': [str(w.message) for w in caught], 'selection': '固定超参数，不用测试集选模型'}
    train_history = estimator.evals_result_['train'][metric]
    valid_history = estimator.evals_result_['valid'][metric]
    gain = estimator.booster_.feature_importance(importance_type='gain').astype(float).tolist()
    splits = estimator.booster_.feature_importance(importance_type='split').astype(int).tolist()
    iterations = int(estimator.booster_.current_iteration())
    history = [{'epoch': i + 1, 'train': float(a), 'valid': float(b)} for (i, (a, b)) in enumerate(zip(train_history, valid_history))]
    detail.update(gain_importance=gain, split_importance=splits, iterations=iterations, validation_best_iteration=int(np.argmin(valid_history)) + 1, history_metric=metric, history_unit='收益率原始尺度' if task == 'regression' else '交叉熵', selection=f"固定最多 {params['n_estimators']} 轮，无早停；验证最优轮次仅作诊断，不替换最终模型。")
    return FittedModel(model, history, detail, infer)
