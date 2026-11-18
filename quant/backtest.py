"""单标的、多空的订单级回测引擎。

信号在收盘产生，最早下一根开盘成交；止损/止盈在持仓期间用 high/low 触发。
不模拟订单簿、部分成交和杠杆。
"""
from dataclasses import asdict, dataclass
import math

import pandas as pd
import numpy as np

ENGINE_VERSION = 'order-v3'


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100000.0
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    position_pct: float = 1.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    max_hold_bars: int = 0

    def validate(self):
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError('初始资金必须大于 0')
        if not 0 <= self.fee_bps <= 1000:
            raise ValueError('手续费必须在 0 到 1000 bps 之间')
        if not 0 <= self.slippage_bps <= 1000:
            raise ValueError('滑点必须在 0 到 1000 bps 之间')
        if not 0 < self.position_pct <= 1:
            raise ValueError('仓位比例必须在 0 到 1 之间')
        if not 0 <= self.stop_loss_pct < 1:
            raise ValueError('止损比例必须在 0 到 1 之间')
        if not 0 <= self.take_profit_pct <= 10:
            raise ValueError('止盈比例必须在 0 到 10 之间')
        if self.max_hold_bars < 0:
            raise ValueError('最大持有根数不能为负')
        return self


def experiment_signals(df, result, task, threshold=None):
    # Compatibility path for reports created before prediction artifacts existed.
    from .policies import threshold_policy, bar_positions
    task = task or 'binary'
    return bar_positions(df, (result or {}).get('rows') or [], threshold_policy(task, {}, threshold))


def _date(df, index):
    if 'date' in df.columns:
        return str(df['date'].iloc[index])
    return str(index)


