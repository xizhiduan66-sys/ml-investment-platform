# 特征与通用事件：六类策略的可复用拆解

> 状态：设计提案，尚未实现。目标是把“策略”拆成两层可复用对象——**每根 K 线的状态特征**与**时点事件**——并说明哪些能直接接进现有因子/事件/标签框架，哪些需要先补数据或执行层。
>
> 以下“默认参数”均以 4h 永续 K 线为基准；1h / 1d 的根数换算见 1.1 末尾。

## 0. 结论先行

1. **特征回答“现在是什么状态”，事件回答“刚刚发生了什么”。** 两者混用会同时失去可解释性和可复用性。
2. 六类策略里，1（EMA 交叉）、2（唐奇安突破）、3（布林回归）、4（RSI 反转）适合抽成事件；5（TSMOM）本质是“时钟 + 状态”；6（网格）本质是“区间状态 + 逐格成交”。硬做成六套事件，会得到六份高度重叠的规则。
3. 更合理的定位是：**策略当事件源与标签生成器，而不是把策略的 0/1 信号当特征。**
   - 策略依赖的指标值 → 通用状态特征；
   - 策略的入场、出场、边界触碰 → 事件；
   - 入场后先到止盈还是先到止损 → 事件标签（meta-labeling）。
   这正好复用现有 `triggers → event sample → target → model` 的链路，也避免“用策略预测策略自己”的循环。
4. **能研究，但还不能完整执行。** 现有回测只做多/空仓，没有做空、杠杆、资金费、标记价、maker 队列和逐格成交；事件样本也不能直接转回测。第 3.3 节逐条说明。

### 与现有代码的对应

| 能力 | 现状 | 位置 |
|---|---|---|
| 行情 | 仅 OHLCV；300–100000 根；UTC；无资金费/持仓量/标记价/基差 | `quant/data.py`, `quant/market.py` |
| 特征 | `series` / `sample` / `event` 三种 scope；参数校验、Manifest、前缀截断因果性测试 | `quant/factors/` |
| 事件 | 仅 `chan`、`rsi_oversold` 两个 provider；每事件一行；首次可见时冻结特征；事件样本只支持向量模型 | `quant/triggers.py`, `quant/chan_events.py` |
| 标签 | 未来收益（回归/二分类/多分类）、缠论结构确认；收益标签不区分买卖方向 | `quant/targets.py` |
| 采样 | 60/20/20 时间切分；跨边界标签剔除；训练≥80、验证/测试各≥30 | `quant/splits.py`, `quant/sampling.py` |
| 回测 | 收盘信号、次根开盘成交；多/空仓；手续费+滑点；止损/止盈/最大持有；同日双触按止损先发生 | `quant/backtest.py` |

## 1. 特征层

### 1.1 设计约定

- **只用已完成 K 线。** 所有窗口右闭；指标在 t 根收盘后可见；交易在 t+1 开盘执行。与 `backtest.py` 的语义一致。
- **不做全序列标准化。** 只用滚动窗口或 ATR/价格归一化，否则 `tests/test_factor_causality.py` 的前缀截断测试会失败。
- **价格无关尺度。** 距离用 ATR 或收盘价百分比表示；强度用 0–1 或分位；避免绝对价格、绝对成交量。
- **缺失保留 NaN。** 预热期输出 NaN，由 `sampling.prepare` 统一剔除；事件型取值缺失应 `missing='drop'`，不能填零假装“没有信号”。
- **一个算法 + 参数 = 一个特征身份。** 沿用 `feature_id(spec_id, params)`，同一 spec 可实例化 20/60、84/168/336 等多个窗口。
- **多周期必须用“已收盘桶”。** 4h 聚合在 4h 边界才能使用；1h 图上引用 4h / 日线指标时，只能取最近一个完整桶，否则是未来函数。
- **控制数量。** 第一批建议 12–16 个特征；同族相关性用现有 Spearman 矩阵检查，|ρ|>0.8 的只留一个。

常用窗口的 K 线根数换算：

| 周期 | 1 周 | 2 周 | 4 周 | 8 周 | 30 天 | 90 天 |
|---|---|---|---|---|---|---|
| 1h | 168 | 336 | 672 | 1344 | 720 | 2160 |
| 4h | 42 | 84 | 168 | 336 | 180 | 540 |
| 1d | 7 | 14 | 28 | 56 | 30 | 90 |

