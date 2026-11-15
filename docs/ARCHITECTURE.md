# 单标的量化研究平台架构

当前实现为本地模块化单体：FastAPI 提供 API 与静态页面，后台单线程执行训练任务；Python 负责全部因子、标签、模型和交易计算。图中实线均对应已有代码。

```mermaid
flowchart TB
    U["研究者"] --> UI["前端管理与可视化<br/>web/app.js + 本地 K 线组件<br/>因子 · 目标 · 模型 · 实验 · 回测 · 数据"]
    UI <-->|"HTTP / JSON"| API["FastAPI · quant/app.py<br/>参数校验 · 目录 · 预览 · 任务提交 · 导出"]

    subgraph Backend["Python 后端"]
        DATA["行情与快照<br/>data.py / binance.py<br/>CSV / Binance → OHLCV 校验 → SHA256"]
        FACTOR["因子系统 · factors/<br/>插件注册 → 参数实例 → 因子集<br/>FactorContext / 特征矩阵 / Manifest"]
        EVAL["特征相关性 · factors/analysis.py<br/>Spearman 相关矩阵<br/>输入由调用方按区间切好"]
        QUEUE["进程内串行队列<br/>ThreadPoolExecutor：1 个训练线程"]
        ENGINE["实验编排 · engine.py<br/>标签与采样 → 时间切分 → 标签边界剔除<br/>训练 / 验证 / 样本外评估"]
        MODEL["模型适配 · models.py<br/>LightGBM · XGBoost · LSTM · GRU<br/>训练集标准化 · 模型产物 · 预测值"]
        DIAG["模型诊断 · evaluation.py<br/>三分区指标 / 训练基线 / 残差或校准<br/>模型专属诊断 / 时间分段 / 可选种子重复"]
        SIGNAL["交易信号<br/>预测值 + 开仓阈值 / SMA 规则"]
        BT["统一订单引擎 · backtest.py<br/>order-v2<br/>次根开盘成交 → 现金与持仓记账<br/>成本 / 风控 / 收盘计价 / 期末平仓"]
        REPORT["结果<br/>预测指标 · 净值 · 同期基准<br/>回撤 · 订单 · 往返交易"]
    end

    API --> DATA
    API --> FACTOR
    API --> EVAL
    DATA --> FACTOR
    FACTOR --> EVAL
    API --> QUEUE --> ENGINE
    DATA --> ENGINE
    FACTOR --> ENGINE
    ENGINE --> MODEL
    MODEL -->|"样本外预测"| ENGINE
    ENGINE --> DIAG
    DIAG --> REPORT
    ENGINE --> SIGNAL
    API -->|"独立回测"| SIGNAL
    SIGNAL --> BT --> REPORT
    REPORT --> API

    subgraph Store["本地持久化 · storage.py / data/"]
        DB["SQLite · research.db<br/>分类 / 因子实例 / 因子集 / 标签<br/>数据元信息 / 实验状态与快照 / 回测摘要"]
        FILES["文件<br/>SHA256.csv 行情<br/>实验或回测 JSON<br/>模型 PKL"]
    end
    API <--> DB
    ENGINE <--> DB
    DATA <--> FILES
    ENGINE --> FILES
    API <--> FILES
```

## 一次实验的执行顺序

```mermaid
sequenceDiagram
    participant U as 前端
    participant A as API
    participant S as SQLite / 文件
    participant E as 实验线程
    participant F as 因子系统
    participant M as 模型
    participant B as 订单引擎
    U->>A: 选择数据、因子集、目标、模型与交易阈值
    A->>F: 校验参数、版本、特征顺序与 Manifest
    A->>S: 保存实验快照，状态 queued
    A-->>U: 实验 ID
    A->>E: 提交串行任务
    E->>S: 读取行情并校验内容哈希
    E->>F: 计算对齐的特征矩阵
    E->>E: 构造标签 / 采样 / 60-20-20 时间切分
    E->>E: 剔除跨边界标签，排除无效样本
    E->>M: 训练；时序模型使用验证集选择轮次
    M-->>E: 测试预测、模型产物、训练历史
    E->>B: 预测转信号，执行样本外区间
    B-->>E: 现金账本、净值、订单、交易指标
    E->>S: 保存模型与结果 JSON，状态 completed
    U->>A: 轮询状态 / 获取详情
    A->>S: 读取结果
    A-->>U: 可视化 / 比较 / JSON 导出
```

