import {paramField} from './parameter-fields.mjs';
import {groupedModels,initialModel} from './model-catalog.mjs';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const day=value=>String(value||'').slice(0,10);
const levels=['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M'];
export function datasetIdentity(dataset){
  const symbol=dataset.symbol||'';
  const interval=dataset.interval||'';
  const perpetual=dataset.market==='usdm_perpetual'&&symbol;
  return {key:perpetual?`usdm_perpetual:${symbol}`:symbol||`unknown:${dataset.id}`,
    symbol:perpetual?`${symbol} · USDT 本位永续`:
      symbol||`未标注 · ${dataset.name}`,interval,
    intervalLabel:interval==='custom'?'自定义 / 不规则':interval||'原始级别（未标注）'};
}
export function matchingDatasets(datasets,symbol,interval){
  return datasets.filter(d=>{const identity=datasetIdentity(d);return identity.key===symbol&&identity.interval===interval});
}
export function marketAuditText(audit){
  if(!audit)return '';
  const count=audit.expected?`（${audit.checked??0}/${audit.expected} 根）`:'';
  const label=audit.state==='passed'?'交易所抽样通过':
    audit.state==='mismatch'?`交易所抽样发现 ${audit.mismatches} 根存在差异`:'交易所校验待完成';
  return label+count+(audit.message?` · ${audit.message}`:'');
}
export function collectModelParams(form){
  return Object.fromEntries([...form.querySelectorAll('[data-model-param]')].map(input=>{
    const value=Number(input.value);
    if(input.value===''||!Number.isFinite(value))throw Error('请填写有效的模型参数');
    return [input.dataset.modelParam,value];
  }));
}
function featureCompatibility(factorIds,eventMode,eventFeatures){
  if(eventMode)return '';
  const names=factorIds.filter(id=>eventFeatures.has(id)).map(id=>eventFeatures.get(id));
  return names.length?`「${names.join('、')}」需要缠论买卖点，当前 K 线采样无法使用。请取消勾选，或在第一步切换到事件采样。`:'';
}
export function wizardError(step,{dataset,factorIds=[],model,target,params={},eventMode=false,eventTypes=[],eventFeatures=new Map()}){
  if(step===0&&!dataset)return '请选择可用的行情区间';
  if(step===0&&eventMode&&!eventTypes.length)return '请至少选择一种买卖点';
  if(step===1&&(!factorIds.length||factorIds.length>30))return '请选择 1–30 个特征';
  if(step===1)return featureCompatibility(factorIds,eventMode,eventFeatures);
  if(step===2){
    if(!model?.available||!model.tasks.includes(target?.task))return '当前模型不可用或不支持所选目标';
    if(model.id==='lightgbm'&&params.num_leaves>2**params.max_depth)return '最大叶子数不能超过 2 的最大树深次方';
  }
  return '';
}
const input=(label,name,value,attributes='')=>`<div class="field"><label for="${name}">${esc(label)}</label><input id="${name}" name="${name}" value="${esc(value)}" ${attributes}></div>`;
const select=(label,id,options,name=id)=>`<div class="field"><label for="${id}">${esc(label)}</label><select id="${id}" ${name?`name="${name}"`:''}>${options}</select></div>`;
const option=(value,label,selected)=>`<option value="${esc(value)}" ${selected?'selected':''}>${esc(label)}</option>`;

