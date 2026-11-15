"""OKX USDT perpetual trade candles and derived, reusable market series."""
import hashlib
import http.client
import json
import math
import os
import sqlite3
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from itertools import islice
from threading import Lock

import pandas as pd

from . import okx, storage

FIELDS = ('open', 'high', 'low', 'close', 'volume')
STEPS = {'1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
         '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600, '8h': 28800,
         '12h': 43200, '1d': 86400, '3d': 259200, '1w': 604800}
DEFAULT_LEVELS = ('5m', '15m', '30m', '1h', '6h', '1d', '3d', '1w')
AGGREGATION_VERSION = 2
NATIVE_ALIGNMENT = ('3d', '1w')
DATABASE = ContextVar('market_database', default=None)
SYNC = Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
 symbol TEXT NOT NULL, period TEXT NOT NULL, ts INTEGER NOT NULL,
 o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL,
 reconstructed INTEGER NOT NULL,
 PRIMARY KEY(symbol, period, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS revisions (
 symbol TEXT PRIMARY KEY, version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS alignments (
 symbol TEXT NOT NULL, period TEXT NOT NULL, origin INTEGER NOT NULL,
 PRIMARY KEY(symbol, period)
);
CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS aggregation_versions (
 symbol TEXT NOT NULL, period TEXT NOT NULL, version INTEGER NOT NULL,
 PRIMARY KEY(symbol, period)
);
CREATE TABLE IF NOT EXISTS audits (
 symbol TEXT NOT NULL, period TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
 version INTEGER NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(symbol, period, start, end)
);
"""


@contextmanager
def connect(write=False):
    db = sqlite3.connect(DATABASE.get() or storage.ROOT / 'market.db', timeout=30)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        with db:
            yield db
    finally:
        db.close()


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _ts(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.microsecond:
        raise ValueError('时间须包含时区，并精确到秒')
    return int(dt.timestamp())


def _floor(ts, step, origin=0):
    return (ts - origin) // step * step + origin


def _origin(db, symbol, period):
    if period in NATIVE_ALIGNMENT:
        row = db.execute('SELECT origin FROM alignments WHERE symbol=? AND period=?',
                         (symbol, period)).fetchone()
        if row is None:
            raise ValueError(f'{period} 的交易所周期边界尚未确认，请先同步标的')
        return row[0]
    return 0


def _aligned_range(db, symbol, period, start, end):
    step = STEPS[period]
    origin = _origin(db, symbol, period)
    return _floor(start + step - 1, step, origin), _floor(end, step, origin)


def bounds(symbol, period, start, end):
    symbol = symbol.strip().upper()
    if not symbol or not symbol.isascii() or not symbol.isalnum() or len(symbol) > 20:
        raise ValueError('交易对格式不正确')
    if period not in STEPS:
        raise ValueError('该级别暂不支持行情库聚合')
    with connect() as db:
        a, b = _aligned_range(db, symbol, period, _ts(start), min(_ts(end), int(time.time())))
    if b <= a:
        raise ValueError('所选区间不包含完整的 K 线周期')
    return symbol, period, a, b


def _read(db, symbol, period, a, b):
    return db.execute('SELECT ts,o,h,l,c,v,reconstructed FROM bars '
                      'WHERE symbol=? AND period=? AND ts>=? AND ts<? ORDER BY ts',
                      (symbol, period, a, b))


def instruments():
    """List stored series using the existing symbol/period/time index."""
    with connect() as db:
        result = []
        for (symbol,) in db.execute('SELECT symbol FROM revisions ORDER BY symbol'):
            periods = {}
            for period in STEPS:
                args = (symbol, period)
                first = db.execute('SELECT ts FROM bars WHERE symbol=? AND period=? ORDER BY ts LIMIT 1', args).fetchone()
                if first:
                    last = db.execute('SELECT ts FROM bars WHERE symbol=? AND period=? ORDER BY ts DESC LIMIT 1', args).fetchone()
                    periods[period] = {'start': _iso(first[0]), 'end': _iso(last[0])}
            if periods:
                result.append({'symbol': symbol, 'periods': periods})
    return {'instruments': result, 'levels': list(STEPS), 'exchange': 'okx', 'exchange_name': 'OKX'}


def candle_page(symbol, period, start=None, end=None, before=None, limit=1000):
    if period not in STEPS or not 1 <= limit <= 2000:
        raise ValueError('不支持的级别或查询数量')
    lower = _ts(start) if start else 0
    upper = _ts(end) if end else int(time.time()) + 1
    if lower >= upper:
        raise ValueError('结束时间应晚于开始时间')
    upper = min(upper, _ts(before)) if before else upper
    with connect() as db:
        rows = db.execute(
            'SELECT ts,o,h,l,c,v,reconstructed FROM bars '
            'WHERE symbol=? AND period=? AND ts>=? AND ts<? ORDER BY ts DESC LIMIT ?',
            (symbol.strip().upper(), period, lower, upper, limit + 1)
        ).fetchall()
    bars = [{'date': _iso(ts), **dict(zip(FIELDS, values[:5])), 'reconstructed': bool(values[5])}
            for ts, *values in reversed(rows[:limit])]
    return {'bars': bars, 'next_before': bars[0]['date'] if len(rows) > limit else None}


def _gaps(db, symbol, period, a, b):
    step = STEPS[period]
    count = db.execute('SELECT count(*) FROM bars WHERE symbol=? AND period=? AND ts>=? AND ts<?',
                       (symbol, period, a, b)).fetchone()[0]
    if count == (b-a)//step:
        return []
    cursor = a
    result = []
    for (ts,) in db.execute('SELECT ts FROM bars WHERE symbol=? AND period=? AND ts>=? AND ts<? ORDER BY ts',
                            (symbol, period, a, b)):
        if ts > cursor:
            result.append((cursor, ts))
        cursor = ts + step
    if cursor < b:
        result.append((cursor, b))
    return result


def _version(db, symbol):
    row = db.execute('SELECT version FROM revisions WHERE symbol=?', (symbol,)).fetchone()
    return row[0] if row else 0


def _bump(db, symbol):
    db.execute('INSERT INTO revisions VALUES (?,1) ON CONFLICT(symbol) DO UPDATE SET version=version+1', (symbol,))


def _put(db, symbol, period, rows, *, count_added=False):
    changed = []
    added = 0
    for row in rows:
        existed = db.execute("SELECT 1 FROM bars WHERE symbol=? AND period=? AND ts=?",
                             (symbol, period, row[0])).fetchone() if count_added else True
        cur = db.execute("""INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,period,ts) DO UPDATE SET
            (o,h,l,c,v,reconstructed)=(excluded.o,excluded.h,excluded.l,excluded.c,excluded.v,excluded.reconstructed)
            WHERE (bars.o,bars.h,bars.l,bars.c,bars.v,bars.reconstructed)
               IS NOT (excluded.o,excluded.h,excluded.l,excluded.c,excluded.v,excluded.reconstructed)""",
                         (symbol, period, *row))
        if cur.rowcount:
            changed.append(row[0])
            added += not existed
    if changed:
        if period == '1m':
            for level, step in STEPS.items():
                if level == '1m':
                    continue
                try:
                    origin = _origin(db, symbol, level)
                except ValueError:
                    continue
                db.executemany('DELETE FROM bars WHERE symbol=? AND period=? AND ts=?',
                               ((symbol, level, ts) for ts in {_floor(ts, step, origin) for ts in changed}))
        _bump(db, symbol)
    return added


def status(symbol, period, a, b):
    with connect() as db:
        gaps = _gaps(db, symbol, period, a, b)
        base_gaps = _gaps(db, symbol, '1m', a, b) if gaps and period != '1m' else gaps
        audit = db.execute('SELECT body FROM audits WHERE symbol=? AND period=? AND start=? AND end=? AND version=?',
                           (symbol, period, a, b, _version(db, symbol))).fetchone()
    return {'start': _iso(a), 'end': _iso(b), 'rows': (b-a)//STEPS[period],
            'coverage': 'complete' if not gaps else 'derivable' if not base_gaps else 'missing',
            'gaps': [[_iso(x), _iso(y)] for x, y in (base_gaps or gaps)[:12]],
            'audit': json.loads(audit[0]) if audit else {'state': 'pending'}}


def generate(symbol, period, a, b, *, audit=True):
    step = STEPS[period]
    requested = a, b
    with connect(write=True) as db:
        if period != '1m':
            version = db.execute('SELECT version FROM aggregation_versions WHERE symbol=? AND period=?',
                                 (symbol, period)).fetchone()
            if version != (AGGREGATION_VERSION,):
                # Rebuild existing derived ranges as well so a retry preserves their coverage.
                first, last = db.execute('SELECT min(ts), max(ts) FROM bars WHERE symbol=? AND period=?',
                                         (symbol, period)).fetchone()
                if first is not None:
                    a, b = min(a, first), max(b, last+step)
                    db.execute('DELETE FROM bars WHERE symbol=? AND period=?', (symbol, period))
                db.execute('INSERT OR REPLACE INTO aggregation_versions VALUES (?,?,?)',
                           (symbol, period, AGGREGATION_VERSION))
        gaps = _gaps(db, symbol, period, a, b)
        if gaps and (period == '1m' or _gaps(db, symbol, '1m', a, b)):
            raise ValueError('1m 底层行情尚未完整')
        for start, end in gaps:
            minute = _read(db, symbol, '1m', start, end)
            def rows():
                for ts in range(start, end, step):
                    group = [next(minute) for _ in range(step//60)]
                    traded = [row for row in group if row[5] > 0]
                    if traded:
                        opened, closed = traded[0][1], traded[-1][4]
                        high, low = max(row[2] for row in traded), min(row[3] for row in traded)
                    else:
                        opened = high = low = closed = group[-1][4]
                    yield (ts, opened, high, low, closed, math.fsum(row[5] for row in traded),
                           int(any(row[6] for row in group)))
            _put(db, symbol, period, rows())
    result = status(symbol, period, *requested)
    if audit:
        result['audit'] = verify(symbol, period, *requested)
    return result


class MarketSourceUnavailable(ValueError):
    pass


def _remote(symbol, period, a, b):
    return _parse_rows(_klines(symbol, period, a, b, (b-a)//STEPS[period]), period, a, b)


def _klines(symbol, period, a, b, limit):
    try:
        return okx.klines(symbol, period, a, b, limit, STEPS[period])
    except okx.SourceUnavailable as exc:
        raise MarketSourceUnavailable(str(exc)) from exc


def live_preview(symbol):
    try:
        rows = okx.preview(symbol)
    except okx.SourceUnavailable as exc:
        raise MarketSourceUnavailable(str(exc)) from exc
    bars = [{'date': _iso(int(row[0]) // 1000), **dict(zip(FIELDS, map(float, row[1:6])))}
            for row in sorted(rows, key=lambda row: int(row[0]))]
    return {'bars': bars, 'next_before': None}


def _parse_rows(raw, period, a, b):
    if not isinstance(raw, list):
        raise ValueError(f'OKX 合约接口返回异常')
    if not raw:
        return []
    step = STEPS[period]
    for row in raw:
        if (len(row) < 7 or not a*1000 <= int(row[0]) < b*1000
                or (int(row[0]) - a*1000) % (step*1000) or int(row[6]) != int(row[0]) + step*1000-1):
            raise ValueError(f'OKX K 线时间边界异常')
    if len({int(row[0]) for row in raw}) != len(raw):
        raise ValueError(f'OKX K 线开盘时间重复')
    parsed = []
    for row in raw:
        opened, high, low, close, volume = map(float, row[1:6])
        if (not all(math.isfinite(value) for value in (opened, high, low, close, volume))
                or min(opened, high, low, close) <= 0 or volume < 0
                or high < max(opened, close, low) or low > min(opened, close)):
            raise ValueError('OKX K 线价格或成交量异常')
        parsed.append((int(row[0]) // 1000, opened, high, low, close, volume, 0))
    return sorted(parsed)


def _next_month(month):
    if month.month == 12:
        return month.replace(year=month.year+1, month=1)
    return month.replace(month=month.month+1)

def _backfill_archives(symbol, a, b, gaps, progress):
    zone = timezone(timedelta(hours=8))
    month = datetime.fromtimestamp(a, zone).replace(day=1, hour=0, minute=0, second=0)
    cutoff = datetime.fromtimestamp(b, zone)
    full_month_end = cutoff.replace(day=1, hour=0, minute=0, second=0)
    count = (b-a)//60 - sum((end-start)//60 for start, end in gaps)

    def import_files(start, end, grouping):
        nonlocal count
        if not any(left < end and right > start for left, right in gaps):
            return
        try:
            files = sorted(set(okx.archives(symbol, start, end, grouping)))
        except (okx.SourceUnavailable, KeyError, TypeError, ValueError):
            return  # REST fills the same gaps if the archive catalog is unavailable.
        for stamp, url in files:
            day = datetime.fromtimestamp(stamp, zone)
            finish = _next_month(day) if grouping == 'monthly' else day+timedelta(days=1)
            left, right = max(stamp, a), min(int(finish.timestamp()), b)
            if left >= right:
                continue
            with connect() as db:
                missing = _gaps(db, symbol, '1m', left, right)
            if not missing:
                continue
            try:
                rows = _parse_rows([row for row in okx.archive_rows(symbol, url)
                                    if left*1000 <= int(row[0]) < right*1000], '1m', left, right)
                if not rows:
                    continue
                for index in sorted({0, len(rows)//2, len(rows)-1}):
                    row = rows[index]
                    native = _remote(symbol, '1m', row[0], row[0]+60)
                    if len(native) != 1 or native[0] != row:
                        raise ValueError('OKX 归档与原生分钟行情不一致')
            except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError, zipfile.BadZipFile):
                continue
            pending = iter(missing)
            gap = next(pending, None)
            accepted = []
            for row in rows:
                while gap and row[0] >= gap[1]:
                    gap = next(pending, None)
                if not gap:
                    break
                if row[0] >= gap[0]:
                    accepted.append(row)
            if accepted:
                with connect(write=True) as db:
                    _put(db, symbol, '1m', accepted)
                count += len(accepted)
                if progress:
                    progress(count, (b-a)//60, '官方归档')

    while month < full_month_end:
        following = month
        for _ in range(9):
            following = _next_month(following)
        following = min(following, full_month_end)
        import_files(int(month.timestamp()), int(following.timestamp()), 'monthly')
        month = following
    # The current month may only have daily archives. Leave the latest two days to REST.
    day = full_month_end
    daily_end = cutoff.replace(hour=0, minute=0, second=0) - timedelta(days=2)
    while day < daily_end:
        following = min(day+timedelta(days=9), daily_end)
        import_files(int(day.timestamp()), int(following.timestamp()), 'daily')
        day = following


def _minute_window(symbol, left, right):
    rows = _remote(symbol, '1m', left, right)
    if [row[0] for row in rows] != list(range(left, right, 60)):
        raise MarketSourceUnavailable(f'OKX 未完整返回 {_iso(left)} 至 {_iso(right)}，可从缺口续跑')
    return rows


def sync(symbol, period, a, b, *, force=False, audit=True, progress=None):
    if b > int(time.time())//60*60:
        raise ValueError('同步范围含尚未收盘的 K 线')
    if not SYNC.acquire(blocking=False):
        raise ValueError('已有行情同步正在运行，请稍后再试')
    try:
        with connect() as db:
            gaps = [(a, b)] if force else _gaps(db, symbol, '1m', a, b)
            # Refresh the latest two hours in the requested range, including prior revisions.
            tail = max(a, b-7200)
        if not force and b-a >= 7*86400 and gaps:
            _backfill_archives(symbol, a, b, gaps, progress)
            with connect() as db:
                gaps = _gaps(db, symbol, '1m', a, b)
        overlap = [(tail, b)] if b >= int(time.time())-2*86400 else []
        ranges = []
        for start, end in sorted([*gaps, *overlap]):
            if ranges and start <= ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
            else:
                ranges.append((start, end))
        page_seconds = okx.PAGE * 60
        windows = ((left, min(end, left+page_seconds)) for start, end in ranges
                   for left in range(start, end, page_seconds))
        with connect() as db:
            count = db.execute("SELECT count(*) FROM bars WHERE symbol=? AND period='1m' AND ts>=? AND ts<?",
                               (symbol, a, b)).fetchone()[0]
        with ThreadPoolExecutor(max_workers=3) as executor:
            while batch := list(islice(windows, 12)):
                futures = [executor.submit(_minute_window, symbol, left, right) for left, right in batch]
                rows, failure = [], None
                for future in futures:
                    try:
                        rows.extend(future.result())
                    except (ValueError, OSError) as exc:
                        failure = failure or exc
                if rows:
                    with connect(write=True) as db:
                        count += _put(db, symbol, '1m', rows, count_added=True)
                    if progress:
                        progress(count, (b-a)//60, 'OKX API')
                if failure:
                    raise failure
    finally:
        SYNC.release()
    result = status(symbol, period, a, b)
    # A higher-level request checks its refreshed source before the derived series is regenerated.
    if not audit:
        return result
    result['base_audit'] = verify(symbol, '1m', a, b)
    if period == '1m':
        result['audit'] = result['base_audit']
    return result


def repair(symbol, period, a, b):
    return sync(symbol, period, a, b, force=True)


def verify(symbol, period, a, b, *, seams=()):
    step = STEPS[period]
    last = b-step
    selected = {min(max(center + j*step, a), last)
                for center in (a, a+((b-a)//step//2)*step, last)
                for j in range(-10, 11)}
    for boundary in seams:
        opening = _floor(boundary, step, a)
        selected.update(ts for ts in (opening-step, opening, opening+step) if a <= ts < b)
    # Check both sides of each UTC month boundary.
    month = datetime.fromtimestamp(a, timezone.utc).replace(day=1, hour=0, minute=0, second=0)
    while month.timestamp() < b:
        month_start = int(month.timestamp())
        after = _floor(month_start+step-1, step, a)
        for ts in (after-step, after):
            if a <= ts < b:
                selected.add(ts)
        month = _next_month(month)
    with connect() as db:
        version = _version(db, symbol)
        if _gaps(db, symbol, period, a, b):
            raise ValueError('请先补齐该级别，再抽样校验')
        selected.update(ts for (ts,) in db.execute('SELECT ts FROM bars WHERE symbol=? AND period=? '
                                                   'AND ts>=? AND ts<? AND reconstructed=1', (symbol, period, a, b)))
        expected = {ts: _read(db, symbol, period, ts, ts+step).fetchone() for ts in selected}
    windows = []
    for ts in sorted(selected):
        if windows and ts == windows[-1][1] and ts-windows[-1][0] < 1000*step:
            windows[-1] = (windows[-1][0], ts+step)
        else:
            windows.append((ts, ts+step))
    remote_rows = {}
    sources = set()
    message = None
    with ThreadPoolExecutor(max_workers=3) as executor:
        for index in range(0, len(windows), 12):
            futures = [executor.submit(_remote, symbol, period, start, end)
                       for start, end in windows[index:index+12]]
            for future in futures:
                try:
                    rows = future.result()
                    remote_rows.update((row[0], row) for row in rows)
                    if rows:
                        sources.add('rest')
                except ValueError as exc:
                    message = message or str(exc)
            if message is not None:
                break
    checked = 0
    details = []
    for ts in sorted(selected):
        remote = remote_rows.get(ts)
        if remote is None:
            continue
        checked += 1
        local = expected[ts]
        diffs = {field: {'local': x, 'exchange': y}
                 for field, x, y in zip(FIELDS, local[1:6], remote[1:6])
                 if x != y and (field != 'volume' or not math.isclose(x, y, rel_tol=1e-12, abs_tol=1e-10))}
        if diffs:
            details.append({'time': _iso(ts), 'fields': diffs})
    failures = len(details)
    if checked < len(selected) and message is None:
        message = '交易所未返回全部抽样时间'
    report = {'state': 'mismatch' if failures else 'passed' if checked == len(selected) else 'pending',
              'checked': checked, 'expected': len(selected), 'mismatches': failures, 'details': details,
              'missing_samples': [_iso(ts) for ts in sorted(selected - remote_rows.keys())],
              'sources': sorted(sources), 'message': message, 'checked_at': _iso(int(time.time()))}
    with connect(write=True) as db:
        if _version(db, symbol) != version:
            raise ValueError('校验期间行情发生更新，请重新校验')
        db.execute('INSERT OR REPLACE INTO audits VALUES (?,?,?,?,?,?)',
                   (symbol, period, a, b, version, json.dumps(report)))
    return report


def snapshot(symbol, period, a, b, *, experiment_id=None):
    with connect() as db:
        if _gaps(db, symbol, period, a, b):
            raise ValueError('选中区间未完整入库')
        rows = list(_read(db, symbol, period, a, b))
        version = _version(db, symbol)
        record = db.execute('SELECT body FROM audits WHERE symbol=? AND period=? AND start=? AND end=? AND version=?',
                            (symbol, period, a, b, version)).fetchone()
        audit = json.loads(record[0]) if record else {'state': 'pending'}
        audit.pop('details', None)
    if len(rows) < 300:
        raise ValueError('实验至少需要 300 根 K 线，请扩大时间范围')
    frame = pd.DataFrame.from_records(rows, columns=('date', *FIELDS, 'reconstructed'))
    frame.date = pd.to_datetime(frame.date, unit='s', utc=True).dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    with tempfile.NamedTemporaryFile(dir=storage.ROOT, delete=False) as temp:
        path = temp.name
    try:
        frame[['date', *FIELDS]].to_csv(path, index=False)
        checksum = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                checksum.update(chunk)
        digest = checksum.hexdigest()
        versioned = hashlib.sha256(f'{symbol}:{period}:{digest}:{version}'.encode()).hexdigest()
        name = (experiment_id or digest) + '.csv'
        os.replace(path, storage.ROOT / name)
    finally:
        if os.path.exists(path):
            os.unlink(path)
    record = {'id': experiment_id or 'market-' + versioned[:24], 'file': name,
        'sha256': digest, 'name': f'{symbol} · {period} · OKX 永续',
        'source': 'market', 'symbol': symbol, 'exchange': 'okx', 'market': 'usdm_perpetual', 'interval': period,
        'start': frame.date.iloc[0], 'end': frame.date.iloc[-1], 'rows': len(rows),
        'market_version': version, 'market_audit': audit,
        'reconstructed_rows': int(frame.reconstructed.sum())}
    if experiment_id:
        return {**record, 'experiment_id': experiment_id}
    return storage.save('dataset', record)
