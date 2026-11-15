class FactorContext:
    """样本上下文：只暴露 <= t 的数据，因子不得访问未来。

    scope="sample" 的因子实现签名为 compute(ctx, params)；
    需要结构/事件信息的因子从 ctx.structure 读取，当前结构层尚未接入，值为 None。
    """

    __slots__ = ("_df", "_t", "structure")

    def __init__(self, df, t, structure=None):
        if t < 0 or t >= len(df):
            raise IndexError("样本索引越界")
        self._df = df.iloc[:t + 1].copy(deep=False)
        self._t = t
        self.structure = structure

    @property
    def index(self):
        return self._t

    @property
    def bar(self):
        return self._df.iloc[self._t].copy()

    @property
    def time(self):
        return self.bar.get("date")

    def history(self, n=None):
        end = self._t + 1
        start = 0 if n is None else max(0, end - n)
        return self._df.iloc[start:end].copy()

    def series(self, column, n=None):
        return self.history(n)[column]

    @property
    def close(self):
        return float(self._df["close"].iloc[self._t])

    @property
    def open(self):
        return float(self._df["open"].iloc[self._t])
