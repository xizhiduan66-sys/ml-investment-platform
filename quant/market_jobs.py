"""Resumable market imports with atomic publication of all candle levels."""
import re
import time

from . import market, okx, storage, market_queue

def contracts():
    try:
        return okx.contracts()
    except okx.SourceUnavailable as exc:
        raise market.MarketSourceUnavailable(str(exc)) from exc


def jobs():
    return list({job['symbol']: job for job in reversed(storage.all_of('market_job'))}.values())


def submit(symbol, mode):
    symbol = symbol.strip().upper()
    if not re.fullmatch('[A-Z0-9]{1,20}', symbol) or mode not in ('full', 'incremental'):
        raise ValueError('请选择有效的 USDT 永续合约和同步方式')
    return market_queue.submit(symbol, mode)


def _stage(symbol, path, mode):
    # Keep the staged symbol on disk so a retry can reuse downloaded pages.
    with market.connect(write=True) as db:
        db.execute('ATTACH DATABASE ? AS staging', (str(path),))
        version = market._version(db, symbol)
        staged = db.execute('SELECT version, mode FROM staging.sync_base').fetchone()
        if staged == (version, mode):
            return version
        for table in ('bars', 'alignments', 'revisions', 'audits', 'aggregation_versions'):
            db.execute(f'DELETE FROM staging.{table} WHERE symbol=?', (symbol,))
            db.execute(f'INSERT INTO staging.{table} SELECT * FROM main.{table} WHERE symbol=?', (symbol,))
        db.execute('DELETE FROM staging.sync_base')
        db.execute('INSERT INTO staging.sync_base VALUES (?,?)', (version, mode))
        return version


def _publish(symbol, path, base_version):
    with market.connect(write=True) as db:
        if market._version(db, symbol) != base_version:
            raise ValueError('正式行情在同步期间发生变化，请重新同步')
        db.execute('ATTACH DATABASE ? AS staging', (str(path),))
        counts = {period: {'added': added, 'revised': revised} for period, added, revised in db.execute(
            '''SELECT s.period, sum(m.ts IS NULL), sum(m.ts IS NOT NULL)
            FROM staging.bars s LEFT JOIN main.bars m USING(symbol,period,ts)
            WHERE s.symbol=? AND (m.ts IS NULL OR
                (s.o,s.h,s.l,s.c,s.v,s.reconstructed) IS NOT (m.o,m.h,m.l,m.c,m.v,m.reconstructed))
            GROUP BY s.period''', (symbol,))}
        db.execute('''DELETE FROM bars WHERE symbol=? AND NOT EXISTS (
            SELECT 1 FROM staging.bars s WHERE (s.symbol,s.period,s.ts)=(bars.symbol,bars.period,bars.ts))''',
                   (symbol,))
        db.execute('''INSERT INTO bars SELECT * FROM staging.bars WHERE symbol=?
            ON CONFLICT(symbol,period,ts) DO UPDATE SET
            (o,h,l,c,v,reconstructed)=(excluded.o,excluded.h,excluded.l,excluded.c,excluded.v,excluded.reconstructed)
            WHERE (bars.o,bars.h,bars.l,bars.c,bars.v,bars.reconstructed)
               IS NOT (excluded.o,excluded.h,excluded.l,excluded.c,excluded.v,excluded.reconstructed)''', (symbol,))
        for table in ('alignments', 'revisions', 'audits', 'aggregation_versions'):
            db.execute(f'INSERT OR REPLACE INTO {table} SELECT * FROM staging.{table} WHERE symbol=?', (symbol,))
    return counts


def _history_start(symbol, end):
    if symbol not in contracts():
        raise ValueError('OKX 合约目录中没有该 USDT 永续合约')
    try:
        return okx.earliest_minute(symbol, end)
    except okx.SourceUnavailable as exc:
        raise market.MarketSourceUnavailable(str(exc)) from exc


