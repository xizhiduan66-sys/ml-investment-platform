"""Backfill public OKX open interest into the local market database."""
import argparse
import math
import time
from datetime import datetime, timezone

from . import market, okx

PERIODS = ('5m', '15m', '30m', *okx.BARS)
HISTORY_LIMIT = 1440


def history(symbol, period):
    if period not in PERIODS:
        raise ValueError(f'OKX 持仓量接口不支持周期 {period}')
    rows = {}
    before = None
    while len(rows) < HISTORY_LIMIT:
        page = okx.open_interest_page(symbol, period, before=before)
        if not page:
            break
        parsed = {}
        for row in page:
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError('OKX 持仓量字段格式错误')
            timestamp = int(row[0])
            values = tuple(float(value) for value in row[1:])
            if (timestamp <= 0 or timestamp in parsed or
                    any(not math.isfinite(value) or value < 0 for value in values)):
                raise ValueError('OKX 持仓量时间戳或数值无效')
            parsed[timestamp] = values
        if before is not None and max(parsed) >= before:
            raise ValueError('OKX 持仓量分页未严格向前推进')
        rows.update(parsed)
        before = min(parsed)
        if len(rows) < HISTORY_LIMIT:
            time.sleep(.21)
    if not rows:
        raise okx.SourceUnavailable(f'{symbol} {period} 没有可用的历史持仓量')
    return sorted(rows.items(), reverse=True)[:HISTORY_LIMIT]


def sync(symbol, period):
    rows = history(symbol, period)
    with market.connect(write=True) as db:
        db.executemany(
            """INSERT INTO open_interest (symbol, period, ts_ms, oi_contracts, oi_coin, oi_usd)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, period, ts_ms) DO UPDATE SET
                 oi_contracts=excluded.oi_contracts, oi_coin=excluded.oi_coin, oi_usd=excluded.oi_usd""",
            ((symbol, period, timestamp, *values) for timestamp, values in rows),
        )
        return db.execute(
            'SELECT count(*), min(ts_ms), max(ts_ms) FROM open_interest WHERE symbol=? AND period=?',
            (symbol, period),
        ).fetchone()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol', help='例如 BTCUSDT')
    parser.add_argument('periods', nargs='*', metavar='周期', help='可选：' + ', '.join(PERIODS))
    args = parser.parse_args()
    periods = args.periods or market.DEFAULT_LEVELS
    if invalid := set(periods) - set(PERIODS):
        parser.error('不支持的周期：' + ', '.join(sorted(invalid)))
    errors = []
    for period in periods:
        try:
            count, start, end = sync(args.symbol, period)
        except ValueError as exc:
            errors.append(f'{args.symbol} {period}：{exc}')
            continue
        first = datetime.fromtimestamp(start / 1000, timezone.utc)
        last = datetime.fromtimestamp(end / 1000, timezone.utc)
        print(f'{args.symbol} {period} · {count} 条 · {first.isoformat()} 至 {last.isoformat()}', flush=True)
        time.sleep(.21)
    if errors:
        parser.exit(1, '\n'.join(errors) + '\n')


if __name__ == '__main__':
    main()