### 1.2 公共积木

| 积木 | 定义 | 默认 |
|---|---|---|
| ATR | `TR=max(H-L, abs(H-C_prev), abs(L-C_prev))`，Wilder RMA | n=14 |
| ADX | `+DM/-DM → ±DI → DX → ADX`，Wilder 平滑；输出除以 100 | n=14 |
| ER | 考夫曼效率：`abs(C_t-C_{t-n}) / Σ abs(ΔC)` | n=20 |
| BB | 中轨 `SMA_n`，带宽 `2kσ_n` | n=20, k=2 |
| RV | 已实现波动：`std(log ret, n)`，可年化 | n=180（4h 约 30 天） |
| 滚动分位 | 当前值在过去 W 根中的排名（0–1） | W=90 天 |
| 已收盘重采样 | 把低周期 OHLCV 聚合成 4h/1d，只在桶闭合后对齐 | — |

### 1.3 特征目录

参数列中 `tf` 表示计算周期；默认 4h。

#### A. 趋势（来自 EMA 交叉）

| 特征 ID | 定义 | 默认参数 | 说明 |
|---|---|---|---|
| `trend.ema_spread` | `(EMA_f - EMA_s) / ATR` | fast=20, slow=60, atr=14 | 有符号趋势强度，跨品种可比 |
| `trend.ema_slope` | `(EMA_s[t] - EMA_s[t-k]) / ATR` | k=1 | 慢线斜率过滤，替代“绝对值 > 阈值” |
| `trend.ema_age` | `sign(spread) * min(距上次符号翻转根数, cap)` | cap=120 | 方向 + 新鲜度；刚交叉 vs 已钝化 |
| `trend.adx` | ADX/100 | n=14 | 趋势/震荡状态 |
| `trend.er` | 见 1.2 | n=20 | 0 附近震荡，1 附近单边 |
| `trend.ema_dist` | `(C - EMA_f) / ATR` | fast=20 | 入场是否已过度延伸 |
| `channel.position` | `(C - L_n)/(U_n - L_n)`，`U/L` 为前 n 根高/低（不含当前） | n=20 | 可越界；>1 表示突破 |
| `channel.break_atr` | 突破前 n 根通道的距离 / ATR，未突破为 0 | n=20 | 唐奇安突破强度 |
| `vol.expansion` | `ATR14 / ATR56` | — | 波动扩张，突破策略的顺风指标 |

#### B. 震荡 / 均值回归（来自布林、RSI）

| 特征 ID | 定义 | 默认参数 | 说明 |
|---|---|---|---|
| `mr.bb_z` | `(C - SMA_n)/σ_n` | n=20 | 布林带位置，带符号 |
| `mr.bb_width` | `2kσ_n / SMA_n` | n=20, k=2 | 带宽，绝对波动 |
| `mr.dist_mid` | `(SMA_n - C)/ATR` | n=20 | 回到中轨的“剩余空间”，用风险单位表示 |
| `momentum.rsi` | Wilder RSI，0–100 | n=14 | 直接复用现有因子，不另注册 |
| `mr.half_life` | 滚动 AR(1)：`Δp=a+b p_prev`，`HL=-ln2/ln(1+b)` | 窗口 120，`p=log C` | 均值回归半衰期；b≥0 或 HL 越界记 NaN |
| `mr.variance_ratio` | `Var(r_q)/(q Var(r_1))`，滚动窗口 | q=5, W=120 | <1 回归，>1 趋势；比自相关更稳 |

#### C. 波动 / 区间状态（布林、网格共用）

| 特征 ID | 定义 | 默认参数 | 说明 |
|---|---|---|---|
| `vol.atr_pct` | `ATR / C` | n=14 | 波动水平，也是止损/格距基准 |
| `vol.rv_z` | `(RV_n - mean(RV, W))/std(RV, W)` | n=180, W=540 | 便宜的波动分位替代 |
| `vol.rv_pct` | RV 在 W 根中的分位 | n=180, W=90d | 对应“近 90 天 40% 分位”过滤；建议在日线重采样上算以控制开销 |
| `vol.width_pct` | BB 带宽的滚动分位 | n=20, W=90d | 压缩程度 |
| `vol.squeeze` | `1 - vol.width_pct` | — | 0–1；越高越压缩 |
| `vol.gap_atr` | `abs(O_t - C_{t-1}) / ATR` | atr=14 | 跳空风险，标记价止损的必要性 |