## 核心对象及边界

| 对象 | 职责与约束 |
|---|---|
| Dataset | OHLCV 文件、时间范围、SHA256；每次读取验证实际文件内容 |
| FactorSpec | Python 算法声明：族、参数 schema、版本、scope、缺失策略、必需行情列 |
| FactorInstance | 具体参数与分类，保存在 SQLite；版本变化需重新创建 |
| FactorSet | 可复用的实例组合，绑定 Manifest 哈希 |
| FeatureManifest | 有序特征清单，记录实例、稳定标识、参数、版本、dtype、缺失策略 |
| Target | 回归收益或二分类标签；区间为下一根开盘至 h 根后开盘 |
| Experiment | 数据/因子/目标/模型配置快照、代码哈希、依赖版本、随机种子、状态 |
| ModelOutput | 回归：收益率；二分类：超过标签门槛的概率。预测值需经交易阈值转换 |
| Backtest | 统一执行语义、成本与风控；记录 `engine_version`，独立回测也记录代码哈希 |

前端只管理配置和展示结果。因子分类不决定计算方法：均线可使用向量化 `series` 插件，结构类可使用 `sample` 插件；最终都输出按行情索引对齐的一维数值序列，供模型组合使用。

`FactorContext` 公开接口只返回当前及历史数据的副本；私有字段不构成安全沙箱。`series` 插件能看到传入区间的完整 DataFrame，作者仍须避免未来函数，并为新增插件编写前缀截断一致性测试。框架不能自动证明任意 Python 算法不存在未来信息。

## 当前研究与成交约定

- 研究切分（60% 训练、20% 验证、20% 测试）统一由 `quant/splits.py` 定义，实验、事件采样与特征相关性共用同一口径。特征模块不感知切分：调用方先按区间切好行情，再交给它计算矩阵与相关性。单标的没有横截面，因此不计算 IC；择时能力由实验与回测判断。
- 标签预测跨度与持仓时间相互独立。收盘预测，下一根开盘成交，收盘估值；最后一个预测在下一根开盘执行后，于同根收盘清仓。
- 实验成本以手续费计入，滑点为零；独立回测继承实验成本，也可显式修改。相同信号、成本、仓位和风控参数下，两入口净值一致。
- 跳空先按开盘价格判断止损/止盈；盘中同时触及两条线且无更细路径时，保守地按止损先发生。实际价格路径不能由 OHLC 唯一确定。
- 基准在同一个可执行开盘全仓买入，并在同一期末清仓，使用相同成本。暴露比例统计发生持仓的 K 线占比，不表示精确盘中持仓时间。
- 历史 JSON 原样保留。旧实验没有 `order-v2` 标记，应重新运行后再与新结果比较。

## 后续扩展位置（尚未实现）

| 需求 | 建议接入位置 | 当前状态 |
|---|---|---|
| 缠论笔、线段、中枢与确认时点 | 新增结构计算层，再注入 `FactorContext.structure` | 仅有接口占位，当前为 None |
| 事件采样、滚动训练 | 从 `engine.py` 抽出采样器与切分器 | 当前逐 K 线采样、固定切分 |
| 自定义损失 | 给模型适配器增加 LossSpec 与兼容性校验 | 损失目前固定在模型实现中 |
| 强化学习奖励 | 新增交易环境、状态/动作及 RewardSpec | 当前是监督学习，无 RL 环境 |
| 模型加载与持续预测 | 新增统一 artifact 加载及预测服务 | 当前只生成训练产物 |
| 持久化任务和多进程部署 | 替换进程内队列，增加任务认领与锁 | 当前要求单服务进程，重启会将未完成任务标记失败 |

快照提供追溯信息，但未保存可独立重建的历史代码包与完整运行环境；长期复现还需版本控制和环境归档。
