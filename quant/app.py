import io
import json
import importlib.metadata
import shutil
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Response, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import targets, planning, policies, prediction_artifacts, jobs, runs, archive, market_queue
from . import data, factors, models, storage, engine, backtest, model_config, chan_events, market, market_jobs
from . import triggers
from .splits import bounds as split_bounds

BASE = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app):
    if not storage.all_of('category'):
        for name in ['均线', '趋势', '波动', '量能', '结构实验']:
            storage.save('category', {'name': name})
    for category in {feature['category'] for feature in registered_features().values()}:
        ensure_category(category)
    jobs.initialize()
    market_queue.initialize()
    yield


app = FastAPI(title='单标的研究台 API', lifespan=lifespan)


@app.exception_handler(ValueError)
async def bad_value(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={'detail': str(exc)})


class FactorSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    factor_ids: List[str] = Field(min_length=1, max_length=30)
    description: str = Field(default='', max_length=300)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class ReclassifyIn(BaseModel):
    category: str = Field(default='', max_length=40)


class BacktestIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source: str
    dataset_id: Optional[str] = None
    experiment_id: Optional[str] = None
    run_id: Optional[str] = None
    fast: int = Field(default=20, ge=1, le=250)
    slow: int = Field(default=60, ge=2, le=500)
    threshold: Optional[float] = Field(default=None, ge=-1, le=1)
    initial_cash: float = Field(default=100000, gt=0, le=1e12)
    fee_bps: Optional[float] = Field(default=None, ge=0, le=1000)
    slippage_bps: Optional[float] = Field(default=None, ge=0, le=1000)
    position_pct: float = Field(default=1, gt=0, le=1)
    stop_loss_pct: float = Field(default=0, ge=0, le=.9)
    take_profit_pct: float = Field(default=0, ge=0, le=10)
    max_hold_bars: int = Field(default=0, ge=0, le=1000)


class MarketRange(BaseModel):
    symbol: str
    period: str
    start: str
    end: str
    audit: bool = True


class TriggerIn(BaseModel):
    kind: str
    rule_id: Optional[str] = None


class EventRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str
    version: int = Field(ge=1)
    params: Dict[str, Any] = Field(default_factory=dict)


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dataset_id: Optional[str] = None
    market_range: Optional[MarketRange] = None
    source_experiment_id: Optional[str] = None
    factor_ids: List[str] = Field(default_factory=list, max_length=30)
    factor_set_id: Optional[str] = None
    target_id: str
    target_version: Optional[int] = Field(default=None, ge=1)
    target_params: Dict[str, Any] = Field(default_factory=dict)
    model: str
    sample_mode: str = 'bar'
    trigger: Optional[TriggerIn] = None
    event_types: Optional[List[str]] = Field(default=None, max_length=4)
    model_params: Dict[str, Any] = Field(default_factory=dict)
    lookback: int = Field(default=30, ge=3, le=120)
    epochs: int = Field(default=10, ge=1, le=100)
    submission_key: Optional[str] = Field(default=None, max_length=128)
    auto_backtest: bool = True
    diagnostic_runs: int = Field(default=1, ge=1, le=3)
    cost_bps: float = Field(default=5, ge=0, le=100)
    entry_threshold: float = Field(default=0, ge=0, le=.5)
    probability_threshold: float = Field(default=.55, ge=0, le=1)


def registered_features():
    """从注册表读取定义，仅从数据库读取用户配置。"""
    metadata = {record['id']: record for record in storage.all_of('feature_metadata')}
    previous = {record['id']: record for record in storage.all_of('factor') if record.get('registered')}
    records = {}
    for spec in factors.specs().values():
        saved = metadata.get(spec.id, previous.get(f'registered:{spec.id}', {}))
        params = {param.name: param.default for param in spec.params if param.default is not None}
        for param in spec.params:
            if param.name in saved.get('params', {}):
                params[param.name] = param.validate(saved['params'][param.name])
        records[spec.id] = {
            'id': spec.id, 'spec_id': spec.id, 'name': spec.name,
            'description': spec.description, 'category': saved.get('category', spec.family),
            'note': saved.get('note', ''), 'params': params,
            'version': spec.version, 'scope': spec.scope, 'registered': True,
            'event_source': (spec.event_source or 'chan') if spec.scope == 'event' else None,
        }
    return records


