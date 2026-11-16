'use strict';

/* ============================================================
   序列 · 量化研究工作台 — UI Demo
   演示目标：信息架构与研究工作流编排，不是真实计算。
   ============================================================ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- icons ---------- */
const ICONS = {
  brand: '<circle cx="5" cy="16" r="2.1" fill="currentColor" stroke="none"/><circle cx="12" cy="10.5" r="2.1" fill="currentColor" stroke="none"/><circle cx="19" cy="5" r="2.1" fill="currentColor" stroke="none"/><path d="M7 14.7 9.9 11.9M14.1 8.7 17 5.9"/>',
  flask: '<path d="M9 3h6M10 3v6L5.2 18.4A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.3-1.6L14 9V3"/><path d="M8 14.5h8"/>',
  chart: '<path d="M4 20V4M4 20h16"/><path d="m7.5 15 3.8-4.2 3 2.2L19.5 7"/>',
  database: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6"/><path d="M4.5 11.5v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6"/>',
  layers: '<path d="m12 3 8.5 4.7L12 12.4 3.5 7.7z"/><path d="m4 12 8 4.4 8-4.4"/><path d="m4 16.3 8 4.4 8-4.4"/>',
  cpu: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><rect x="10" y="10" width="4" height="4" rx="1"/><path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevron: '<path d="m9.5 5 7 7-7 7"/>',
  arrow: '<path d="M4 12h15M13 6l6 6-6 6"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m19.5 19.5-4-4"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 6.5"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
  play: '<path d="M8.5 5.8v12.4L19 12z" fill="currentColor" stroke="none"/>',
  download: '<path d="M12 4v11m0 0 4.2-4.2M12 15l-4.2-4.2"/><path d="M5 20h14"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.4 5.7"/><path d="M20 5.5V11h-5.5"/>',
  info: '<circle cx="12" cy="12" r="8"/><path d="M12 11v5M12 8h.01"/>',
  x: '<path d="m6.5 6.5 11 11M17.5 6.5l-11 11"/>',
  shield: '<path d="M12 3.2 5.5 6v5.6c0 4 2.9 6.6 6.5 9 3.6-2.4 6.5-5 6.5-9V6z"/><path d="m9.2 12 2 2 3.7-4.2"/>',
  server: '<rect x="4" y="4.5" width="16" height="6.5" rx="1.6"/><rect x="4" y="13" width="16" height="6.5" rx="1.6"/><path d="M8 7.7h.01M8 16.2h.01M12 7.7h5M12 16.2h5"/>',
  activity: '<path d="M3 12h3.5l2-5.5 3.5 11 2.5-5.5H21"/>',
  trend: '<path d="M3 17 9 11l3.8 3.8L21 7"/><path d="M15 7h6v6"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.2 6.2l2.6 2.6M15.2 15.2l2.6 2.6M17.8 6.2l-2.6 2.6M8.8 15.2l-2.6 2.6"/>',
  file: '<path d="M6 3.5h8l4 4V20.5H6z"/><path d="M14 3.5v4h4"/>',
  settings: '<path d="M4 7h8M16 7h4M4 12h4M12 12h8M4 17h8M16 17h4"/><circle cx="14" cy="7" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="14" cy="17" r="2"/>',
  filter: '<path d="M4 5h16l-6.4 7.4V19l-3.2 1.6v-8.2z"/>',
  alert: '<path d="M12 4 21 20H3z"/><path d="M12 10v4M12 17.2h.01"/>',
  external: '<path d="M14 4h6v6"/><path d="m20 4-8.5 8.5"/><path d="M19 14v5.5H5V5h5.5"/>',
  book: '<path d="M5 4.5h11.5A2.5 2.5 0 0 1 19 7v13H7a2 2 0 0 1-2-2z"/><path d="M5 18h14"/>',
  bolt: '<path d="M13 3 5 13.5h5.5L11 21l8-10.5h-5.5z"/>'
};
const icon = (name, cls = '') => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
function injectSprite() {
  const body = Object.entries(ICONS).map(([name, paths]) =>
    `<symbol id="i-${name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</symbol>`).join('');
  document.body.insertAdjacentHTML('afterbegin', `<svg id="icon-sprite" aria-hidden="true" focusable="false" style="position:absolute;width:0;height:0;overflow:hidden">${body}</svg>`);
}
function paintStatic() {
  $$('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
}

const fixture = window.WORKBENCH_FIXTURE;
const pages = [
  ['experiments', '实验中心', 'flask'],
  ['backtests', '回测中心', 'chart'], ['assets', '研究资产', 'layers'], ['data', '行情数据', 'database']
];
const tabs = [
  ['features', '特征', 'trend'], ['sets', '特征集', 'layers'],
  ['tasks', '训练任务', 'target'], ['models', '模型', 'cpu']
];
const selectedAssets = {};
const app = $('#app');
const typeName = task => task === 'regression' ? '回归' : '二分类';
const sampling = mode => mode === 'chan_event' ? '缠论事件采样' : 'K 线采样';
const number = (value, decimals = 2) => value == null ? '—' : Number(value).toFixed(decimals);
const percent = value => value == null ? '—' : number(value * 100) + '%';
const date = value => String(value || '').slice(0, 10);
const time = value => String(value || '').replace('T', ' ').replace(/Z$/, '');
const route = (page, fragment = '') => '#/' + page + (fragment ? '/' + fragment : '');
const link = (text, page, primary = false) => '<a class="btn'+(primary?' primary':'')+'" href="'+route(page)+'">'+text+'</a>';
function systemUrl(page, extra = {}) {
  return 'http://127.0.0.1:8776/?'+new URLSearchParams({page,...extra});
}
function systemLink(text, page, primary = false) {
  return '<a class="btn'+(primary?' primary':'')+'" href="'+esc(systemUrl(page))+'">'+text+icon('external')+'</a>';
}
const tasks = fixture?.tasks || [];
const targetFor = task => fixture.targets.find(target => target.id === task.target_id);
const table = (headings, rows) => '<div class="table-wrap"><table><thead><tr>'+headings.map(label=>'<th scope="col">'+label+'</th>').join('')+
  '</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(cell=>'<td>'+cell+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
const details = rows => '<dl class="asset-meta">'+rows.map(([label, value])=>'<div><dt>'+label+'</dt><dd>'+value+'</dd></div>').join('')+'</dl>';
const panelHead = (title, aside = '') => '<div class="panel-head"><h2>'+title+'</h2>'+aside+'</div>';
const pageHead = (title, text, action = '') => '<div class="page-head"><div><h1>'+title+'</h1>'+(text?'<p class="subtitle">'+text+'</p>':'')+'</div>'+action+'</div>';
function historyLink(page, text = '历史记录') {
  return '<a class="btn small" href="'+route(page,'history')+'">'+text+'</a>';
}
function historyHeading(title, description, page, systemPage) {
  return pageHead(title,description,'<div class="actions">'+link('返回'+(page==='experiments'?'实验中心':'回测中心'),page)+
    systemLink('查看本地记录',systemPage)+'</div>');
}
function flowLink(glyph, label, description, href) {
  return '<a class="desk-flow-link" href="'+esc(href)+'"><span class="desk-flow-icon">'+icon(glyph)+'</span>'+
    '<span><b>'+label+'</b><small>'+description+'</small></span>'+icon('chevron')+'</a>';
}
function deskKpis(items, label) {
  return '<dl class="desk-kpis" aria-label="'+label+'">'+items.map(([name,value])=>
    '<div><dt>'+name+'</dt><dd>'+value+'</dd></div>').join('')+'</dl>';
}
let chartDisposers = [];
let draft = { step: 0, task: tasks[0]?.id, factors: [], model: '', targetParams: {}, modelParams: {},
  eventTypes: Object.keys(fixture?.eventTypes || {}), lookback: fixture?.experimentFields.lookback.default,
  epochs: fixture?.experimentFields.epochs.default, auto: false };

function clearCharts() {
  for (const dispose of chartDisposers) dispose();
  chartDisposers = [];
}

function mountChart(host, options = {}) {
  if (!host) return null;
  if (!window.LightweightCharts) {
    host.innerHTML = '<p class="empty">图表组件未加载。</p>';
    return null;
  }
  const chart = LightweightCharts.createChart(host, {
    autoSize: true,
    layout: { background: { type: 'solid', color: '#fff' }, textColor: '#586a82', fontSize: 11 },
    grid: { vertLines: {color:'#edf1f6'}, horzLines: {color:'#edf1f6'} },
    rightPriceScale: { borderColor:'#e3e9f2' },
    timeScale: { timeVisible:true, secondsVisible:false, rightOffset:2, borderColor:'#e3e9f2' },
    ...options
  });
  chartDisposers.push(() => chart.remove());
  return chart;
}
const stamp = value => Math.floor(Date.parse(value) / 1000);

function mountCandles(host, bars) {
  if (!bars?.length) {
    host.innerHTML = '<p class="empty">该快照没有可展示的 K 线。</p>';
    return;
  }
  const chart = mountChart(host, {rightPriceScale:{scaleMargins:{top:.08,bottom:.25}}});
  if (!chart) return;
  const up='#159c80', down='#ce5965';
  const candle = chart.addCandlestickSeries({upColor:up,downColor:down,wickUpColor:up,wickDownColor:down,borderVisible:false,priceLineVisible:false});
  const volume = chart.addHistogramSeries({priceScaleId:'',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false});
  volume.priceScale().applyOptions({scaleMargins:{top:.82,bottom:.01}});
  candle.setData(bars.map(bar=>({...bar,time:stamp(bar.date)})));
  volume.setData(bars.map(bar=>({time:stamp(bar.date),value:bar.volume,color:(bar.close>=bar.open?up:down)+'55'})));
  chart.timeScale().fitContent();
}

function stat(label, value, note) {
  return '<div class="stat"><div><b>'+label+'</b><strong>'+value+'</strong><span>'+note+'</span></div></div>';
}
function assetInventory(tab) {
  if (tab === 'features') return fixture.features.map(item=>({...item, group:item.category || '未分类', caption:item.scope === 'event' ? '事件特征' : 'K 线特征'}));
  if (tab === 'sets') return fixture.factorSets.map(item=>({...item,caption:item.factor_ids.length+' 个特征'}));
  if (tab === 'tasks') return tasks.map(item=>({...item,group:typeName(targetFor(item).task),caption:sampling(item.sample_mode)}));
  return fixture.models.map(item=>({...item,caption:item.input==='sequence'?'时序模型':'树模型'}));
}
function fieldName(param) {
  return param.label || param.description || param.name;
}
function assetDetails(tab, item) {
  const title = '<h2 id="asset-title" tabindex="-1">'+esc(item.name)+'</h2>';
  if (tab === 'features') {
    const event = item.scope === 'event';
    return title+'<p class="asset-description">'+esc(item.description)+'</p>'+details([
      ['分类',esc(item.group)],['计算参数',esc(Object.entries(item.params).map(([key,value])=>key+' = '+value).join(' · ') || '无可配置参数')],
      ['适用采样',event?'缠论事件采样':'K 线与缠论事件采样']
    ])+'<div class="asset-preview"><div class="asset-preview-head"><h3>取值预览</h3><label class="mini">行情快照 <select id="preview-snapshot"><option>'+esc(fixture.snapshot.name)+'</option></select></label></div>'+
      '<p class="panel-sub">合成行情。'+(event?'按候选点首次可见时取值，按事件列出结果。空值以「—」显示。':'按 K 线对齐，热身期等缺失值保留空值。')+'</p>'+
      '<button class="btn small" id="feature-preview" type="button">查看取值</button><div id="preview-result" aria-live="polite"></div></div>';
  }
  if (tab === 'sets') return title+details([['特征成员',item.factor_ids.map(id=>esc(fixture.features.find(f=>f.id===id)?.name || id)).join('、')]]);
  if (tab === 'tasks') {
    const target = targetFor(item);
    return title+'<p class="asset-description">'+esc(target.description)+'</p>'+details([
      ['任务类型',esc(item.group)],['采样方式',esc(item.caption)],['标签确定时点',esc(target.maturity)],
      ...target.parameters.map(param=>[esc(fieldName(param)),esc(param.default)])
    ])+'<div class="asset-action"><button class="btn primary" id="use-task" type="button">查看此任务的配置'+icon('arrow')+'</button></div>';
  }
  return title+'<p class="asset-description">'+esc(item.description)+'</p>'+details([
    ['输入形式',esc(item.caption)],['适用任务',item.tasks.map(typeName).join('、')],
    ['适用采样',item.input==='sequence'?'K 线采样':'K 线与缠论事件采样']
  ])+'<p class="footnote">正式系统会在运行环境中检查模型依赖。</p>';
}
function showFeaturePreview(item) {
  const result=$('#preview-result');
  const preview=fixture.factorPreviews[item.id];
  if (!preview) {
    result.innerHTML='<p class="empty">该快照没有预览结果。</p>';
    return;
  }
  if (item.scope === 'event') {
    const events=preview.events;
    result.innerHTML=events.length?table(['观察时间 (UTC)','事件','特征值'],events.slice(-20).reverse().map(event=>[
      esc(time(event.time)),esc(fixture.eventTypes[event.type+':'+event.side]),number(event.value,5)
    ])):'<p class="empty">该快照没有候选买卖点。</p>';
    return;
  }
  result.innerHTML='<div id="feature-candles" class="demo-chart compact"></div><div id="feature-values" class="demo-chart values"></div>';
  mountCandles($('#feature-candles'),preview.bars);
  const chart=mountChart($('#feature-values'));
  if (chart) {
    const series=chart.addLineSeries({color:'#3868ef',title:'特征值'});
    series.setData(preview.bars.map((bar,index)=>({
      time:stamp(bar.date),...(preview.factor[index]==null?{}:{value:preview.factor[index]})
    })));
    chart.timeScale().fitContent();
  }
}
function assets(requested) {
  const tab = tabs.some(([id])=>id===requested)?requested:'features';
  const items = assetInventory(tab);
  const label = tabs.find(([id])=>id===tab)[1];
  app.innerHTML=pageHead('研究资产','')+
    '<section class="panel asset-browser"><nav class="asset-tabs" aria-label="资产类型">'+tabs.map(([id,name,glyph])=>
      '<a class="asset-tab" href="'+route('assets',id)+'" '+(tab===id?'aria-current="page"':'')+'>'+icon(glyph)+name+'</a>').join('')+
    '</nav><div class="asset-layout"><section class="asset-inventory" aria-label="'+label+'列表"><div class="asset-toolbar">'+
    '<label class="asset-search">'+icon('search')+'<input id="asset-search" type="search" placeholder="搜索'+label+'…" aria-label="搜索'+label+'"></label>'+
    '<span class="mini" id="asset-count" aria-live="polite"></span></div><div id="asset-list" class="asset-list"></div></section>'+
    '<section class="asset-detail" id="asset-detail" aria-label="资产详情"></section></div></section>';
  const input=$('#asset-search'), list=$('#asset-list'), detail=$('#asset-detail');
  function update() {
    clearCharts();
    const query=input.value.trim().toLowerCase();
    const found=items.filter(item=>[item.name,item.group,item.caption].join(' ').toLowerCase().includes(query));
    const active=found.find(item=>item.id===selectedAssets[tab]) || found[0];
    $('#asset-count').textContent=found.length+' 项';
    if (!active) {
      list.replaceChildren();
      detail.innerHTML='<div class="empty">'+(items.length?'没有符合搜索条件的'+label+'。':tab==='sets'?'演示库还没有特征集。正式系统可从已注册特征保存组合。':'目录为空。')+'</div>';
      return;
    }
    const row=item=>'<button type="button" class="asset-entry" data-entry="'+esc(item.id)+'" aria-pressed="'+(item===active)+'"><span><b>'+esc(item.name)+'</b><small>'+esc(item.caption)+'</small></span>'+icon('chevron')+'</button>';
    const groups=[...new Set(found.map(item=>item.group))];
    list.innerHTML=groups[0]===undefined?found.map(row).join(''):groups.map(group=>
      '<section class="asset-group"><h3 class="asset-group-title">'+esc(group)+'</h3>'+found.filter(item=>item.group===group).map(row).join('')+'</section>').join('');
    detail.innerHTML=assetDetails(tab,active);
    const preview=$('#feature-preview');
    if (preview) preview.onclick=()=>{clearCharts();showFeaturePreview(active)};
    const use=$('#use-task');
    if (use) use.onclick=()=>{chooseTask(active.id);draft.step=0;location.hash=route('new')};
  }
  input.oninput=update;
  list.onclick=event=>{
    const button=event.target.closest('[data-entry]');
    if (!button) return;
    selectedAssets[tab]=button.dataset.entry;
    update();
    if (matchMedia('(max-width:800px)').matches) $('#asset-title')?.focus();
    else $$('[data-entry]',list).find(item=>item.dataset.entry===selectedAssets[tab])?.focus();
  };
  update();
}

const currentTask = () => tasks.find(task => task.id === draft.task);
const modelFor = id => fixture.models.find(model => model.id === id);
function allowedFeatures(task) {
  return fixture.features.filter(feature=>task.sample_mode==='chan_event'||feature.scope!=='event');
}
function compatibleModels(task) {
  const type = targetFor(task).task;
  return fixture.models.filter(model=>model.tasks.includes(type) &&
    (task.sample_mode!=='chan_event'||model.input==='vector'));
}
function chooseTask(id) {
  const task = tasks.find(item=>item.id===id);
  draft.task=id;
  draft.targetParams={...targetFor(task).params};
  const eligible=allowedFeatures(task);
  draft.factors=draft.factors.filter(id=>eligible.some(feature=>feature.id===id));
  if (!compatibleModels(task).some(model=>model.id===draft.model)) {
    draft.model=compatibleModels(task).find(model=>model.available)?.id || '';
    draft.modelParams={};
  }
  if (task.sample_mode==='chan_event') draft.auto=false;
}
function numericFields(parameters, values, group) {
  return parameters.map(param=>'<label class="field">'+esc(fieldName(param))+
    '<input required type="number" data-param-group="'+group+'" name="'+esc(param.name)+'" value="'+esc(values[param.name] ?? param.default)+
    '" min="'+esc(param.minimum)+'" max="'+esc(param.maximum)+'" step="'+(param.kind==='int'?'1':'any')+'"></label>').join('');
}
function wizard() {
  const task=currentTask(), target=targetFor(task), model=modelFor(draft.model), event=task.sample_mode==='chan_event';
  const steps=['研究任务','数据与样本','特征','模型','确认运行'];
  let body='';
  if (draft.step===0) {
    body='<div class="task-cards">'+tasks.map(item=>'<button type="button" class="task" data-task="'+esc(item.id)+'" aria-pressed="'+(item===task)+'"><b>'+esc(item.name)+
      '</b><small>'+sampling(item.sample_mode)+' · '+typeName(targetFor(item).task)+'</small></button>').join('')+'</div>'+
      '<p class="subtitle">'+esc(target.maturity)+'</p><div class="form-grid">'+numericFields(target.parameters,draft.targetParams,'targetParams')+'</div>';
  } else if (draft.step===1) {
    const snap=fixture.snapshot;
    body=details([['数据来源','合成行情'],['示例快照',esc(snap.name)],['覆盖区间',date(snap.start)+' 至 '+date(snap.end)],['K 线根数',snap.rows]])+
      (event?'<fieldset class="event-options"><legend>事件类型</legend>'+Object.entries(fixture.eventTypes).map(([id,label])=>
        '<label><input type="checkbox" data-event="'+esc(id)+'" '+(draft.eventTypes.includes(id)?'checked':'')+'>'+esc(label)+'</label>').join('')+'</fieldset>':'');
  } else if (draft.step===2) {
    const eligible=allowedFeatures(task);
    body=eligible.length?'<div class="checks">'+eligible.map(item=>'<label class="check"><input type="checkbox" data-factor="'+esc(item.id)+
      '" '+(draft.factors.includes(item.id)?'checked':'')+'><span>'+esc(item.name)+'</span><span class="tag">'+esc(item.category)+'</span></label>').join('')+'</div>':
      '<p class="info">当前代码目录没有注册可用于 K 线采样的特征。可回到第一步选择缠论事件任务。</p>';
  } else if (draft.step===3) {
    const models=compatibleModels(task);
    const fields=fixture.experimentFields;
    const sequenceParams=['lookback','epochs'].map(name=>({name, label:name==='lookback'?'历史窗口（根）':'训练轮数',kind:'int',...fields[name]}));
    body='<label class="field">训练模型<select id="draft-model"><option value="">请选择</option>'+models.map(item=>'<option value="'+esc(item.id)+'" '+
      (item===model?'selected ':'')+(item.available?'':'disabled')+'>'+esc(item.name)+(item.available?'':' · 导出环境未加载依赖')+'</option>').join('')+'</select></label>'+
      '<div class="form-grid demo-form-space">'+numericFields(model?.parameters[target.task] || [],draft.modelParams,'modelParams')+
      (model?.input==='sequence'?numericFields(sequenceParams,draft,'sequence'):'')+'</div>';
  } else {
    body='<p class="info">正式系统会检查任务、因子清单和模型参数，并在实际计算时检查有效样本数。</p>'+
      '<label class="check demo-form-space"><input id="auto-backtest" type="checkbox" '+(draft.auto?'checked ':'')+
      (event?'disabled':'')+'>训练后自动回测</label>'+
      (event?'<p class="footnote">缠论事件预测需要独立的交易规则。当前系统不直接回测这一类预测。</p>':'')+
      '<p class="footnote">此页面用于核对配置。实验中心提供由后端生成的示例结果。</p>';
  }
  app.innerHTML=pageHead('实验配置预览','用示例数据试填。打开正式表单时会读取本地数据，请在表单中确认配置。',link('返回实验中心','experiments'))+
    '<ol class="steps" aria-label="实验步骤">'+steps.map((name,i)=>'<li><button type="button" data-step="'+i+'" '+
      (draft.step===i?'aria-current="step"':'')+'><span class="num">'+(i+1)+'</span>'+name+'</button></li>').join('')+'</ol>'+
    '<div class="workspace-grid"><form class="panel wizard-form" id="draft-form"><h2 id="draft-step-title" tabindex="-1">'+steps[draft.step]+'</h2><div class="demo-form-space">'+body+'</div>'+
    '<div class="wizard-footer">'+(draft.step>0?'<button type="button" class="btn" data-step="'+(draft.step-1)+'">上一步</button>':'<span></span>')+
    (draft.step<steps.length-1?'<button type="submit" class="btn primary">下一步'+icon('arrow')+'</button>':systemLink('打开正式训练表单','training',true))+
    '</div></form><aside class="panel summary">'+panelHead('本次配置')+'<div class="block">'+details([
      ['训练任务',esc(task.name)],['采样方式',sampling(task.sample_mode)],['特征',draft.factors.length+' 项'],['模型',esc(model?.name || '待选择')],
      ['时间切分','训练 60% · 验证 20% · 测试 20%']
    ])+'</div></aside></div>';
  const form=$('#draft-form');
  const move=step=>{
    draft.step=step;
    wizard();
    const title=$('#draft-step-title');
    title.focus({preventScroll:true});
    title.scrollIntoView({block:'nearest'});
  };
  form.onsubmit=e=>{e.preventDefault();move(draft.step+1)};
  app.querySelectorAll('[data-step]').forEach(button=>button.onclick=()=>move(Number(button.dataset.step)));
  form.querySelectorAll('[data-task]').forEach(button=>button.onclick=()=>{
    chooseTask(button.dataset.task);
    wizard();
    $('#draft-form [data-task][aria-pressed="true"]')?.focus({preventScroll:true});
  });
  form.oninput=event=>{
    const input=event.target;
    const group=input.dataset.paramGroup;
    if (group==='sequence') draft[input.name]=input.value;
    else if (group) draft[group][input.name]=input.value;
    if (input.id==='draft-model') {
      draft.model=input.value;
      draft.modelParams={};
      wizard();
      $('#draft-model')?.focus({preventScroll:true});
    }
    if (input.dataset.factor) {
      draft.factors=input.checked?[...draft.factors,input.dataset.factor]:draft.factors.filter(id=>id!==input.dataset.factor);
      const featureCount=$$('.summary dd')[2];
      featureCount.textContent=draft.factors.length+' 项';
    }
    if (input.dataset.event) {
      draft.eventTypes=input.checked?[...draft.eventTypes,input.dataset.event]:draft.eventTypes.filter(id=>id!==input.dataset.event);
    }
    if (input.id==='auto-backtest') draft.auto=input.checked;
  };
}
function experimentStatus(example) {
  const status=example.status==='completed'?'已完成':example.status==='failed'?'失败':esc(example.status);
  return '<span class="badge '+(example.status==='failed'?'failed':'')+'">'+status+'</span>';
}
function experimentOverview() {
  const example=fixture.trainingExample;
  const sample=fixture.snapshot;
  const model=modelFor(example?.model);
  const test=example?.metrics.test;
  app.innerHTML=pageHead('实验中心','')+
    '<div class="desk-grid"><div class="desk-main">'+
    '<section class="panel desk-command" aria-labelledby="experiment-start"><div>'+
    '<h2 id="experiment-start">实验配置</h2>'+
    '<p>选择研究任务、行情、特征和模型。</p></div>'+
    '<div class="actions">'+link('预览配置','new')+systemLink('新建实验','training',true)+'</div></section>'+
    '<section class="panel desk-recent">'+panelHead('实验结果',historyLink('experiments'))+
    (example?'<a class="desk-result-row" href="#/experiments/history"><span class="desk-flow-icon">'+icon('flask')+'</span>'+
      '<span class="desk-result-name"><b>'+esc(example.name)+'</b><small>'+esc(model?.name || example.model)+' · '+sampling(example.sampleMode)+'</small></span>'+
      '<span class="desk-result-status">'+experimentStatus(example)+'<small>合成行情示例</small></span>'+icon('chevron')+'</a>':
      '<p class="empty">暂无可展示的实验结果。</p>')+
    (test?deskKpis([['测试样本',number(example.counts.test,0)],['测试 MAE',number(test.mae,6)],
      ['测试 RMSE',number(test.rmse,6)]],'样本外诊断'):'')+'</section></div>'+
    '<aside class="desk-rail"><section class="panel desk-resources">'+panelHead('研究资源')+
      flowLink('database','行情数据',esc(sample.interval)+' · '+sample.rows.toLocaleString('en-US')+' 根示例 K 线',route('data'))+
      flowLink('layers','研究资产',fixture.features.length+' 个注册特征 · '+tasks.length+' 项训练任务',route('assets'))+
    '</section><section class="panel desk-resources">'+panelHead('交易验证')+
      flowLink('chart','回测中心','配置回测或查看订单结果',route('backtests'))+
    '</section></aside></div>';
}
function experiments(view) {
  if (view !== 'history') {
    experimentOverview();
    return;
  }
  const example=fixture.trainingExample;
  app.innerHTML=historyHeading('实验历史','以下结果来自合成行情。','experiments','experiments');
  if (!example) {
    app.insertAdjacentHTML('beforeend','<section class="panel"><div class="empty">导出时没有可用的向量模型，暂无训练示例。</div></section>');
    return;
  }
  const labels={train:'训练',valid:'验证',test:'测试'};
  const splits=Object.entries(example.metrics).map(([split,metric])=>[
    labels[split],number(example.counts[split],0),number(metric.mae,6),number(metric.rmse,6),number(metric.spearman,4),number(metric.r2,4)
  ]);
  app.insertAdjacentHTML('beforeend','<div class="workspace-grid"><section class="panel">'+panelHead(esc(example.name),
    experimentStatus(example))+
    (splits.length?table(['区间','样本数','MAE','RMSE','Spearman','R²'],splits):
      '<div class="panel-body"><p class="wizard-error">'+esc(example.message || '该运行没有可展示的诊断。')+'</p></div>')+
    '</section><aside class="panel">'+panelHead('实验配置')+'<div class="block">'+details([
      ['采样',sampling(example.sampleMode)],['目标',esc(example.target)],['模型',esc(modelFor(example.model)?.name || example.model)]
    ])+'<p class="footnote">事件预测当前没有独立的交易执行规则。</p></div></aside></div>');
}
function marketPage() {
  const snap=fixture.snapshot;
  app.innerHTML=pageHead('行情数据','合成行情快照，用于演示数据依赖和预览。')+
    '<div class="market-layout"><section class="panel"><div class="market-heading"><h2>'+esc(snap.name)+'</h2><span class="tag">合成行情</span></div>'+
    '<div id="market-chart" aria-label="示例 K 线与成交量"></div><div class="market-foot">最近 '+fixture.bars.length+' 根 K 线 · UTC</div></section>'+
    '<aside class="panel">'+panelHead('快照覆盖')+'<div class="coverage-body">'+details([
      ['起点（UTC）',esc(time(snap.start))],['终点（UTC）',esc(time(snap.end))],['K 线数量',snap.rows]
    ])+'<div class="demo-form-space">'+link('查看实验数据配置','new/data',true)+'</div></div></aside></div>';
  mountCandles($('#market-chart'),fixture.bars);
}
function mountBacktestEquity(host, report, compact = false) {
  const chart=mountChart(host, {
    timeScale:{ timeVisible:!compact, secondsVisible:false, minBarSpacing:.03, borderColor:'#e3e9f2' }
  });
  if (!chart) return;
  const strategy=chart.addLineSeries({color:'#3868ef',lineWidth:2,title:compact?'':'策略',priceLineVisible:!compact});
  const benchmark=chart.addLineSeries({color:'#8290a4',lineWidth:2,title:compact?'':'买入持有',
    lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:!compact});
  strategy.setData(report.equity.map(row=>({time:stamp(row.date),value:row.equity/report.config.initial_cash})));
  benchmark.setData(report.equity.map(row=>({time:stamp(row.date),value:row.benchmark})));
  chart.timeScale().fitContent();
}
function backtestOverview() {
  const report=fixture.backtest;
  const metrics=report.metrics;
  app.innerHTML=pageHead('回测中心','')+
    '<div class="desk-grid"><div class="desk-main">'+
    '<section class="panel desk-command" aria-labelledby="backtest-start"><div>'+
    '<h2 id="backtest-start">回测配置</h2><p>选择信号来源，设置仓位、成本和风控。</p></div>'+
    '<div class="actions">'+systemLink('运行回测','backtest',true)+'</div></section>'+
    '<section class="panel desk-recent">'+panelHead('最近回测示例',historyLink('backtests'))+
    '<div class="desk-chart-head"><div><h3>'+esc(report.name)+'</h3><p class="panel-sub">合成行情 · '+date(report.period.start)+' 至 '+date(report.period.end)+'</p></div>'+
    '<div class="desk-legend" aria-label="图例"><span>策略</span><span>买入持有</span></div></div>'+
    '<div id="backtest-overview-chart" class="demo-chart desk-chart" aria-label="策略和基准的归一化净值"></div>'+
    deskKpis([['策略净收益',percent(metrics.net_return)],['买入持有',percent(metrics.benchmark_return)],
      ['最大回撤',percent(metrics.max_drawdown)]],'示例指标')+'</section></div>'+
    '<aside class="desk-rail"><section class="panel desk-resources">'+panelHead('选择信号来源')+
    flowLink('trend','SMA 规则','选择行情快照，设置快线和慢线。',systemUrl('backtest'))+
    flowLink('target','实验预测','选择已完成的 K 线实验运行记录。',systemUrl('backtest',{source:'experiment'}))+'</section>'+
    '<section class="panel desk-resources">'+panelHead('回测准备')+
    flowLink('database','检查行情','查看快照区间和 K 线',route('data'))+
    flowLink('flask','查看实验','配置训练或查看结果',route('experiments'))+
    '</section></aside></div>';
  mountBacktestEquity($('#backtest-overview-chart'),report,true);
}
function backtests(view) {
  if (view !== 'history') {
    backtestOverview();
    return;
  }
  const report=fixture.backtest;
  const metrics=report.metrics;
  app.innerHTML=historyHeading('回测历史','以下报告由订单引擎在合成行情上执行 SMA 规则所得。','backtests','backtest-history')+
    '<div class="stats">'+stat('净收益',percent(metrics.net_return),'策略')+stat('同期收益',percent(metrics.benchmark_return),'买入持有基准')+
    stat('最大回撤',percent(metrics.max_drawdown),metrics.order_count+' 笔成交订单')+'</div>'+
    '<div class="workspace-grid"><div class="stack"><section class="panel">'+panelHead('策略与基准净值')+
    '<div id="backtest-chart" class="demo-chart" aria-label="策略和基准的归一化净值"></div></section>'+
    '<section class="panel">'+panelHead('成交订单（UTC）')+table(['成交时间','方向','成交价','手续费'],report.orders.slice().reverse().map(order=>[
      esc(time(order.time)),order.side==='buy'?'买入':'卖出',number(order.price),number(order.fee)
    ]))+'</section></div><aside class="panel">'+panelHead('执行配置')+'<div class="block">'+details([
      ['信号来源','SMA '+report.source.fast+' / '+report.source.slow],['初始资金',number(report.config.initial_cash,0)],
      ['单侧手续费',report.config.fee_bps+' bps'],['单侧滑点',report.config.slippage_bps+' bps'],['引擎',esc(report.engine_version)]
    ])+'</div></aside></div>';
  mountBacktestEquity($('#backtest-chart'),report);
}

function render() {
  clearCharts();
  const [page,tab]=location.hash.replace(/^#\/?/,'').split('/');
  const current=pages.some(([id])=>id===page)||page==='new'?page:'experiments';
  const name=tab==='history'&&current==='experiments'?'实验历史':
    tab==='history'&&current==='backtests'?'回测历史':pages.find(([id])=>id===current)?.[1] || '实验配置预览';
  $('#crumb').textContent=name;
  $$('#nav a').forEach(item=>{
    if(item.dataset.page===(current==='new'?'experiments':current)) item.setAttribute('aria-current','page');
    else item.removeAttribute('aria-current');
  });
  if (!fixture) {
    app.innerHTML='<p class="empty">缺少研究示例数据。请重新导出后刷新。</p>';
    return;
  }
  if (current==='assets') assets(tab);
  else if (current==='new') {
    if (tab==='data') draft.step=1;
    wizard();
  } else if (current==='backtests') backtests(tab);
  else if (current==='data') marketPage();
  else experiments(tab);
  window.scrollTo(0,0);
}
injectSprite();
paintStatic();
$('#nav').innerHTML=pages.map(([id,name,glyph])=>'<a href="'+route(id)+'" data-page="'+id+'">'+icon(glyph)+name+'</a>').join('');
if (fixture && tasks.length) chooseTask(tasks[0].id);
window.addEventListener('hashchange',()=>{
  render();
  app.focus({preventScroll:true});
});
render();
