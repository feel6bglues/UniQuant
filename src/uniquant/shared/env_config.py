"""
环境变量配置模块

在所有入口点脚本的最开始（import 之前）调用此模块，
确保底层并行库不会与 Python 多进程冲突。

使用方法:
    # 在脚本最开始
    from src.shared.env_config import configure_environment
    configure_environment()

    # 或者直接导入（自动配置）
    import src.shared.env_config  # noqa: F401
"""

import os


def configure_environment() -> None:
    """
    配置环境变量以防止进程炸弹
    
    在多进程环境下，numpy/scipy/joblib 等库会尝试使用多线程，
    这与 Python 的 ProcessPoolExecutor 冲突，导致：
    1. 进程数爆炸
    2. CPU 争抢
    3. 内存耗尽
    4. 系统死锁
    
    解决方案：强制这些库使用单线程。
    """
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("BLIS_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("LPPL_DISABLE_PARALLEL", "1")


configure_environment()