def save_feature_settings(feature_id, **changes):
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("SELECT body FROM objects WHERE id=? AND kind='feature_metadata'", (feature_id,)).fetchone()
        if row:
            settings = json.loads(row[0])
        else:
            legacy = con.execute("SELECT body FROM objects WHERE id=? AND kind='factor'",
                                 (f'registered:{feature_id}',)).fetchone()
            previous = json.loads(legacy[0]) if legacy else {}
            settings = {key: previous[key] for key in ('category', 'note', 'params') if key in previous}
        settings.update(id=feature_id, **changes)
        con.execute("""INSERT INTO objects VALUES (?, 'feature_metadata', ?)
                       ON CONFLICT(id) DO UPDATE SET body=excluded.body""",
                    (feature_id, json.dumps(settings, ensure_ascii=False, allow_nan=False)))


def catalog():
    """目录内容（纯函数，保留给脚本直接调用）。"""
    features = registered_features().values()
    return {
        'datasets': [item for item in storage.all_of('dataset') if not item.get('archived')],
        'market_levels': list(market.STEPS),
        'categories': storage.all_of('category'),
        'factors': [feature for feature in features if feature['scope'] != 'event'],
        'recipes': factors.RECIPES,
        'specs': factors.spec_catalog(),
        'families': factors.families(),
        'factor_sets': storage.all_of('factor_set'),
        'targets': targets.catalog(),
        'task_templates': [{'id': mode + ':' + t['id'], 'target_id': t['id'], 'sample_mode': mode,
                            'name': ('事件 · ' if mode == 'chan_event' else '') + t['name']}
                           for t in targets.catalog() for mode in t['sample_modes'] if mode in ('bar', 'chan_event')],
        'events': triggers.catalog(),
        'models': models.registry(),
        'chan_event': {'features': [feature for feature in features if feature['scope'] == 'event'],
                       'version': chan_events.VERSION,
                       'types': chan_events.EVENT_TYPES, 'models': [m['id'] for m in models.registry() if m['input'] == 'vector']},
        'backtests': storage.all_of('backtest'),
        'experiments': storage.all_of('experiment'),
    }


@app.get('/api/catalog')
def catalog_route(if_none_match: Optional[str] = Header(default=None)):
    """目录按修订号打 ETag：浏览器每次都重验证，内容未变时只回 304。"""
    tag = f'W/"rev-{storage.revision()}"'
    headers = {'ETag': tag, 'Cache-Control': 'no-cache'}
    if if_none_match and if_none_match.strip() == tag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(catalog(), headers=headers)


