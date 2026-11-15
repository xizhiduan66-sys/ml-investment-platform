"""研究切分口径：60% 训练 / 20% 验证 / 20% 测试。

唯一来源。特征模块不感知切分，只对调用方切好的数据做计算。
"""

TRAIN_SHARE, VALID_SHARE = .6, .8
SEGMENTS = ('train', 'valid', 'test', 'all')


def edges(n):
    """返回训练/验证边界：训练 [0, a)，验证 [a, b)，测试 [b, n)。"""
    if n < 1:
        raise ValueError('切分需要至少一根 K 线')
    a, b = int(n * TRAIN_SHARE), int(n * VALID_SHARE)
    return a, b


def bounds(n, segment='train'):
    if segment not in SEGMENTS:
        raise ValueError('segment 必须为 train、valid、test 或 all')
    a, b = edges(n)
    return {'train': (0, a), 'valid': (a, b), 'test': (b, n), 'all': (0, n)}[segment]