#### D. 动量 / TSMOM

| 特征 ID | 定义 | 默认参数 | 说明 |
|---|---|---|---|
| `mom.return` | `C_t/C_{t-n} - 1` | n=168（4h 4 周） | 实例化 84/168/336 得到 2/4/8 周 |
| `mom.vol_adj` | `ret_n / (σ_bar,n * sqrt(n))` | n=168 | 波动调整动量，等价于 t 值；TSMOM 的仓位分子 |
| `mom.consensus` | `mean(sign(ret_84), sign(ret_168), sign(ret_336))` | 2/4/8 周 | −1…1，多周期一致性 |
| `mom.drawdown` | `C_t / max(C, W) - 1` | W=90d | 距高点回撤 |
| `mom.time_since_high` | 距 W 内最高点根数，截断 | W=90d, cap=500 | 水下时间 |
| `mom.funding_carry` | 资金费年化 / RV | — | **缺数据**，见 4.3 |

#### E. 区间 / 网格

| 特征 ID | 定义 | 默认参数 | 说明 |
|---|---|---|---|
| `range.width_atr` | `(U_n - L_n) / ATR` | n=60 | 区间宽度，格数上限 |
| `range.touch_balance` | `(#上沿触碰 - #下沿触碰)/n`，触碰容差 `tol*ATR` | n=60, tol=0.1 | 区间是否被反复测试 |
| `range.chop` | 收盘价方向翻转次数 `/(n-1)` | n=60 | 0–1，越高越震荡 |
| `range.width_stability` | `std(width, n)/mean(width, n)` | n=60 | 区间是否稳定，网格最怕宽度漂移 |
| `cost.edge_ratio` | `(ATR/C) / (2*(fee_bps+slippage_bps)/1e4)` | fee=5, slip=2 | 单根典型波幅覆盖往返成本的倍数；<3 网格不可做 |

#### F. 策略元特征（可选，默认不启用）

- `strat.signal`：某策略在 t 的方向（−1/0/1）。
- `strat.signal_age`：该方向持续根数。
- `strat.cluster`：同类策略同向数量。

**这些特征有循环风险：** 如果标签就是“该策略是否盈利”，再把它的入场信号喂给模型，模型学到的只是规则本身；如果标签是通用未来收益，它们又和 A/B/D 组高度共线。建议只在“用 A 策略的 regime 特征预测 B 策略”时启用，并单独做消融。

### 1.4 六策略 → 特征映射

| 策略 | 主要特征 | 辅助特征 | 备注 |
|---|---|---|---|
| 1 EMA 交叉 | `trend.ema_spread`, `trend.ema_slope`, `trend.ema_age` | `trend.adx`, `vol.expansion`, `trend.ema_dist` | 斜率阈值用 ATR 单位，不用价格单位 |
| 2 唐奇安 | `channel.position`, `channel.break_atr` | `trend.er`, `vol.atr_pct`, `vol.gap_atr` | 止损距离 = 2×ATR，天然是风险单位 |
| 3 布林回归 | `mr.bb_z`, `mr.dist_mid` | `trend.adx`, `vol.rv_pct`, `trend.er`, `vol.width_pct` | 过滤比信号重要；趋势币禁用 |
| 4 RSI 反转 | `momentum.rsi` | `trend.er`, `mr.bb_z`, `vol.rv_pct` | 日线 RSI(2) 需要多周期支持 |
| 5 TSMOM | `mom.return`(2/4/8w), `mom.vol_adj` | `mom.consensus`, `mom.drawdown`, `vol.rv_z` | 波动率目标 = 0.3/RV；需要资金费 |
| 6 网格 | `range.width_atr`, `range.chop`, `range.width_stability` | `range.touch_balance`, `cost.edge_ratio`, `vol.squeeze` | 只在高流动性、低波动区间启用 |

### 1.5 推荐的第一批特征（12–16 个）