export function mountExperimentWizard({catalog,inventory,copy,datasetId,factorId,modal,mountForm,marketRequest}){
  const c=copy?.snapshot.config||{};
  const eventCatalog=catalog.chan_event;
  const eventTypes=Object.entries(eventCatalog?.types||{});
  const eventFeatures=new Map((eventCatalog?.features||[]).map(f=>[f.id,f.name]));
  const allFactors=[...catalog.factors,...(eventCatalog?.features||[])];
  const factors=[...allFactors,...(copy?.snapshot.factors||[]).filter(f=>!allFactors.some(x=>x.id===f.id))];
  const targets=catalog.targets;
  const copiedTarget=copy?.snapshot.target;
  const copiedTargetId=targets.find(target=>target.id===c.target_id)?.id||
    targets.find(target=>target.kind==='forward_return'&&target.task===copiedTarget?.task)?.id;
  let eventMode=c.sample_mode==='chan_event';
  const savedChoices={bar:{},event:{}};
  const datasets=[...catalog.datasets];
  const copiedDataset=copy?.snapshot.dataset;
  if(copiedDataset&&!datasets.some(d=>d.id===copiedDataset.id))datasets.push(copiedDataset);
  const marketInstruments=new Map(inventory.instruments.map(item=>[`usdm_perpetual:${item.symbol}`,item]));
  const instruments=new Map([...marketInstruments].map(([key,item])=>[key,`${item.symbol} · ${inventory.exchange_name||'OKX'} 永续`]));
  const initial=copiedDataset||
    datasets.find(d=>d.id===datasetId&&instruments.has(datasetIdentity(d).key));
  const identity=initial?datasetIdentity(initial):null;
  // A copied historical experiment can still reuse its original, immutable snapshot.
  if(copiedDataset&&!instruments.has(identity.key))instruments.set(identity.key,`${identity.symbol}（原实验区间）`);
  const selectedIds=new Set(c.factor_ids||[factorId].filter(Boolean));
  const selectedTypes=new Set(c.event_types||eventTypes.map(([id])=>id));
  const setOptions=(catalog.factor_sets||[]).map(s=>option(s.id,`${s.name} · ${s.factor_ids.length} 个特征`,s.id===c.factor_set_id)).join('');
  const body=`<nav class="wizard-steps" aria-label="创建实验步骤">${['标的选择','选择特征','选择模型'].map((name,i)=>`<button type="button" data-wizard-step="${i}"><span>${i+1}</span>${name}</button>`).join('')}</nav>
    <div class="experiment-layout"><div>
    <section data-wizard-panel="0"><div class="section-heading"><div><h3>标的、周期与采样</h3><p>使用已导入行情，固定本次训练的数据来源。</p></div></div>
    <div class="form-grid">${select('标的','wizard-symbol',[...instruments].map(([key,name])=>option(key,name,key===identity?.key)).join(''),'')}${select('K 线级别','wizard-interval','','')}</div>
    <div id="wizard-market" role="group" aria-label="时间范围" hidden>
      <div class="form-grid">${input('起始日（北京时间）','market-start','','type="date"')}${input('结束日（含）','market-end','','type="date"')}</div>
      <p id="wizard-market-status" class="detail-note" aria-live="polite"></p>
      <button type="button" class="btn" id="wizard-market-sync" hidden>补齐缺失行情</button>
    </div>
    <input type="hidden" name="dataset_id" id="dataset_id">
    ${select('采样方式','sample_mode',option('bar','K 线采样（默认）',!eventMode)+(eventCatalog?option('chan_event','事件采样',eventMode):''))}
    <fieldset id="wizard-events" hidden><legend>缠论买卖点</legend>
    <p class="sub">候选点首次出现时取样。同一根 K 线上的不同买卖点各保留一条样本。</p>
    <div class="check-list">${eventTypes.map(([id,label])=>`<label><input type="checkbox" name="event_types" value="${esc(id)}" ${selectedTypes.has(id)?'checked':''}>${esc(label)}</label>`).join('')}</div>
    </fieldset></section>
    <section data-wizard-panel="1" hidden><div class="section-heading"><div><h3>选择模型输入特征</h3><p>复用特征集，或组合不同分类下的特征。</p></div></div>
    ${select('特征组合','factor_set_id',option('','手动选择特征',!c.factor_set_id)+setOptions)}
    <div class="wizard-filter"><input type="search" id="wizard-feature-search" placeholder="搜索特征名称或分类" aria-label="搜索特征"><span class="badge gray" id="wizard-feature-count"></span></div>
    <p id="wizard-feature-warning" class="error" role="status" hidden></p>
    <div class="check-list wizard-features">${factors.map(f=>`<label data-feature-search="${esc((f.name+' '+f.category).toLocaleLowerCase())}"><input type="checkbox" name="factor_ids" value="${esc(f.id)}" ${selectedIds.has(f.id)?'checked':''}><span>${esc(f.name)}<small>${esc(Object.entries(f.params||{}).map(([k,v])=>k+'='+v).join(' · '))}</small></span><span class="badge gray">${esc(f.category)}</span></label>`).join('')}</div>
    <p id="wizard-feature-empty" class="sub" hidden>没有匹配的特征；已勾选的其他特征仍然保留。</p><p id="wizard-feature-help" class="sub"></p></section>
    <section data-wizard-panel="2" hidden><div class="section-heading"><div><h3>模型与训练</h3><p>选择预测目标，配置模型及训练参数。</p></div></div>
    ${input('实验名称','name',copy?copy.name+' · 副本':'单标的研究','type="text" required maxlength="100"')}
    <div class="form-grid">${select('预测目标','target_id','')}${select('训练模型','model','')}</div>
    <input type="hidden" name="target_version"><div id="wizard-target-params" class="form-grid"></div>
    <div id="wizard-model-output" class="detail-note"></div><h3 class="diagnostic-heading">模型与训练参数</h3>
    <div id="wizard-model-params" class="form-grid"></div><div id="wizard-sequence" class="form-grid">
    ${input('历史窗口（K 线根数）','lookback',c.lookback||30,'type="number" min="3" max="120" step="1" required')}
    ${input('训练轮数','epochs',c.epochs||10,'type="number" min="1" max="100" step="1" required')}</div>
    <p class="sub" id="wizard-training-help"></p></section>
    </div><aside class="experiment-summary" id="wizard-summary" aria-live="polite"></aside></div>`;
  const dialog=mountForm?null:document.querySelector('#dialog');
  if(dialog)modal(copy?'复制实验配置':'新建实验',body,'experiment');
  const form=mountForm?mountForm(body):dialog.querySelector('form');
  const q=s=>form.querySelector(s);
  form.noValidate=true;
  const submit=q('[type=submit]');
  const footer=q('.form-footer');
  const back=document.createElement('button'),next=document.createElement('button');
  back.type=next.type='button';back.className='btn';next.className='btn primary';back.textContent='上一步';next.textContent='下一步';
  footer.insertBefore(back,submit);footer.insertBefore(next,submit);submit.textContent='开始训练';
  let step=0,paramKey='',paramCache={},paramsReady=false;
  // Preserve existing execution defaults only when copying, without creating a fourth step.
  form.experimentDefaults=copy?Object.fromEntries(['cost_bps','entry_threshold','probability_threshold'].filter(k=>c[k]!=null).map(k=>[k,c[k]])):{};
  const chosen=()=>{
    const set=catalog.factor_sets.find(s=>s.id===q('#factor_set_id').value);
    return set?set.factor_ids:[...form.querySelectorAll('[name=factor_ids]:checked:not(:disabled)')].map(el=>el.value);
  };
  function saveParams(){if(paramsReady)paramCache[paramKey]=Object.fromEntries([...form.querySelectorAll('[data-model-param]')].map(el=>[el.dataset.modelParam,el.value]))}
  const targetParamCache=new Map();
  let currentTargetId;
  function renderTarget(target){
    if(target?.id===currentTargetId)return;
    const container=q('#wizard-target-params');
    if(currentTargetId)targetParamCache.set(currentTargetId,Object.fromEntries(
      [...container.querySelectorAll('[data-param]')].map(el=>[el.dataset.param,el.type==='checkbox'?el.checked:el.value])));
    currentTargetId=target?.id;
    const prior=targetParamCache.get(currentTargetId)||(currentTargetId===copiedTargetId?(copiedTarget?.params||copiedTarget):null);
    container.innerHTML=(target?.parameters||[]).map(param=>paramField({...param,default:prior?.[param.name]??param.default})).join('');
    q('[name=target_version]').value=target?.version??'';
  }
  function renderParams(){
    saveParams();
    const model=catalog.models.find(m=>m.id===q('#model').value),target=targets.find(t=>t.id===q('#target_id').value);
    renderTarget(target);
    for(const el of q('#model').options){const m=catalog.models.find(x=>x.id===el.value);el.disabled=!m?.available||!m.tasks.includes(target?.task)}
    const key=(model?.id||'')+':'+target?.task;
    const prior=paramCache[key]||(model?.id===c.model&&target?.task===copy?.snapshot.target.task?c.model_params:{} )||{};
    const schema=model?.parameters?.[target?.task]||[];
    q('#wizard-model-params').innerHTML=schema.map(p=>`<div class="field"><label for="mp-${p.name}">${esc(p.label)}</label><input id="mp-${p.name}" data-model-param="${esc(p.name)}" type="number" value="${esc(prior[p.name]??p.default)}" min="${p.minimum}" max="${p.maximum}" step="${p.kind==='int'?'1':'any'}" required><small>范围 ${p.minimum}–${p.maximum} · 默认 ${p.default}</small></div>`).join('')||'<p class="sub">请选择可用模型以配置训练参数。</p>';
    const seq=model?.input==='sequence';q('#wizard-sequence').hidden=!seq;q('#lookback').disabled=!seq;q('#epochs').disabled=!seq;
    q('#wizard-model-output').textContent=target?.description||'当前采样方式没有可用目标。';
    q('#wizard-training-help').textContent=eventMode?'事件实验展示样本外预测和模型诊断。':'训练完成后自动生成模型诊断和交易表现。';
    paramKey=key;paramsReady=true;summary();
  }
  const marketPanel=q('#wizard-market'),marketStatus=q('#wizard-market-status'),syncButton=q('#wizard-market-sync');
  let marketToken=0,preparedDataset=null,marketBusy=false;
  const marketMode=()=>Boolean(marketRequest)&&marketInstruments.has(q('#wizard-symbol').value);
  const rangeMode=()=>marketMode()&&(!copiedDataset||q('#dataset_id').value!==copiedDataset.id||
    q('#market-start').value||q('#market-end').value);
  const chosenDataset=()=>rangeMode()?preparedDataset:datasets.find(d=>d.id===q('#dataset_id').value);
  function marketPayload(){
    const start=q('#market-start').value,end=q('#market-end').value;
    if(!start||!end||start>end)return null;
    return {symbol:marketInstruments.get(q('#wizard-symbol').value).symbol,period:q('#wizard-interval').value,
      start:start+'T00:00:00+08:00',end:new Date(Date.parse(end+'T00:00:00+08:00')+86400000).toISOString()};
  }
  function showCoverage(result,period){
    syncButton.hidden=result.coverage!=='missing';
    const audit=marketAuditText(result.audit);
    if(result.coverage==='derivable'){
      marketStatus.textContent=period+' 级别在所选区间尚未完整入库，点击「下一步」将由 1m 自动生成。';
    }else if(result.coverage==='missing'){
      const gap=result.gaps[0];
      const format=value=>new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
      const interval=gap?`首个缺口为北京时间 ${format(gap[0])} 至 ${format(gap[1])}（不含结束时间）。`:'';
      marketStatus.textContent=`${period} 级别在所选区间缺少底层 1m 行情。${interval}`;
    }else{
      marketStatus.textContent=`区间已覆盖，共 ${result.rows.toLocaleString('zh-CN')} 根 K 线。${audit}`;
    }
  }
  function marketReset(){
    const token=++marketToken;
    preparedDataset=null;
    delete form.experimentDefaults.market_range;
    delete form.experimentDefaults.source_experiment_id;
    marketBusy=false;
    next.disabled=false;
    syncButton.hidden=true;
    syncButton.disabled=false;
    marketPanel.hidden=!marketMode();
    if(!rangeMode()){
      if(copy&&q('#dataset_id').value===copiedDataset?.id)form.experimentDefaults.source_experiment_id=copy.id;
      marketStatus.textContent=marketMode()?'可沿用原实验区间，或选择起止日期。':'';
      return;
    }
    const payload=marketPayload();
    if(!payload){
      marketStatus.textContent='请选择起止日期。';
      return;
    }
    marketStatus.textContent='正在检查所选区间…';
    marketRequest('status',payload).then(result=>{
      if(token===marketToken&&form.isConnected)showCoverage(result,payload.period);
    }).catch(error=>{
      if(token===marketToken&&form.isConnected)marketStatus.textContent=error.message;
    });
  }
  async function prepareMarket({sync=false}={}){
    if(marketBusy)return false;
    const payload=marketPayload();
    if(!payload){marketStatus.textContent='请选择有效的起止日期。';return false}
    const token=++marketToken;
    const current=()=>token===marketToken&&form.isConnected&&(!dialog||dialog.open);
    marketBusy=true;
    next.disabled=true;
    syncButton.disabled=true;
    marketStatus.textContent=sync?'正在补齐缺失行情…':'正在检查所选区间…';
    try{
      let result=await marketRequest(sync?'sync':'status',payload);
      if(!current())return false;
      showCoverage(result,payload.period);
      if(sync||result.coverage==='missing')return false;
      if(result.coverage==='derivable'){
        marketStatus.textContent=`正在用 1m 生成所选区间的 ${payload.period} K 线…`;
        result=await marketRequest('generate',{...payload,audit:false});
        if(!current())return false;
        if(result.coverage!=='complete'){showCoverage(result,payload.period);return false}
        marketStatus.textContent=`聚合完成，正在和 ${inventory.exchange_name||'OKX'} 原生 ${payload.period} K 线做抽样校验…`;
        result={...result,audit:await marketRequest('verify',payload)};
        if(!current())return false;
        showCoverage(result,payload.period);
      }
      if(result.rows<300){marketStatus.textContent='实验至少需要 300 根 K 线，请扩大时间范围。';return false}
      preparedDataset={symbol:payload.symbol,interval:payload.period,market:'usdm_perpetual',
        start:q('#market-start').value,end:q('#market-end').value,rows:result.rows,market_audit:result.audit};
      form.experimentDefaults.market_range=payload;
      showCoverage(result,payload.period);
      summary();
      return true;
    }catch(error){
      if(current())marketStatus.textContent=error.message;
      return false;
    }finally{
      if(token===marketToken){
        marketBusy=false;
        next.disabled=false;
        syncButton.disabled=false;
      }
    }
  }
  syncButton.onclick=()=>prepareMarket({sync:true});
  for(const id of ['market-start','market-end'])q('#'+id).onchange=()=>snapshots();
  function snapshots(preferred){
    const choices=matchingDatasets(datasets,q('#wizard-symbol').value,q('#wizard-interval').value);
    q('#dataset_id').value=(choices.find(d=>d.id===(preferred||copiedDataset?.id))||choices[0])?.id||'';
    marketReset();summary();
  }
  function intervals(preferredDataset){
    const preferred=datasets.find(d=>d.id===preferredDataset),meta=preferred?datasetIdentity(preferred):null;
    const available=new Map(datasets.filter(d=>datasetIdentity(d).key===q('#wizard-symbol').value).map(d=>{const m=datasetIdentity(d);return [m.interval,m.intervalLabel]}));
    const key=q('#wizard-symbol').value;
    if(marketInstruments.has(key)){
      available.clear();
      for(const level of inventory.levels)available.set(level,level);
    }
    q('#wizard-interval').innerHTML=[...available].map(([value,label],i)=>option(value,label,meta?.key===q('#wizard-symbol').value?value===meta.interval:i===0)).join('');
    snapshots(preferredDataset);
  }
  function summary(){
    const dataset=chosenDataset(),m=catalog.models.find(m=>m.id===q('#model').value),target=targets.find(t=>t.id===q('#target_id').value);
    const chosenIds=chosen(),n=chosenIds.length,meta=dataset?datasetIdentity(dataset):null;
    const warning=featureCompatibility(chosenIds,eventMode,eventFeatures);
    const audit=marketAuditText(dataset?.market_audit);
    q('#wizard-feature-warning').textContent=warning;
    q('#wizard-feature-warning').hidden=!warning;
    q('#wizard-feature-count').textContent=`已选 ${n} / 30`;
    q('#wizard-summary').innerHTML=`<span class="eyebrow">EXPERIMENT</span><h3>本次配置</h3><dl><dt>标的 / 级别</dt><dd>${esc(meta?.symbol||'未选择')}<br>${esc(meta?.intervalLabel||'')}</dd><dt>采样</dt><dd>${eventMode?'事件 · '+esc(eventTypes.filter(([id])=>chosenTypes().includes(id)).map(([,name])=>name).join('、')||'未选择'):'每根 K 线'}</dd><dt>特征</dt><dd>${n} 个</dd><dt>模型</dt><dd>${esc(m?.name||'未选择')}</dd><dt>预测目标</dt><dd>${esc(target?.name||'未选择')}</dd></dl><div class="summary-foot">${dataset?`${dataset.rows} 根 K 线<br>${day(dataset.start)} → ${day(dataset.end)}${audit?'<br>'+esc(audit):''}`:'请先选择行情'}</div>`;

  }
  function show(targetStep){
    step=targetStep;
    form.querySelectorAll('[data-wizard-panel]').forEach(el=>el.hidden=Number(el.dataset.wizardPanel)!==step);
    form.querySelectorAll('[data-wizard-step]').forEach(el=>{const active=Number(el.dataset.wizardStep)===step;el.classList.toggle('active',active);if(active)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current')});
    back.hidden=step===0;next.hidden=step===2;submit.hidden=step!==2;
    q('#form-error').textContent='';if(dialog)dialog.scrollTop=0;
  }
  function valid(index){
    const fields=form.querySelector(`[data-wizard-panel="${index}"]`).querySelectorAll('input,select');
    for(const field of fields)if(!field.disabled&&!field.checkValidity()){show(index);field.reportValidity();return false}
    const error=wizardError(index,{dataset:chosenDataset(),factorIds:chosen(),
      model:catalog.models.find(m=>m.id===q('#model').value),target:targets.find(t=>t.id===q('#target_id').value),eventMode,eventTypes:chosenTypes(),eventFeatures,
      params:index===2?collectModelParams(form):{}});
    if(error){show(index);q('#form-error').textContent=error;return false}return true;
  }
  async function advance(to){
    if(to>step){
      if(step===0&&rangeMode()&&!preparedDataset&&!(await prepareMarket()))return;
      for(let i=step;i<to;i++)if(!valid(i))return;
    }
    show(to);
  }
  next.onclick=()=>advance(step+1);back.onclick=()=>show(step-1);
  form.querySelectorAll('[data-wizard-step]').forEach(el=>el.onclick=()=>advance(Number(el.dataset.wizardStep)));
  function chosenTypes(){
    return [...form.querySelectorAll('[name=event_types]:checked:not(:disabled)')].map(el=>el.value);
  }
  function syncFeatures(){
    const set=catalog.factor_sets.find(s=>s.id===q('#factor_set_id').value);
    const term=q('#wizard-feature-search').value.trim().toLocaleLowerCase();
    let visible=0;
    for(const label of form.querySelectorAll('[data-feature-search]')){
      const el=label.querySelector('input');
      el.disabled=!!set;
      el.checked=set?set.factor_ids.includes(el.value):selectedIds.has(el.value);
      label.hidden=!label.dataset.featureSearch.includes(term);
      if(!label.hidden)visible++;
    }
    q('#wizard-feature-empty').hidden=!!visible;
    q('#wizard-feature-help').textContent=set?`使用「${set.name}」的固定组合，共 ${set.factor_ids.length} 个特征。`:eventMode?'可组合缠论与量价特征，按候选点首次出现的收盘时刻取值。':'可组合不同分类，切换特征集会保留手动选择。';
    summary();
  }
  function renderChoices(targetId,modelId){
    const mode=eventMode?'chan_event':'bar';
    const availableTargets=targets.filter(t=>!t.sample_modes||t.sample_modes.includes(mode));
    const selectedTarget=availableTargets.find(t=>t.id===targetId)||(eventMode&&availableTargets.find(t=>t.kind==='chan_structure'))||availableTargets[0];
    q('#target_id').innerHTML=availableTargets.map(t=>option(t.id,t.name,t.id===selectedTarget?.id)).join('');
    const availableModels=eventMode?catalog.models.filter(m=>eventCatalog.models.includes(m.id)):catalog.models;
    const selectedModel=initialModel(availableModels,selectedTarget?.task,modelId);
    q('#model').innerHTML=(modelId&&!selectedModel?option('','请重新选择模型',true):'')+groupedModels(availableModels).map(g=>`<optgroup label="${esc(g.name)}">${g.models.map(m=>option(m.id,m.name+(m.recommended?' · 推荐':'')+(m.available?'':'（不可用）'),m.id===selectedModel)).join('')}</optgroup>`).join('');
    renderParams();
  }
  function syncMode(){
    q('#wizard-events').hidden=!eventMode;
    for(const el of form.querySelectorAll('[name=event_types]'))el.disabled=!eventMode;
    syncFeatures();
  }
  q('#sample_mode').onchange=()=>{
    savedChoices[eventMode?'event':'bar']={target:q('#target_id').value,model:q('#model').value};
    eventMode=q('#sample_mode').value==='chan_event';
    const saved=savedChoices[eventMode?'event':'bar'];
    renderChoices(saved.target,saved.model);
    syncMode();
  };
  q('#wizard-symbol').onchange=()=>intervals();
  q('#wizard-interval').onchange=()=>snapshots();
  q('#model').onchange=q('#target_id').onchange=renderParams;
  q('#factor_set_id').onchange=syncFeatures;
  q('#wizard-feature-search').oninput=syncFeatures;
  form.addEventListener('input',ev=>{if(ev.target.name==='factor_ids'){ev.target.checked?selectedIds.add(ev.target.value):selectedIds.delete(ev.target.value)}summary()});
  form.addEventListener('submit',ev=>{
    if(step<2){ev.preventDefault();ev.stopPropagation();advance(step+1);return}
    for(let i=0;i<3;i++)if(!valid(i)){ev.preventDefault();ev.stopPropagation();return}
  });
  intervals(initial?.id);renderChoices(copiedTargetId,c.model);syncMode();show(0);
}
