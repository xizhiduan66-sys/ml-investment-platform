"""Import the OKX BTC swap's available taker-flow and OI statistics."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from quant import market, okx


def sync(period, metric):
    api_period = okx.BARS[period]
    flow = metric == 'taker'
    endpoint = '/rubik/stat/taker-volume-contract' if flow else '/rubik/stat/contracts/open-interest-history'
    params = dict(instId='BTC-USDT-SWAP', period=api_period, limit=100)
    if flow:
        params['unit'] = '1'
    step = market.STEPS[period] * 1000
    records = {}
    while len(records) < 1440:
        page = okx._get(endpoint, base='https://openapi.okx.com/api/v5', **params)
        if not page:
            break
        stamps = []
        for row in page:
            stamp = int(row[0])
            values = tuple(map(float, row[1:]))
            if len(values) != (2 if flow else 3) or not all(math.isfinite(v) and v >= 0 for v in values):
                raise ValueError('Invalid OKX statistic')
            stamps.append(stamp)
            records[stamp] = values
        if min(stamps) >= params.get('end', float('inf')):
            raise ValueError('Cursor stalled')
        params['end'] = min(stamps)
        time.sleep(.45)
    stamps = sorted(records)
    if not stamps or any(b-a != step for a,b in zip(stamps,stamps[1:])):
        raise ValueError(f'Incomplete {metric} {period} page sequence')
    with market.connect(write=True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS taker_volume (
            symbol TEXT NOT NULL, period TEXT NOT NULL, ts_ms INTEGER NOT NULL,
            sell_contracts REAL NOT NULL, buy_contracts REAL NOT NULL,
            PRIMARY KEY(symbol,period,ts_ms)) WITHOUT ROWID""")
        table = 'taker_volume' if flow else 'open_interest'
        fields = ('sell_contracts','buy_contracts') if flow else ('oi_contracts','oi_coin','oi_usd')
        names = ','.join(fields)
        updates = ','.join(f'{f}=excluded.{f}' for f in fields)
        placeholders = ','.join('?' for _ in range(3+len(fields)))
        db.executemany(f'INSERT INTO {table}(symbol,period,ts_ms,{names}) VALUES ({placeholders}) ON CONFLICT(symbol,period,ts_ms) DO UPDATE SET {updates}',
                       [('BTCUSDT',period,t,*records[t]) for t in stamps])
    print(metric, period, len(stamps), *(datetime.fromtimestamp(t/1000,timezone.utc).isoformat() for t in (stamps[0],stamps[-1])), flush=True)


if __name__ == '__main__':
    # Page each endpoint sequentially to respect its per-instrument rate limit.
    def run_metric(metric):
        for period in ('1h','6h','1d'):
            sync(period,metric)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(run_metric, ('taker','oi')))