`trend.ema_spread`、`trend.ema_slope`、`trend.adx`、`trend.er`、`channel.position`、`mr.bb_z`、`momentum.rsi`、`mr.dist_mid`、`vol.atr_pct`、`vol.rv_pct`、`vol.squeeze`、`mom.return(4w)`、`mom.vol_adj(4w)`、`mom.drawdown`、`range.chop`、`cost.edge_ratio`。

理由：覆盖趋势/回归/波动/动量/区间五类状态，参数少、预热短、彼此相关度可控；`mr.half_life`、`mr.variance_ratio` 先作为实验特征，不稳定就先不进默认集。

## 2. 事件层

### 2.1 事件是什么

事件是**可复现的状态转移**：在 t 根收盘后判定“刚刚发生了一件事”，带类型、方向、锚点、首次可见时间，可选带冻结上下文。它不直接产生仓位，只决定“看哪一根 K 线、用什么标签”。

与现有 `chan_events` 的语义保持：
- 事件身份 = 类型 + 方向 + 锚点，删除重建不产生新样本；
- 特征在首次可见时冻结，之后不再重算；
- 事件样本按 `observed_at` 归入 60/20/20 分区；
- 标签成熟时间跨界的事件剔除。

### 2.2 事件记录

```json
{
  "event_id": "channel.break:up:10231",
  "type": "channel.break",
  "side": "up",
  "anchor": 10220,
  "anchor_time": "...",
  "observed_at": 10231,
  "observed_time": "...",
  "confirmed_at": 10231,
  "eligible": true,
  "params": {"n": 20, "mode": "episode", "reset_bars": 5, "adx_min": 20},
  "context": {"atr": 412.5, "break_atr": 1.8, "adx": 24.1, "vol_pct": 0.62},
  "features": {"channel.break_atr:ab12cd34": 1.8}
}
```

相对现有缠论事件，新增 `confirmed_at`（另有通用字段 `params`/`context`）：`anchor` 是事情发生的 K 线，`observed_at` 是第一次可确认的 K 线。指标类两者相等；分形/摆点类 `observed_at = anchor + k`。**任何用 anchor 当观测时点的写法都是未来函数。**

### 2.3 去重与状态机

- **episode（默认）**：条件由假变真时发一次，直到复位条件成立才允许下一次。震荡期的唐奇安/布林突破必须用这种模式，否则每根新高都是一条样本。
- **new_extreme**：突破后仍创新高就继续发，但带 `cooldown_bars`。海龟加仓可用，研究默认不用。
- **cross/threshold**：交叉本身是瞬态的，不发重复事件。
- **共同过滤参数**：`adx_min`、`adx_max`、`vol_pct_max`、`er_max`、`slope_min`、`cooldown_bars`。过滤只用 `observed_at` 及之前的值。
- 事件总数要有上限意识：4h 三年约 6570 根，EMA 交叉约 100–300 次，布林下轨触碰约 200–500 次；周频 TSMOM 约 156 次——按 60/20/20 切分后测试集只有约 31 条，刚过 30 条门槛。**要跑周频事件，至少准备 5 年数据。**

### 2.4 原子事件目录

| 事件 ID | 触发（t 根收盘后） | 方向 | 去重 | 主要消费者 |
|---|---|---|---|---|
| `cross.ema` | `spread[t-1] <= 0` 且 `spread[t] > 0`（下穿对称） | up/down | 天然单次 | 策略 1 |
| `cross.price_ma` | 收盘价上穿/下穿 MA_n | up/down | 天然单次 | 通用 |
| `threshold` | 指标从阈值一侧穿到另一侧，如 RSI 下穿 30、上穿 70、ADX 上穿 20 | up/down | 天然单次 | 策略 4、regime 过滤 |
| `channel.break` | `C_t > max(H[t-n:t]) 或 C_t < min(L[t-n:t])` | up/down | episode + reset | 策略 2、6 |
| `band.breach` | `C_t` 超出 `SMA_n ± kσ` | up/down | episode 至回到带内 | 策略 3 |
| `band.mid_touch` | 收盘价上穿/下穿中轨 | up/down | episode | 策略 3 出场 |
| `squeeze.release` | 带宽分位连续 m 根低于 p，随后回到 q 以上 | up/down | episode | 策略 6、突破前兆 |
| `extreme.z` | 成交量/振幅/资金费/OI 的 z 分数超过 k | up/down | cooldown | 微观结构、清算 |
| `clock` | 每周一 00:00 UTC / 资金费结算 00、08、16 UTC | none | 每次触发 | 策略 5 调仓 |
| `structure.break` | 分形高点/低点被突破；锚点为摆点，确认滞后 k 根 | up/down | episode | 通用结构，先于缠论 |

