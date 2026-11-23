import importlib.metadata
import shutil
import uuid

from . import event_inputs, engine, evaluation, factors, jobs, market, model_config, models, planning, runs, storage, targets, triggers
from .feature_catalog import feature_records
from .research_inputs import ExperimentIn


def submit(inp: ExperimentIn):
    if inp.submission_key:
        jobs.initialize()
        with storage.connect() as db:
            prior = db.execute('SELECT experiment_id FROM submission_keys WHERE key=?', (inp.submission_key,)).fetchone()
        if prior:
            return runs.latest(prior[0])
    trigger = triggers.request(inp.trigger, inp.sample_mode, inp.event_types)
    sample_mode = triggers.sample_mode(trigger)
    target = targets.get(inp.target_id, inp.target_version, inp.target_params)
    if not models.is_sequence(inp.model) and inp.diagnostic_runs != 1:
        raise ValueError('多随机种子诊断当前仅适用于 LSTM / GRU')
    model = next((m for m in models.registry() if m['id'] == inp.model), None)
    if not model or not model['available'] or target['task'] not in model['tasks']:
        raise ValueError('模型不可用或不支持当前目标')
    if inp.factor_ids and inp.factor_set_id:
        raise ValueError('请选择因子集或直接选择因子，二选一')
    if inp.factor_set_id:
        factor_set = storage.get('factor_set', inp.factor_set_id)
        factor_ids = list(factor_set['factor_ids'])
    else:
        factor_set = None
        factor_ids = list(inp.factor_ids)
    if len(set(factor_ids)) != len(factor_ids):
        raise ValueError('因子不能重复')
    factor_records = feature_records(factor_ids)
    if factor_set and factor_set.get('features'):
        frozen = {entry['instance_id']: entry for entry in factor_set['features']}
        factor_records = [
            {**record, **{key: frozen[record['id']][key] for key in ('spec_id', 'params', 'version', 'name')}}
            if record['id'] in frozen else record
            for record in factor_records
        ]
    event_features = event_inputs.freeze(inp.event_features)
    event_inputs.validate_count(factor_records, event_features)
    planning.validate_features(factor_records, trigger)
    manifest = factors.build_manifest(factor_records)
    if factor_set and factor_set.get('manifest_hash') not in (None, manifest.hash):
        raise ValueError('因子集清单已变化，请重新保存因子集')
    if event_features:
        manifest = factors.build_manifest(factor_records, event_features)
    packages = {p: importlib.metadata.version(p) for p in ['numpy', 'pandas', 'scikit-learn']}
    for p in ['torch', 'lightgbm', 'xgboost']:
        try:
            packages[p] = importlib.metadata.version(p)
        except importlib.metadata.PackageNotFoundError:
            pass
    config = {**inp.model_dump(), 'factor_ids': factor_ids,
              'trigger': trigger, 'sample_mode': sample_mode,
              'target_version': target['version'], 'target_params': target.get('params', {}),
              'model_params': model_config.resolve(inp.model, target['task'], inp.model_params)}
    snapshot = {
        'config': config,
        'factors': factor_records,
        'factor_set': ({k: factor_set[k] for k in ('id', 'name', 'version', 'manifest_hash', 'factor_ids') if k in factor_set} if factor_set else None),
        'manifest': manifest.to_dict(),
        'target': target,
        'code_sha256': engine.code_hash(),
        'packages': packages,
        'seed': 42,
        'evaluation_version': evaluation.VERSION,
        'diagnostic_seeds': list(range(42, 42 + inp.diagnostic_runs)) if models.is_sequence(inp.model) else [42],
        'split': 'chronological 60/20/20; purge labels reaching next split; train-only scaling',
    }
    if event_features:
        snapshot['event_features'] = event_features
        if any(feature['provider'] == 'chan' for feature in event_features):
            snapshot['chan'] = triggers.chan_snapshot()
    snapshot['research_plan'] = planning.compile_plan(config, target)
    if triggers.source(trigger) == 'chan':
        config['event_types'] = trigger['rule']['params']['types']
        snapshot['chan'] = triggers.chan_snapshot()
    if sum(bool(source) for source in (inp.market_range, inp.source_experiment_id, inp.dataset_id)) != 1:
        raise ValueError('请选择一份实验行情')
    experiment_id = uuid.uuid4().hex
    private_file = storage.ROOT / f'{experiment_id}.csv'
    try:
        if inp.market_range:
            source = inp.market_range
            args = market.bounds(source.symbol, source.period, source.start, source.end)
            dataset = market.snapshot(*args, experiment_id=experiment_id)
        else:
            if inp.source_experiment_id:
                source_exp = runs.latest(inp.source_experiment_id)
                if source_exp['status'] == 'deleting':
                    raise ValueError('原实验正在删除')
                original = source_exp['snapshot']['dataset']
            else:
                original = storage.get('dataset', inp.dataset_id)
            shutil.copyfile(storage.ROOT / original['file'], private_file)
            dataset = {**original, 'id': experiment_id, 'file': private_file.name,
                       'experiment_id': experiment_id}
        snapshot['dataset'] = dataset
        config['dataset_id'] = dataset['id']
        exp = jobs.enqueue({'id': experiment_id, 'name': inp.name, 'status': 'queued',
                                          'message': '等待运行', 'snapshot': snapshot})
    except Exception:
        private_file.unlink(missing_ok=True)
        raise
    if exp['id'] != experiment_id:
        private_file.unlink(missing_ok=True)
    return exp
