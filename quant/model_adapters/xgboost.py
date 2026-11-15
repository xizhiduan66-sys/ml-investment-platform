import warnings
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from ..contracts import FittedModel

def fit(kind, task, xtrain, ytrain, xvalid, yvalid, epochs, progress, seed, params):
    from xgboost import XGBRegressor, XGBClassifier
    cls = XGBRegressor if task == 'regression' else XGBClassifier
    estimator = cls(**params, random_state=seed, n_jobs=2, tree_method='hist', objective='reg:squarederror' if task == 'regression' else 'binary:logistic', eval_metric='rmse' if task == 'regression' else 'logloss')
    scaler = StandardScaler().set_output(transform='pandas').fit(xtrain)
    (tx, vx) = [scaler.transform(x) for x in (xtrain, xvalid)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        estimator.fit(tx, ytrain, eval_set=[(tx, ytrain), (vx, yvalid)], verbose=False)
    model = make_pipeline(scaler, estimator)
    predict = estimator.predict if task == 'regression' else lambda x: estimator.predict_proba(x)[:, 1]

    def infer(x):
        return np.asarray(predict(scaler.transform(x)))
    history = []
    detail = {'kind': kind, 'seed': seed, 'parameters': params, 'warnings': [str(w.message) for w in caught], 'selection': '固定超参数，不用测试集选模型'}
    metric = 'rmse' if task == 'regression' else 'binary_logloss' if kind == 'lightgbm' else 'logloss'
    curves = estimator.evals_result()
    train_history = curves['validation_0'][metric]
    valid_history = curves['validation_1'][metric]
    booster = estimator.get_booster()
    (gain_scores, split_scores) = (booster.get_score(importance_type='total_gain'), booster.get_score(importance_type='weight'))
    gain = [float(gain_scores.get(name, 0.0)) for name in booster.feature_names]
    splits = [int(split_scores.get(name, 0)) for name in booster.feature_names]
    iterations = booster.num_boosted_rounds()
    history = [{'epoch': i + 1, 'train': float(a), 'valid': float(b)} for (i, (a, b)) in enumerate(zip(train_history, valid_history))]
    detail.update(gain_importance=gain, split_importance=splits, iterations=iterations, validation_best_iteration=int(np.argmin(valid_history)) + 1, history_metric=metric, history_unit='收益率原始尺度' if task == 'regression' else '交叉熵', selection=f"固定最多 {params['n_estimators']} 轮，无早停；验证最优轮次仅作诊断，不替换最终模型。")
    return FittedModel(model, history, detail, infer)
