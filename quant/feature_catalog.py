from . import factors, storage


def registered_features():
    """从注册表读取定义，仅从数据库读取用户配置。"""
    metadata = {record['id']: record for record in storage.all_of('feature_metadata')}
    previous = {record['id']: record for record in storage.all_of('factor') if record.get('registered')}
    records = {}
    for spec in factors.specs().values():
        saved = metadata.get(spec.id, previous.get(f'registered:{spec.id}', {}))
        params = {param.name: param.default for param in spec.params if param.default is not None}
        for param in spec.params:
            if param.name in saved.get('params', {}):
                params[param.name] = param.validate(saved['params'][param.name])
        records[spec.id] = {
            'id': spec.id, 'spec_id': spec.id, 'name': spec.name,
            'description': spec.description, 'category': saved.get('category', spec.family),
            'note': saved.get('note', spec.default_note), 'params': params,
            'version': spec.version, 'scope': spec.scope, 'registered': True,
            'event_source': (spec.event_source or 'chan') if spec.scope == 'event' else None,
        }
    return records


def feature_records(ids):
    registered = registered_features()
    return [registered[key] if key in registered else storage.get('factor', key) for key in ids]
