import {paramField,collectParams} from './parameter-fields.mjs';
import {eventPanel} from './chan-events.mjs';
import {groupedModels} from './model-catalog.mjs';
import {mountExperimentWizard,collectModelParams,marketAuditText} from './experiment-wizard.mjs?v=okx-only-2';
import {renderDiagnostics} from './diagnostics.mjs';
import {filterExperiments, comparisonDifferences, pageWindow, createRequestGate, pollTarget} from './ui-state.mjs';
import {categoryLabel} from './ui-state.mjs';
const $=s=>document.querySelector('#dialog[open]')?.querySelector(s)||document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const navigationGroups=[
  {name:'训练模型',links:[['training','训练模型'],['settings','模型设置'],['experiments','历史记录']]},
  {name:'回测',links:[['backtest','运行回测'],['backtest-settings','回测设置'],['backtest-history','历史记录']]},
];
const settingsPages=[['factors','特征工程'],['targets','目标变量'],['models','模型库']];
function renderNavigation(){
  const activePage=settingsPages.some(([id])=>id===page)?'settings':page;
  const link=([id,name])=>`<button data-page="${id}" class="${activePage===id?'active':''}" ${activePage===id?'aria-current="page"':''}>${name}</button>`;
  $('#nav').innerHTML=navigationGroups.map((group,i)=>`<div class="nav-section" role="group" aria-labelledby="nav-section-${i}">
    <div class="nav-section-title" id="nav-section-${i}">${group.name}</div>
    ${group.links.map(link).join('')}
  </div>`).join('')+`<div class="nav-section nav-section-direct">
    ${link(['data','数据库'])}
  </div>`;
}

let catalog, page='training', category='全部', factorId, datasetId, selected=new Set(), detail=null, poll, toastTimer, activeChart=null, activeResize=null, backtestResult=null, btPage=1, btQuery='';
let activeDiagnostics=null,diagnosticsSplit='valid',diagnosticsExperiment=null;
let selectedRun=null, backtestRunSeed=null;
let renderVersion=0, experimentQuery='', experimentStatus='all', backtestSeed=null, pollBusy=false;
const previewGate=createRequestGate(), labelGate=createRequestGate(), evaluationGate=createRequestGate(),comparisonGate=createRequestGate();
const colors=['#3c72ee','#1aaa91','#ab86df','#e9ad53'];
const labelOf=categoryLabel;
const fmt=(v,n=3)=>v==null?'—':Number(v).toFixed(n), pct=v=>v==null?'—':(v*100).toFixed(2)+'%', money=(v,d=2)=>v==null?'—':Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}), date=s=>String(s||'').slice(0,10);
function toast(s){$('#toast').textContent=s;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4000)}
async function api(url,options={}){
  let res;
  try { res=await fetch('/api'+url,options); }
  catch { throw Error('连接中断，请确认本地服务正在运行后重试。'); }
  const body=await res.json().catch(()=>null);
  if(!res.ok){
    const message=Array.isArray(body?.detail)?body.detail.map(x=>`${x.loc?.slice(1).join('.')||'参数'}：${x.msg}`).join('；'):body?.detail;
    throw Error(typeof message==='string'?message:`请求失败（${res.status}），请稍后重试。`);
  }
  if(body===null)throw Error('服务返回格式异常，请重试。');
  return body;
}
async function panelRequest(url,node,current){
  try{return await api(url)}catch(error){if(current())node.innerHTML=`<div class="empty"><b>加载失败</b>${esc(error.message)}<br>${button('重新加载','retry')}</div>`;throw error}
}
const post=(url,body)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const specOf=id=>(catalog?.specs||[]).find(s=>s.id===id)||catalog?.recipes?.[id];
const paramsOf=f=>f.params||(f.window!=null?{window:f.window}:{});
const paramSummary=f=>{const e=Object.entries(paramsOf(f));return e.length?e.map(([k,v])=>`${k}=${v}`).join(' · '):'无参数'};

function badge(status){const m={completed:['完成','green'],running:['运行中','orange'],queued:['排队中','gray'],failed:['失败','red']};const [s,c]=m[status]||[status,'gray'];return `<span class="badge ${c}">${esc(s)}</span>`}
function head(title,sub,buttons=''){return `<div class="page-head"><div><h1>${title}</h1><p class="sub">${sub}</p></div><div class="actions">${buttons}</div></div>`}
function button(label,action,primary=false){return `<button class="btn ${primary?'primary':''}" data-action="${action}">${label}</button>`}
function empty(text='还没有完成的实验',hint='选择特征、目标和模型，开始第一次研究。'){return `<div class="empty"><b>${text}</b>${hint}<br>${button('＋ 新建实验','new-experiment',true)}</div>`}
function stat(label,value,note,cls=''){return `<div class="stat"><div class="label">${label}</div><div class="number ${cls}">${value}</div><div class="note">${note}</div></div>`}
function chart(series,{height=230,percent=false,hit=false}={}){const w=1000,l=58,r=20,t=15,b=30,all=series.flatMap(s=>s.values.filter(Number.isFinite));if(!all.length)return '<div class="empty">暂无有效曲线</div>';let min=Infinity,max=-Infinity;for(const value of all){min=Math.min(min,value);max=Math.max(max,value)}if(min===max){min-=.01;max+=.01}const pad=(max-min)*.12;min-=pad;max+=pad;const x=(i,n)=>l+i*(w-l-r)/Math.max(1,n-1),y=v=>t+(max-v)*(height-t-b)/(max-min);let svg=`<svg class="chart ${hit?'chart-hit':''}" viewBox="0 0 ${w} ${height}" role="img" aria-label="${esc(series.map(s=>s.name).join('、'))}趋势图">`;for(let i=0;i<5;i++){let v=min+(max-min)*i/4,yy=y(v);svg+=`<line x1="${l}" x2="${w-r}" y1="${yy}" y2="${yy}" stroke="#edf1f6" stroke-dasharray="3 4"/><text x="${l-10}" y="${yy+4}" text-anchor="end" font-size="10" fill="#9ba7b8">${percent?pct(v):fmt(v,2)}</text>`}series.forEach((s,j)=>{let pen=false,d='';s.values.forEach((v,i)=>{if(!Number.isFinite(v)){pen=false;return}d+=`${pen?'L':'M'}${x(i,s.values.length).toFixed(2)},${y(v).toFixed(2)} `;pen=true});svg+=`<path d="${d}" fill="none" stroke="${s.color||colors[j%4]}" stroke-width="2" ${s.dashed?'stroke-dasharray="5 5"':''}/>`});svg+='<line class="cursor-line" x1="0" x2="0" y1="10" y2="'+(height-b)+'" stroke="#a1b4dc" stroke-dasharray="3 3" opacity="0"/>';svg+='</svg>';return svg}
function legend(series){return `<div class="legend">${series.map((s,i)=>`<span><i style="background:${s.color||colors[i%4]}"></i>${esc(s.name)}</span>`).join('')}</div>`}
function datasetSelect(){return `<select class="inline-select" id="dataset-select" aria-label="预览数据集">${catalog.datasets.map(d=>`<option value="${d.id}" ${d.id===datasetId?'selected':''}>${esc(d.name)}</option>`).join('')}</select>`}
function applyCatalog(next){
  catalog=next;
  if(!catalog.datasets.some(d=>d.id===datasetId))datasetId=catalog.datasets[0]?.id;
  const features=[...catalog.factors,...(catalog.chan_event?.features||[])];
  if(!features.some(f=>f.id===factorId))factorId=features[0]?.id;
  selected=new Set([...selected].filter(id=>catalog.experiments.some(e=>e.id===id&&e.status==='completed')));
  renderNavigation();

}
async function render({cached=false}={}){
  const version=++renderVersion;
  if(!cached){const next=await api('/catalog');if(version!==renderVersion)return;applyCatalog(next)}
  else applyCatalog(catalog);
  clearKline();
  if(detail){await renderDetail();return}
  if(page==='training')await trainingPage();
  if(page==='settings')settingsPage();
  if(page==='backtest-settings')backtestSettingsPage();
  if(page==='backtest-history')await backtestPage();
  if(page==='experiments')experiments();
  if(page==='factors')await factorPage();
  if(page==='targets')await targetPage();
  if(page==='models')modelPage();
  if(page==='backtest')await backtestPage();
  if(page==='data')await dataPage();
}
function loading(text='正在加载…'){return `<div class="loading" role="status"><span class="spinner"></span>${esc(text)}</div>`}
function prerequisite(message,action,label){return `<div class="empty"><b>${message}</b>${button(label,action,true)}</div>`}
function rowsTable(exps,selectable=false){return `<div class="table-wrap"><table><thead><tr>${selectable?'<th>对比</th>':''}<th>实验名称</th><th>模型 / 目标</th><th>净收益</th><th>最大回撤</th><th>状态</th><th>操作</th></tr></thead><tbody>${exps.map(e=>`<tr>${selectable?`<td><input type="checkbox" aria-label="对比 ${esc(e.name)}" data-compare="${e.id}" ${selected.has(e.id)?'checked':''} ${e.status!=='completed'?'disabled':''}></td>`:''}<td><button class="table-link" data-detail="${e.id}">${esc(e.name)}</button><small>${esc(e.snapshot.dataset.name)} · ${e.snapshot.factors.length} 个特征</small></td><td>${esc(e.snapshot.config.model)}<small>${esc(e.snapshot.target.name)}</small></td><td class="${e.summary?.net_return>=0?'positive':'negative'}">${pct(e.summary?.net_return)}</td><td>${pct(e.summary?.max_drawdown)}</td><td>${badge(e.status)}${['running','queued','failed'].includes(e.status)?`<small class="run-message" title="${esc(e.message)}">${esc(e.message||'')}</small>`:''}</td><td><button class="table-link" data-copy="${e.id}">复制配置</button></td></tr>`).join('')}</tbody></table></div>`}
async function trainingPage(){
  const version=renderVersion;
  const root=$('#app');
  root.innerHTML=head('训练模型','选择行情范围、特征、目标变量和模型。',button('数据库','data'))+
    '<section class="panel training-config" id="training-config">'+loading('正在读取数据库标的…')+'</section>';
  const container=$('#training-config');
  const inventory=await panelRequest('/market/instruments',container,()=>page==='training'&&version===renderVersion);
  if(page!=='training'||version!==renderVersion)return;
  if(!inventory.instruments.length){
    container.innerHTML=prerequisite('数据库还没有可用标的','data','打开数据库');return;
  }
  mountExperimentWizard({
    catalog,inventory,datasetId,factorId,modal,
    mountForm(body){
      const container=$('#training-config');
      container.innerHTML=`<form id="training-form" data-kind="experiment">
        <div class="form-body">${body}<div id="form-error" class="error" role="alert"></div></div>
        <div class="form-footer"><button type="submit" class="btn primary">开始训练</button></div>
      </form>`;
      return container.querySelector('form');
    },
    marketRequest:(action,payload)=>post('/market/'+action,payload),
  });
}

