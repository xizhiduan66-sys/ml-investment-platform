const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export const paramField=p=>{
  const label=esc(p.description||p.name);
  if(p.kind==='bool')return `<div class="field"><label><input type="checkbox" data-param="${esc(p.name)}" data-kind="bool" ${p.default?'checked':''}> ${label}</label></div>`;
  if(p.kind==='enum')return `<div class="field"><label>${label}</label><select data-param="${esc(p.name)}" data-kind="enum">${(p.options||[]).map(o=>`<option value="${esc(o)}" ${o===p.default?'selected':''}>${esc(o)}</option>`).join('')}</select></div>`;
  const numeric=p.kind==='int'||p.kind==='float';
  const attrs=`${p.minimum!=null?`min="${p.minimum}"`:''} ${p.maximum!=null?`max="${p.maximum}"`:''} ${numeric?`step="${p.kind==='int'?'1':'0.0001'}" required`:''}`;
  return `<div class="field"><label>${label}</label><input type="${numeric?'number':'text'}" data-param="${esc(p.name)}" data-kind="${esc(p.kind)}" value="${esc(p.default??'')}" ${attrs}></div>`;
};
export const collectParams=form=>{
  const out={};
  form.querySelectorAll('[data-param]').forEach(el=>{
    const kind=el.dataset.kind,name=el.dataset.param;
    if((kind==='int'||kind==='float')&&el.value==='')throw Error('参数 '+name+' 不能为空');
    out[name]=kind==='bool'?el.checked:(kind==='int'||kind==='float')?Number(el.value):el.value;
  });
  return out;
};