> 网格的“每格成交”不是 bar 级事件：1h OHLC 无法判断挂单队列与成交顺序。网格只保留 `channel.break`（区间下沿破位）与 `squeeze.release` 两类事件，其余用区间特征。

### 2.5 六策略 → 事件配方

| 策略 | 事件配方 | 过滤（都在 observed_at） | 出场/标签 |
|---|---|---|---|
| 1 EMA | `cross.ema(20,60)` | `adx >= 20` 且 `abs(ema_slope) >= 阈值` | 反向交叉；2×ATR 跟踪；三屏障 2/2 ATR |
| 2 唐奇安 | `channel.break(20, episode)` | `vol.expansion >= 1`（可选） | 反向 10 根通道；2×ATR；三屏障 2/2 ATR |
| 3 布林 | `band.breach(20,2σ, down)` | `adx < 20`、`vol.rv_pct < 0.4`、`er < 0.3`、非单边趋势 | 回到中轨（`band.mid_touch`）或 24 根时间止损；止损 1.5×ATR / 3σ |
| 4 RSI | `threshold(rsi,30, down)` / 日线 RSI2 10 | 只做多版本可加 `trend.ema_spread > 0` | RSI 回 50 或 12 根；三屏障 |
| 5 TSMOM | `clock.weekly` + 条件：`abs(mom.vol_adj) > 阈值` | 波动率目标、资金费过滤 | 下周同一时刻调仓；1 周远期收益 |
| 6 网格 | 无入场事件 | `range.chop` 高、`vol.rv_pct` 低、`cost.edge_ratio >= 3` | 区间破位停手；逐格 PnL 需低周期成交模拟 |

配方不是新算法，只是“原子事件 + 过滤参数”的 JSON 预设，可存成 `event_rule` 复用。

### 2.6 事件的三种用途

1. **采样触发（现有能力）**：`triggers.collect` 用 `observed_at` 取训练样本。事件模式当前只支持向量模型，且不自动回测——这与研究用途相符。
2. **事件编码特征（需要小改管线）**：把事件流压成每根 K 线可见的状态，供 K 线采样模型使用：
   - `event.occur(type)`：t 根是否发生（0/1）；
   - `event.age(type)`：距上次事件根数，截断；可带方向；
   - `event.count(type,n)`：过去 n 根内次数；
   - `event.last_side(type)`：最近方向。
   这些量只依赖 `observed_at <= t` 的事件，是 K 线模型感知“策略刚刚触发过”的桥。当前 `FactorContext` 看不到事件流，需要在 `sampling.prepare` 里把所选事件编码注入特征矩阵，或给 `FactorSpec` 增加事件依赖并缓存事件流；后者更干净，但改动面更大。
3. **事件标签（需要新增 target）**：
   - 现有 `forward_return` 可用，但它**不区分方向**（见 4.2）；
   - 新增 `forward_return_signed`：`side * (O[t+h+1]/O[t+1] - 1)`；
   - 新增 `triple_barrier`：以 `O[t+1]` 为入场，`ATR_t` 为尺度，按事件 side 镜像上下轨，先到止盈轨记 1、先到止损轨记 0、到期未触按超时处理；同一根同时触及时按**止损先发生**，与回测一致。

### 2.7 事件标签的语义

- 标签必须从 `observed_at` 的下一根开盘起算；确认滞后的事件（分形、缠论）不能用 anchor 起算。
- 方向必须跟随事件 side；卖点事件的“未来收益为正”对交易是坏事，不能直接复用多头标签。
- 成熟时间用于分区剔除：`t+h` 跨入验证/测试边界的样本要丢弃。
- 超时标签建议单列一类（三分类：止盈 / 止损 / 超时），不要强行塞进二分类，否则“没动”会被当成“止损”。

