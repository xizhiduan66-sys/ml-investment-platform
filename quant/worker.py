"""Run with python -m quant.worker, using the API's QUANT_DATA_DIR."""
import argparse
from contextlib import contextmanager
import fcntl
import logging
import signal
import threading
import uuid
from . import jobs, storage, market_queue

log = logging.getLogger(__name__)


@contextmanager
def exclusive_worker(queue="research"):
    with (storage.ROOT / f'{queue}-worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('该数据目录已有研究 Worker 运行') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def execute(job, worker_id, queue="research"):
    backend = jobs if queue == "research" else market_queue
    from . import engine
    done = threading.Event()

    def beat():
        while not done.wait(5):
            try:
                backend.heartbeat(job['id'], worker_id)
            except Exception:
                log.exception('任务心跳写入失败')

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    error = None
    try:
        if queue == 'research':
            engine.run(job['run_id'])
        else:
            from . import market_jobs
            market_jobs.run(job['id'])
    except Exception as exc:
        log.exception('任务执行失败')
        error = f'{type(exc).__name__}: {exc}'
    finally:
        done.set()
        thread.join()
    backend.finish(job, worker_id, error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='最多执行一个任务后退出')
    parser.add_argument('--queue', choices=['research', 'market'], default='research')
    args = parser.parse_args()
    backend = jobs if args.queue == 'research' else market_queue
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with exclusive_worker(args.queue):
        backend.recover_exclusive()
        worker_id = uuid.uuid4().hex
        while not stop.is_set():
            job = backend.claim(worker_id)
            if job:
                log.info('执行研究任务 %s', job['id'])
                execute(job, worker_id, args.queue)
            if args.once:
                break
            if not job:
                stop.wait(1)


if __name__ == '__main__':
    main()
