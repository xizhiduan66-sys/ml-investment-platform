import io
import json
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Response, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import targets, planning, backtest_submission, experiment_submission, jobs, runs, archive, market_queue
from . import data, factors, models, storage, chan_events, market, market_jobs
from . import triggers
from . import event_inputs
from .research_inputs import BacktestIn, EventFeatureIn, ExperimentIn, MarketRange, TriggerIn
from .feature_catalog import feature_records, registered_features
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


app = FastAPI(title='Candlestick Dance（K线跳动）API', lifespan=lifespan)


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


class EventRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str
    version: int = Field(ge=1)
    params: Dict[str, Any] = Field(default_factory=dict)


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
        'experiments': runs.projected_all(),
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
    factor_ids: List[str] = Field(default_factory=list, max_length=30)
    event_features: List[EventFeatureIn] = Field(default_factory=list, max_length=30)


@app.post('/api/research/preflight')
def research_preflight(inp: PreflightIn):
    target = targets.get(inp.target_id, None, inp.target_params)
    records = feature_records(inp.factor_ids)
    trigger = triggers.request(inp.trigger, inp.sample_mode, inp.event_types)
    planning.validate_features(records, trigger)
    events = event_inputs.freeze(inp.event_features)
    plan = planning.compile_plan({**inp.model_dump(), 'trigger': trigger}, target)
    event_inputs.validate_count(inp.factor_ids, events)
    manifest = factors.build_manifest(records, events)
    return {'plan': plan, 'manifest': manifest.to_dict()}


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


@app.post('/api/event-features/preview/{dataset_id}')
def preview_event_feature(dataset_id: str, inp: EventFeatureIn):
    feature, = event_inputs.freeze([inp])
    dataset = storage.get('dataset', dataset_id)
    if feature['provider'] == 'chan' and dataset['rows'] > 10000:
        raise ValueError('缠论事件预览最多回放 10000 根 K 线，请选择较短的行情快照')
    df = data.load(dataset)
    marks = event_inputs.mark_bars(len(df), triggers.replay(df, feature))
    triggered = df.date.iloc[marks.nonzero()[0]]
    return {'count': len(triggered), 'recent': triggered.tail(8).tolist()}


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


@app.get('/api/experiments/{experiment_id}/runs/{run_id}/backtest-settings')
def experiment_backtest_settings(experiment_id: str, run_id: str):
    return backtest_submission.settings(experiment_id, run_id)


@app.post('/api/backtests')
def create_backtest(inp: BacktestIn):
    return backtest_submission.create(inp)


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
    return experiment_submission.submit(inp)


@app.get('/api/experiments/{experiment_id}')
def experiment(experiment_id: str, include_result: bool = True):
    exp = runs.latest(experiment_id)
    if include_result and exp['status'] == 'completed':
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