function settingsPage(){
  const descriptions=['特征定义、分类与特征集','收益率、收益阈值与缠论结构确认','可用模型与训练参数'];
  $('#app').innerHTML=head('模型设置','管理训练时可选的配置。')+
    `<section class="panel settings-links">${settingsPages.map(([id,name],i)=>`
      <button type="button" class="settings-link" data-page="${id}">
        <span><strong>${name}</strong><span class="sub">${descriptions[i]}</span></span>
        <span class="settings-chevron" aria-hidden="true">›</span>
      </button>`).join('')}</section>`;
}

function settingsHead(title, description){
  return '<button type="button" class="btn settings-back" data-page="settings">← 返回模型设置</button>'+
    head(title,description);
}

function backtestSettingsPage(){
  $('#app').innerHTML=head('回测设置','仓位、交易成本和退出条件可在运行回测时设置。')+
    `<section class="panel"><div class="panel-head"><h2>交易参数</h2><button class="btn" data-page="backtest">打开回测配置</button></div></section>`;
}

function experiments(){
  $('#app').innerHTML=head('历史记录','查找研究记录，比较不同特征与模型的样本外表现。',`<button class="btn primary" data-page="training">训练模型</button>`)+
    `<section class="panel"><div class="panel-head"><h2>实验运行记录 <span class="badge gray">${catalog.experiments.length}</span></h2><button id="compare-button" class="btn small" data-action="compare" ${selected.size<2?'disabled':''}>对比选中实验（${selected.size}/4）</button></div>
    <div class="research-toolbar"><input id="experiment-search" type="search" placeholder="搜索实验、数据、模型或目标" aria-label="搜索实验" value="${esc(experimentQuery)}"><select id="experiment-status" aria-label="筛选实验状态">${[['all','全部状态'],['completed','已完成'],['running','运行中'],['queued','排队中'],['failed','失败']].map(([v,n])=>`<option value="${v}" ${v===experimentStatus?'selected':''}>${n}</option>`).join('')}</select><span id="experiment-count" class="selection-hint"></span></div>
    <div id="experiment-table"></div></section><div id="comparison"></div>`;
  updateExperimentTable();
}
function updateExperimentTable(){
  const items=filterExperiments(catalog.experiments,experimentQuery,experimentStatus);
  $('#experiment-count').textContent=`${items.length} 条结果`;
  $('#experiment-table').innerHTML=items.length?rowsTable(items,true):catalog.experiments.length?'<div class="empty"><b>没有匹配的实验</b>试试其他关键词或状态。</div>':empty();
}
let featureView='list',featureQuery='';
async function factorPage(){
  clearKline();previewGate.next();evaluationGate.next();
  const events=catalog.chan_event?.features||[];
  const all=[...catalog.factors,...events];
  const categories=['全部',...new Set([...catalog.categories.map(c=>c.name),...all.map(f=>labelOf(f.category))])];
  const visible=all.filter(f=>(category==='全部'||labelOf(f.category)===category)&&
    [f.name,paramSummary(f),labelOf(f.category)].join(' ').toLowerCase().includes(featureQuery.toLowerCase()));
  const chosen=visible.find(f=>f.id===factorId)||visible[0];
  if(chosen)factorId=chosen.id;
  const event=chosen&&events.some(f=>f.id===chosen.id);
  const tabs=`<div class="feature-tabs"><button class="table-link" data-feature-view="list" aria-pressed="${featureView==='list'}">全部特征</button><button class="table-link" data-feature-view="sets" aria-pressed="${featureView==='sets'}">特征集</button></div>`;
  $('#app').innerHTML=settingsHead('特征工程','浏览特征、设置计算参数，管理常用研究组合。')+tabs;
  if(featureView==='sets'){
    $('#app').insertAdjacentHTML('beforeend',`<section class="panel"><div class="panel-head"><h2>特征集</h2>${button('新建特征集','new-factor-set')}</div>${factorSetsTable()}</section>`);return;
  }
  $('#app').insertAdjacentHTML('beforeend',`
    <div class="feature-filter-row"><div class="filters">${categories.map(c=>`<button class="chip ${c===category?'active':''}" data-category="${esc(c)}">${esc(c)}</button>`).join('')}</div><button class="table-link" data-action="manage-categories">管理分类</button></div>
    <div class="feature-layout"><section class="panel feature-inventory">
      <div class="panel-head"><input id="feature-search" type="search" value="${esc(featureQuery)}" placeholder="搜索特征名称、参数…" aria-label="搜索特征"></div>
      <div class="feature-list-heading"><span>特征 · ${visible.length}</span><span>使用条件</span></div>
      ${visible.map(f=>`<button class="feature-row ${f.id===factorId?'selected':''}" data-factor="${esc(f.id)}" aria-pressed="${f.id===factorId}"><span><strong>${esc(f.name)}</strong><small>${esc(paramSummary(f))} · ${esc(labelOf(f.category))}</small></span><span class="badge gray">${events.some(e=>e.id===f.id)?'缠论事件':'K 线序列'}</span></button>`).join('')||'<div class="empty">没有匹配的特征</div>'}
    </section><section class="panel feature-detail">
      ${chosen?`<div class="panel-head"><div><span class="sub">${esc(labelOf(chosen.category))} · v${esc(chosen.version)}</span><h2>${esc(chosen.name)}</h2></div></div>
      <div class="panel-body"><p class="sub">${esc(chosen.description||specOf(chosen.spec_id||chosen.recipe)?.description||'')}</p>
      <div class="info-row"><span>计算参数</span><div class="actions">${esc(paramSummary(chosen))}
      ${specOf(chosen.spec_id||chosen.recipe)?.params?.length?'<button type="button" class="table-link" data-action="configure-feature">设置参数</button>':''}</div></div><div class="info-row"><span>使用条件</span>${event?'需要缠论事件采样':'每根 K 线可计算'}</div>
      <div class="feature-preview-heading"><h3>人工备注</h3><button type="button" class="table-link" data-action="edit-feature-note">${chosen.note?'编辑备注':'添加备注'}</button></div>
      ${chosen.note?`<p class="detail-note feature-note">${esc(chosen.note)}</p>`:''}
      ${event?`<p class="detail-note">按候选点首次出现的时间取值。</p>
      <div class="feature-preview-heading">${datasetSelect()}<button class="btn small" data-action="preview-event-feature">预览事件取值</button></div><div id="event-feature-preview"></div>
      <div class="actions feature-detail-actions"><button class="btn small" data-reclassify="${esc(chosen.id)}">更改分类</button><button class="btn small" data-action="new-factor-set">加入新特征集</button></div>`:`<div class="feature-preview-heading"><h3>特征预览</h3>${datasetSelect()}</div><div id="factor-preview"></div><div class="actions feature-detail-actions"><button class="btn small" data-reclassify="${esc(chosen.id)}">更改分类</button><button class="btn small" data-action="new-factor-set">加入新特征集</button>${chosen.registered?'':`<button class="table-link" data-archive="${esc(chosen.id)}">归档</button>`}</div>`}
      </div>`:'<div class="empty">选择特征查看详情</div>'}
    </section></div>
    <details class="panel"><summary class="panel-head">特征相关性分析</summary><div class="panel-body">${button('计算当前分类相关性','factor-corr')}<div id="factor-eval-panel" class="detail-note">使用训练区间的 Spearman 相关性检查重复特征。</div></div></details>`);
  if(chosen&&!event)await previewFactor();
}
function manageCategories(){
  modal('管理分类',`<div class="actions">${button('新建分类','new-category')}</div>${catalog.categories.map(c=>`<div class="info-row"><span>${esc(c.name)} · ${[...catalog.factors,...(catalog.chan_event?.features||[])].filter(f=>f.category===c.name).length} 项</span><div class="actions"><button type="button" class="table-link" data-category-edit="${esc(c.id)}">重命名</button><button type="button" class="table-link" data-category-remove="${esc(c.id)}">删除</button></div></div>`).join('')}`,'notice');
  $('#modal-form button[type=submit]').hidden=true;
}

async function previewFactor(){const target=$('#factor-preview'),token=previewGate.next();if(!target)return;clearKline();if(!datasetId){target.innerHTML=prerequisite('先导入行情，再观察特征的实际表现。','data','导入行情');return}if(!factorId){$('#factor-preview').innerHTML='<div class="empty">请选择特征</div>';return}target.innerHTML=loading('正在计算特征预览…');const p=await panelRequest(`/preview/${datasetId}?factor_id=${factorId}`,target,()=>previewGate.current(token)&&target===$('#factor-preview'));if(!previewGate.current(token)||target!==$('#factor-preview'))return;$('#factor-preview').innerHTML='<div id="factor-kline" style="height:260px"></div>'+`<div class="detail-note">上方：可交互 K 线（最近 400 根）；下方：最近 400 根特征值。特征值保留热身缺失，不使用未来值填补。</div>`+chart([{name:'特征值',values:p.factor}],{height:170})+`<div class="chart-caption"><span>${date(p.bars[0]?.date)}</span><span>${date(p.bars.at(-1)?.date)}</span></div>`;mountKline($('#factor-kline'),p.bars,{height:260})}
async function targetPage(){
  const sampling={bar:'K 线采样',chan_event:'缠论事件采样'};
  $('#app').innerHTML=settingsHead('目标变量','查看标签含义、确定时间与训练时可配置的参数。')+
    `<div class="cards">${catalog.targets.map(t=>`<article class="card">
      <div class="card-top"><span class="badge">${t.task==='regression'?'回归':'二分类'}</span><span class="sub">v${esc(t.version)}</span></div>
      <h3>${esc(t.name)}</h3><p>${esc(t.description)}</p><p>${esc(t.maturity)}</p>
      <p>${esc(t.sample_modes.map(mode=>sampling[mode]||mode).join('、'))}</p>
      <p>${t.parameters.map(p=>esc(p.description+' · 默认 '+p.default)).join('<br>')||'固定规则'}</p>
      <div class="card-foot"><button class="table-link" data-label="${esc(t.id)}">预览默认标签 →</button></div>
    </article>`).join('')}</div><section class="panel"><div class="panel-head"><h2>标签时间线</h2>${datasetSelect()}</div>
    <div class="panel-body" id="label-preview"><div class="detail-note">选择目标，查看默认参数下的标签值和确定时间。</div></div></section>`;
}
async function labelPreview(id){const target=$('#label-preview'),token=labelGate.next();if(!datasetId){target.innerHTML=prerequisite('先导入行情，再查看标签时间线。','data','导入行情');return}target.innerHTML=loading();const p=await panelRequest(`/label-preview/${datasetId}/${id}`,target,()=>labelGate.current(token)&&target===$('#label-preview'));if(!labelGate.current(token)||target!==$('#label-preview'))return;
  if(p.kind==='chan_structure'){
    const status={confirmed:'保留',invalidated:'撤销',pending:'待确认',ineligible:'不纳入训练'};
    target.innerHTML=`<p class="detail-note">保留 ${p.counts.confirmed} · 撤销 ${p.counts.invalidated} · 待确认 ${p.counts.pending}</p>`+(p.events.length?`<div class="table-wrap"><table><thead><tr><th>候选首次出现</th><th>标签确定时间</th><th>标签</th><th>状态</th></tr></thead><tbody>${p.events.slice().reverse().map(e=>`<tr><td>${esc(e.observed_time)}</td><td>${esc(e.label_time||'—')}</td><td>${e.label??'—'}</td><td>${esc(status[e.status])}</td></tr>`).join('')}</tbody></table></div>`:'<p class="sub">该区间没有候选买卖点。</p>');
    return;
  }
  $('#label-preview').innerHTML=`<div class="stats">${stat('① 特征截止',date(p.decision_time),'当根收盘决策')}${stat('② 最早入场',date(p.entry_time),'下一根开盘 '+fmt(p.entry_price,2))}${stat('③ 标签结束',date(p.end_time),'开盘 '+fmt(p.end_price,2))}${stat('④ 目标值',p.task==='binary'?p.label:pct(p.label),'只用于训练与事后评价')}</div>`}
