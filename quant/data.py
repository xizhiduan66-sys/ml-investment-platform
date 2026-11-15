import hashlib
import io
import numpy as np
import pandas as pd
from . import storage


def validate(df):
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = ['date', 'open', 'high', 'low', 'close', 'volume']
    if any(c not in df for c in required):
        raise ValueError('CSV 必须包含 date,open,high,low,close,volume 六列')
    df = df[required].copy()
    dates = pd.to_datetime(df.date, errors='coerce', utc=True)
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('时间必须有效、唯一，并按升序排列')
    df.date = dates.dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    for key in required[1:]:
        df[key] = pd.to_numeric(df[key], errors='coerce')
    if not np.isfinite(df[required[1:]].values).all():
        raise ValueError('行情含缺失或非有限数值')
    if (df[['open', 'high', 'low', 'close']] <= 0).any().any() or (df.volume < 0).any():
        raise ValueError('价格必须大于 0，成交量不能为负')
    if ((df.high < df[['open', 'close', 'low']].max(axis=1)) | (df.low > df[['open', 'close', 'high']].min(axis=1))).any():
        raise ValueError('OHLC 高低价关系不正确')
    if len(df) < 300 or len(df) > 100000:
        raise ValueError('初版支持 300 至 100000 根 K 线')
    return df


def persist(df, name, source, symbol='', interval=''):
    symbol, interval = symbol.strip(), interval.strip()
    if len(symbol) > 80:
        raise ValueError('标的名称不能超过 80 个字符')
    if interval:
        from .market import STEPS
        if interval not in (*STEPS, '1M', 'custom'):
            raise ValueError('不支持的 K 线级别')
    df = validate(df)
    content = df.to_csv(index=False)
    digest = hashlib.sha256(content.encode()).hexdigest()
    path = storage.ROOT / (digest + '.csv')
    path.write_text(content)
    return storage.save('dataset', {'name': name[:100], 'source': source, 'symbol': symbol, 'interval': interval, 'sha256': digest, 'rows': len(df), 'start': df.date.iloc[0], 'end': df.date.iloc[-1], 'file': path.name})


def load(info):
    content = (storage.ROOT / info['file']).read_bytes()
    if hashlib.sha256(content).hexdigest() != info['sha256']:
        raise ValueError('数据快照校验失败：文件内容已变化，请重新导入')
    return pd.read_csv(io.BytesIO(content))


def preview_page(info, limit, before=None):
    """Read an OHLCV page ending at a CSV record boundary."""
    checksum = hashlib.sha256()
    with (storage.ROOT / info['file']).open('rb') as stream:
        header = stream.readline()
        checksum.update(header)
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
        if checksum.hexdigest() != info['sha256']:
            raise ValueError('数据快照校验失败：文件内容已变化，请重新导入')
        size = stream.tell()
        end = size if before is None else before
        if not len(header) <= end <= size:
            raise ValueError('历史行情游标无效')
        if end != size:
            stream.seek(end - 1)
            if stream.read(1) != b'\n':
                raise ValueError('历史行情游标无效')
        offset = max(len(header), end - 64 * 1024)
        while True:
            stream.seek(offset)
            if offset > len(header):
                stream.readline()  # The seek may land inside a record.
            rows = stream.read(end - stream.tell()).splitlines(keepends=True)
            if len(rows) >= limit or offset == len(header):
                break
            offset = max(len(header), offset - (end - offset))
    content = b''.join(rows[-limit:])
    cursor = end - len(content)
    return pd.read_csv(io.BytesIO(header + content)), cursor if cursor > len(header) else None


def seed():
    if storage.all_of('dataset'):
        return
    rng = np.random.default_rng(42)
    n = 1500
    returns = rng.normal(0.0002, 0.012, n) + np.sin(np.arange(n) / 45) * 0.001
    close = 100 * np.exp(np.cumsum(returns))
    opens = np.r_[100, close[:-1]] * np.exp(rng.normal(0, .002, n))
    spread = rng.uniform(.002, .018, n)
    df = pd.DataFrame({'date': pd.bdate_range('2020-01-01', periods=n), 'open': opens, 'high': np.maximum(opens, close) * (1 + spread), 'low': np.minimum(opens, close) * (1 - spread), 'close': close, 'volume': rng.lognormal(14, .4, n)})
    persist(df, 'DEMO · 合成日线', 'synthetic')
