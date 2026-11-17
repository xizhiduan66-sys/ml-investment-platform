"""Static presentation metadata; runtime availability comes from adapters."""


def entries():
    return [{'id': 'lightgbm',
      'diagnostics': ['训练/验证曲线', 'Gain 与分裂重要性', '验证最优轮次'],
      'name': 'LightGBM',
      'input': 'vector',
      'tasks': ['regression', 'binary', 'multiclass'],
      'description': '梯度提升树，支持收益回归与概率分类'},
     {'id': 'xgboost',
      'diagnostics': ['训练/验证曲线', 'Gain 与分裂重要性', '验证最优轮次'],
      'name': 'XGBoost',
      'input': 'vector',
      'tasks': ['regression', 'binary'],
      'description': '梯度提升树，使用直方图算法；可与 LightGBM 对比'},
     {'id': 'lstm',
      'diagnostics': ['检查点与损失曲线', '梯度范数与裁剪', '可选多随机种子'],
      'name': 'LSTM',
      'input': 'sequence',
      'tasks': ['regression', 'binary'],
      'description': '历史特征序列 → LSTM → 输出层；用于验证时序信息的增益'},
     {'id': 'gru',
      'diagnostics': ['检查点与损失曲线', '梯度范数与裁剪', '可选多随机种子'],
      'name': 'GRU',
      'input': 'sequence',
      'tasks': ['regression', 'binary'],
      'description': '历史特征序列 → GRU → 输出层；同等隐藏维度下参数少于 LSTM'}]
