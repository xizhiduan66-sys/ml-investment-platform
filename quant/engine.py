import hashlib
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from . import storage, data, factors, models, backtest, evaluation, targets, triggers, sampling
from . import planning, pipeline, policies, prediction_artifacts, runs
from .execution_reports import trading_rows
from .contracts import PreparedDataset
from .targets import STRUCTURE_CONFIRMATION


def simulate(df, indices, predictions, task, config):
    """Adapt the shared order ledger to the experiment report schema."""
    indices = np.asarray(indices, dtype=int)
    predictions = np.asarray(predictions, dtype=float)
    if not len(indices) or len(indices) != len(predictions) or np.any(np.diff(indices) != 1):
        raise ValueError('回测需要连续且与预测一一对应的样本索引')
    weights = policies.threshold_policy(task, config).weights(predictions)
    signals = pd.Series(0., index=df.index)
    signals.iloc[indices] = weights
    ledger = backtest.run(df, signals, backtest.BacktestConfig(
        initial_cash=1., fee_bps=config['cost_bps'], slippage_bps=0.),
        int(indices[0]), int(indices[-1]) + 1)
    return trading_rows(df, indices, predictions, weights, ledger, config)


def run(experiment_id):
    exp = runs.execution(experiment_id)
    exp['artifact_id'] = experiment_id
    exp['started_at'] = datetime.now(timezone.utc).isoformat()

    def progress(message):
        exp.update(status='running', message=message)
        runs.save_execution(exp)

    try:
        progress('计算因子与目标变量')
        snap = exp['snapshot']
        config, target = snap['config'], snap.get('target', STRUCTURE_CONFIRMATION)
        plan = planning.compile_plan(config, target)
        if snap.get('research_plan', plan) != plan:
            raise ValueError('研究计划与当前执行契约不一致')
        df = data.load(snap['dataset'])
        trigger = triggers.for_config(config)
        event_mode = trigger['kind'] == 'event'
        task = target['task']
        classes = tuple(targets.class_names(target))
        manifest = factors.build_manifest(snap['factors'], snap.get('event_features', ()))
        expected = (snap.get('manifest') or {}).get('hash')
        if expected and expected != manifest.hash:
            raise ValueError('因子清单与实验快照不一致，请基于当前因子重新创建实验')

        sequence = models.is_sequence(config['model'])
        window = config['lookback'] if sequence else 1
        batch, features, labels, partitions = sampling.prepare(df, snap, target, window, progress)
        observations, array, y = batch.bars, features.to_numpy(), labels.values
        test = partitions['test']
        if task == 'binary' and len(np.unique(y[partitions['train']])) < 2:
            raise ValueError('训练标签只有一个类别，请检查目标或增加行情')

        def pack(ids):
            return np.stack([array[i - window + 1:i + 1] for i in ids]) if sequence else array[ids]

        progress('拟合模型（仅使用训练集）')
        inputs = {name: pack(ids) for name, ids in partitions.items()}
        prepared = {name: PreparedDataset(tuple(batch.ids[i] for i in ids), inputs[name], y[ids])
                    for name, ids in partitions.items()}
        trained, predictions = pipeline.train_and_predict(config, task, prepared, progress, classes=classes)
        artifact, history = trained.artifact, trained.history
        fitted = {'predictions': {name: output.values for name, output in predictions.items()},
                  'model': trained.diagnostics}
        samples = {name: {'y': y[ids], 'pred': fitted['predictions'][name], 'dates': df.date.iloc[observations[ids]].tolist()}
                   for name, ids in partitions.items()}
        diagnostics = (evaluation.multiclass_report(samples, fitted['model'], classes) if task == 'multiclass'
                       else evaluation.report(task, samples, fitted['model']))
        diagnostics['features'] = [{'id': e.instance_id, 'name': e.name} for e in manifest.features]
        diagnostics['history'] = history
        repeat_count = config.get('diagnostic_runs', 1) if sequence and task != 'multiclass' else 1
        repeat_scores = [{'seed': 42, 'metrics': diagnostics['splits']['test']['metrics']}]
        for repeat in range(1, repeat_count):
            seed = 42 + repeat
            progress(f'重复训练诊断 {repeat + 1}/{repeat_count} · seed={seed}')
            _, repeat_output = pipeline.train_and_predict(config, target['task'], prepared, progress, seed=seed)
            repeat_pred = repeat_output['test'].values
            repeat_scores.append({'seed': seed, 'metrics': evaluation.metrics(y[test], repeat_pred, target['task'])})
        diagnostics['repeats'] = {'runs': repeat_scores, 'primary_seed': 42,
                                  'note': '固定数据切分与超参数，仅改变随机种子；保留 seed=42 作为主模型，不按测试表现挑选种子。' if repeat_count > 1 else '仅运行一次；尚不能评价随机初始化稳定性。'}
        repeat_metrics = ['mae', 'rmse', 'spearman'] if target['task'] == 'regression' else ['auc', 'log_loss', 'brier']
        diagnostics['repeats']['summary'] = {}
        if repeat_count > 1:
            for key in repeat_metrics:
                values = [r['metrics'][key] for r in repeat_scores if r['metrics'][key] is not None]
                diagnostics['repeats']['summary'][key] = {
                    'count': len(values), 'mean': float(np.mean(values)) if values else None,
                    'std': float(np.std(values, ddof=1)) if len(values) > 1 else None,
                    'min': min(values) if values else None, 'max': max(values) if values else None}
        metrics = diagnostics['splits']['test']['metrics']
        # Keep the legacy scalar summary contract; detailed diagnostics are separate.
        metrics = {k: v for k, v in metrics.items() if not isinstance(v, dict)}
        progress('生成样本外结果')
        output = targets.output(target)
        result = {
            'diagnostics': diagnostics, 'metrics': metrics, 'history': history,
            'feature_manifest': manifest.to_dict(),
            'feature_set': [{'id': e.instance_id, 'feature_id': e.id, 'name': e.name,
                             'version': e.version, 'params': e.params} for e in manifest.features],
            'splits': {name: {'count': len(ids), 'start': df.date.iloc[observations[ids[0]]],
                              'end': df.date.iloc[observations[ids[-1]]]} for name, ids in partitions.items()},
            'output': output,
        }
        prediction_rows = []
        for partition, ids in partitions.items():
            for i, value in zip(ids, fitted['predictions'][partition]):
                bar = int(observations[i])
                values = ({'probabilities': value.tolist(), 'predicted_class': int(value.argmax()),
                           'label': int(y[i])} if task == 'multiclass' else {'prediction': float(value)})
                prediction_rows.append({
                    'sample_id': batch.ids[i], 'bar_index': bar, 'observed_at': str(df.date.iloc[bar]),
                    'split': partition, 'valid_prediction': True, **values,
                })
        result['prediction_artifact'] = prediction_artifacts.publish(
            experiment_id, snap['dataset'], task, triggers.sample_mode(trigger), prediction_rows,
            output=output if config.get('trigger') or task == 'multiclass' else None)
        can_trade = policies.supports_backtest(triggers.sample_mode(trigger), task)
        result['backtest_available'] = can_trade or event_mode or task == 'multiclass'
        test_rows = [row for row in prediction_rows if row['split'] == 'test']
        if event_mode:
            diagnostics['notes'].append('事件按首次可见时间归入分区，标签跨界的样本已剔除。')
            annotated = {row['sample_id']: {'split': row['split'],
                          **({'probabilities': row['probabilities'], 'predicted_class': row['predicted_class']}
                             if task == 'multiclass' else {'prediction': row['prediction']}),
                          'target_label': float(y[i]), 'target_label_time': str(df.date.iloc[labels.ends[i]]),
                          'features': {**batch.report['events'][i]['features'], **features.iloc[i].to_dict()}}
                         for i, row in zip(np.concatenate(list(partitions.values())), prediction_rows)}
            events = batch.report['events']
            for event in events:
                event.update(annotated.get(event['event_id'], {}))
            if triggers.source(trigger) == 'chan' and task != 'multiclass':
                chan_test = [{**events[i], 'label': float(y[i]), 'label_end': int(labels.ends[i]),
                              'label_time': str(df.date.iloc[labels.ends[i]]), 'eligible': True} for i in test]
                result.update(kind='chan_event', rows=chan_test, event_report=batch.report)
            else:
                result.update(kind='event', rows=test_rows, event_report=batch.report)
        else:
            result.update(kind='prediction_only', rows=test_rows)
        artifact_path = storage.ROOT / (experiment_id + '.pkl')
        with artifact_path.open('wb') as f:
            pickle.dump(artifact, f)
        result['artifact'] = artifact_path.name
        (storage.ROOT / (experiment_id + '.json')).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
        exp.update(status='completed', message='实验完成', summary=result['metrics'])
    except Exception as exc:
        exp.update(status='failed', message=f'{type(exc).__name__}: {exc}')
    exp['finished_at'] = datetime.now(timezone.utc).isoformat()
    runs.save_execution(exp)


def code_hash():
    h = hashlib.sha256()
    root = Path(__file__).parent
    for file in sorted(root.rglob('*.py')):
        if '__pycache__' in file.parts:
            continue
        h.update(str(file.relative_to(root)).encode())
        h.update(file.read_bytes())
    return h.hexdigest()