def run(df, signals, config, start_index=None, end_index=None):
    config.validate()
    required = {'open', 'high', 'low', 'close'}
    if not required.issubset(df.columns):
        raise ValueError('行情缺少 open/high/low/close 列')
    if len(df) < 2:
        raise ValueError('行情至少需要 2 根 K 线')
    prices = df[['open', 'high', 'low', 'close']]
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError('行情价格必须是有限正数')
    if ((df.high < df[['open', 'close', 'low']].max(axis=1)) | (df.low > df[['open', 'close', 'high']].min(axis=1))).any():
        raise ValueError('OHLC 高低价关系不正确')

    if isinstance(signals, pd.Series):
        signal = signals.reindex(df.index).fillna(0.0).astype('float64')
    else:
        signal = pd.Series(list(signals), index=df.index, dtype='float64').fillna(0.0)
    if not np.isfinite(signal.to_numpy()).all():
        raise ValueError('交易信号必须是有限数值')
    start = 0 if start_index is None else int(start_index)
    end = len(df) - 1 if end_index is None else int(end_index)
    if not (0 <= start < end < len(df)):
        raise ValueError('回测区间无效')

    fee_rate = config.fee_bps / 10000.0
    slip_rate = config.slippage_bps / 10000.0
    cash = float(config.initial_cash)
    qty = 0.0
    entry_price = entry_time = None
    entry_index = None
    entry_fee = entry_value = 0.0
    stop_price = take_price = None
    bars_held = 0
    pending = None
    rows = []
    trades = []
    orders = []
    # Benchmark uses the same executable entry time, full allocation and costs.
    benchmark_qty = config.initial_cash / (float(df.open.iloc[start + 1]) * (1 + slip_rate) * (1 + fee_rate))

    def add_order(side, order_type, signal_time, fill_time, price, quantity, fee, reason, pnl=None):
        orders.append({
            'side': side,
            'type': order_type,
            'signal_time': signal_time,
            'time': fill_time,
            'price': float(price),
            'qty': float(quantity),
            'fee': float(fee),
            'reason': reason,
            'status': 'filled',
            'pnl': None if pnl is None else float(pnl),
        })

    def close_position(i, price, reason, order_type, signal_time):
        nonlocal cash, qty, entry_price, entry_time, entry_index, entry_fee, entry_value, stop_price, take_price, bars_held
        direction = 1 if qty > 0 else -1
        exec_price = price * (1 - direction * slip_rate)
        notional = qty * exec_price
        exit_fee = abs(notional) * fee_rate
        cash += notional - exit_fee
        pnl = notional - entry_value - entry_fee - exit_fee
        base = abs(entry_value) + entry_fee
        trade = {
            'entry_time': entry_time,
            'exit_time': _date(df, i),
            'entry_price': float(entry_price),
            'exit_price': float(exec_price),
            'qty': float(abs(qty)),
            'direction': 'long' if qty > 0 else 'short',
            'fee': float(entry_fee + exit_fee),
            'pnl': float(pnl),
            'return_pct': float(pnl / base) if base else 0.0,
            'hold_bars': int(i - entry_index) if entry_index is not None else 0,
            'exit_reason': reason,
        }
        add_order('sell' if qty > 0 else 'buy', order_type, signal_time, _date(df, i), exec_price, abs(qty), exit_fee, reason, pnl)
        trades.append(trade)
        qty = 0.0
        entry_price = entry_time = entry_index = None
        entry_fee = entry_value = 0.0
        stop_price = take_price = None
        bars_held = 0
        return trade, exit_fee

    for i in range(start, end + 1):
        actions = []
        row_fee = 0.0
        last_fill = None
        realized = None

        if i > start and pending:
            direction, reason = pending
            opening = float(df['open'].iloc[i])
            if qty:
                actions.append('卖出' if qty > 0 else '平空')
                trade, exit_fee = close_position(i, opening, reason, 'market', _date(df, i - 1))
                row_fee += exit_fee
                last_fill = trade['exit_price']
                realized = (realized or 0.) + trade['pnl']
            if direction and cash > 0:
                exec_price = opening * (1 + direction * slip_rate)
                budget = cash * config.position_pct
                quantity = budget / (exec_price * (1 + fee_rate)) if exec_price > 0 else 0.0
                if quantity > 0:
                    notional = quantity * exec_price
                    fee = notional * fee_rate
                    cash -= direction * notional + fee
                    qty = direction * quantity
                    entry_price = exec_price
                    entry_time = _date(df, i)
                    entry_index = i
                    entry_fee = fee
                    entry_value = direction * notional
                    stop_price = exec_price * (1 - direction * config.stop_loss_pct) if config.stop_loss_pct > 0 else None
                    take_price = exec_price * (1 + direction * config.take_profit_pct) if config.take_profit_pct > 0 else None
                    bars_held = 0
                    actions.append('买入' if direction > 0 else '开空')
                    row_fee += fee
                    last_fill = exec_price
                    add_order('buy' if direction > 0 else 'sell', 'market', _date(df, i - 1), _date(df, i), exec_price, quantity, fee, reason)

        exposed = qty != 0.0
        if exposed:
            low = float(df['low'].iloc[i])
            high = float(df['high'].iloc[i])
            open_ = float(df['open'].iloc[i])
            exit_price = None
            exit_reason = None
            exit_type = None
            long = qty > 0
            if stop_price is not None and (open_ <= stop_price if long else open_ >= stop_price):
                exit_price, exit_reason, exit_type = open_, '止损', 'stop'
            elif take_price is not None and (open_ >= take_price if long else open_ <= take_price):
                exit_price, exit_reason, exit_type = open_, '止盈', 'take_profit'
            elif stop_price is not None and (low <= stop_price if long else high >= stop_price):
                exit_price = stop_price
                exit_reason = '止损'
                exit_type = 'stop'
            elif take_price is not None and (high >= take_price if long else low <= take_price):
                exit_price = take_price
                exit_reason = '止盈'
                exit_type = 'take_profit'
            if exit_price is not None:
                trade, exit_fee = close_position(i, exit_price, exit_reason, exit_type, _date(df, i))
                actions.append(exit_reason)
                row_fee += exit_fee
                last_fill = trade['exit_price']
                realized = (realized or 0.) + trade['pnl']

        if qty:
            bars_held += 1
            if i == end:
                trade, exit_fee = close_position(i, float(df['close'].iloc[i]), '期末平仓', 'close', _date(df, i))
                actions.append('期末平仓')
                row_fee += exit_fee
                last_fill = trade['exit_price']
                realized = (realized or 0.) + trade['pnl']

        close = float(df['close'].iloc[i])
        benchmark = 1.0 if i == start else benchmark_qty * close / config.initial_cash
        if i == end:
            benchmark *= (1 - slip_rate) * (1 - fee_rate)
        rows.append({
            'time': _date(df, i),
            'signal': float(signal.iloc[i]),
            'close': close,
            'qty': float(qty),
            'exposed': exposed,
            'cash': float(cash),
            'equity': float(cash + qty * close),
            'benchmark': float(benchmark),
            'action': ' / '.join(actions) if actions else None,
            'fill_price': None if last_fill is None else float(last_fill),
            'fee': float(row_fee),
            'trade_pnl': None if realized is None else float(realized),
        })

        if i < end:
            direction = int(np.sign(signal.iloc[i]))
            held = int(np.sign(qty))
            if direction != held:
                reason = {1: '信号做多', -1: '信号做空', 0: '信号空仓'}[direction]
                pending = (direction, reason)
            elif qty and config.max_hold_bars and bars_held >= config.max_hold_bars:
                pending = (0, '达到最大持有')
            else:
                pending = None
        else:
            pending = None

    equity_values = [float(config.initial_cash)] + [row['equity'] for row in rows]
    peak = equity_values[0]
    max_drawdown = 0.0
    for value in equity_values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1)

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = sum(t['pnl'] for t in losses)
    final_equity = rows[-1]['equity']

    if 'date' in df.columns and end > start:
        dates = pd.to_datetime(df['date'].iloc[start:end + 1], utc=True, errors='coerce')
    else:
        dates = None
    if dates is not None and dates.notna().all() and len(dates) > 1:
        span_days = float((dates.iloc[-1] - dates.iloc[0]).total_seconds() / 86400)
    else:
        span_days = float(end - start)
    annualize_power = (365.0 / span_days) if span_days > 0 else None

    def annualized(total):
        base = 1.0 + total
        if annualize_power is None or base <= 0:
            return None
        try:
            value = float(base ** annualize_power - 1)
        except OverflowError:
            return None
        return value if math.isfinite(value) else None

    returns = [rows[i]['equity'] / rows[i - 1]['equity'] - 1 for i in range(1, len(rows)) if rows[i - 1]['equity'] > 0]
    mean_return = sum(returns) / len(returns) if returns else 0.0
    std_return = (sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5 if len(returns) > 1 else 0.0
    periods_per_year = (len(rows) - 1) * 365.0 / span_days if span_days > 0 else 365.0
    sharpe = (mean_return / std_return * periods_per_year ** 0.5) if std_return > 0 else None
    downside = [min(r, 0.0) for r in returns]
    downside_dev = (sum(r * r for r in downside) / len(downside)) ** 0.5 if downside else 0.0
    sortino = (mean_return / downside_dev * periods_per_year ** 0.5) if downside_dev > 0 else None
    annual_return = annualized(final_equity / config.initial_cash - 1)
    benchmark_annualized = annualized(rows[-1]['benchmark'] - 1)
    calmar = (annual_return / abs(max_drawdown)) if (annual_return is not None and max_drawdown < 0) else None

    metrics = {
        'initial_cash': float(config.initial_cash),
        'final_equity': float(final_equity),
        'net_return': float(final_equity / config.initial_cash - 1),
        'benchmark_return': float(rows[-1]['benchmark'] - 1),
        'annualized_return': annual_return,
        'benchmark_annualized': benchmark_annualized,
        'max_drawdown': float(max_drawdown),
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'trade_count': len(trades),
        'win_rate': float(len(wins) / len(trades)) if trades else None,
        'profit_factor': float(gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
        'avg_trade_pnl': float(sum(t['pnl'] for t in trades) / len(trades)) if trades else None,
        'avg_hold_bars': float(sum(t['hold_bars'] for t in trades) / len(trades)) if trades else None,
        'total_fees': float(sum(o['fee'] for o in orders)),
        'exposure': float(sum(row['exposed'] for row in rows[1:]) / (len(rows) - 1)),
        'order_count': len(orders),
        'period_days': span_days,
    }
    return {
        'engine_version': ENGINE_VERSION,
        'rows': rows,
        'trades': trades,
        'orders': orders,
        'metrics': metrics,
        'config': asdict(config),
        'period': {'start': _date(df, start), 'end': _date(df, end), 'bars': end - start + 1},
    }
