"""实验产物的删除与回收。

产物的文件名全部由 id 派生：``{id}.json``（结果报告）、``{id}.pkl``（模型）、
``{id}.predictions.json``（预测）、``{id}.csv``（实验私有行情副本）；快照库里的
文件则以内容摘要命名。因此“哪些文件还有引用”可以直接从库里已有的 id 推出来，
不必解析结果 JSON 的内部结构。

删除顺序：先删库里的行（唯一事实来源），再尽力删文件。旧实现是先删文件再删行，
中途失败会留下“记录还在、文件没了”的破状态；反过来，最坏情况只留下孤儿文件，
由 gc() 兜底清掉。
"""
import json
import re
import sys

from . import storage, runs, jobs

SUFFIXES = ('.json', '.pkl', '.predictions.json', '.csv')

# 只认由 id 派生的文件名，避免误删日志、数据库、锁文件或手工产物。
_ID_NAME = re.compile(r'^(?:[0-9a-f]{12}|[0-9a-f]{32}|market-[0-9a-f]{24})'
                      r'(?:\.json|\.pkl|\.predictions\.json|\.csv)$')


def artifact_names(identifier, executions=()):
    """一个实验（及其运行记录）认领的全部文件名。"""
    names = {identifier + suffix for suffix in SUFFIXES}
    for execution in executions:
        for owner in (execution['id'], execution.get('artifact_id')):
            if owner:
                names |= {owner + suffix for suffix in SUFFIXES}
    return names


def referenced():
    """当前库里所有仍有引用的产物文件名。"""
    names = set()
    for dataset in storage.all_of('dataset'):
        if dataset.get('file'):
            names.add(dataset['file'])
    executions = storage.all_of('run')
    for record in storage.all_of('experiment'):
        names |= artifact_names(record['id'], [e for e in executions if e['experiment_id'] == record['id']])
        # 历史实验可能直接引用共享快照文件（而不是以实验 id 命名的私有副本），
        # 这里的兜底保证 gc 不会把仍在使用的快照删掉。
        snapshot = (record.get('snapshot') or {}).get('dataset') or {}
        if snapshot.get('file'):
            names.add(snapshot['file'])
    for record in executions:
        names |= artifact_names(record['id'])
    for record in storage.all_of('backtest'):
        names |= artifact_names(record['id'])
    return names


def orphans():
    """磁盘上存在、但没有任何记录引用的产物。只读。"""
    keep = referenced()
    return sorted(path.name for path in storage.ROOT.iterdir()
                  if path.is_file() and _ID_NAME.match(path.name) and path.name not in keep)


def gc(apply=False):
    """回收孤儿产物。默认 dry-run，只有 apply=True 才真的删除。"""
    names = orphans()
    removed, failed = [], []
    if apply:
        for name in names:
            try:
                (storage.ROOT / name).unlink(missing_ok=True)
                removed.append(name)
            except OSError as exc:
                failed.append(f'{name}: {exc}')
    return {'applied': apply, 'orphans': names, 'removed': removed, 'failed': failed}


def purge(experiment_id):
    """删除一个实验：库里的记录、队列状态与产物文件。"""
    executions = runs.list_for(experiment_id)
    jobs.forget([execution['id'] for execution in executions], experiment_id)
    for execution in executions:
        storage.delete('run', execution['id'])
    storage.delete('experiment', experiment_id)
    removed, failed = [], []
    for name in sorted(artifact_names(experiment_id, executions)):
        try:
            (storage.ROOT / name).unlink(missing_ok=True)
            removed.append(name)
        except OSError as exc:
            failed.append(f'{name}: {exc}')
    return {'files': removed, 'failed': failed}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='清理没有引用的实验产物（默认只打印）')
    parser.add_argument('--apply', action='store_true', help='真正删除，不加只做 dry-run')
    args = parser.parse_args(argv)
    print(json.dumps(gc(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
