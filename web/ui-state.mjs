// Pure UI rules shared by views and regression tests.
// 未分类是展示层约定：空或纯空白分类统一显示为“未分类”，不写入分类表。
export function categoryLabel(value) {
  return String(value ?? '').trim() || '未分类';
}

export function filterExperiments(items, query = '', status = 'all') {
  const term = query.trim().toLocaleLowerCase();
  return items.filter(e => (status === 'all' || e.status === status) &&
    [e.name, e.snapshot?.dataset?.name, e.snapshot?.target?.name, e.snapshot?.config?.model]
      .some(value => String(value ?? '').toLocaleLowerCase().includes(term)));
}

export function comparisonDifferences(experiments) {
  if (experiments.length < 2) return [];
  const checks = [
    ['数据快照', e => e.snapshot.dataset.sha256],
    ['标签定义', e => { const t = e.snapshot.target; return [t.task, t.horizon, t.task === 'binary' ? t.threshold : null]; }],
    ['测试时间点', e => e.result.rows.map(r => r.signal_time)],
    ['手续费', e => e.result.execution?.fee_bps ?? e.snapshot.config.cost_bps],
    ['滑点', e => e.result.execution?.slippage_bps ?? 0],
    ['开仓门槛', e => e.snapshot.config[e.snapshot.target.task === 'binary' ? 'probability_threshold' : 'entry_threshold']],
    ['执行版本', e => e.result.engine_version ?? 'legacy'],
  ];
  return checks.filter(([, get]) => experiments.slice(1).some(e =>
    JSON.stringify(get(e)) !== JSON.stringify(get(experiments[0])))).map(([label]) => label);
}

export function pageWindow(current, total) {
  const pages = new Set([1, total]);
  for (let i = current - 1; i <= current + 1; i++) if (i > 0 && i <= total) pages.add(i);
  return [...pages].sort((a, b) => a - b);
}

export function createRequestGate() {
  let version = 0;
  return { next: () => ++version, current: token => token === version };
}

// Background status updates must never replace an editable research form.
export function pollTarget(page, detail) {
  if (detail || page === 'overview') return 'view';
  return page === 'experiments' ? 'table' : null;
}