function modelPage(){
  $('#app').innerHTML=settingsHead('模型库','按输入方式选择模型；新实验默认使用 LightGBM。')+groupedModels(catalog.models).map(g=>`
    <section><div class="section-heading"><div><h3>${esc(g.name)}</h3><p>${esc(g.description)}</p></div></div><div class="cards">${g.models.map(m=>`
      <article class="card"><div class="card-top"><span class="card-icon">◇</span><span class="badge ${m.available?'green':'gray'}">${m.available?'可用':'依赖未安装'}</span></div>
      <h3>${esc(m.name)} ${m.recommended?'<span class="badge blue">推荐</span>':''}</h3><p>${esc(m.description)}</p>
      <div class="info-row"><span>输入形式</span>${m.input==='sequence'?'历史窗口 × 特征':'当前特征向量'}</div>
      <div class="info-row"><span>回归输出</span>预测收益率</div><div class="info-row"><span>分类输出</span>正类概率 [0, 1]</div>
      <div class="info-row"><span>损失函数</span>${m.input==='sequence'?'MSE / BCEWithLogits':'平方误差 / Binary log loss'}</div>
      <div class="info-row"><span>专属诊断</span>${esc((m.diagnostics||[]).join(' / '))}</div>
      <div class="card-foot"><span>输出语义继承目标变量</span></div></article>`).join('')}</div></section>`).join('')+
    '<div class="banner">LSTM 与 GRU 使用历史窗口，以验证损失选择训练检查点；树模型采用固定参数。测试集仅用于最终评估。</div>';
}
let stopKlineHistory=null;
function clearKline(){
  if(stopKlineHistory){stopKlineHistory();stopKlineHistory=null}
  if(activeChart){activeChart.remove();activeChart=null}
  if(activeResize){window.removeEventListener('resize',activeResize);activeResize=null}
}
function mountKline(el,bars,{height=320}={}){
  if(!el)return null;
  clearKline();
  el.replaceChildren();
  if(!window.LightweightCharts){el.innerHTML='<div class="empty"><b>图表库未加载</b>请检查 /static/vendor/lightweight-charts.standalone.production.js</div>';return null}
  if(!bars||!bars.length){el.innerHTML='<div class="empty">当前数据集没有 K 线</div>';return null}
  const first=Date.parse(bars[0].date),second=bars.length>1?Date.parse(bars[1].date):first+86400000;
  const daily=(second-first)>=86400000*0.9;
  const chart=LightweightCharts.createChart(el,{
    width:el.clientWidth||900,height,
    layout:{background:{type:'solid',color:'#ffffff'},textColor:'#1b293d'},
    grid:{vertLines:{color:'#edf1f6'},horzLines:{color:'#edf1f6'}},
    rightPriceScale:{borderColor:'#e8edf3'},
    timeScale:{borderColor:'#e8edf3',timeVisible:!daily,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    localization:{priceFormatter:price=>price.toFixed(2)},
  });
  const candles=chart.addCandlestickSeries({upColor:'#159c80',downColor:'#ce5965',borderVisible:false,wickUpColor:'#159c80',wickDownColor:'#ce5965'});
  const volume=chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:''});
  volume.priceScale().applyOptions({scaleMargins:{top:.82,bottom:0}});
  const setBars=rows=>{
    candles.setData(rows.map(b=>({time:Math.floor(Date.parse(b.date)/1000),open:+b.open,high:+b.high,low:+b.low,close:+b.close})));
    volume.setData(rows.map(b=>({time:Math.floor(Date.parse(b.date)/1000),value:+b.volume,color:b.close>=b.open?'#159c8055':'#ce596555'})));
  };
  setBars(bars);
  chart.timeScale().fitContent();
  activeChart=chart;
  activeResize=()=>{const width=el.clientWidth;if(width)chart.resize(width,height)};
  window.addEventListener('resize',activeResize);
  return {chart,setBars,candles};
}
function enableKlineHistory(el,view,initial,url,current){
  const scale=view.chart.timeScale();
  const controls=document.createElement('div');
  controls.className='chart-caption';
  controls.innerHTML='<span role="status"></span><button type="button" class="btn small">加载更早行情</button>';
  el.after(controls);
  const status=controls.querySelector('span'),loadOlder=controls.querySelector('button');
  let rows=initial.bars,cursor=initial.next_before,request=null,failed=false;
  function ready(){
    status.textContent=cursor==null?'已到数据起点':'向左拖动可继续加载历史行情';
    loadOlder.hidden=cursor==null;
  }
  async function load(){
    if(request||cursor==null||!current())return;
    failed=false;
    request=new AbortController();
    const timer=setTimeout(()=>request?.abort(),10000);
    loadOlder.disabled=true;
    status.textContent='正在加载更早行情…';
    try{
      const p=await api(`${url}&before=${encodeURIComponent(cursor)}`,{signal:request.signal,cache:'no-store'});
      if(!current()||!controls.isConnected)return;
      const range=scale.getVisibleLogicalRange();
      if(p.bars.length){
        rows=[...p.bars,...rows];
        view.setBars(rows);
        if(range)scale.setVisibleLogicalRange({from:range.from+p.bars.length,to:range.to+p.bars.length});
      }
      cursor=p.next_before;
      ready();
    }catch(error){
      failed=true;
      if(current()&&controls.isConnected)status.textContent='历史行情加载失败，可点击右侧重试';
    }finally{
      clearTimeout(timer);
      request=null;
      loadOlder.disabled=false;
    }
  }
  const onRange=range=>{if(range&&range.from<=40&&!failed)void load()};
  scale.setVisibleLogicalRange({from:Math.max(0,rows.length-200),to:Math.max(1,rows.length-1)});
  scale.subscribeVisibleLogicalRangeChange(onRange);
  loadOlder.onclick=load;
  ready();
  stopKlineHistory=()=>{
    scale.unsubscribeVisibleLogicalRangeChange(onRange);
    request?.abort();
    controls.remove();
  };
}
const marketBrowser={symbol:'',period:'1m'};
function marketQuery(){
  const {symbol,period}=marketBrowser;
  return new URLSearchParams({symbol,period,limit:'1000'});
}
let marketLiveTimer;
async function mountDataKline(live=false){
  clearTimeout(marketLiveTimer);
  const el=$('#data-kline'),token=previewGate.next();
  if(!el)return;
  clearKline();
  const readout=$('#market-readout');
  readout.textContent='';
  if(!marketBrowser.symbol){el.innerHTML='<div class="empty">行情库还没有标的。</div>';return}
  el.innerHTML=loading('正在加载行情…');
  const current=()=>previewGate.current(token)&&el===$('#data-kline');
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),10000);
  const url=live?'/market/live?'+new URLSearchParams({symbol:marketBrowser.symbol}):'/market/candles?'+marketQuery();
  try{
    const result=await api(url,{signal:controller.signal,cache:'no-store'});
    if(!current())return;
    if(!result.bars.length){
      el.innerHTML='<div class="empty">所选级别或时间范围暂无入库行情。</div>';
      return;
    }
    const view=mountKline(el,result.bars,{height:420});
    if(!view)return;
    const showBar=bar=>{
      readout.textContent=`开 ${fmt(bar.open,2)}　高 ${fmt(bar.high,2)}　低 ${fmt(bar.low,2)}　收 ${fmt(bar.close,2)}`;
    };
    const latest=result.bars.at(-1);
    showBar(latest);
    view.chart.subscribeCrosshairMove(event=>showBar(event.seriesData.get(view.candles)||latest));
    if(live){
      const refreshLive=async()=>{
        if(!current())return;
        try{
          const next=await api(url,{cache:'no-store',signal:AbortSignal.timeout(10000)});
          if(!current())return;
          const bar=next.bars.at(-1);
          if(bar){
            view.setBars(next.bars);
            showBar(bar);
          }
        }catch(error){if(current())readout.textContent='实时行情更新失败，正在重试。'}
        if(current())marketLiveTimer=setTimeout(refreshLive,10000);
      };
      marketLiveTimer=setTimeout(refreshLive,10000);
    }else enableKlineHistory(el,view,result,url,current);
  }catch(error){
    if(current()){
      clearKline();
      const message=controller.signal.aborted?'行情加载超时':error.message;
      el.innerHTML=`<div class="empty"><b>无法显示 K 线</b>${esc(message)}<br>${button('重试','retry-kline')}</div>`;
    }
  }finally{clearTimeout(timer)}
}
function backtestChart(r){
  const rows=r.rows||[],trades=r.trades||[],initial=r.metrics.initial_cash||1;
  if(!rows.length)return '<div class="empty">暂无净值数据</div>';
  const w=1000,h=300,l=58,rr=62,t=15,b=28,n=rows.length;
  let min=initial,max=initial;for(const row of rows){min=Math.min(min,row.equity,row.benchmark*initial);max=Math.max(max,row.equity,row.benchmark*initial)}
  if(!Number.isFinite(min)||!Number.isFinite(max))return '<div class="empty">净值数据异常</div>';
  if(min===max){min-=.01;max+=.01}
  const pad=(max-min)*.08;min-=pad;max+=pad;
  const x=i=>l+(n<=1?0:i*(w-l-rr)/(n-1));
  const y=v=>t+(max-v)*(h-t-b)/(max-min);
  let svg=`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="净值曲线">`;
  svg+='<defs><linearGradient id="btArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#3c72ee" stop-opacity=".18"/><stop offset="100%" stop-color="#3c72ee" stop-opacity="0"/></linearGradient></defs>';
  for(let i=0;i<5;i++){
    const v=min+(max-min)*i/4,yy=y(v);
    svg+=`<line x1="${l}" x2="${w-rr}" y1="${yy}" y2="${yy}" stroke="#edf1f6" stroke-dasharray="3 4"/>`;
    svg+=`<text x="${l-10}" y="${yy+4}" text-anchor="end" font-size="10" fill="#9ba7b8">${money(v,0)}</text>`;
    const p=(v/initial-1)*100;
    svg+=`<text x="${w-rr+10}" y="${yy+4}" text-anchor="start" font-size="10" fill="#9ba7b8">${p>=0?'+':''}${p.toFixed(1)}%</text>`;
  }
  const pts=rows.map((row,i)=>`${x(i).toFixed(2)},${y(row.equity).toFixed(2)}`);
  svg+=`<path d="M${x(0).toFixed(2)},${(h-b).toFixed(2)} L${pts.join(' L')} L${x(n-1).toFixed(2)},${(h-b).toFixed(2)} Z" fill="url(#btArea)"/>`;
  svg+=`<path d="M${pts.join(' L')}" fill="none" stroke="#3c72ee" stroke-width="2"/>`;
  const baseline=rows.map((row,i)=>`${x(i).toFixed(2)},${y(row.benchmark*initial).toFixed(2)}`);
  svg+=`<path d="M${baseline.join(' L')}" fill="none" stroke="#8d9bb1" stroke-width="1.5" stroke-dasharray="5 5"/>`;
  for(let i=0;i<5;i++){
    const idx=Math.min(n-1,Math.round((n-1)*i/4));
    svg+=`<text x="${x(idx)}" y="${h-8}" text-anchor="middle" font-size="10" fill="#9ba7b8">${date(rows[idx].time)}</text>`;
  }
  const indexByTime={};rows.forEach((row,i)=>indexByTime[row.time]=i);
  trades.forEach(tr=>{
    const ei=indexByTime[tr.entry_time],xi=indexByTime[tr.exit_time];
    if(ei!=null){const cx=x(ei),cy=y(rows[ei].equity);svg+=`<polygon points="${cx},${cy-15} ${cx-5},${cy-4} ${cx+5},${cy-4}" fill="#159c80" opacity=".95"/>`}
    if(xi!=null){const cx=x(xi),cy=y(rows[xi].equity);svg+=`<polygon points="${cx},${cy+15} ${cx-5},${cy+4} ${cx+5},${cy+4}" fill="#ce5965" opacity=".95"/>`}
  });
  return svg+'</svg>';
}
function backtestExecutionPanel(current){
  const r=current.result,c=r.config||current.config||{},orders=r.orders||[];
  return `<details class="panel"><summary class="panel-head"><h2>执行配置与订单明细</h2><span class="selection-hint">${orders.length} 笔成交订单 · 点击展开</span></summary><div class="panel-body"><div class="detail-note">手续费 ${fmt(c.fee_bps,1)} bps / 滑点 ${fmt(c.slippage_bps,1)} bps / 仓位 ${pct(c.position_pct)}<br>止损 ${c.stop_loss_pct?pct(c.stop_loss_pct):'关闭'} / 止盈 ${c.take_profit_pct?pct(c.take_profit_pct):'关闭'} / 最大持有 ${c.max_hold_bars?c.max_hold_bars+' 根':'不限'}<br>下一根开盘成交；期末收盘平仓。以下展示最近 50 笔订单。</div><div class="table-wrap"><table><thead><tr><th>信号时间</th><th>成交时间</th><th>方向</th><th>成交价格</th><th>数量</th><th>手续费</th><th>原因</th></tr></thead><tbody>${orders.slice(-50).reverse().map(o=>`<tr><td>${esc(o.signal_time)}</td><td>${esc(o.time)}</td><td>${o.side==='buy'?'买入':'卖出'}</td><td>${money(o.price)}</td><td>${fmt(o.qty,6)}</td><td>${money(o.fee)}</td><td>${esc(o.reason)}</td></tr>`).join('')||'<tr><td colspan="7">没有成交订单</td></tr>'}</tbody></table></div></div></details>`;
}
function backtestReport(current){
  const r=current.result,m=r.metrics;
  const trades=r.trades||[];
  const fallbackSymbol=(current.dataset?.name||'标的').split(' · ')[0];
  const holding=r.holding||{symbol:fallbackSymbol,name:fallbackSymbol,direction:trades.length?'多头':'空仓',trade_count:trades.length,realized_pnl:trades.reduce((sum,t)=>sum+t.pnl,0),market_value:0,margin:0,fees:m.total_fees};
  const query=btQuery.toLowerCase();
  const filtered=query?trades.filter(t=>`${t.entry_time} ${t.exit_time} ${t.exit_reason}`.toLowerCase().includes(query)):trades;
  const pageSize=10,pages=Math.max(1,Math.ceil(filtered.length/pageSize));
  const page=Math.max(1,Math.min(btPage,pages));
  const shown=filtered.slice((page-1)*pageSize,page*pageSize);
  const pageButtons=pageWindow(page,pages).map((n,i,list)=>`${i&&n-list[i-1]>1?'<span>…</span>':''}<button class="btn small ${page===n?'active':''}" data-bt-page="${n}" aria-label="第 ${n} 页" ${page===n?'aria-current="page"':''}>${n}</button>`).join('');
  const kpi=(label,value,cls='')=>`<div class="stat compact"><div class="label">${label}</div><div class="number ${cls}">${value}</div></div>`;
  const stats=[
    kpi('总收益',pct(m.net_return),m.net_return>=0?'positive':'negative'),
    kpi('年化',pct(m.annualized_return),m.annualized_return>=0?'positive':'negative'),
    kpi('最大回撤',pct(m.max_drawdown),m.max_drawdown<0?'negative':''),
    kpi('夏普',fmt(m.sharpe,2)),
    kpi('交易笔数',m.trade_count??'—'),
    kpi('最终权益',money(m.final_equity)),
    kpi('基准收益',pct(m.benchmark_return),m.benchmark_return>=0?'positive':'negative'),
    kpi('基准年化',pct(m.benchmark_annualized),m.benchmark_annualized>=0?'positive':'negative'),
    kpi('索提诺',fmt(m.sortino,2)),
    kpi('卡玛',fmt(m.calmar,2))
  ].join('');
  const rowsHtml=shown.length?shown.map(t=>`<tr><td>${date(t.entry_time)}</td><td>${date(t.exit_time)}</td><td>${fmt(t.entry_price,2)}</td><td>${fmt(t.exit_price,2)}</td><td>${fmt(t.qty,6)}</td><td class="${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</td><td>${t.hold_bars}</td><td>${esc(t.exit_reason)}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">没有匹配的成交</td></tr>';
  return `<div class="page-head"><div><h1>${esc(current.name)}</h1><p class="sub">订单级回测 · ${date(r.period?.start)} – ${date(r.period?.end)} · ${date(current.created_at)} · ${esc(current.engine_version||'旧版引擎')}</p></div><div class="actions"><button class="btn" data-action="backtest-close">× 关闭报告</button></div></div><div class="stats five compact">${stats}</div><section class="panel"><div class="panel-head"><h2>净值曲线</h2>${legend([{name:'策略净值'},{name:'买入持有',color:'#8d9bb1'},{name:'买入',color:'#159c80'},{name:'卖出',color:'#ce5965'}])}</div><div class="panel-body">${backtestChart(r)}<div class="chart-caption"><span>绿色三角买入 · 红色三角卖出</span><span>${date(r.period?.start)} → ${date(r.period?.end)}</span></div></div></section><section class="panel"><div class="panel-head"><h2>持仓与标的收益</h2><span class="badge gray">期末已平仓 · ${holding.trade_count} 笔往返交易</span></div><div class="panel-body"><div class="summary-row"><div class="summary-item"><span>市值</span><b>${money(holding.market_value)}</b></div><div class="summary-item"><span>初始资金</span><b>${money(m.initial_cash)}</b></div><div class="summary-item"><span>手续费</span><b>${money(holding.fees)}</b></div></div><div class="table-wrap"><table><thead><tr><th>标的代码</th><th>标的名称</th><th>方向</th><th>交易总笔数</th><th>最终收益</th></tr></thead><tbody><tr><td>${esc(holding.symbol)}</td><td>${esc(holding.name)}</td><td>${esc(holding.direction)}</td><td>${holding.trade_count}</td><td class="${holding.realized_pnl>=0?'positive':'negative'}">${money(holding.realized_pnl)}</td></tr></tbody></table></div></div></section><section class="panel"><div class="panel-head"><h2>成交记录</h2><div class="pager">共 ${filtered.length} 条 ${pageButtons}</div></div><div class="panel-body"><div class="table-toolbar"><input class="table-search" id="bt-search" placeholder="搜索日期 / 原因" value="${esc(btQuery)}"><div class="pager">第 ${page} / ${pages} 页</div></div><div class="table-wrap"><table><thead><tr><th>入场</th><th>出场</th><th>入场价</th><th>出场价</th><th>数量</th><th>收益</th><th>持有</th><th>原因</th></tr></thead><tbody>${rowsHtml}</tbody></table></div></div></section>${backtestExecutionPanel(current)}`;
}
async function backtestPage(){
  if(backtestResult){
    $('#app').innerHTML=backtestReport(backtestResult);
    const search=$('#bt-search');
    if(search)search.onchange=()=>{btQuery=search.value.trim();btPage=1;backtestPage()};
    return;
  }
  const datasets=catalog.datasets||[];
  const experiments=(catalog.experiments||[]).filter(e=>e.snapshot.config.sample_mode!=='chan_event');
  if(page==='backtest-history'){
    const recent=catalog.backtests||[];
    const rows=recent.map(b=>`<tr><td><button class="table-link" data-backtest="${esc(b.id)}">${esc(b.name)}</button><small>${esc(b.source?.kind||'')}</small></td><td>${pct(b.metrics?.net_return)}</td><td>${pct(b.metrics?.max_drawdown)}</td><td>${b.metrics?.trade_count??'—'}</td><td>${date(b.created_at)}</td></tr>`).join('');
    $('#app').innerHTML=head('回测历史记录','查看已完成的回测。')+
      `<section class="panel">${recent.length?`<div class="table-wrap"><table><thead><tr><th>名称</th><th>净收益</th><th>最大回撤</th><th>成交</th><th>创建</th></tr></thead><tbody>${rows}</tbody></table></div>`:'<div class="empty">还没有回测记录</div>'}</section>`;
    return;
  }
  const current=backtestResult;
  const r=current?.result;
  const cfg=r?.config||{};
  const src=backtestSeed?'experiment':current?.source?.kind||'sma';
  const selectedDataset=current?.dataset?.id||datasetId||datasets[0]?.id||'';
  const selectedExperiment=backtestSeed||current?.source?.experiment_id||experiments[0]?.id||'';
  $('#app').innerHTML=head('运行回测','订单级执行：收盘信号、下一根开盘成交，含手续费、滑点、止损止盈。')
    +`<section class="panel"><div class="panel-head"><h2>回测配置</h2><span class="badge gray">单标的 · 只做多/空仓</span></div><div class="panel-body"><form id="backtest-form">`
    +`<div class="form-grid">${field('回测名称','name',current?.name||((datasets.find(d=>d.id===selectedDataset)?.name||'单标的')+' · SMA 回测'),'text','required maxlength="100"')}${selectField('信号来源','source',`<option value="sma" ${src==='sma'?'selected':''}>SMA 规则</option><option value="experiment" ${src==='experiment'?'selected':''}>实验预测</option>`)}</div>`
    +`<div id="sma-fields" class="form-grid">${selectField('数据快照','dataset_id',datasets.map(d=>`<option value="${d.id}" ${d.id===selectedDataset?'selected':''}>${esc(d.name)}</option>`).join('')||'<option value="">暂无数据</option>')}${field('快线','fast',current?.source?.fast??20,'number','min="1" max="250" required')}${field('慢线','slow',current?.source?.slow??60,'number','min="2" max="500" required')}</div>`
    +`<div id="experiment-fields" class="form-grid" style="display:none">${selectField('实验','experiment_id',experiments.map(e=>`<option value="${e.id}" ${e.id===selectedExperiment?'selected':''}>${esc(e.name)}</option>`).join('')||'<option value="">暂无已完成实验</option>')}${selectField('运行记录','run_id','<option value="">正在读取运行记录…</option>')}${field('开仓阈值（可选）','threshold',current?.source?.threshold??'','number','step="any" min="-1" max="1"')}<small>选择已完成的运行后，可调整阈值、成本和风控，无需重新训练。</small></div>`
    +`<div class="form-grid">${field('初始资金（行情计价单位）','initial_cash',cfg.initial_cash??100000,'number','min="1" step="any" required')}${field('手续费（bps）','fee_bps',cfg.fee_bps??5,'number','min="0" max="1000" step="any" required')}${field('滑点（bps）','slippage_bps',cfg.slippage_bps??2,'number','min="0" max="1000" step="any" required')}${field('仓位比例','position_pct',cfg.position_pct??1,'number','min="0.01" max="1" step="any" required')}</div>`
    +`<div class="form-grid">${field('止损（比例，0 关闭）','stop_loss_pct',cfg.stop_loss_pct??0,'number','min="0" max="0.9" step="any" required')}${field('止盈（比例，0 关闭）','take_profit_pct',cfg.take_profit_pct??0,'number','min="0" max="10" step="any" required')}${field('最大持有根数（0 关闭）','max_hold_bars',cfg.max_hold_bars??0,'number','min="0" max="1000" step="1" required')}</div>`
    +`<div class="actions"><button class="btn primary" type="submit">运行回测</button><span class="selection-hint">信号在收盘产生，下一根开盘成交；止损/止盈用当根 high/low 触发。</span></div><div class="error" id="backtest-error"></div></form></div></section>`;
  const sourceSel=$('#source');
  const syncSource=()=>{
    const isSma=sourceSel.value==='sma';
    for(const [id,on] of [['sma-fields',isSma],['experiment-fields',!isSma]]){
      const group=$('#'+id);group.hidden=!on;group.style.display=on?'':'none';
      group.querySelectorAll('input,select').forEach(el=>el.disabled=!on);
    }
    const ready=isSma?datasets.length:experiments.length;
    $('#backtest-form button[type=submit]').disabled=!ready;
    $('#backtest-error').textContent=ready?'':isSma?'请先在行情数据页导入数据。':'请先完成一次模型实验，再使用预测信号回测。';
  };
  const syncCosts=()=>{
    if(sourceSel.value!=='experiment')return;
    const selected=experiments.find(e=>e.id===$('#experiment_id').value);
    if(!selected)return;
    $('#fee_bps').value=selected.snapshot?.config?.cost_bps??5;
    $('#slippage_bps').value=0;
    $('#threshold').value='';
  };
  if(sourceSel){sourceSel.onchange=()=>{syncSource();syncCosts()};syncSource()}
  let runRequest=0, runsReady=false;
  const loadRuns=async(preferred=null)=>{
    const token=++runRequest, input=$('#run_id'), experiment=$('#experiment_id').value;
    runsReady=false;$('#backtest-form button[type=submit]').disabled=sourceSel.value==='experiment';
    input.innerHTML='<option value="">正在读取运行记录…</option>';
    try{
      const records=experiment?await api('/experiments/'+experiment+'/runs'):[];
      if(token!==runRequest||input!==$('#run_id'))return;
      const completed=records.filter(r=>r.status==='completed');
      input.innerHTML=completed.map(r=>`<option value="${esc(r.id)}">${esc(r.created_at||'历史运行')} · ${esc(r.id.slice(0,8))}</option>`).join('')||'<option value="">没有已完成的运行</option>';
      if(completed.some(r=>r.id===preferred))input.value=preferred;
      runsReady=completed.length>0;
      if(sourceSel.value==='experiment'){$('#backtest-form button[type=submit]').disabled=!runsReady;$('#backtest-error').textContent=runsReady?'':'该实验没有已完成的运行。'}
    }catch(error){if(input===$('#run_id')){$('#backtest-error').textContent=error.message;input.innerHTML='<option value="">读取失败，请重新选择实验</option>'}}
  };
  $('#experiment_id').onchange=()=>{syncCosts();void loadRuns()};
  sourceSel.onchange=()=>{syncSource();syncCosts();if(sourceSel.value==='experiment')void loadRuns()};
  const formNode=$('#backtest-form');
  await loadRuns(backtestRunSeed||current?.source?.run_id);if(formNode!==$('#backtest-form'))return;backtestRunSeed=null;
  if(backtestSeed){syncCosts();$('#name').value=(experiments.find(e=>e.id===backtestSeed)?.name||'实验')+' · 回测';backtestSeed=null}
}
async function dataPage(){
  const version=renderVersion;
  const root=$('#app');
  root.innerHTML=head('数据库','')+loading('正在读取行情库…');
  const inventory=await panelRequest('/market/instruments',root,()=>page==='data'&&version===renderVersion);
  if(page!=='data'||version!==renderVersion)return;
  const instruments=inventory.instruments;
  if(!marketBrowser.symbol)marketBrowser.symbol=instruments[0]?.symbol||'BTCUSDT';
  const availableSymbols=new Set([marketBrowser.symbol,...instruments.map(item=>item.symbol)]);
  root.innerHTML=head('数据库','OKX · USDT 本位永续')+`
    <section class="panel market-panel">
      <div class="panel-head market-toolbar">
        <select id="market-browser-symbol" aria-label="标的"></select>
        <div id="market-browser-periods" class="market-periods" role="group" aria-label="K 线级别"></div>
      </div>
      <div class="panel-body">
        <div class="actions">
          <button type="button" id="market-full" class="btn">下载历史行情</button>
          <button type="button" id="market-incremental" class="btn primary">补充新数据</button>
        </div>
        <p class="sub" id="market-job-status" role="status"></p>
        <div id="market-job-reports"></div>
        <div class="chart-caption"><span id="market-coverage"></span><span>图表时间（UTC）</span></div>
        <div id="market-readout" class="market-readout"></div>
        <div id="data-kline" style="min-height:420px"></div>
      </div>
    </section>`;
  const periodList=$('#market-browser-periods');
  const storedPeriods=()=>instruments.find(item=>item.symbol===marketBrowser.symbol)?.periods||{};
  function refresh(){
    const stored=storedPeriods();
    const live=!stored['1m'];
    if(live||!stored[marketBrowser.period])marketBrowser.period='1m';
    periodList.hidden=live;
    periodList.innerHTML=Object.keys(stored).map(level=>`<button type="button" class="chip ${level===marketBrowser.period?'active':''}" data-market-level="${level}" aria-pressed="${level===marketBrowser.period}">${level}</button>`).join('');
    const coverage=stored[marketBrowser.period];
    $('#market-coverage').textContent=live?'OKX 实时预览 · 1m':`库内范围 ${coverage.start} 至 ${coverage.end}`;
    return mountDataKline(live);
  }
  periodList.onclick=event=>{
    const level=event.target.closest('[data-market-level]')?.dataset.marketLevel;
    if(level&&level!==marketBrowser.period){marketBrowser.period=level;void refresh()}
  };
  const selector=$('#market-browser-symbol'),jobStatus=$('#market-job-status');
  const full=$('#market-full'),incremental=$('#market-incremental'),reports=$('#market-job-reports');
  let latestJobs=[],published=new Set(),pollTimer;
  const active=job=>['queued','running'].includes(job?.status);
  const currentJob=()=>latestJobs.find(job=>job.symbol===marketBrowser.symbol);
  function updateSelector(){
    selector.replaceChildren(...[...availableSymbols].sort().map(symbol=>new Option(symbol.replace(/USDT$/,''),symbol)));
    selector.value=marketBrowser.symbol;
  }
  function updateJob(){
    const job=currentJob();
    full.hidden=Boolean(storedPeriods()['1m']);
    incremental.hidden=!full.hidden;
    full.disabled=incremental.disabled=active(job);
    jobStatus.textContent=job?.message||'';
    reports.innerHTML=Object.entries(job?.reports||{}).map(([period,report])=>{
      const differences=(report.details||[]).map(row=>`<li>${esc(row.time)} · ${esc(Object.entries(row.fields).map(([name,values])=>`${name} ${values.local} / ${values.exchange}`).join('、'))}</li>`).join('');
      const audit=report.state==='insufficient'?report.message:marketAuditText(report);
      const changes=report.added==null?'':` · 新增 ${report.added.toLocaleString()} · 修正 ${report.revised.toLocaleString()}`;
      return `<div class="info-row"><strong>${esc(period)}</strong><span>${esc(audit+changes)}</span></div>`+
        (differences?`<details><summary>差异明细（本地 / 交易所）</summary><ul>${differences}</ul></details>`:'');
    }).join('');
  }
  async function pollJobs(){
    clearTimeout(pollTimer);
    try{
      const jobs=await api('/market/jobs');
      if(!selector.isConnected)return;
      latestJobs=jobs;
      const completed=jobs.filter(job=>job.status==='completed'&&!published.has(job.id));
      if(completed.length){
        const fresh=await api('/market/instruments');
        if(!selector.isConnected)return;
        completed.forEach(job=>published.add(job.id));
        instruments.splice(0,instruments.length,...fresh.instruments);
        fresh.instruments.forEach(item=>availableSymbols.add(item.symbol));
        updateSelector();
        await refresh();
      }
      updateJob();
      if(jobs.some(active))pollTimer=setTimeout(pollJobs,1500);
    }catch(error){
      if(selector.isConnected){jobStatus.textContent=error.message;pollTimer=setTimeout(pollJobs,4000)}
    }
  }
  async function startJob(mode){
    full.disabled=incremental.disabled=true;
    jobStatus.textContent='正在提交同步任务…';
    try{
      const job=await post('/market/jobs',{symbol:marketBrowser.symbol,mode});
      if(!selector.isConnected)return;
      latestJobs=[job,...latestJobs.filter(item=>item.symbol!==job.symbol)];
      updateJob();
      void pollJobs();
    }catch(error){if(selector.isConnected){updateJob();jobStatus.textContent=error.message}}
  }
  full.onclick=()=>{
    const symbol=marketBrowser.symbol;
    if(window.confirm(`下载 ${symbol.replace(/USDT$/,'')}-USDT-SWAP 的 OKX 分钟历史行情？`))void startJob('full');
  };
  incremental.onclick=()=>startJob('incremental');
  selector.onchange=()=>{
    marketBrowser.symbol=selector.value;
    updateJob();
    void refresh();
  };
  updateSelector();
  updateJob();
  void pollJobs();
  void api('/market/contracts').then(({symbols})=>{
    if(!selector.isConnected)return;
    symbols.forEach(symbol=>availableSymbols.add(symbol));
    updateSelector();
  }).catch(error=>{
    if(selector.isConnected&&!currentJob())jobStatus.textContent=error.message;
  });
  await refresh();
}

async function renderDetail(){const id=detail,version=renderVersion;let e=await api('/experiments/'+id);const executions=await api('/experiments/'+id+'/runs');const chosen=selectedRun||e.latest_run_id;const run=chosen?await api('/runs/'+chosen):null;if(run)e={...e,...run,id:e.id,result:run.result};const r=e.result;if(id!==detail||version!==renderVersion)return;activeDiagnostics=r?.diagnostics||null;if(diagnosticsExperiment!==id){diagnosticsSplit='valid';diagnosticsExperiment=id}$('#app').innerHTML=head(esc(e.name),`实验 ${e.id} · ${esc(e.snapshot.dataset.name)}${e.snapshot.factor_set?' · 特征集 '+esc(e.snapshot.factor_set.name):''}`,button('← 返回实验','back')+`<button class="btn" data-rerun="${e.id}">原配置重新运行</button>`+(e.status==='completed'&&r?.kind!=='chan_event'?`<button class="btn primary" data-replay="${e.id}" data-run="${esc(chosen||'')}">用此预测回测</button>`:'')+`<button class="btn" data-copy="${e.id}">复制配置</button>${['running','queued'].includes(e.status)?'':`<button class="btn" data-delete-experiment="${esc(e.id)}">删除实验</button>`}<a class="btn" href="${chosen?'/api/runs/'+chosen:'/api/experiments/'+e.id+'/export'}" download="${esc(chosen||e.id)}.json">导出 JSON</a>`)+`<div class="banner">${badge(e.status)} ${esc(e.message)} <span style="margin-left:auto">${esc(e.snapshot.config.model)} · ${esc(e.snapshot.target.name)}</span></div>`;$('#app').insertAdjacentHTML('beforeend',`<section class="panel"><div class="panel-body"><label for="detail-run">历史运行</label><select id="detail-run"><option value="">跟随最新运行</option>${executions.map(x=>`<option value="${esc(x.id)}" ${selectedRun===x.id?'selected':''}>${esc(x.created_at||'历史运行')} · ${esc(x.id.slice(0,8))} · ${esc(x.status)}</option>`).join('')}</select><p class="detail-note">每次运行保留独立结果。重新运行沿用当前实验的冻结配置。</p></div></section>`);const marketAudit=marketAuditText(e.snapshot.dataset.market_audit);if(marketAudit)$('#app').insertAdjacentHTML('beforeend',`<p class="detail-note">${esc(marketAudit)}</p>`);if(!r)return;if(r.kind==='prediction_only'){$('#app').innerHTML+=`<div id="model-diagnostics">${renderDiagnostics(r.diagnostics,diagnosticsSplit)}</div><p class="detail-note">预测已保存。可点击“用此预测回测”配置交易策略。</p>`;return}if(r.kind==='chan_event'){$('#app').innerHTML+=`<div id="model-diagnostics">${renderDiagnostics(r.diagnostics,diagnosticsSplit)}</div>${eventPanel(r.event_report,true,r.output)}<div class="detail-note">${esc(r.policy)}</div>`;return}$('#app').innerHTML+=`<div id="model-diagnostics">${renderDiagnostics(r.diagnostics,diagnosticsSplit)}</div><div class="section-heading"><div><h2>交易表现</h2><p>以下指标评价预测转交易后的结果，与上方模型诊断分开观察。</p></div></div><div class="stats">${stat('样本外净收益',pct(r.metrics.net_return),'含每侧 '+e.snapshot.config.cost_bps+' bps 成本',r.metrics.net_return>=0?'positive':'negative')}${stat('最大回撤',pct(r.metrics.max_drawdown),'从初始净值 1 开始统计')}${stat('成交次数',r.metrics.trade_count,'含期末平仓')}${stat(r.output.task==='regression'?'预测 MAE':'分类 AUC',fmt(r.output.task==='regression'?r.metrics.mae:r.metrics.auc,4),r.output.task==='regression'?'收益率比例单位':'仅测试集 · 单一类别时不定义')}</div><section class="panel"><div class="panel-head"><h2>样本外轨迹</h2>${legend([{name:'策略净值'},{name:'买入持有',color:'#bdc6d5'}])}</div><div class="panel-body"><div id="detail-chart">${chart([{name:'策略净值',values:[1,...r.rows.map(x=>x.equity)]},{name:'买入持有',values:[1,...r.rows.map(x=>x.benchmark)],color:'#bdc6d5',dashed:true}],{hit:true})}</div><div class="chart-caption"><span>${date(r.rows[0]?.entry_time)}</span><span>移动鼠标查看对应决策与特征</span><span>${date(r.rows.at(-1)?.time)}</span></div><div id="inspector" class="inspect"></div></div></section><div class="grid-two"><section class="panel"><div class="panel-head"><h2>预测值与实际标签</h2><span class="badge gray">${esc(r.output.meaning)}</span></div><div class="panel-body">${legend([{name:'预测值'},{name:'实际标签',color:'#c4cedd'}])}${chart([{name:'预测值',values:r.rows.map(x=>x.prediction)},{name:'实际标签',values:r.rows.map(x=>x.label),color:'#c4cedd'}],{height:200})}</div></section><section class="panel"><div class="panel-head"><h2>时间切分与标签隔离</h2></div><div class="panel-body">${Object.entries(r.splits).map(([k,v])=>`<div class="info-row"><span>${{train:'训练',valid:'验证',test:'测试'}[k]} · ${v.count} 样本</span>${date(v.start)} → ${date(v.end)}</div>`).join('')}<p class="sub" style="margin-top:14px">原始时间轴 60 / 20 / 20 切分；剔除标签跨界样本。标准化只拟合训练输入。</p></div></section></div><section class="panel"><div class="panel-head"><h2>执行约定</h2></div><div class="panel-body"><div class="detail-note">${esc(r.policy)}</div></div></section><section class="panel"><div class="panel-head"><h2>成交记录</h2><span class="selection-hint">显示最近 50 条 · 完整记录可导出</span></div><div class="table-wrap"><table><thead><tr><th>信号日期</th><th>成交日期</th><th>动作</th><th>成交价</th><th>仓位变化</th><th>成本比例</th></tr></thead><tbody>${r.trades.slice(-50).reverse().map(t=>`<tr><td>${date(t.signal_time)||'期末'}</td><td>${date(t.time)}</td><td>${esc(t.action)}</td><td>${fmt(t.price,2)}</td><td>${pct(t.weight_change)}</td><td>${pct(t.cost_rate)}</td></tr>`).join('')}</tbody></table></div></section>${!r.diagnostics&&r.history.length?`<section class="panel"><div class="panel-head"><h2>训练过程</h2></div><div class="panel-body">${legend([{name:'训练损失'},{name:'验证损失'}])}${chart([{name:'训练损失',values:r.history.map(x=>x.train)},{name:'验证损失',values:r.history.map(x=>x.valid)}])}<p class="sub">回归损失在训练目标标准化后的尺度计算。</p></div></section>`:''}`;const inspect=i=>{const row=r.rows[Math.max(0,Math.min(i,r.rows.length-1))];$('#inspector').innerHTML=`<strong>信号 ${date(row.signal_time)}</strong> → ${date(row.entry_time)} 开盘调仓 → ${date(row.time)} 计价 <div class="inspect-grid"><div>预测<span>${row.valid_prediction?fmt(row.prediction,5):'缺失 · 空仓'}</span></div><div>实际标签<span>${fmt(row.label,5)}</span></div><div>仓位<span>${pct(row.weight)}</span></div><div>区间净收益<span>${pct(row.net_return)}</span></div>${e.snapshot.factors.map(f=>`<div>${esc(f.name)}<span>${fmt(row.features[f.id],5)}</span></div>`).join('')}</div>`};inspect(0);$('#detail-chart svg').onmousemove=ev=>{const svg=ev.currentTarget,rect=svg.getBoundingClientRect(),x=(ev.clientX-rect.left)/rect.width*1000,idx=Math.round((x-58)/922*r.rows.length)-1;inspect(idx);const line=svg.querySelector('.cursor-line');line.setAttribute('x1',Math.max(58,Math.min(980,x)));line.setAttribute('x2',Math.max(58,Math.min(980,x)));line.setAttribute('opacity',1)}}
function factorSetsTable(){const sets=catalog.factor_sets||[];if(!sets.length)return '<div class="empty">还没有特征集<b>把常用特征组合保存下来，实验时直接引用。</b></div>';return `<div class="table-wrap"><table><thead><tr><th>名称</th><th>特征数</th><th>清单哈希</th><th>创建时间</th></tr></thead><tbody>${sets.map(s=>`<tr><td>${esc(s.name)}<small>${esc(s.description||'')}</small></td><td>${s.factor_ids.length}</td><td class="mono">${esc((s.manifest_hash||'').slice(0,16))}…</td><td>${date(s.created_at)}</td></tr>`).join('')}</tbody></table></div>`}
async function factorCorrelation(){
  const target=$('#factor-eval-panel'),token=evaluationGate.next(),sourceDataset=datasetId,sourceCategory=category;
  if(!datasetId){target.innerHTML=prerequisite('先导入行情，再计算特征相关性。','data','导入行情');return}
  const ids=catalog.factors.filter(f=>category==='全部'||labelOf(f.category)===category).map(f=>f.id);
  if(ids.length<2){target.innerHTML='<div class="detail-note">当前分类不足两个特征，无法计算相关性。切换到「全部」或补充特征后再试。</div>';return}
  const use=ids.slice(0,20);
  target.innerHTML=loading('正在计算训练区间的特征相关性…');
  try{
    const p=await api(`/factor-correlation/${datasetId}?factor_ids=${use.join(',')}`);
    if(!evaluationGate.current(token)||target!==$('#factor-eval-panel')||sourceDataset!==datasetId||sourceCategory!==category)return;
    const names=Object.fromEntries(catalog.factors.map(f=>[f.id,f.name]));
    const corr=p.correlation;
    $('#factor-eval-panel').innerHTML=`<div class="detail-note">仅训练区间（前 60%）：${date(p.scope.start)} → ${date(p.scope.end)} · 只衡量特征之间的重复程度，不涉及收益</div><div class="table-wrap"><table><thead><tr><th></th>${corr.columns.map(c=>`<th>${esc(names[c]||c)}</th>`).join('')}</tr></thead><tbody>${corr.values.map((row,i)=>`<tr><th>${esc(names[corr.columns[i]]||corr.columns[i])}</th>${row.map(v=>`<td>${fmt(v,3)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${ids.length>use.length?`<div class="detail-note">只计算前 20 个特征的相关性（共 ${ids.length} 个）。</div>`:''}`;
  }catch(err){if(!evaluationGate.current(token)||target!==$('#factor-eval-panel'))return;target.innerHTML=`<div class="error">${esc(err.message)}</div>`}
}

function newFactorSet(){
  if(!catalog.factors.length&&!catalog.chan_event?.features?.length){toast('暂无可用特征');return}
  modal('新建特征集',field('名称','name','我的特征组合','text','required maxlength="100"')+field('说明','description','','text','maxlength="300"')+`<div class="field"><label>包含特征</label><div class="check-list">${[...catalog.factors,...(catalog.chan_event?.features||[])].map(f=>`<label><input type="checkbox" name="factor_ids" value="${f.id}" ${f.id===factorId?'checked':''}>${esc(f.name)} <span class="badge gray">${esc(labelOf(f.category))}</span></label>`).join('')}</div><small>包含缠论事件特征的组合需要事件采样。</small></div>`,'factor-set');
}
function field(label,name,value='',type='text',extra=''){return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}></div>`}
function selectField(label,name,options){return `<div class="field"><label for="${name}">${label}</label><select id="${name}" name="${name}">${options}</select></div>`}
function modal(title,body,kind){$('#dialog').innerHTML=`<form id="modal-form" data-kind="${kind}"><div class="modal-head"><h2 id="dialog-title">${title}</h2><button type="button" data-close aria-label="关闭">×</button></div><div class="form-body">${body}<div id="form-error" class="error"></div></div><div class="form-footer"><button type="button" class="btn" data-close>取消</button><button class="btn primary" type="submit">${kind==='experiment'?'启动实验':'保存'}</button></div></form>`;$('#dialog').setAttribute('aria-labelledby','dialog-title');$('#dialog').classList.toggle('experiment-dialog',kind==='experiment');$('#dialog').showModal()}
function configureFeature(){
  const feature=[...catalog.factors,...(catalog.chan_event?.features||[])].find(record=>record.id===factorId);
  const spec=feature&&specOf(feature.spec_id||feature.recipe);
  if(!spec?.params?.length)return;
  const current=paramsOf(feature);
  modal('设置特征参数',`<h3>${esc(feature.name)}</h3><p class="sub">${esc(spec.description)}</p>
    <input type="hidden" name="factor_id" value="${esc(feature.id)}">
    ${spec.params.map(param=>paramField({...param,default:current[param.name]??param.default})).join('')}
    <p class="sub">保存后作为直接选择该特征时的默认参数。</p>`,'feature-params');
}
async function newExperiment(copy=null){
  const version=renderVersion;
  const inventory=await api('/market/instruments');
  if(version!==renderVersion)return;
  if(!inventory.instruments.length&&!copy?.snapshot.dataset){
    modal('准备第一次实验',prerequisite('数据库还没有可用标的','data','打开数据库'),'notice');
    $('#modal-form button[type=submit]').hidden=true;
    return;
  }
  mountExperimentWizard({catalog,inventory,copy,datasetId,factorId,modal,
    marketRequest:(action,payload)=>post('/market/'+action,payload)});
}

async function compare(){if(selected.size<2){toast('请选择至少两个已完成实验');return}const target=$('#comparison'),token=comparisonGate.next();target.innerHTML=loading('正在加载对比结果…');const exps=await Promise.all([...selected].map(id=>api('/experiments/'+id)));if(!comparisonGate.current(token)||target!==$('#comparison'))return;if(exps.some(e=>['chan_event','prediction_only'].includes(e.result.kind))){target.innerHTML='<p class="detail-note">请在各实验详情按目标比较预测误差、分类指标和样本外事件区间。</p>';return}const differences=comparisonDifferences(exps),differs=differences.length>0;const series=exps.map(e=>({name:e.name,values:[1,...e.result.rows.map(r=>r.equity)]}));$('#comparison').innerHTML=`<section class="panel"><div class="panel-head"><h2>实验对比</h2><span class="badge ${differs?'orange':'green'}">${differs?'比较条件存在差异':'数据、目标、区间与执行门槛一致'}</span></div><div class="panel-body">${legend(series)}${chart(series)}<div class="detail-note">按样本外进度对齐。${differs?'差异项：'+esc(differences.join('、'))+'。请结合这些差异解释曲线。':'比较条件一致，可观察特征与模型组合的效果。'}</div><div class="table-wrap"><table><thead><tr><th>实验</th><th>模型</th><th>特征集</th><th>目标</th><th>测试区间</th><th>成本</th><th>特征清单</th></tr></thead><tbody>${exps.map(e=>`<tr><td>${esc(e.name)}</td><td>${esc(e.snapshot.config.model)}</td><td>${esc(e.snapshot.factors.map(f=>f.name).join(' / '))}</td><td>${esc(e.snapshot.target.name)}</td><td>${date(e.result.splits.test.start)} → ${date(e.result.splits.test.end)}</td><td>${e.snapshot.config.cost_bps} bps</td><td class="mono">${esc((e.result.feature_manifest?.hash||'—').slice(0,8))}</td></tr>`).join('')}</tbody></table></div></div></section>`;$('#comparison').scrollIntoView({behavior:'smooth'})}
async function navigate(next, experiment=null){
  if(next!==page)backtestResult=null;
  selectedRun=null;page=next;detail=experiment;await render();
}
document.addEventListener('click',async ev=>{
  const el=ev.target.closest('button,a[data-action],article[data-factor]');if(!el)return;
  try{
    if(el.hasAttribute('data-close')){$('#dialog').close();return}
    if(el.dataset.page){await navigate(el.dataset.page);return}
    if(el.dataset.deleteExperiment){
      modal('删除实验','<p>删除后将清理本实验的行情、配置和训练结果。</p>'+
        `<input type="hidden" name="experiment_id" value="${esc(el.dataset.deleteExperiment)}">`,'delete-experiment');
      $('#modal-form button[type=submit]').textContent='确认删除';
      return;
    }
    if(el.dataset.rerun){el.disabled=true;try{const run=await post('/experiments/'+el.dataset.rerun+'/runs',{});selectedRun=run.id;toast('新运行已加入队列');await render()}finally{el.disabled=false}return}
    if(el.dataset.replay){backtestRunSeed=el.dataset.run||null;backtestSeed=el.dataset.replay;backtestResult=null;await navigate('backtest');return}
    if(el.dataset.archive){await post('/factors/'+el.dataset.archive+'/archive',{});if(factorId===el.dataset.archive)factorId=null;toast('已归档，历史实验快照仍保留');await render();return}
    if(el.dataset.reclassify){
      const f=[...catalog.factors,...(catalog.chan_event?.features||[])].find(x=>x.id===el.dataset.reclassify);if(!f)return;
      const opts=['<option value="" '+(labelOf(f.category)==='未分类'?'selected':'')+'>未分类</option>'].concat(catalog.categories.map(c=>`<option value="${esc(c.name)}" ${labelOf(f.category)===c.name?'selected':''}>${esc(c.name)}</option>`)).join('');
      modal('修改特征分类',`<div class="detail-note">${esc(f.name)} 当前分类：${esc(labelOf(f.category))}。归入未分类后仍可用于实验与特征集。</div>`+selectField('已有分类','category',opts)+field('或新建分类','new_category','','text','maxlength="40" placeholder="留空则使用上方分类"')+`<input type="hidden" name="factor_id" value="${esc(f.id)}">`,'factor-category');
      return}
    if(el.dataset.featureView){featureView=el.dataset.featureView;await factorPage();return}
    if(el.dataset.categoryEdit||el.dataset.categoryRemove){
      const item=catalog.categories.find(c=>c.id===(el.dataset.categoryEdit||el.dataset.categoryRemove));
      const remove=Boolean(el.dataset.categoryRemove);
      modal(remove?'删除分类':'重命名分类',`<input type="hidden" name="category_id" value="${esc(item.id)}"><input type="hidden" name="operation" value="${remove?'remove':'rename'}">`+
        (remove?selectField('其中的特征移到','name','<option value="">未分类</option>'+catalog.categories.filter(c=>c.id!==item.id).map(c=>`<option value="${esc(c.name)}">${esc(c.name)}</option>`).join('')):field('分类名称','name',item.name,'text','required maxlength="40"')),'category-manage');return;
    }
    if(el.dataset.category){category=el.dataset.category;await factorPage();return}
    if(el.dataset.factor){factorId=el.dataset.factor;await factorPage();return}
    if(el.dataset.label){await labelPreview(el.dataset.label);return}
    if(el.dataset.detail){await navigate('experiments',el.dataset.detail);return}
    if(el.dataset.copy){await newExperiment(catalog.experiments.find(e=>e.id===el.dataset.copy));return}
    if(el.dataset.backtest){
      const version=++renderVersion;el.disabled=true;
      try{const result=await api('/backtests/'+el.dataset.backtest);if(version!==renderVersion)return;backtestResult=result;btPage=1;btQuery='';await backtestPage()}
      finally{el.disabled=false}return;
    }
    if(el.dataset.btPage){btPage=Number(el.dataset.btPage);await backtestPage();return}
    const action=el.dataset.action;
    if(action==='backtest-close'){backtestResult=null;btPage=1;btQuery='';await backtestPage();return}
    if(action==='preview-event-feature'){
      const target=$('#event-feature-preview'),token=previewGate.next();
      if(!datasetId)throw Error('请先选择行情快照');
      target.innerHTML=loading('正在回放缠论事件…');
      const current=()=>previewGate.current(token)&&target===$('#event-feature-preview');
      const result=await panelRequest(`/preview/${encodeURIComponent(datasetId)}?factor_id=${encodeURIComponent(factorId)}`,target,current);
      if(current())target.innerHTML=result.events.length?`<div class="table-wrap"><table><thead><tr><th>观察时间（UTC）</th><th>事件</th><th>特征值</th></tr></thead><tbody>${result.events.slice(-20).reverse().map(e=>`<tr><td>${esc(e.time)}</td><td>${esc(e.type)}${e.side==='buy'?'买':'卖'}</td><td>${fmt(e.value,5)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="detail-note">该区间没有候选买卖点。</p>';
      return;
    }
    if(action==='edit-feature-note'){
      const feature=[...catalog.factors,...(catalog.chan_event?.features||[])].find(f=>f.id===factorId);
      if(!feature)return;
      modal('人工备注',`<p class="sub">${esc(feature.name)}</p><input type="hidden" name="factor_id" value="${esc(feature.id)}">
        <div class="field"><label for="feature-note-input">备注（最多 2000 字）</label><textarea id="feature-note-input" class="feature-note-input" name="note" maxlength="2000" rows="6">${esc(feature.note||'')}</textarea><small>清空后保存即可删除备注。</small></div>`,'feature-note');
      return;
    }
    if(action==='manage-categories')manageCategories();
    if(action==='new-category')modal('新建特征分类',field('分类名称','name','','text','required maxlength="40"'),'category');
    if(action==='configure-feature')configureFeature();
    if(action==='new-experiment')await newExperiment();
    if(action==='data'||action==='open-factors'){if($('#dialog').open)$('#dialog').close();await navigate(action==='data'?'data':'factors')}
    if(action==='back')await navigate('experiments');
    if(action==='factor-corr')await factorCorrelation();
    if(action==='new-factor-set')newFactorSet();
    if(action==='compare')await compare();
    if(action==='retry-kline')await mountDataKline(Boolean($('#market-browser-periods')?.hidden));
    if(action==='retry')await render();
  }catch(e){toast(e.message)}
});
document.addEventListener('input',ev=>{
  if(ev.target.id==='feature-search'){
    featureQuery=ev.target.value;
    const position=ev.target.selectionStart;
    void factorPage().catch(error=>toast(error.message));
    const input=$('#feature-search');input.focus();
    if(position!=null&&input.type!=='search')input.setSelectionRange(position,position);
  }
  if(ev.target.id==='experiment-search'){experimentQuery=ev.target.value;updateExperimentTable()}
});
document.addEventListener('change',async ev=>{
  try{
    if(ev.target.id==='detail-run'){selectedRun=ev.target.value||null;await render();return}
    if(ev.target.id==='diagnostics-split'){diagnosticsSplit=ev.target.value;$('#model-diagnostics').innerHTML=renderDiagnostics(activeDiagnostics,diagnosticsSplit);return}
    if(ev.target.id==='experiment-status'){experimentStatus=ev.target.value;updateExperimentTable()}
    if(ev.target.id==='dataset-select'){
      datasetId=ev.target.value;evaluationGate.next();
      if(page==='factors'){
        const ep=$('#factor-eval-panel');if(ep)ep.innerHTML='<div class="detail-note">数据集已切换，请重新计算相关性。</div>';
        if($('#event-feature-preview')){previewGate.next();$('#event-feature-preview').replaceChildren()}
        else await previewFactor();
      }else if(page==='targets'){labelGate.next();$('#label-preview').innerHTML='<div class="detail-note">请选择目标以预览新数据集的标签。</div>'}
      else if(page==='data')await dataPage();
    }
    if(ev.target.dataset.compare){
      if(ev.target.checked&&selected.size>=4){ev.target.checked=false;toast('每次最多对比 4 个实验');return}
      ev.target.checked?selected.add(ev.target.dataset.compare):selected.delete(ev.target.dataset.compare);
      const button=$('#compare-button');button.textContent=`对比选中实验（${selected.size}/4）`;button.disabled=selected.size<2;
      comparisonGate.next();$('#comparison').innerHTML='';
    }
  }catch(e){toast(e.message)}
});
document.addEventListener('submit',async ev=>{
  const form=ev.target;if(!['modal-form','training-form','upload-form','backtest-form'].includes(form.id))return;
  ev.preventDefault();if(form.dataset.busy)return;
  const submit=form.querySelector('[type=submit]'),label=submit.textContent;
  form.dataset.busy='true';form.setAttribute('aria-busy','true');submit.disabled=true;
  submit.textContent=form.id==='backtest-form'?'正在执行回测…':'正在提交…';
  form.querySelectorAll('[data-close]').forEach(el=>el.disabled=true);
  const error=form.querySelector('.error');if(error)error.textContent='';
  try{
    const fd=new FormData(form);
    if(form.id==='upload-form'){
      const file=fd.get('file');if(file?.size>20*1024*1024)throw Error('CSV 文件不能超过 20 MB。');
      const dataset=await api('/datasets',{method:'POST',body:fd});datasetId=dataset.id;toast('行情校验通过，已选中新数据快照');await render();return;
    }
    if(form.id==='backtest-form'){
      const obj=Object.fromEntries(fd);
      for(const key of ['fast','slow','threshold','initial_cash','fee_bps','slippage_bps','position_pct','stop_loss_pct','take_profit_pct','max_hold_bars'])if(obj[key]!==undefined&&obj[key]!=='')obj[key]=Number(obj[key]);
      if(obj.threshold===''||obj.threshold===undefined)delete obj.threshold;
      if(obj.source==='sma'){delete obj.experiment_id;delete obj.run_id;delete obj.threshold;if(obj.fast>=obj.slow)throw Error('慢线窗口必须大于快线窗口。')}
      else{delete obj.dataset_id;delete obj.fast;delete obj.slow;if(!obj.run_id)throw Error('请选择已完成的运行')}
      const result=await post('/backtests',obj);backtestResult=result;btPage=1;btQuery='';toast('回测完成');
      if(form.isConnected)await render();return;
    }
    const kind=form.dataset.kind,obj=Object.fromEntries(fd);
    for(const key of ['horizon','threshold','lookback','epochs','diagnostic_runs','cost_bps','entry_threshold','probability_threshold'])if(key in obj)obj[key]=Number(obj[key]);
    if(kind==='delete-experiment'){
      await api('/experiments/'+encodeURIComponent(obj.experiment_id),{method:'DELETE'});
      detail=null;selected.delete(obj.experiment_id);
    }else if(kind==='category-manage'){await post('/categories/'+obj.category_id,obj);category='全部'}else if(kind==='feature-params'){
      await post('/factors/'+encodeURIComponent(obj.factor_id)+'/params',{params:collectParams(form)});
    }else if(kind==='feature-note'){
      await post('/factors/'+encodeURIComponent(obj.factor_id)+'/note',{note:obj.note});
    }else if(kind==='factor-category'){
      const target=String(obj.new_category||'').trim()||String(obj.category||'').trim();
      await post('/factors/'+obj.factor_id+'/category',{category:target});
      category=target||'未分类';factorId=obj.factor_id;toast('已归类到 '+(target||'未分类'));
    }else if(kind==='factor-set'){
      obj.factor_ids=fd.getAll('factor_ids');if(!obj.factor_ids.length)throw Error('请至少选择一个特征');await post('/factor-sets',obj);
    }else if(kind==='experiment'){
      obj.auto_backtest=fd.get('auto_backtest')==='on';
      obj.submission_key=form.submissionKey;
      for(const key of ['market-start','market-end'])delete obj[key];
      Object.assign(obj,form.experimentDefaults||{});
      if(obj.market_range||obj.source_experiment_id)delete obj.dataset_id;
      obj.model_params=collectModelParams(form);
      obj.target_params=collectParams(form.querySelector('#wizard-target-params'));
      obj.target_version=Number(obj.target_version);
      if(obj.sample_mode==='chan_event')obj.event_types=fd.getAll('event_types');
      else delete obj.event_types;
      if(obj.factor_set_id)delete obj.factor_ids;
      else{delete obj.factor_set_id;obj.factor_ids=fd.getAll('factor_ids');if(!obj.factor_ids.length)throw Error('请至少选择一个特征');if(obj.factor_ids.length>30)throw Error('最多选择 30 个特征')}
      const e=await post('/experiments',obj);detail=e.id;page='experiments';
    }else if(kind==='category')await post('/categories',obj);
    if(form.id==='modal-form')$('#dialog').close();const notice=kind==='delete-experiment'?'实验已删除':kind==='experiment'?'实验已加入计算队列':kind==='factor-set'?'特征集已保存':kind==='factor-category'?'已归类到 '+(category||'未分类'):'已保存';toast(notice);await render();
  }catch(e){if(error?.isConnected){error.textContent=e.message;error.setAttribute('role','alert');error.scrollIntoView({block:'nearest'})}else toast(e.message)}
  finally{delete form.dataset.busy;form.removeAttribute('aria-busy');submit.disabled=false;submit.textContent=label;form.querySelectorAll('[data-close]').forEach(el=>el.disabled=false)}
});
$('#dialog').addEventListener('cancel',ev=>{if($('#modal-form')?.dataset.busy)ev.preventDefault()});
window.addEventListener('keydown',ev=>{if(['Enter',' '].includes(ev.key)&&ev.target.matches('article[data-factor]')){ev.preventDefault();ev.target.click()}});
await render().catch(e=>{$('#app').innerHTML=`<div class="empty"><b>无法连接研究引擎</b>${esc(e.message)}<br>${button('重新连接','retry',true)}</div>`});
poll=setInterval(async()=>{
  if(pollBusy||document.hidden||$('#dialog').open||(!detail&&!catalog?.experiments.some(e=>['running','queued'].includes(e.status))))return;
  pollBusy=true;const version=renderVersion;
  try{
    const next=await api('/catalog');if(version!==renderVersion)return;
    const state=items=>JSON.stringify(items.map(e=>[e.id,e.status,e.message]));
    const changed=state(next.experiments)!==state(catalog.experiments);
    applyCatalog(next);
    if(changed||detail){
      const target=pollTarget(page,detail);
      if(target==='view')await render({cached:true});
      else if(target==='table'&&$('#experiment-table'))updateExperimentTable();
    }
  }catch(error){console.warn('实验状态更新失败',error)}
  finally{pollBusy=false}
},2500);