def _native_alignment(symbol, period, end):
    step = market.STEPS[period]
    rows = market._klines(symbol, period, end-4*step, end, 5)
    if not rows:
        raise ValueError(f'未取得OKX 原生 {period} K 线，无法确认周期边界')
    origins = {int(row[0]) // 1000 % step for row in rows}
    if len(origins) != 1 or any(int(row[0]) % 1000 or int(row[6]) != int(row[0])+step*1000-1 for row in rows):
        raise ValueError(f'OKX {period} K 线开盘边界不一致')
    with market.connect(write=True) as db:
        origin = origins.pop()
        prior = db.execute('SELECT origin FROM alignments WHERE symbol=? AND period=?', (symbol, period)).fetchone()
        if prior and prior[0] != origin:
            raise ValueError(f'OKX {period} 周期边界与已入库规则不一致')
        db.execute('INSERT OR IGNORE INTO alignments VALUES (?,?,?)', (symbol, period, origin))


def _audit_range(db, symbol, period, start, end, changed, full):
    left, right = market._aligned_range(db, symbol, period, start, end)
    if left >= right:
        return left, right
    gaps = market._gaps(db, symbol, period, left, right)
    if full or gaps:
        return left, right
    step = market.STEPS[period]
    earliest = market._floor(changed, step, left)
    return max(left, min(earliest-step, right-step)), right


def run(job_id):
    job = storage.get('market_job', job_id)
    symbol = job['symbol']
    path = storage.ROOT / f'market-stage-{symbol}.db'
    reports = {}

    def update(message, status='running', **fields):
        job.update(status=status, message=message, reports=reports, **fields)
        storage.save('market_job', job)

    try:
        update('正在读取已入库行情')
        end = int(time.time()) // 60 * 60
        with market.connect() as db:
            first, last = db.execute("SELECT min(ts),max(ts) FROM bars WHERE symbol=? AND period='1m'", (symbol,)).fetchone()
        full = job['mode'] == 'full' or first is None
        if full:
            update('正在确认合约历史起点')
            start = _history_start(symbol, end)
        else:
            start = first
        token = market.DATABASE.set(path)
        try:
            with market.connect(write=True) as db:
                db.execute('CREATE TABLE IF NOT EXISTS sync_base (version INTEGER NOT NULL, mode TEXT NOT NULL)')
        finally:
            market.DATABASE.reset(token)
        version = _stage(symbol, path, job['mode'])
        token = market.DATABASE.set(path)
        try:
            update('正在下载和校验 1m 行情', start=market._iso(start), end=market._iso(end))
            changed = start if full or last is None else max(start, last+60-7200)
            if job.get('changed_from') is not None:
                changed = max(start, min(changed, job['changed_from']))
            with market.connect() as db:
                holes = market._gaps(db, symbol, '1m', start, end)
            if holes:
                changed = min(changed, holes[0][0])
            update('正在补齐并核对历史分钟行情', changed_from=changed)
            try:
                result = market.sync(symbol, '1m', start, end, audit=False,
                                     progress=lambda count, total, source: update(
                                         f'{source} · 已暂存 {count:,} / {total:,} 根 1m（{count/total:.1%}）'))
            except market.MarketSourceUnavailable as exc:
                with market.connect() as db:
                    missing = market._gaps(db, symbol, '1m', start, end)
                    count = db.execute("SELECT count(*) FROM bars WHERE symbol=? AND period='1m' AND ts>=? AND ts<?",
                                       (symbol, start, end)).fetchone()[0]
                gap = f'。首个缺口从 {market._iso(missing[0][0])} 开始' if missing else ''
                update(f'已暂存 {count:,} 根 1m 行情。数据源暂不可用：{exc}{gap}。恢复后可续跑', 'pending')
                return
            if result['coverage'] != 'complete':
                raise ValueError('1m 尚有缺口，暂未发布')
            for period in market.NATIVE_ALIGNMENT:
                with market.connect() as db:
                    left = db.execute('SELECT 1 FROM alignments WHERE symbol=? AND period=?', (symbol, period)).fetchone()
                if left is None:
                    _native_alignment(symbol, period, end)
            with market.connect() as db:
                existing = {p for (p,) in db.execute('SELECT DISTINCT period FROM bars WHERE symbol=?', (symbol,))}
            levels = ('1m', *market.DEFAULT_LEVELS, *(p for p in market.STEPS if p in existing and p not in ('1m', *market.DEFAULT_LEVELS)))
            ranges = {}
            for period in levels:
                with market.connect() as db:
                    a, b = _audit_range(db, symbol, period, start, end, changed, full)
                if a < b:
                    ranges[period] = (a, b)
                    if period != '1m':
                        update(f'正在聚合 {period}')
                        market.generate(symbol, period, a, b, audit=False)
                else:
                    reports[period] = {'state': 'insufficient', 'message': '尚无完整收盘周期'}
            for period, (a, b) in ranges.items():
                update(f'正在对照OKX 原生 {period} K 线')
                report = market.verify(symbol, period, a, b, seams=(changed, last or start))
                reports[period] = {**report, 'details': report['details'][:10],
                                   'start': market._iso(a), 'end': market._iso(b)}
        finally:
            market.DATABASE.reset(token)
        if any(report['state'] == 'mismatch' for report in reports.values()):
            update('发现交易所数据差异，正式行情未更新。可查看差异后重试', 'mismatch')
            return
        if any(report['state'] == 'pending' for report in reports.values()):
            update('部分样本尚未取得交易所数据，正式行情未更新。可重试校验', 'pending')
            return
        update('正在发布已校验的行情')
        counts = _publish(symbol, path, version)
        for period, report in reports.items():
            report.update(counts.get(period, {'added': 0, 'revised': 0}))
        update('行情已更新', 'completed')
        for suffix in ('', '-wal', '-shm'):
            try:
                path.with_name(path.name+suffix).unlink(missing_ok=True)
            except OSError:
                pass  # The next job can reset a leftover staging database.
    except Exception as exc:
        update(str(exc), 'failed')
