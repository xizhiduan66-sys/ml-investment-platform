from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from . import backtest, data, engine, policies, prediction_artifacts, runs, splits, storage, triggers
from .research_inputs import BacktestIn


@dataclass
class PredictionSource:
    experiment: dict
    run_id: str | None
    artifact_id: str
    report: dict
    task: str
    defaults: dict
    sampling: str
    structure: bool


def _prediction_source(experiment_id, run_id):
    experiment = runs.latest(experiment_id)
    if not run_id and experiment.get('status') != 'completed':
        raise ValueError('实验尚未完成')
    run_id = run_id or experiment.get('latest_run_id')
    selected_run = storage.get('run', run_id) if run_id else None
    if selected_run and (selected_run['experiment_id'] != experiment['id'] or selected_run['status'] != 'completed'):
        raise ValueError('运行不属于该实验或尚未完成')
    artifact_id = selected_run.get('artifact_id', selected_run['id']) if selected_run else experiment['id']
    result_path = storage.ROOT / (artifact_id + '.json')
    if not result_path.exists():
        raise ValueError('实验 result 文件不存在')
    experiment_result = json.loads(result_path.read_text())
    execution = experiment_result.get('execution') or {}
    task = (experiment.get('snapshot', {}).get('target') or {}).get('task') or experiment_result.get('output', {}).get('task') or 'binary'
    trigger = triggers.for_config(experiment['snapshot']['config'])
    band = task == 'multiclass' and experiment_result.get('output', {}).get('classes') == ['下跌', '横盘', '上涨']
    if task not in ('binary', 'regression') and not band:
        raise ValueError('多分类交易需要下跌、横盘、上涨三个有序类别')
    sampling = triggers.sample_mode(trigger)
    target = experiment['snapshot'].get('target') or {}
    structure = target.get('kind') == 'chan_structure'
    defaults = asdict(backtest.BacktestConfig())
    defaults.update(fee_bps=experiment['snapshot']['config'].get('cost_bps', 5.), slippage_bps=0.)
    defaults.update({key: execution[key] for key in defaults if execution.get(key) is not None})
    if sampling != 'bar':
        defaults['max_hold_bars'] = target.get('horizon') or 0
    defaults['threshold'] = policies.threshold_policy(
        task, experiment['snapshot']['config'], (experiment_result.get('strategy') or {}).get('threshold')
    ).threshold
    return PredictionSource(experiment, run_id, artifact_id, experiment_result, task, defaults, sampling, structure)


def settings(experiment_id, run_id):
    return _prediction_source(experiment_id, run_id).defaults


def create(inp: BacktestIn):
    prediction = _prediction_source(inp.experiment_id, inp.run_id)
    experiment, task, defaults = prediction.experiment, prediction.task, prediction.defaults
    dataset = experiment['snapshot']['dataset']
    df = data.load(dataset)
    threshold = defaults['threshold'] if inp.threshold is None else inp.threshold
    if (inp.strategy == 'return_band') != (task == 'multiclass'):
        raise ValueError('收益分档概率策略需要匹配多分类实验')
    if (inp.strategy == 'structure_confirmation') != prediction.structure:
        raise ValueError('结构确认策略需要匹配结构确认实验')
    if inp.strategy in ('long_flat', 'structure_confirmation'):
        if inp.short_threshold is not None:
            raise ValueError('当前策略只接受一个预测阈值')
        policy = policies.ThresholdPolicy(task, threshold)
    else:
        if inp.short_threshold is None:
            raise ValueError('请设置做空阈值')
        policy = policies.DirectionalPolicy(task, threshold, inp.short_threshold)
    reference = prediction.report.get('prediction_artifact')
    if reference:
        rows = prediction_artifacts.load(reference, prediction.artifact_id, dataset, task, sampling=prediction.sampling)
    elif prediction.sampling != 'bar':
        raise ValueError('缺少样本外事件预测产物')
    else:
        rows = prediction.report.get('rows') or []
    source = {'kind': 'experiment', 'experiment_id': experiment['id'], 'experiment_name': experiment.get('name'), 'run_id': prediction.run_id, 'threshold': float(threshold),
              'strategy': policy.definition(),
              'prediction_artifact': reference}

    defaults.pop('threshold')
    overrides = inp.model_dump(include=set(defaults), exclude_none=True)
    config = backtest.BacktestConfig(**{**defaults, **overrides})
    if prediction.sampling == 'bar':
        signal, start, end = policies.bar_positions(df, rows, policy)
        result = backtest.run(df, signal, config, start, end)
    else:
        if not (config.max_hold_bars or config.stop_loss_pct or config.take_profit_pct):
            raise ValueError('事件回测至少设置一个平仓条件')
        start, stop = splits.bounds(len(df), 'test')
        events = None
        if prediction.structure:
            events = {event['event_id']: event for event in prediction.report['event_report']['events']}
            source['strategy'].update(id='structure_confirmation', direction='event_side')
        entries = policies.event_entries(rows, policy, start, stop - 1, events)
        source['strategy'].update(sampling=prediction.sampling, holding='ignore_new_events',
                                  simultaneous='merge_same_direction_skip_conflict')
        result = backtest.run(df, [0.] * len(df), config, start, stop - 1, event_entries=entries)
    symbol = (dataset.get('name') or '标的').split(' · ')[0]
    trades = result.get('trades') or []
    directions = {t['direction'] for t in trades}
    holding = {
        'symbol': symbol,
        'name': symbol,
        'direction': '多空' if len(directions) == 2 else {'long': '多头', 'short': '空头'}.get(next(iter(directions), None), '空仓'),
        'trade_count': len(trades),
        'realized_pnl': float(sum(t['pnl'] for t in trades)),
        'market_value': 0.0,
        'margin': 0.0,
        'fees': float(result['metrics']['total_fees']),
    }
    result['holding'] = holding
    result['instruments'] = [holding]
    dataset_snapshot = {k: dataset[k] for k in ('id', 'name', 'sha256', 'rows', 'start', 'end', 'file') if k in dataset}
    if dataset.get('experiment_id'):
        dataset_snapshot.pop('file', None)
    record = storage.save('backtest', {
        'name': inp.name,
        'status': 'completed',
        'source': source,
        'dataset': dataset_snapshot,
        'config': result['config'],
        'engine_version': backtest.ENGINE_VERSION,
        'code_hash': engine.code_hash(),
        'metrics': result['metrics'],
        'period': result['period'],
    })
    payload = {**record, 'result': result}
    (storage.ROOT / (record['id'] + '.json')).write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    return payload
