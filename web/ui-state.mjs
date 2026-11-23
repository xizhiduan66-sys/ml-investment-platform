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
    ['标签定义', e => e.snapshot.target],
    ['采样规则', e => e.snapshot.config.trigger ?? e.snapshot.config.sample_mode],
    ['测试时间点', e => (e.result.rows || []).map(r => r.sample_id ?? r.observed_at ?? r.signal_time ?? r.time)],
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
  if (detail) return 'view';
  if (page === 'experiments') return 'table';
  return page === 'experiment-center' ? 'recent' : null;
}
