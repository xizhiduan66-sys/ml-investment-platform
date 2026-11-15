"""自定义因子模板：复制为 my_factor.py 后按需修改。

文件以 _ 开头不会自动加载；复制成 my_factor.py 即可在启动时注册。
"""
from ..registry import factor
from ..spec import ParamSpec


@factor(
    id="custom.example",
    name="示例因子",
    family="自定义",
    description="收盘价相对 N 根均线的偏离",
    params=(ParamSpec("window", "int", 20, minimum=2, maximum=250, description="窗口"),),
)
def example(df, params):
    window = params["window"]
    return df.close / df.close.rolling(window).mean() - 1