@app.get('/api/workers')
def worker_status():
    import fcntl
    result = {}
    for queue in ('research', 'market'):
        with (storage.ROOT / f'{queue}-worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
                online = False
            except BlockingIOError:
                online = True
        result[queue] = {'online': online}
    return result


@app.get('/api/status')
def status():
    """轮询用的轻量状态：实验状态板 + 队列计数（不加载任何实验快照）。"""
    jobs.initialize()
    market_queue.initialize()
    return {'revision': storage.revision(), 'experiments': runs.status_board(),
            'queues': {'research': jobs.counts(), 'market': market_queue.counts()}}


class PreflightIn(BaseModel):
    model: str
    sample_mode: str = 'bar'
    trigger: Optional[TriggerIn] = None
    event_types: Optional[List[str]] = Field(default=None, max_length=4)
    target_id: str
    target_params: Dict[str, Any] = Field(default_factory=dict)
    model_params: Dict[str, Any] = Field(default_factory=dict)
    factor_ids: List[str] = Field(min_length=1, max_length=30)


@app.post('/api/research/preflight')
def research_preflight(inp: PreflightIn):
    target = targets.get(inp.target_id, None, inp.target_params)
    records = feature_records(inp.factor_ids)
    trigger = triggers.request(inp.trigger, inp.sample_mode, inp.event_types)
    planning.validate_features(records, trigger)
    manifest = factors.build_manifest(records)
    return {'plan': planning.compile_plan({**inp.model_dump(), 'trigger': trigger}, target), 'manifest': manifest.to_dict()}


@app.post('/api/event-rules', status_code=201)
def save_event_rule(inp: EventRuleIn):
    name = inp.name.strip()
    if not name:
        raise ValueError('请填写事件规则名称')
    return storage.save('event_rule', {'name': name, **triggers.definition(inp.provider, inp.params, inp.version)})


@app.get('/api/event-rules/{rule_id}/preview/{dataset_id}')
def preview_event_rule(rule_id: str, dataset_id: str):
    rule = triggers.rule(rule_id)
    dataset = storage.get('dataset', dataset_id)
    if rule['provider'] == 'chan' and dataset['rows'] > 10000:
        raise ValueError('缠论事件预览最多回放 10000 根 K 线，请选择较短的行情快照')
    events = triggers.replay(data.load(dataset), rule)['events']
    return {'count': len(events), 'events': events[-50:]}


@app.get('/api/chan-events/{dataset_id}')
def chan_event_preview(dataset_id: str):
    return chan_events.replay(data.load(storage.get('dataset', dataset_id)))


def ensure_category(name):
    """分类名归一：空名表示未分类；新分类名自动登记，避免默认族无法创建因子。"""
    name = (name or '').strip()
    if not name:
        return ''
    if name not in [c['name'] for c in storage.all_of('category')]:
        storage.save('category', {'name': name})
    return name


class FeatureParamsIn(BaseModel):
    params: Dict[str, Any]


@app.post('/api/factors/{factor_id}/params')
def configure_feature(factor_id: str, inp: FeatureParamsIn):
    spec = factors.spec(factor_id)
    if not spec.params:
        raise ValueError('该特征没有可配置参数')
    save_feature_settings(factor_id, params=factors.canonical_params(spec, inp.params))
    return registered_features()[factor_id]


@app.post('/api/categories')
def create_category(inp: CategoryIn):
    name = inp.name.strip()
    if not name or name in [c['name'] for c in storage.all_of('category')]:
        raise ValueError('分类名称为空或已存在')
    return storage.save('category', {'name': name})


class CategoryManageIn(BaseModel):
    name: str = Field(default='', max_length=40)
    operation: str


@app.post('/api/categories/{category_id}')
def manage_category(category_id: str, inp: CategoryManageIn):
    if inp.operation not in ('rename', 'remove'):
        raise ValueError('未知分类操作')
    target = inp.name.strip()
    registered = registered_features()
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        rows = con.execute('SELECT id,kind,body FROM objects WHERE kind IN (?,?,?)', ('category', 'factor', 'feature_metadata')).fetchall()
        records = [(key, kind, json.loads(body)) for key, kind, body in rows]
        current = next((body for key, kind, body in records if key == category_id and kind == 'category'), None)
        if current is None:
            raise ValueError('分类不存在')
        source = current['name']
        names = {body['name'] for key, kind, body in records if kind == 'category' and key != category_id}
        if inp.operation == 'rename' and (not target or target in names or target in ('全部', '未分类')):
            raise ValueError('分类名称为空、保留名称或已存在')
        if inp.operation == 'remove' and target and target not in names:
            raise ValueError('目标分类不存在')
        for key, kind, body in records:
            if body.get('category', registered.get(key, {}).get('category')) == source and kind != 'category':
                body['category'] = target
                con.execute('UPDATE objects SET body=? WHERE id=?', (json.dumps(body, ensure_ascii=False), key))
        metadata_ids = {key for key, kind, _ in records if kind == 'feature_metadata'}
        previous = {key: body for key, kind, body in records if kind == 'factor' and body.get('registered')}
        for key, feature in registered.items():
            if key not in metadata_ids and feature['category'] == source:
                legacy = previous.get(f'registered:{key}', {})
                settings = {field: legacy[field] for field in ('note', 'params') if field in legacy}
                settings.update(id=key, category=target)
                con.execute("INSERT INTO objects VALUES (?, 'feature_metadata', ?)",
                            (key, json.dumps(settings, ensure_ascii=False)))
        if inp.operation == 'remove':
            con.execute('DELETE FROM objects WHERE id=? AND kind=?', (category_id, 'category'))
        else:
            current['name'] = target
            con.execute('UPDATE objects SET body=? WHERE id=?', (json.dumps(current, ensure_ascii=False), category_id))
    return {'ok': True}


@app.post('/api/factors/{factor_id}/archive')
def archive_factor(factor_id: str):
    factor = storage.get('factor', factor_id)
    factor['archived'] = True
    return storage.save('factor', factor)


@app.post('/api/factors/{factor_id}/category')
def reclassify_factor(factor_id: str, inp: ReclassifyIn):
    """修改已有特征的分类；空字符串表示归入未分类。"""
    if factor_id in factors.specs():
        save_feature_settings(factor_id, category=ensure_category(inp.category))
        return registered_features()[factor_id]
    factor = storage.get('factor', factor_id)
    factor['category'] = ensure_category(inp.category)
    return storage.save('factor', factor)


class FeatureNoteIn(BaseModel):
    note: str = Field(default='', max_length=2000)


@app.post('/api/factors/{factor_id}/note')
def save_feature_note(factor_id: str, inp: FeatureNoteIn):
    note = inp.note.strip()
    if factor_id in factors.specs():
        save_feature_settings(factor_id, note=note)
        return {'id': factor_id, 'note': note}
    kind = 'factor'
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT body FROM objects WHERE id=? AND kind=?', (factor_id, kind)).fetchone()
        if row is None:
            raise ValueError('特征不存在')
        record = json.loads(row[0])
        record['note'] = note
        con.execute('UPDATE objects SET body=? WHERE id=? AND kind=?',
                    (json.dumps(record, ensure_ascii=False), factor_id, kind))
    return {'id': factor_id, 'note': note}


def feature_records(ids):
    registered = registered_features()
    return [registered[key] if key in registered else storage.get('factor', key) for key in ids]


@app.post('/api/factor-sets')
def create_factor_set(inp: FactorSetIn):
    if len(set(inp.factor_ids)) != len(inp.factor_ids):
        raise ValueError('因子不能重复')
    records = feature_records(inp.factor_ids)
    manifest = factors.build_manifest(records)
    return storage.save('factor_set', {
        **inp.model_dump(),
        'version': 1,
        'manifest_hash': manifest.hash,
        'features': [e.to_dict() for e in manifest.features],
    })


@app.post('/api/datasets')
async def import_data(file: UploadFile = File(...), symbol: str = Form(default=''), interval: str = Form(default='')):
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise ValueError('文件不能超过 20 MB')
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception:
        raise ValueError('无法读取 CSV，请使用 UTF-8 编码')
    return data.persist(df, file.filename or '导入行情', 'csv', symbol=symbol, interval=interval)


@app.get('/api/market/instruments')
def market_instruments():
    return market.instruments()


class MarketSyncIn(BaseModel):
    symbol: str
    mode: str


@app.get('/api/market/contracts')
def market_contracts():
    return {'symbols': sorted(market_jobs.contracts())}


@app.get('/api/market/jobs')
def market_job_list():
    return market_jobs.jobs()


@app.post('/api/market/jobs', status_code=202)
def market_job_submit(inp: MarketSyncIn):
    return market_jobs.submit(inp.symbol, inp.mode)


@app.get('/api/market/live')
def market_live(symbol: str):
    return market.live_preview(symbol)


@app.get('/api/market/candles')
def market_candles(symbol: str, period: str, start: Optional[str] = None, end: Optional[str] = None,
                   before: Optional[str] = None, limit: int = 1000):
    return market.candle_page(symbol, period, start, end, before, limit)


@app.post('/api/market/{action}')
def market_range(action: str, inp: MarketRange):
    operations = {'status': market.status, 'generate': market.generate, 'sync': market.sync,
                  'verify': market.verify, 'snapshot': market.snapshot, 'repair': market.repair}
    if action not in operations:
        raise HTTPException(404, '未知行情操作')
    args = market.bounds(inp.symbol, inp.period, inp.start, inp.end)
    if action == 'generate':
        return market.generate(*args, audit=inp.audit)
    return operations[action](*args)


@app.post('/api/backtests')
def create_backtest(inp: BacktestIn):
    if inp.source not in ('sma', 'experiment'):
        raise ValueError('回测信号来源必须是 sma 或 experiment')
    default_fee, default_slippage = 5., 2.
    if inp.source == 'sma':
        if not inp.dataset_id:
            raise ValueError('请选择数据快照')
        dataset = storage.get('dataset', inp.dataset_id)
        df = data.load(dataset)
        if inp.slow <= inp.fast:
            raise ValueError('SMA 慢线必须大于快线')
        signal = backtest.sma_signals(df, inp.fast, inp.slow)
        start, end = inp.slow - 1, len(df) - 1
        threshold = None
        source = {'kind': 'sma', 'fast': inp.fast, 'slow': inp.slow}
    else:
        if not inp.experiment_id:
            raise ValueError('请选择已完成实验')
        experiment = storage.get('experiment', inp.experiment_id)
        if not inp.run_id and experiment.get('status') != 'completed':
            raise ValueError('实验尚未完成')
        selected_run = storage.get('run', inp.run_id) if inp.run_id else (storage.get('run', experiment['latest_run_id']) if experiment.get('latest_run_id') else None)
        if selected_run and (selected_run['experiment_id'] != experiment['id'] or selected_run['status'] != 'completed'):
            raise ValueError('运行不属于该实验或尚未完成')
        artifact_id = selected_run.get('artifact_id', selected_run['id']) if selected_run else experiment['id']
        result_path = storage.ROOT / (artifact_id + '.json')
        if not result_path.exists():
            raise ValueError('实验 result 文件不存在')
        if triggers.for_config(experiment['snapshot']['config'])['kind'] == 'event':
            if experiment['snapshot']['target'].get('kind') == 'chan_structure':
                raise ValueError('结构有效性概率需要独立的交易执行规则')
            raise ValueError('事件收益预测需要独立的交易执行规则')
        experiment_result = json.loads(result_path.read_text())
        execution = experiment_result.get('execution') or {}
        default_fee = execution.get('fee_bps', experiment['snapshot']['config'].get('cost_bps', 5.))
        default_slippage = execution.get('slippage_bps', 0.)
        dataset = experiment['snapshot']['dataset']
        df = data.load(dataset)
        task = (experiment.get('snapshot', {}).get('target') or {}).get('task') or experiment_result.get('output', {}).get('task') or 'binary'
        if task == 'multiclass':
            raise ValueError('多分类预测需要独立的交易执行规则')
        threshold = inp.threshold
        if threshold is None:
            config = experiment.get('snapshot', {}).get('config') or {}
            threshold = config.get('entry_threshold' if task == 'regression' else 'probability_threshold')
        if threshold is None:
            threshold = 0.0 if task == 'regression' else 0.55
        if task == 'binary' and not 0 <= float(threshold) <= 1:
            raise ValueError('二分类阈值必须在 0 到 1 之间')
        reference = experiment_result.get('prediction_artifact')
        if reference:
            rows = prediction_artifacts.load(reference, artifact_id, dataset, task)
            signal, start, end = policies.bar_positions(df, rows, policies.ThresholdPolicy(task, float(threshold)))
        else:
            signal, start, end = backtest.experiment_signals(df, experiment_result, task, threshold)
        source = {'kind': 'experiment', 'experiment_id': experiment['id'], 'experiment_name': experiment.get('name'), 'run_id': selected_run['id'] if selected_run else None, 'threshold': float(threshold),
                  'strategy': policies.ThresholdPolicy(task, float(threshold)).definition(),
                  'prediction_artifact': reference}

    config = backtest.BacktestConfig(
        initial_cash=inp.initial_cash,
        fee_bps=default_fee if inp.fee_bps is None else inp.fee_bps,
        slippage_bps=default_slippage if inp.slippage_bps is None else inp.slippage_bps,
        position_pct=inp.position_pct,
        stop_loss_pct=inp.stop_loss_pct,
        take_profit_pct=inp.take_profit_pct,
        max_hold_bars=inp.max_hold_bars,
    )
    result = backtest.run(df, signal, config, start, end)
    symbol = (dataset.get('name') or '标的').split(' · ')[0]
    trades = result.get('trades') or []
    holding = {
        'symbol': symbol,
        'name': symbol,
        'direction': '多头' if trades else '空仓',
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


@app.get('/api/backtests')
def backtests():
    return storage.all_of('backtest')


@app.get('/api/backtests/{backtest_id}')
def backtest_detail(backtest_id: str):
    record = storage.get('backtest', backtest_id)
    result_path = storage.ROOT / (backtest_id + '.json')
    if record.get('status') == 'completed' and result_path.exists():
        record['result'] = json.loads(result_path.read_text())['result']
    return record


@app.get('/api/preview/{dataset_id}')
def preview(dataset_id: str, factor_id: str = '', limit: int = 400, before: Optional[int] = None):
    if not 100 <= limit <= 2000:
        raise ValueError('预览数量必须在 100 到 2000 之间')
    dataset = storage.get('dataset', dataset_id)
    if factor_id:
        if before is not None:
            raise ValueError('特征预览仅支持最新区间')
        factor = feature_records([factor_id])[0]
        if factors.resolve(factor)[0].scope == 'event':
            if dataset['rows'] > 10000:
                raise ValueError('事件特征预览最多回放 10000 根 K 线，请选择较短的行情快照')
            df = data.load(dataset)
            events = chan_events.replay(df, feature_records=[factor])['events'][-limit:]
            values = factors.event_matrix(df, [factor], events)[factor_id]
            return {'events': [
                {'event_id': event['event_id'], 'time': event['observed_time'],
                 'type': event['type'], 'side': event['side'],
                 'value': None if pd.isna(value) else float(value)}
                for event, value in zip(events, values)
            ]}
        df = data.load(dataset)
        series = factors.compute(df, factor)
        return {'bars': json.loads(df.tail(limit).to_json(orient='records')),
                'factor': json.loads(series.tail(limit).to_json(orient='values'))}
    tail, cursor = data.preview_page(dataset, limit, before)
    return {'bars': json.loads(tail.to_json(orient='records')), 'factor': None, 'next_before': cursor}


@app.get('/api/factor-correlation/{dataset_id}')
def factor_correlation(dataset_id: str, factor_ids: str = '', segment: str = 'train'):
    """特征间相关矩阵；区间由 splits 决定，特征模块只接收切好的矩阵。"""
    df = data.load(storage.get('dataset', dataset_id))
    ids = [x for x in factor_ids.split(',') if x]
    if not ids:
        raise ValueError('至少选择一个特征')
    if len(ids) > 30 or len(set(ids)) != len(ids):
        raise ValueError('最多计算 30 个不重复特征的相关性')
    instances = feature_records(ids)
    start, end = split_bounds(len(df), segment)
    features = factors.matrix(df.iloc[:end], instances)
    return {'correlation': factors.correlation(features.iloc[start:end]),
            'scope': {'segment': segment, 'start': str(df.date.iloc[start]),
                      'end': str(df.date.iloc[end - 1]), 'rows': end - start}}


@app.get('/api/label-preview/{dataset_id}/{target_id}')
def label_preview(dataset_id: str, target_id: str):
    dataset = storage.get('dataset', dataset_id)
    target = targets.get(target_id)
    if target['kind'] == 'chan_structure':
        if dataset['rows'] > 10000:
            raise ValueError('事件标签预览最多回放 10000 根 K 线，请选择较短的行情快照')
        df = data.load(dataset)
        report = chan_events.replay(df)
        recent = report['events'][-20:]
        labels = targets.calculate(df, target, [event['observed_at'] for event in recent], events=recent)
        events = [
            {'event_id': event['event_id'], 'observed_time': event['observed_time'],
             'label_time': event['label_time'] if end >= 0 else None,
             'label': int(value) if end >= 0 else None,
             'status': event['status'] if event['eligible'] else 'ineligible'}
            for event, value, end in zip(recent, labels.values, labels.ends)
        ]
        return {'kind': target['kind'], 'counts': report['counts'], 'events': events}
    df = data.load(dataset)
    if len(df) < target['horizon'] + 2:
        raise ValueError('行情快照太短，无法计算所选目标')
    i = len(df) - target['horizon'] - 2
    labels = targets.calculate(df, target, [i])
    end = labels.ends[0]
    if end < 0:
        raise ValueError('当前样本的标签无法确定')
    return {'decision_time': df.date.iloc[i], 'entry_time': df.date.iloc[i + 1],
            'end_time': df.date.iloc[end], 'entry_price': float(df.open.iloc[i + 1]),
            'end_price': float(df.open.iloc[end]), 'label': float(labels.values[0]), 'task': target['task'],
            'classes': targets.class_names(target)}


@app.post('/api/experiments')
def create_experiment(inp: ExperimentIn):
    if inp.submission_key:
        jobs.initialize()
        with storage.connect() as db:
            prior = db.execute('SELECT experiment_id FROM submission_keys WHERE key=?', (inp.submission_key,)).fetchone()
        if prior:
            return storage.get('experiment', prior[0])
    trigger = triggers.request(inp.trigger, inp.sample_mode, inp.event_types)
    sample_mode = triggers.sample_mode(trigger)
    target = targets.get(inp.target_id, inp.target_version, inp.target_params)
    if not models.is_sequence(inp.model) and inp.diagnostic_runs != 1:
        raise ValueError('多随机种子诊断当前仅适用于 LSTM / GRU')
    model = next((m for m in models.registry() if m['id'] == inp.model), None)
    if not model or not model['available'] or target['task'] not in model['tasks']:
        raise ValueError('模型不可用或不支持当前目标')
    if not inp.factor_ids and not inp.factor_set_id:
        raise ValueError('至少选择一个因子或一个因子集')
    if inp.factor_ids and inp.factor_set_id:
        raise ValueError('请选择因子集或直接选择因子，二选一')
    if inp.factor_set_id:
        factor_set = storage.get('factor_set', inp.factor_set_id)
        factor_ids = list(factor_set['factor_ids'])
    else:
        factor_set = None
        factor_ids = list(inp.factor_ids)
    if not factor_ids:
        raise ValueError('至少选择一个因子')
    if len(set(factor_ids)) != len(factor_ids):
        raise ValueError('因子不能重复')
    if len(factor_ids) > 30:
        raise ValueError('一次实验最多选择 30 个因子')
    factor_records = feature_records(factor_ids)
    if factor_set and factor_set.get('features'):
        frozen = {entry['instance_id']: entry for entry in factor_set['features']}
        factor_records = [
            {**record, **{key: frozen[record['id']][key] for key in ('spec_id', 'params', 'version', 'name')}}
            if record['id'] in frozen else record
            for record in factor_records
        ]
    planning.validate_features(factor_records, trigger)
    manifest = factors.build_manifest(factor_records)
    if factor_set and factor_set.get('manifest_hash') not in (None, manifest.hash):
        raise ValueError('因子集清单已变化，请重新保存因子集')
    packages = {p: importlib.metadata.version(p) for p in ['numpy', 'pandas', 'scikit-learn']}
    for p in ['torch', 'lightgbm', 'xgboost']:
        try:
            packages[p] = importlib.metadata.version(p)
        except importlib.metadata.PackageNotFoundError:
            pass
    config = {**inp.model_dump(), 'factor_ids': factor_ids,
              'trigger': trigger, 'sample_mode': sample_mode,
              'auto_backtest': inp.auto_backtest and sample_mode == 'bar' and target['task'] != 'multiclass',
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
        'evaluation_version': engine.evaluation.VERSION,
        'diagnostic_seeds': list(range(42, 42 + inp.diagnostic_runs)) if models.is_sequence(inp.model) else [42],
        'split': 'chronological 60/20/20; purge labels reaching next split; train-only scaling',
    }
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
                source_exp = storage.get('experiment', inp.source_experiment_id)
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


@app.get('/api/experiments/{experiment_id}')
def experiment(experiment_id: str):
    exp = storage.get('experiment', experiment_id)
    if exp['status'] == 'completed':
        execution = storage.get('run', exp['latest_run_id']) if exp.get('latest_run_id') else None
        artifact_id = execution.get('artifact_id', execution['id']) if execution else experiment_id
        exp['result'] = json.loads((storage.ROOT / (artifact_id + '.json')).read_text())
    return exp


@app.delete('/api/experiments/{experiment_id}')
def delete_experiment(experiment_id: str):
    jobs.initialize()
    if not experiment_id or any(char not in '0123456789abcdef' for char in experiment_id):
        raise HTTPException(404, '实验不存在')
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("SELECT body FROM objects WHERE kind='experiment' AND id=?", (experiment_id,)).fetchone()
        if not row:
            return {'ok': True, 'files': [], 'failed': []}
        record = json.loads(row[0])
        if (record.get('status') in ('queued', 'running') or
                any(execution['status'] in ('queued', 'running') for execution in runs.list_for(experiment_id))):
            raise HTTPException(409, '请等实验结束后再删除')
        record.update(status='deleting', message='正在清理实验')
        con.execute("UPDATE objects SET body=? WHERE id=?", (json.dumps(record, ensure_ascii=False), experiment_id))
    # 行与文件、队列状态的清理集中在一处（archive.purge），HTTP 层不再自己拼文件名。
    return {'ok': True, **archive.purge(experiment_id)}


@app.get('/api/experiments/{experiment_id}/runs')
def experiment_runs(experiment_id: str):
    runs.definition(experiment_id)
    return runs.list_for(experiment_id)


@app.post('/api/experiments/{experiment_id}/runs', status_code=202)
def rerun_experiment(experiment_id: str):
    return jobs.retry(experiment_id)


@app.get('/api/runs/{run_id}')
def run_detail(run_id: str):
    execution = storage.get('run', run_id)
    if execution['status'] == 'completed':
        artifact_id = execution.get('artifact_id', execution['id'])
        execution['result'] = json.loads((storage.ROOT / (artifact_id + '.json')).read_text())
    return execution


@app.get('/api/experiments/{experiment_id}/export')
def export(experiment_id: str):
    exp = experiment(experiment_id)
    return JSONResponse(exp, headers={'Content-Disposition': f'attachment; filename="experiment-{experiment_id}.json"'})


@app.get('/')
def index():
    return FileResponse(BASE / 'web' / 'index.html')


app.mount('/static', StaticFiles(directory=BASE / 'web'), name='static')
