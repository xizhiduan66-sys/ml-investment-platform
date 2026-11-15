# 模型插件接口

`quant.models` 是兼容入口；内置实现位于 `quant/model_adapters/`。
LightGBM 和 XGBoost 各有独立后端，LSTM/GRU 共用循环网络训练实现。

注册一个模型需要构造 `ModelAdapter`，提供唯一 ID、输入布局
（vector 或 sequence）、支持的任务（regression / binary）、依赖模块、
参数 schema、训练函数以及目录展示元数据，然后调用 `register(adapter)`。
注册必须在 API 和执行端开始工作前完成。重复 ID 会被拒绝。

训练函数签名：

```python
def train(kind, task, xtrain, ytrain, xvalid, yvalid,
          epochs, progress, seed, params) -> FittedModel:
    ...
```

`params` 已按插件 schema 验证。训练函数不接收测试集。
返回的 `FittedModel` 包含可持久化 artifact、history、diagnostics 和
预测 callable；只保存 artifact，不序列化运行时 callable。
二分类预测必须返回类别 1 的概率，回归返回连续值，均为一维数组。

`models.registry()` 自动生成 API 模型目录；参数校验和研究计划编译
均使用注册的能力。事件采样当前接受向量模型，序列模型只支持 K 线采样。

测试中的 test_custom_model_runs_without_core_changes 演示无外部依赖的
均值回归器从注册、计划编译到流水线执行的完整路径。

当前边界：输入能力仅支持向量和序列，任务仅支持回归和二分类；
任务评价和输出语义尚未插件化。模型产物重新加载接口、独立 worker、
预测与策略分离属于后续改造，不能据此假定已经具备这些能力。
