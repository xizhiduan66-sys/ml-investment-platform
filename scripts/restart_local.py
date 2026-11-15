"""Controlled local restart; takes the verified old API PID as an argument."""
import json, os, signal, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path
root = Path(__file__).resolve().parents[1]
old = int(sys.argv[1])
# Preserve only the service's data-directory override, not unrelated environment values.
process = subprocess.check_output(['ps', 'eww', '-p', str(old), '-o', 'command='], text=True, errors='replace')
env = dict(os.environ)
if 'QUANT_DATA_DIR=' in process:
    value = process.split('QUANT_DATA_DIR=', 1)[1].split(' ', 1)[0]
    env['QUANT_DATA_DIR'] = value
folder = Path(env.get('QUANT_DATA_DIR', root / 'data'))
with urllib.request.urlopen('http://127.0.0.1:8776/api/catalog', timeout=15) as response:
    catalog = json.load(response)
if any(e['status'] == 'running' for e in catalog['experiments']):
    raise SystemExit('当前仍有实验执行，未停止服务')
os.kill(old, signal.SIGTERM)
for _ in range(100):
    try: os.kill(old, 0)
    except ProcessLookupError: break
    time.sleep(.1)
else: raise SystemExit('旧 API 未退出，未启动新进程')
backup = folder / ('research-before-runs-' + time.strftime('%Y%m%d-%H%M%S') + '.db')
with sqlite3.connect(folder / 'research.db') as source, sqlite3.connect(backup) as dest:
    source.backup(dest)
python = str(root / '.venv/bin/python')
commands = [('api', ['-m', 'uvicorn', 'quant.app:app', '--host', '127.0.0.1', '--port', '8776']),
            ('research', ['-m', 'quant.worker', '--queue', 'research']),
            ('market', ['-m', 'quant.worker', '--queue', 'market'])]
processes = {}
for name, args in commands:
    with (folder / (name + '.log')).open('ab') as log:
        child = subprocess.Popen([python, '-B', *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
        processes[name] = child.pid
(folder / 'service-pids.json').write_text(json.dumps(processes))
for _ in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8776/api/catalog', timeout=2) as response:
            result = json.load(response)
        break
    except Exception: time.sleep(.2)
else: raise SystemExit('API 未就绪，请检查 api.log')
for pid in processes.values(): os.kill(pid, 0)
print(json.dumps({'pids': processes, 'backup': str(backup), 'experiments': len(result['experiments'])}))
