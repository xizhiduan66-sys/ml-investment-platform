"""Point-in-time Chan buy/sell events; labels settle only behind the freeze frontier."""
import copy
import numpy as np
import pandas as pd
from . import factors, splits, targets
from .targets import STRUCTURE_CONFIRMATION as TARGET, settle_structure_label
from .factors.plugins.chan import comparison_pair

VERSION = 'chan-events-v1'
UPSTREAM = 'f8ca3b5e44d7166e2abd756a8e7fa816c79faebe'
CONFIG = {'trigger_step': True, 'bi_strict': True, 'bs_type': '1,2',
          'divergence_rate': 1., 'min_zs_cnt': 1, 'macd_algo': 'peak',
          'bsp2_follow_1': True, 'print_warning': False}
FEATURES = [
    {'id': spec.id, 'spec_id': spec.id, 'name': spec.name, 'description': spec.description,
     'category': spec.family, 'params': {}, 'version': spec.version, 'scope': spec.scope}
    for spec in factors.specs().values() if spec.id.startswith('chan.') and spec.scope == 'event'
]

EVENT_TYPES = {'1:buy': '一买', '1:sell': '一卖', '2:buy': '二买', '2:sell': '二卖'}
EVENT_FEATURES = {record['id']: record for record in FEATURES}


def normalize_types(values):
    if values is None:
        return list(EVENT_TYPES)
    if not values or len(set(values)) != len(values) or not set(values) <= EVENT_TYPES.keys():
        raise ValueError('请选择不重复的一买、一卖、二买或二卖')
    return [key for key in EVENT_TYPES if key in values]


def filter_report(report, types):
    selected = set(normalize_types(types))
    events = [event for event in report['events'] if f"{event['type']}:{event['side']}" in selected]
    return {**report, 'events': events,
            'counts': {status: sum(e['status'] == status for e in events)
                       for status in ('pending', 'confirmed', 'invalidated')},
            'immediately_settled': sum(not e['eligible'] for e in events)}


manifest = factors.build_manifest

class EventTracker:
    def __init__(self):
        self.events = {}
        self.frontier = -1

    def update(self, observed, frontier, bar, time):
        if frontier < self.frontier:
            raise ValueError('结构冻结边界回退，不能安全标注')
        current = {e['event_id']: e for e in observed}
        for key, event in current.items():
            if key not in self.events:
                # Already frozen when first observed: no actionable prediction interval.
                self.events[key] = {**copy.deepcopy(event), 'observed_at': bar, 'observed_time': str(time),
                                    'label': None, 'label_end': None, 'label_time': None,
                                    'status': 'pending', 'eligible': event['anchor'] > frontier}
        for key, event in self.events.items():
            if event['label'] is None and event['anchor'] <= frontier:
                event.update(settle_structure_label(key in current, bar, time))
        self.frontier = frontier


def _features(bsp, kind, lines, feature_records):
    context = {'bsp': bsp, 'kind': kind, 'lines': lines, 'pair': comparison_pair(bsp, kind)}
    return {key: factors.compute_event(record, context) for key, record in feature_records.items()}


def replay(df, progress=lambda _: None, *, feature_records=()):
    from .vendor.chanpy.ChanConfig import CChanConfig
    from .vendor.chanpy.Common.CEnum import KL_TYPE
    from .vendor.chanpy.Common.CTime import CTime
    from .vendor.chanpy.KLine.KLine_Unit import CKLine_Unit
    from .vendor.chanpy.KLine.KLine_List import CKLine_List
    event_records = {}
    for record in [*FEATURES, *feature_records]:
        spec, params, _, _, _ = factors.resolve(record)
        if spec.scope == 'event':
            event_records[factors.event_value_key(spec, params)] = record
    lines = CKLine_List(KL_TYPE.K_DAY, CChanConfig(dict(CONFIG)))
    tracker, previous = EventTracker(), None
    for i, row in enumerate(df.itertuples(index=False)):
        stamp = pd.Timestamp(row.date)
        unit = CKLine_Unit({'time_key': CTime(stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second, auto=False),
                           **{k: float(getattr(row, k)) for k in ('open', 'high', 'low', 'close', 'volume')}})
        unit.set_idx(i)
        if previous is not None:
            unit.set_pre_klu(previous)
        previous = unit
        lines.add_single_klu(unit)
        points = []
        for bsp in lines.bs_point_lst.bsp_iter():
            for point_type in bsp.type:
                kind = point_type.value
                if kind not in ('1', '2'):
                    continue
                anchor = bsp.klu.idx
                side = 'buy' if bsp.is_buy else 'sell'
                event_id = f'{kind}:{side}:{anchor}'
                points.append({'event_id': event_id, 'type': kind, 'side': side,
                               'anchor': anchor, 'anchor_time': str(df.date.iloc[anchor]),
                               'features': (_features(bsp, kind, lines, event_records) if event_id not in tracker.events else {})})
        tracker.update(points, lines.bs_point_lst.last_sure_pos, i, row.date)
        if i % 500 == 0:
            progress(f'缠论逐根回放 {i + 1}/{len(df)} · 候选 {len(tracker.events)}')
    events = list(tracker.events.values())
    return {'version': VERSION, 'upstream': UPSTREAM, 'config': CONFIG, 'events': events,
            'counts': {s: sum(e['status'] == s for e in events) for s in ('pending', 'confirmed', 'invalidated')},
            'immediately_settled': sum(not e['eligible'] for e in events)}


def split_events(events, n):
    a, b = splits.edges(n)
    return {name: [e for e in events if e['eligible'] and e['label'] is not None and
                  lo <= e['observed_at'] < hi and e['label_end'] < hi]
            for name, lo, hi in [('train', 0, a), ('valid', a, b), ('test', b, n)]}


def prepare_samples(df, snap, progress, target=None):
    """Assemble one row per event, using ordinary factor values at its observation bar."""
    if snap.get('chan') != {'version': VERSION, 'upstream': UPSTREAM, 'config': CONFIG}:
        raise ValueError('缠论计算配置已变化，请重新创建实验')
    records = snap['factors']
    report = filter_report(replay(df, progress, feature_records=records), snap['config'].get('event_types'))
    matrix = factors.event_matrix(df, records, report['events'])
    target = target if target is not None else snap.get('target', TARGET)
    observations = [event['observed_at'] for event in report['events']]
    labels = targets.calculate(df, target, observations, events=report['events'])
    samples = []
    for event, values, label, end in zip(report['events'], matrix.to_dict(orient='records'), labels.values, labels.ends):
        if end < 0 or not all(np.isfinite(value) for value in values.values()):
            continue
        sample = {**event, 'features': {**event['features'], **values},
                  'eligible': True, 'label': float(label), 'label_end': int(end),
                  'label_time': str(df.date.iloc[end])}
        samples.append(sample)
    return report, split_events(samples, len(df))
