import numpy as np
from ..contracts import FittedModel

def fit(kind, task, xtrain, ytrain, xvalid, yvalid, epochs, progress, seed, params):
    import torch
    from torch import nn
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    mean = xtrain.mean(axis=(0, 1), keepdims=True)
    std = xtrain.std(axis=(0, 1), keepdims=True) + 1e-08
    (tx, vx) = [torch.tensor((x - mean) / std, dtype=torch.float32) for x in [xtrain, xvalid]]
    ym = float(ytrain.mean()) if task == 'regression' else 0.0
    ys = float(ytrain.std() + 1e-08) if task == 'regression' else 1.0
    (ty, vy) = [torch.tensor((y - ym) / ys, dtype=torch.float32) for y in [ytrain, yvalid]]

    class Network(nn.Module):

        def __init__(self):
            super().__init__()
            recurrent = nn.LSTM if kind == 'lstm' else nn.GRU
            setattr(self, kind, recurrent(tx.shape[-1], params['hidden_size'], batch_first=True))
            self.out = nn.Linear(params['hidden_size'], 1)

        def forward(self, x):
            (x, _) = getattr(self, kind)(x)
            return self.out(x[:, -1]).squeeze(-1)
    model = Network()
    loss_fn = nn.MSELoss() if task == 'regression' else nn.BCEWithLogitsLoss()
    optim = torch.optim.Adam(model.parameters(), lr=params['learning_rate'])
    (history, best, checkpoint, best_epoch) = ([], float('inf'), None, None)

    def forward_batches(x):
        return torch.cat([model(batch) for batch in x.split(256)])
    for epoch in range(epochs):
        model.train()
        (order, gradients) = (torch.randperm(len(tx)), [])
        for indices in order.split(params['batch_size']):
            optim.zero_grad()
            loss = loss_fn(model(tx[indices]), ty[indices])
            if not torch.isfinite(loss):
                raise ValueError('训练损失非有限，请检查特征与目标尺度')
            loss.backward()
            norm = float(nn.utils.clip_grad_norm_(model.parameters(), 1.0))
            if not np.isfinite(norm):
                raise ValueError('梯度非有限，请检查特征与目标尺度')
            gradients.append(norm)
            optim.step()
        model.eval()
        with torch.no_grad():
            train_loss = float(loss_fn(forward_batches(tx), ty))
            val = float(loss_fn(forward_batches(vx), vy))
        if not np.isfinite([train_loss, val]).all():
            raise ValueError('训练或验证损失非有限')
        history.append({'epoch': epoch + 1, 'train': train_loss, 'valid': val, 'gradient_mean': float(np.mean(gradients)), 'gradient_max': float(max(gradients)), 'clipped_fraction': float(np.mean(np.asarray(gradients) > 1.0))})
        if val < best:
            (best, best_epoch) = (val, epoch + 1)
            checkpoint = {k: v.detach().clone() for (k, v) in model.state_dict().items()}
        progress(f'训练 {epoch + 1}/{epochs} · 验证损失 {val:.4f}')
    if checkpoint is None:
        raise ValueError('没有有效模型检查点')
    model.load_state_dict(checkpoint)
    model.eval()

    def infer(x):
        tensor = torch.tensor((x - mean) / std, dtype=torch.float32)
        with torch.no_grad():
            output = forward_batches(tensor)
            return (output * ys + ym if task == 'regression' else torch.sigmoid(output)).numpy()
    artifact = {'kind': kind, 'state_dict': checkpoint, 'input_features': tx.shape[-1], 'mean': mean, 'std': std, 'target_mean': ym, 'target_std': ys, 'task': task, 'seed': seed, 'best_epoch': best_epoch, 'model_params': params}
    detail = {'kind': kind, 'seed': seed, 'parameters': params, 'best_epoch': best_epoch, 'epochs': epochs, 'parameter_count': sum((p.numel() for p in model.parameters())), 'history_metric': 'mse' if task == 'regression' else 'binary_logloss', 'history_unit': '训练标签标准化尺度' if task == 'regression' else '交叉熵', 'selection': '按验证损失选取检查点；全部分区指标来自同一检查点。', 'gradient_clip': 1.0, 'warnings': []}
    return FittedModel(artifact, history, detail, infer)
