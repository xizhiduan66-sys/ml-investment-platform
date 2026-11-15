"""自定义因子目录：放在这里的模块会在启动时自动导入并注册。"""
import importlib
import pkgutil
from pathlib import Path


def load_plugins():
    package = __name__
    for info in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if info.name.startswith("_"):
            continue
        importlib.import_module("%s.%s" % (package, info.name))
