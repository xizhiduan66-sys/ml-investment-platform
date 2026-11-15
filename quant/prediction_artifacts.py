"""Versioned prediction files independent of trading reports."""
import hashlib
import json
import os
import tempfile
from . import storage


def publish(experiment_id, dataset, task, sampling, rows):
    payload = {'version': 1, 'experiment_id': experiment_id, 'dataset_sha256': dataset['sha256'],
               'task': task, 'sampling': sampling,
               'semantic': 'probability' if task == 'binary' else 'value',
               'positive_class': 1 if task == 'binary' else None, 'rows': rows}
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    name = experiment_id + '.predictions.json'
    fd, temporary = tempfile.mkstemp(prefix='prediction-', suffix='.tmp', dir=storage.ROOT)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, storage.ROOT / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'version': 1, 'file': name, 'sha256': hashlib.sha256(content).hexdigest()}


def load(reference, experiment_id, dataset, task):
    expected_name = experiment_id + '.predictions.json'
    if reference.get('version') != 1 or reference.get('file') != expected_name:
        raise ValueError('预测产物引用无效')
    content = (storage.ROOT / expected_name).read_bytes()
    if hashlib.sha256(content).hexdigest() != reference.get('sha256'):
        raise ValueError('预测产物校验失败')
    payload = json.loads(content)
    if (payload.get('version') != 1 or payload.get('experiment_id') != experiment_id or
            payload.get('dataset_sha256') != dataset['sha256'] or payload.get('task') != task):
        raise ValueError('预测产物与实验或数据不一致')
    if payload.get('sampling') != 'bar':
        raise ValueError('事件预测需要独立的交易执行规则')
    return [row for row in payload['rows'] if row['split'] == 'test']
