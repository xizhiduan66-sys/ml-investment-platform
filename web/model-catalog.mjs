export const modelGroups = [
  {id:'tree',name:'树模型',description:'适合已计算好的特征向量，建议从 LightGBM 开始。'},
  {id:'sequence',name:'时序模型',description:'输入连续多根 K 线的特征，用 LSTM 与 GRU 对照。'},
];

export function groupedModels(models){
  const group=m=>m.group||(['lstm','gru'].includes(m.id)?'sequence':'tree');
  return modelGroups.map(g=>({...g,models:models.filter(m=>group(m)===g.id)})).filter(g=>g.models.length);
}

export function initialModel(models,task,copiedId){
  // A copied configuration must not silently change its model, even if unavailable.
  if(copiedId)return models.some(m=>m.id===copiedId)?copiedId:'';
  const available=models.filter(m=>m.available&&m.tasks.includes(task));
  return available.find(m=>m.recommended)?.id||
    ['lightgbm','xgboost','lstm','gru'].find(id=>available.some(m=>m.id===id))||
    available[0]?.id||models[0]?.id||'';
}
