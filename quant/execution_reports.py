import numpy as np


def trading_rows(df, indices, predictions, weights, ledger, config):
    rows = []
    previous = 1.
    for i, pred, weight, value in zip(indices, predictions, weights, ledger['rows'][1:]):
        nav = value['equity']
        rows.append({'time': value['time'], 'signal_time': str(df.date.iloc[i]),
                     'entry_time': str(df.date.iloc[i + 1]), 'prediction': float(pred) if np.isfinite(pred) else None,
                     'weight': float(weight), 'net_return': nav / previous - 1,
                     'equity': nav, 'benchmark': value['benchmark'], 'bar_index': int(i)})
        previous = nav
    trades = [{'time': o['time'], 'signal_time': o['signal_time'],
               'action': '买入' if o['side'] == 'buy' else ('期末平仓' if o['type'] == 'close' else '卖出'),
               'price': o['price'], 'weight_change': 1. if o['side'] == 'buy' else -1.,
               'cost_rate': config['cost_bps'] / 10000} for o in ledger['orders']]
    metrics = dict(ledger['metrics'])
    metrics['round_trip_count'] = metrics['trade_count']
    metrics['trade_count'] = metrics['order_count']  # Historical experiment UI counts fills.
    return rows, trades, metrics
