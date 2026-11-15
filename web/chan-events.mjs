const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v==null?'—':Number(v).toFixed(4);
export function eventPanel(report, predictedOnly=false,output=null,compact=false){
  const events=report.events||[], rows=predictedOnly?events.filter(e=>e.split==='test'):events;
  const predictedReturn=output?.unit==='return';
  const isReturnTarget=output?.horizon!=null;
  const predictionTitle=isReturnTarget?(predictedReturn?'预测收益率':'超门槛概率'):'保留概率';
  const value=v=>predictedReturn&&v!=null?(v*100).toFixed(2)+'%':num(v);
  const overview=compact?'':`<div class="stats">${['confirmed','invalidated','pending'].map(s=>`<div class="stat"><span>${{confirmed:'确认保留 · 1',invalidated:'结构失效 · 0',pending:'结构待确认'}[s]}</span><strong>${report.counts?.[s]??0}</strong></div>`).join('')}</div>
  <div class="detail-note">峰值比与面积比在首次可见时冻结。二类点使用当时关联一类点的背驰特征。</div>`;
  return `${overview}
  <section class="panel"><div class="panel-head"><h2>${predictedOnly?'样本外事件预测':'买卖点生命周期'}</h2><span>最近 ${Math.min(rows.length,300)} / ${rows.length} 条</span></div><div class="table-wrap"><table><thead><tr><th>类型</th><th>拐点时间</th><th>首次可见</th><th>${isReturnTarget?'收益标签可知时间':'结构定型时间'}</th><th>状态</th><th>峰值比</th><th>面积比</th><th>${predictionTitle}</th>${predictedOnly?'<th>实际标签</th>':''}</tr></thead><tbody>${rows.slice(-300).reverse().map(e=>`<tr><td>${e.type==='1'?'一':'二'}类${e.side==='buy'?'买':'卖'}点</td><td>${esc(e.anchor_time)}</td><td>${esc(e.observed_time)}</td><td>${esc(isReturnTarget?e.target_label_time:e.label_time)}</td><td>${{pending:'待确认',confirmed:'保留 1',invalidated:'失效 0'}[e.status]}${!e.eligible?' · 首现即冻结':''}</td><td>${num(e.features?.['chan.peak_ratio'])}</td><td>${num(e.features?.['chan.area_ratio'])}</td><td>${value(e.prediction)}</td>${predictedOnly?`<td>${value(e.target_label??e.label)}</td>`:''}</tr>`).join('')||`<tr><td colspan="${predictedOnly?9:8}">尚无符合条件的事件，请增加历史行情。</td></tr>`}</tbody></table></div></section>`;
}