## 3. 合理性审查

### 3.1 合理、可以直接做

- 六类策略依赖的指标都是标准、因果、可向量化的；映射到 `series` 因子没有障碍。
- 交叉、阈值穿越、通道突破、带宽触碰四类原子事件足以覆盖策略 1–4，不需要为每个策略写一套检测器。
- “策略 → 事件 → 方向感知标签 → meta-labeling”与现有事件样本链路一致，且比“策略信号当特征”更干净。
- 用 ATR/收盘价归一化、滚动分位、0–1 强度，适合跨时间段的加密行情；现有 Spearman 矩阵可以做冗余裁剪。
- 现有前缀截断测试会自动覆盖新注册的 `series` 因子，是很好的守门器。

### 3.2 必须调整的地方

1. **不要把策略 0/1 信号当主力特征。** 它是价格的确定性变换，和 `ema_spread`/`bb_z` 高度共线；当标签是策略盈亏时更是循环。特征是“策略看到的世界”，不是“策略的结论”。
2. **收益标签要分方向。** `targets.forward_labels` 现在对所有事件返回同一个多头收益；卖点样本会被教成“价格上涨=好”。要么新增 signed 目标，要么规定事件实验只用结构类标签。这是当前代码里的实际缺口，不是风格问题。
3. **多周期必须先补“已收盘桶”对齐。** 4h EMA + 1h 布林 + 日线 RSI2 是三种周期；在 1h 数据集上直接 `resample` 会把当前未完成的日线桶喂进模型。需要统一的 `resample_closed`，并对齐到桶闭合后的第一根。
4. **90 天分位特征有预热与性能成本。** 1h 90 天 = 2160 根，滚动排名在 10 万根数据上很慢；建议在日线重采样上算，或用 `vol.rv_z` 近似。预热期还会吃掉训练集前段样本，需在界面上提示。
5. **事件去重与样本数控制是硬约束。** 震荡期通道突破若不按 episode 去重，会产生数千条高度重叠样本；周频事件三年只有约 156 条，刚够切分。事件规则必须带 `mode/cooldown/reset_bars`，并在预览里显示各分区数量。
6. **网格不适合做成 bar 级事件。** 它的收益来自逐格 maker 成交，1h OHLC 既不知道排队也不知道路径；只能提取“区间是否适合网格”的状态特征和“破位停手”事件。要真研究网格，先补 1m/tick 数据和 maker 成交模型。
7. **TSMOM 不是事件策略。** 它的“事件”是每周一的重启时钟，方向由状态特征决定；应做成 clock 触发 + 条件采样，而不是价格事件。否则会把“每周都发生”误当成信号。
8. **“震荡期 ADX>20 过滤能减少一半交易”这类经验阈值不要写死。** ADX 的绝对水平随周期/品种漂移，建议用滚动分位或参数化阈值，回测里做敏感性检查。
9. **事件特征冻结与 bar 特征要一致。** 同一个 `adx` 在事件样本里是冻结值、在 bar 样本里是逐根值；两套实现必须共用同一函数，否则会出现“同一特征两种数”的静默偏差。

### 3.3 当前做不到（执行层/数据层缺口）

| 策略需求 | 缺什么 | 影响 |
|---|---|---|
| 永续双向、做空 | 回测只有多/空仓，`position_pct<=1` | 策略 1、2、3、4 的空头腿无法验证 |
| 杠杆 2–3×、风险 0.5–1%/笔 | 无杠杆/保证金/爆仓模型 | 仓位公式只能当研究假设 |
| 资金费计入 | 行情无 funding | 策略 5 的多头收益会被高估；拥挤交易无法识别 |
| 标记价止损 | 行情无 mark price | 策略 2 的“插针误平仓”无法复现 |
| maker 挂单/网格 | 无订单簿、无排队、无部分成交 | 策略 6 无法做订单级回测 |
| 趋势 alt 禁用、跨品种 | 单标的平台 | 只能用自身趋势代理，不能判断“相对 BTC 的单边” |
| 持仓量/基差/清算 | 无 OI/basis/liq 数据 | 微观结构类特征和事件缺失 |

