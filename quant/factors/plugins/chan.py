"""Features evaluated against the Chan structure visible at event observation."""
import numpy as np

from ..registry import factor


def comparison_pair(bsp, kind):
    source = bsp if kind == '1' else bsp.relate_bsp1
    if source is None:
        return None
    out = source.bi
    seg = out.parent_seg
    inside = seg.zs_lst[-1].bi_in if seg and seg.zs_lst else None
    if inside is not None and inside.idx < out.idx and inside.dir == out.dir:
        return inside, out
    return None


def _ratio(pair, algorithm):
    if pair is None:
        return None
    inside, out = pair
    denominator = inside.cal_macd_metric(algorithm, False)
    numerator = out.cal_macd_metric(algorithm, True)
    if denominator > 1e-6 and np.isfinite([numerator, denominator]).all():
        return float(numerator / denominator)
    return None


@factor('chan.peak_ratio', '背驰峰值比', '缠论事件', '一类点出入笔 MACD 峰值比；二类点取关联一类点在当前时刻的比值', scope='event', missing='drop')
def peak_ratio(context, params):
    from ...vendor.chanpy.Common.CEnum import MACD_ALGO
    return _ratio(context['pair'], MACD_ALGO.PEAK)


@factor('chan.area_ratio', '背驰面积比', '缠论事件', '与峰值比相同笔对，使用 FULL_AREA 同方向柱面积', scope='event', missing='drop')
def area_ratio(context, params):
    from ...vendor.chanpy.Common.CEnum import MACD_ALGO
    return _ratio(context['pair'], MACD_ALGO.FULL_AREA)


@factor('chan.retrace', '二类点回撤比例', '缠论事件', '二类点回撤笔 / 突破笔振幅；一类点取 0', scope='event', missing='drop')
def retrace(context, params):
    if context['kind'] != '2':
        return 0.
    bsp, lines = context['bsp'], context['lines']
    prev = lines.bi_list[bsp.bi.idx - 1] if bsp.bi.idx > 0 else None
    return float(bsp.bi.amp() / prev.amp()) if prev and prev.amp() > 0 else None


@factor('chan.side', '买卖方向', '缠论事件', '买点 1，卖点 -1', scope='event', missing='drop')
def side(context, params):
    return 1. if context['bsp'].is_buy else -1.


@factor('chan.type', '买卖点类别', '缠论事件', '一类 1，二类 2', scope='event', missing='drop')
def point_type(context, params):
    return float(context['kind'])
