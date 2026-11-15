# Worker 与运行记录

API 只提交任务。研究和行情各需要一个独立 Worker，使用与 API 相同的
工作目录、Python 环境和 QUANT_DATA_DIR（默认项目 data 目录）：

```sh
.venv/bin/python -B -m uvicorn quant.app:app --host 127.0.0.1 --port 8776
.venv/bin/python -B -m quant.worker --queue research
.venv/bin/python -B -m quant.worker --queue market
```

以上命令分别在三个终端运行。未启动对应 Worker 时任务保持排队。
升级前必须停止全部旧版 API 和 Worker，备份 research.db 及产物目录，
再启动新版；不能让旧版线程池任务和新 Worker 同时写入。
代码改造不会自动重启用户正在运行的服务。

## 数据模型

Experiment 保存 name、snapshot、created_at 等研究定义；运行状态不再写回定义。
每次执行是独立 Run，保存 experiment_id、状态、时间、种子、摘要、产物 ID。
Job 通过 run_id 关联 Run，负责领取、心跳和结果登记。
同一实验重跑不复制数据快照，模型/报告/预测文件使用各自 Run ID，互不覆盖。

首次初始化会将旧实验执行状态迁移为一个 Run，使用 artifact_id 保留旧文件引用；
迁移在事务中执行且可重复运行。旧任务列 experiment_id 自动改名为 run_id。
历史记录继续存放在 objects 表，以 kind 区分；尚未改为专用关系表。

旧实验查询和列表通过兼容投影返回最近一次 Run 的状态；现有页面继续可用。
新增接口：
- GET /api/experiments/{id}/runs：列出全部运行。
- POST /api/experiments/{id}/runs：使用冻结定义创建新运行。
- GET /api/runs/{id}：单次运行及完成结果。
- POST /api/backtests：可选 run_id，指定该实验某次已完成运行。

运行列表和重跑当前通过 API 提供，前端尚未增加专门的 Run 管理页面。
删除实验时，任何运行仍在排队/执行都会阻止删除；完成后清理全部运行产物。

## 执行与恢复

两类队列分别使用 SQLite 原子领取与独立的 OS 文件锁，互不阻塞计算。
同一目录每类只能有一个 Worker；支持 macOS/Linux（fcntl）。
每 5 秒更新心跳，不单凭超时夺取执行权。
获得锁后恢复：保留 queued；运行已完成则补记结果；其他中断任务标记失败。
研究任务可通过新建 Run 重试；行情通过重新提交复用暂存下载数据。
行情 pending/mismatch 保留原状态，不自动无限重试。

SIGTERM/SIGINT 停止领取新任务，等待当前任务完成后退出。
--once 最多执行一个任务后退出。暂不支持训练检查点续跑、用户取消、
跨机器调度和文件/数据库的统一产物恢复协议。