**结论：** 作为“特征工程 + 事件研究 + meta-labeling”，现在就能做；作为“这 6 套策略的实盘级回测”，需要先扩执行层和数据层，否则报告会系统性偏乐观。

### 3.4 风险排序

| 风险 | 严重度 | 处理 |
|---|---|---|
| 事件方向与标签不一致 | 高 | 先加 signed/triple-barrier 目标 |
| 多周期前视 | 高 | 已收盘桶 + 前缀测试 |
| 事件重复/爆炸 | 中高 | episode 状态机 + 预览计数 |
| 特征共线 | 中 | Spearman 裁剪 + 消融 |
| 90 天分位预热/性能 | 中 | 日线重采样或 z 近似 |
| 资金费/做空缺失导致结论偏差 | 中高 | 报告里显式标注“未计资金费/仅多头” |

## 4. 落地建议

### 4.1 分期

| 阶段 | 内容 | 产出 |
|---|---|---|
| A1 特征 | `trend/channel/vol/mr/mom/range/cost` 插件 + 公共 Wilder/分位/重采样工具 | 12–16 个可注册特征，自动进因果性测试 |
| A2 事件 | 原子事件 provider、episode 状态机、过滤参数、事件预览计数；方向感知标签 + 三屏障 | 策略 1–4 的事件规则与 meta-label 实验 |
| A3 桥接 | 事件编码特征注入 K 线采样；多周期已收盘桶 | 同一模型可看“状态 + 刚发生的事” |
| B 数据 | funding / mark / OI / basis 入库；`extreme.z`、`clock.funding` | 策略 2、5 的真实成本与止损 |
| C 执行 | 做空、杠杆、资金费、maker/taker、低周期网格 | 六策略的订单级回测 |

### 4.2 验收测试

1. **前缀因果性**：所有新 `series` 因子通过现有 `tests/test_factor_causality.py`（前 k 根与全量前 k 根逐点一致）。
2. **事件前缀不变性**：对任意截断，`replay(前 k 根)` 的事件集合与全量回放中 `observed_at < k` 的事件一致；确认滞后事件在 `observed_at` 之前不可见。
3. **去重**：通道突破在一个 episode 内只发一次；复位后才允许下一次；`event_id` 不含重复。
4. **方向标签**：买点用 +1、卖点用 −1；同一根双触按止损先发生；标签成熟前不可用于训练。
5. **事件编码**：`event.age/count` 在 t 根只使用 `observed_at <= t` 的事件。
6. **分区计数**：预览接口返回 train/valid/test 事件数，低于 80/30/30 时明确报错而不是静默降标准。
7. **性能**：10 万根 1h + 16 特征 + 单事件规则在可接受时间内完成；分位类特征需缓存或降采样。

### 4.3 对现有代码的改动面

- `quant/factors/plugins/`：新增因子模块，不改注册机制。
- `quant/triggers.py`：把 `SPECS` 从硬编码扩展为 provider 注册表；保留 `chan`、`rsi_oversold` 的版本兼容。
- `quant/chan_events.py`：抽通用的 `EventTracker`/冻结/分区逻辑，缠论只作为 provider。
- `quant/targets.py`：新增 signed forward return 与 triple barrier；`TargetSpec.sample_modes` 放开到任意事件 provider。
- `quant/sampling.py`：事件编码注入、方向信息传递。
- `quant/backtest.py`：阶段 C 才动；A/B 阶段不改执行语义，避免“研究结论被未完成执行层污染”。

## 5. 待确认

1. **主战场是单标的 BTC 4h，还是要 1h + 日线混用？** 这决定多周期工具是否必须进 A 阶段，以及 90 天分位的实现方式。
2. **“通用事件”主要拿去做什么：** 只当采样触发，还是要同时做事件编码特征和事件标签？三者工作量差别很大。
3. **是否接受“策略当事件源 + meta-labeling”的主线？** 如果坚持把六套策略信号本身做成特征，需要先接受共线和循环风险，并设计消融。
4. **是否现在补 funding/mark/OI 数据？** 不补也能做研究，但策略 5 和止损真实性的结论要降级。
5. **是否需要跨品种（BTC 基准、alt 趋势禁用）？** 单标的平台只能用自己的趋势代理，跨品种需要改数据模型。
