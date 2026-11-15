const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, digits = 4) => v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits);
const percent = v => v == null ? '—' : `${(v * 100).toFixed(2)}%`;
const splitNames = {train:'训练集', valid:'验证集', test:'测试集'};
const metricNames = {mae:'MAE ↓',rmse:'RMSE ↓',r2:'R² ↑',pearson:'Pearson ↑',spearman:'Spearman ↑',direction_accuracy:'方向准确率 ↑',bias:'平均偏差',auc:'ROC-AUC ↑',average_precision:'AP ↑',log_loss:'Log Loss ↓',brier:'Brier ↓',accuracy:'Accuracy ↑',precision:'Precision ↑',recall:'Recall ↑',specificity:'Specificity ↑',f1:'F1 ↑',positive_rate:'实际正类占比',predicted_positive_rate:'预测正类占比'};
const regressionMetrics = ['mae','rmse','r2','pearson','spearman','direction_accuracy','bias'];
const binaryMetrics = ['auc','average_precision','log_loss','brier','accuracy','precision','recall','specificity','f1','positive_rate','predicted_positive_rate'];
const metricValue = (key,value) => ['direction_accuracy','accuracy','precision','recall','specificity','f1','positive_rate','predicted_positive_rate'].includes(key) ? percent(value) : fmt(value);
const table = (heads, rows) => `<div class="table-wrap"><table><thead><tr>${heads.map(h=>`<th>${escape(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
const note = text => `<div class="detail-note">${escape(text)}</div>`;

// Coordinates use actual x/y values; calibration and ROC are not index-aligned plots.
export function xyChart(series, {title='',xLabel='',yLabel='',unit=false,scatter=false,diagonal=false}={}) {
  const points=series.flatMap(s=>s.points).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
  if(!points.length)return note('当前样本无法定义此曲线。');
  let xmin=unit?0:Math.min(...points.map(p=>p.x)),xmax=unit?1:Math.max(...points.map(p=>p.x));
  let ymin=unit?0:Math.min(...points.map(p=>p.y)),ymax=unit?1:Math.max(...points.map(p=>p.y));
  if(diagonal&&!unit){xmin=ymin=Math.min(xmin,ymin);xmax=ymax=Math.max(xmax,ymax)}
  if(xmax===xmin){xmin-=.01;xmax+=.01}if(ymax===ymin){ymin-=.01;ymax+=.01}
  const x=v=>60+(v-xmin)/(xmax-xmin)*470,y=v=>190-(v-ymin)/(ymax-ymin)*170;
  let svg=`<svg viewBox="0 0 560 240" class="diagnostic-chart" role="img" aria-label="${escape(title)}">`;
  for(let i=0;i<=4;i++){
    const xx=xmin+(xmax-xmin)*i/4,yy=ymin+(ymax-ymin)*i/4;
    svg+=`<line x1="60" x2="530" y1="${y(yy)}" y2="${y(yy)}" stroke="#e8edf3"/><text x="52" y="${y(yy)+4}" text-anchor="end">${fmt(yy,3)}</text><text x="${x(xx)}" y="209" text-anchor="middle">${fmt(xx,3)}</text>`;
  }
  if(diagonal)svg+=`<line x1="${x(xmin)}" y1="${y(xmin)}" x2="${x(xmax)}" y2="${y(xmax)}" stroke="#96a5bc" stroke-dasharray="5 4"/>`;
  series.forEach((s,i)=>{
    const valid=s.points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)),color=i?'#159c80':'#3868ef';
    if(scatter)svg+=valid.map(p=>`<circle cx="${x(p.x)}" cy="${y(p.y)}" r="2.5" fill="${color}" opacity=".55"/>`).join('');
    else svg+=`<path d="${valid.map((p,j)=>`${j?'L':'M'}${x(p.x)},${y(p.y)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2"/>`;
  });
  svg+=`<text x="290" y="235" text-anchor="middle">${escape(xLabel)}</text><text x="10" y="12">${escape(yLabel)}</text></svg>`;
  return `<div class="diagnostic-plot"><h3>${escape(title)}</h3>${svg}<div class="legend">${series.map((s,i)=>`<span><i style="background:${i?'#159c80':'#3868ef'}"></i>${escape(s.name)}</span>`).join('')}${diagonal?'<span>虚线：理想一致线</span>':''}</div></div>`;
}

function histogram(bins){
  const maximum=Math.max(1,...bins.map(b=>b.count));
  return `<div class="diagnostic-plot"><h3>残差分布 · 预测 − 实际</h3><div class="diagnostic-histogram" role="img" aria-label="残差分布，详细区间见下表">${bins.map(b=>`<div title="${fmt(b.lower)} 至 ${fmt(b.upper)}：${b.count} 个"><span>${b.count}</span><i style="height:${b.count/maximum*135}px"></i></div>`).join('')}</div><details><summary>查看残差区间与数量</summary>${table(['区间下界','区间上界','样本数'],bins.map(b=>[fmt(b.lower),fmt(b.upper),b.count]))}</details></div>`;
}

function modelPanel(d){
  const m=d.model,h=d.history||[],features=d.features||[];
  let html=`<details class="diagnostic-section" open><summary>模型专属诊断 · ${escape(m.kind)}</summary>${note(m.selection)}`;
  if(m.parameters)html+=table(['实际生效参数','值'],Object.entries(m.parameters).map(([key,value])=>[escape(key),escape(value)]));
  if(m.kind==='linear'){
    html+=`<div class="diagnostic-facts"><span>收敛检查：<b>${m.converged?'未出现收敛警告':'出现收敛警告'}</b></span><span>迭代次数：${m.iterations??'不适用（解析求解）'}</span><span>正则化：${escape(JSON.stringify(m.regularization))}</span><span>截距：${fmt(m.intercept)}</span></div>`;
    html+=table(['输入特征','标准化输入系数'],(m.coefficients||[]).map((v,i)=>[escape(features[i]?.name||`特征 ${i+1}`),fmt(v,6)]));
    html+=note(m.coefficient_scale);
  }
  if(['lightgbm','xgboost'].includes(m.kind)){
    html+=`<div class="diagnostic-facts"><span>实际迭代：${m.iterations}</span><span>验证损失最低轮次：${m.validation_best_iteration}</span></div>`;
    html+=table(['输入特征','Gain 重要性','分裂次数'],(m.gain_importance||[]).map((v,i)=>[escape(features[i]?.name||`特征 ${i+1}`),fmt(v),m.split_importance[i]]));
    html+=note('重要性描述模型使用特征的方式；不同模型的数值尺度不直接可比，也不代表因果贡献。');
  }
  if(['lstm','gru','cnn_lstm'].includes(m.kind))html+=`<div class="diagnostic-facts"><span>验证选中轮次：<b>${m.best_epoch} / ${m.epochs}</b></span><span>参数量：${m.parameter_count}</span><span>主模型种子：${m.seed}</span><span>梯度裁剪上限：${m.gradient_clip}</span></div>`;
  if(h.length){
    html+=xyChart([{name:'训练',points:h.map(r=>({x:r.epoch,y:r.train}))},{name:'验证',points:h.map(r=>({x:r.epoch,y:r.valid}))}],{title:`训练过程 · ${m.history_metric}`,xLabel:'迭代 / 轮次',yLabel:m.history_unit});
    html+=note(`曲线尺度：${m.history_unit}。上方预测指标使用最终模型在对应分区计算；不能把训练曲线的标准化损失直接与原始收益 RMSE 比较。`);
    if(['lstm','gru','cnn_lstm'].includes(m.kind))html+=`<details><summary>梯度与裁剪记录</summary>${table(['轮次','裁剪前平均范数','裁剪前最大范数','被裁剪批次占比'],h.map(r=>[r.epoch,fmt(r.gradient_mean),fmt(r.gradient_max),percent(r.clipped_fraction)]))}</details>`;
  }
  for(const warning of m.warnings||[])html+=`<p class="error">${escape(warning)}</p>`;
  return html+'</details>';
}

export function renderDiagnostics(d, selected='valid'){
  if(!d)return `<section class="panel"><div class="panel-head"><h2>模型诊断</h2><span class="badge gray">历史实验</span></div><div class="panel-body">${note('此实验尚未保存完整模型诊断。复制配置并重新运行后，可查看分区指标、基线与模型诊断；历史结果保持不变。')}</div></section>`;
  const split=d.splits[selected]?selected:'valid',s=d.splits[split],binary=d.task==='binary',keys=binary?binaryMetrics:regressionMetrics;
  const baseLabels={train_mean:'训练均值预测',zero:'恒定零收益',train_prevalence:'训练正类比例预测'};
  let html=`<section class="panel"><div class="panel-head"><div><span class="eyebrow">MODEL DIAGNOSTICS</span><h2>模型预测质量</h2></div><label class="diagnostic-select">详细诊断分区 <select id="diagnostics-split">${Object.entries(splitNames).map(([k,n])=>`<option value="${k}" ${k===split?'selected':''}>${n}</option>`).join('')}</select></label></div><div class="panel-body">`;
  html+=note(`${binary?'二分类概率预测；分类指标固定阈值 0.5，与交易门槛无关。':'收益率回归；MAE、RMSE、残差均为收益率比例单位。'} 默认查看验证集；测试集仅用于最终评价。指标为 — 表示数学上未定义。`);
  const splitRows = [['样本数', ...Object.keys(splitNames).map(k => d.splits[k].count)]];
  for (const key of keys) splitRows.push([metricNames[key], ...Object.keys(splitNames).map(name => metricValue(key, d.splits[name].metrics[key]))]);
  html+=`<h3 class="diagnostic-heading">训练 / 验证 / 测试对照</h3>`+table(['指标','训练集','验证集','测试集'], splitRows);
  html+=`<div class="diagnostic-section"><h3>${splitNames[split]} · 基线对照</h3><p class="sub">${escape(s.start)} → ${escape(s.end)} · ${s.count} 个有效样本</p>`;
  const baseKeys=binary?['log_loss','brier','auc','average_precision']:['mae','rmse','r2'];
  html+=table(['方法',...baseKeys.map(k=>metricNames[k])],[['当前模型',...baseKeys.map(k=>fmt(s.metrics[k]))],...Object.entries(s.baseline_metrics).map(([name,metrics])=>[baseLabels[name],...baseKeys.map(k=>fmt(metrics[k]))])]);
  html+=note(`${s.primary_metric==='rmse'?'RMSE 相对训练均值基线':'Log Loss 相对训练正类比例基线'}改善：${percent(s.baseline_improvement)}。正值表示误差更小；负值表示不如基线。基线参数只由训练标签估计。`);
  for(const warning of s.warnings||[])html+=`<p class="error">${escape(warning)}</p>`;
  html+='</div>';
  if(binary){
    const c=s.metrics.confusion,bins=s.charts.calibration;
    html+=`<div class="diagnostic-grid">${xyChart([{name:'ROC',points:s.charts.roc}],{title:'类别区分 · ROC',xLabel:'假正例率',yLabel:'真正例率',unit:true})}${xyChart([{name:'PR',points:s.charts.pr}],{title:'正类识别 · Precision / Recall',xLabel:'Recall',yLabel:'Precision',unit:true})}</div>`;
    html+=`<div class="diagnostic-grid">${xyChart([{name:'概率分箱',points:bins.map(b=>({x:b.prediction_mean,y:b.actual_rate}))}],{title:'概率可靠性 · 校准曲线',xLabel:'平均预测概率',yLabel:'实际正类比例',unit:true,diagonal:true})}<div class="diagnostic-plot"><h3>混淆矩阵 · 阈值 0.5</h3>${table(['实际 / 预测','预测 0','预测 1'],[['实际 0',c.tn,c.fp],['实际 1',c.fn,c.tp]])}${note(`校准误差 ECE：${fmt(s.charts.ece)}，采用固定 10 个概率区间。小样本分箱波动较大，结合数量判断。`)}</div></div>`;
    html+=`<details class="diagnostic-section"><summary>概率分箱详情</summary>${table(['概率区间','样本数','平均预测概率','实际正类比例'],bins.map(b=>[`${fmt(b.lower,1)} – ${fmt(b.upper,1)}`,b.count,percent(b.prediction_mean),percent(b.actual_rate)]))}</details>`;
  }else{
    html+=`<div class="diagnostic-grid">${xyChart([{name:'按时间等距抽样，最多 300 点',points:s.charts.scatter}],{title:'预测值与实际值',xLabel:'实际收益',yLabel:'预测收益',scatter:true,diagonal:true})}${histogram(s.charts.residual_histogram)}</div>`;
    html+=note(`绝对误差 P95：${fmt(s.charts.absolute_error_p95,6)}；残差中位数：${fmt(s.charts.residual_quantiles['0.5'],6)}。散点图抽样展示，指标与残差分布使用全部有效样本。`);
  }
  const segmentKeys=binary?['auc','log_loss','brier','positive_rate']:['mae','rmse','spearman','bias'];
  html+=`<details class="diagnostic-section" open><summary>${splitNames[split]} · 时间分段表现</summary>${table(['起止时间','样本数',...segmentKeys.map(k=>metricNames[k])],s.segments.map(row=>[`${escape(row.start)}<br>${escape(row.end)}`,row.count,...segmentKeys.map(k=>metricValue(k,row.metrics[k]))]))}${note('按有效样本时间顺序分段，最多四段，每段至少约 20 个样本。使用同一个模型，无滚动重训练，不是独立重复实验。')}</details>`;
  html+=modelPanel(d);
  const repeats=d.repeats||{runs:[],note:'未记录重复训练'};
  html+=`<details class="diagnostic-section"><summary>随机种子稳定性 · ${repeats.runs.length} 次训练</summary>${note(repeats.note)}`;
  if(repeats.runs.length>1)html+=table(['随机种子','测试 '+metricNames[s.primary_metric],binary?'测试 AUC':'测试 Spearman'],repeats.runs.map(r=>[r.seed,fmt(r.metrics[s.primary_metric]),fmt(r.metrics[binary?'auc':'spearman'])]));
  if(Object.keys(repeats.summary||{}).length)html+=table(['测试指标','均值','样本标准差','最小值','最大值'],Object.entries(repeats.summary).map(([key,v])=>[metricNames[key],fmt(v.mean),fmt(v.std),fmt(v.min),fmt(v.max)]));
  html+='</details><details class="diagnostic-section"><summary>评价口径与限制</summary>'+d.notes.map(note).join('')+'</details></div></section>';
  return html;
}
