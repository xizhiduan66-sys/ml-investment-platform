"""Public OKX USDT perpetual trade candles."""
import csv
import http.client
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from threading import Lock, local

BASE = 'https://www.okx.com/api/v5'
PAGE = 300
HISTORY_INTERVAL = .18
_history_lock = Lock()
_history_next = 0.
_connections = local()
BARS = {'1h': '1H', '2h': '2H', '4h': '4H', '6h': '6Hutc',
        '12h': '12Hutc', '1d': '1Dutc', '3d': '3Dutc', '1w': '1Wutc'}


class SourceUnavailable(ValueError):
    pass


def _history_response(request):
    global _history_next
    with _history_lock:
        delay = _history_next - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _history_next = time.monotonic() + HISTORY_INTERVAL
    if urllib.request.getproxies().get('https') and not urllib.request.proxy_bypass('www.okx.com'):
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    connection = getattr(_connections, 'history', None)
    if connection is None:
        connection = _connections.history = http.client.HTTPSConnection('www.okx.com', timeout=10)
    try:
        connection.request('GET', request.selector, headers=dict(request.header_items()))
        with connection.getresponse() as response:
            if response.status != 200:
                raise urllib.error.HTTPError(request.full_url, response.status, response.reason, response.headers, None)
            return json.loads(response.read())
    except (OSError, http.client.HTTPException):
        connection.close()
        _connections.history = None
        raise


def _get(path, **params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        'User-Agent': 'QuantResearch/1.0', 'Accept': 'application/json',
    })
    for attempt in range(4):
        try:
            if path == '/market/history-candles':
                body = _history_response(request)
            else:
                with urllib.request.urlopen(request, timeout=10) as response:
                    body = json.load(response)
            if body.get('code') == '0':
                return body['data']
            if body.get('code') != '50011':
                raise SourceUnavailable(f'OKX 返回 {body.get("code")}：{body.get("msg")}')
            error = body.get('msg')
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise SourceUnavailable(f'OKX 接口返回 HTTP {exc.code}') from exc
            error = exc
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            error = exc
        if attempt < 3:
            time.sleep(2 ** attempt)
    raise SourceUnavailable(f'OKX 接口重试后仍不可用：{error}')


def contracts():
    return {row['instId'].replace('-USDT-SWAP', 'USDT'): int(row['listTime']) // 1000
            for row in _get('/public/instruments', instType='SWAP')
            if row['instId'].endswith('-USDT-SWAP') and row['state'] == 'live'}


def _instrument(symbol):
    if not symbol.endswith('USDT') or not symbol[:-4].isascii() or not symbol[:-4].isalnum():
        raise ValueError('请选择 USDT 本位永续合约')
    return symbol[:-4]+'-USDT-SWAP'


def preview(symbol):
    return _get('/market/candles', instId=_instrument(symbol), bar='1m', limit=100)


def _page(symbol, period, before, limit):
    return _get('/market/history-candles', instId=_instrument(symbol),
                bar=BARS.get(period, period), after=before, limit=limit)


def earliest_minute(symbol, end):
    # Locate the earliest minute exposed by the public history endpoint.
    left, right = 0, end // 60
    if not _page(symbol, '1m', right * 60000, 1):
        raise SourceUnavailable('OKX 未返回历史分钟行情')
    while right - left > 1:
        middle = (left + right) // 2
        if _page(symbol, '1m', middle * 60000, 1):
            right = middle
        else:
            left = middle
    data = _page(symbol, '1m', right * 60000, 1)
    if not data or data[0][-1] != '1':
        raise SourceUnavailable('OKX 最早分钟行情尚未确认')
    return int(data[0][0]) // 1000


def klines(symbol, period, start, end, limit, step):
    """Adapt OKX trade candles to the shared candle validator."""
    before = end * 1000
    lower = start * 1000
    found = []
    while before > lower and len(found) < limit:
        size = min(PAGE, limit - len(found))
        page = _page(symbol, period, before, size)
        if not page:
            break
        timestamps = [int(row[0]) for row in page]
        if max(timestamps) >= before or len(set(timestamps)) != len(timestamps):
            raise ValueError('OKX 分页时间戳重复或超出游标')
        for row in page:
            opened = int(row[0])
            if opened >= lower and row[-1] == '1' and opened + step * 1000 <= end * 1000:
                found.append([*row[:6], opened + step * 1000 - 1])
        before = min(timestamps)
    return sorted(found, key=lambda row: int(row[0]))


def archives(symbol, start, end, grouping):
    instrument = _instrument(symbol)
    entries = _get('/public/market-data-history', module=2, instType='SWAP',
                   instFamilyList=instrument.removesuffix('-SWAP'), dateAggrType=grouping,
                   begin=start * 1000, end=end * 1000 - 1)
    for batch in entries:
        for detail in batch['details']:
            for item in detail['groupDetails']:
                stamp = int(item['dateTs']) // 1000
                if start <= stamp < end and item['filename'].startswith(instrument+'-candlesticks-'):
                    yield stamp, item['url']


def archive_rows(symbol, url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'static.okx.com' or not parsed.path.startswith('/cdn/okex/traderecords/candlesticks/'):
        raise ValueError('OKX 归档链接异常')
    with urllib.request.urlopen(url, timeout=20) as response:
        if urllib.parse.urlsplit(response.geturl()).netloc != 'static.okx.com':
            raise ValueError('OKX 归档重定向异常')
        content = response.read(16 * 1024 * 1024 + 1)
    if len(content) > 16 * 1024 * 1024:
        raise ValueError('OKX 归档超过大小限制')
    instrument = _instrument(symbol)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        files = archive.infolist()
        if (len(files) != 1 or not files[0].filename.startswith(instrument+'-candlesticks-')
                or not files[0].filename.endswith('.csv') or files[0].file_size > 32 * 1024 * 1024):
            raise ValueError('OKX 归档内容异常')
        with archive.open(files[0]) as stream:
            for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig')):
                if row['instrument_name'] != instrument or row['confirm'] != '1':
                    raise ValueError('OKX 归档包含其他合约或未收盘数据')
                timestamp = int(row['open_time'])
                yield [timestamp, *(row[key] for key in ('open', 'high', 'low', 'close', 'vol')), timestamp+59999]
