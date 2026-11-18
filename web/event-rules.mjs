export function eventRuleSummary(rule, providers = []) {
  const provider = providers.find(item => item.id === rule?.provider);
  if (!rule) return '';
  const parameters = Object.entries(rule.params).filter(([key]) =>
    key !== 'weekday' || rule.params.frequency !== '每天').map(([key, value]) => {
    if (key === 'types') return value.map(id => provider?.types?.[id] || id).join('、');
    const description = provider?.parameters.find(param => param.name === key)?.description || key;
    return description + ' ' + value;
  });
  return ['v' + rule.version, ...parameters].join(' · ');
}
