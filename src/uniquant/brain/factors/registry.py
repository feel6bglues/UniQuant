"""
因子注册中心 - 支持无限扩展因子库
所有因子必须在此注册，才能被 ScanPipeline、FactorAnalyzer、FactorComposer 使用
"""

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional
import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger("FactorRegistry")


class FactorAccessLevel(Enum):
    """因子访问级别"""
    FREE = "free"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class FactorInfo:
    """因子元信息"""
    name: str                    # 因子名称（唯一）
    category: str                # technical / fundamental / alternative / custom
    compute_func: Callable[[pd.DataFrame], pd.Series]  # 计算函数
    default_weight: float = 1.0
    enabled: bool = True
    description: str = ""



class FactorRegistry:
    """
    全局因子注册中心（单例模式 + 线程安全）
    
    Thread-safe implementation with lock-protected dictionary.
    Also provides access control gate (WARN/BLOCK mode).
    """
    _factors: Dict[str, FactorInfo] = {}
    _instance = None
    _lock = threading.Lock()
    _loaded: bool = False
    _mode: FactorAccessLevel = FactorAccessLevel.WARN

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _ensure_loaded(cls):
        """Lazy-load custom factors on first query for deterministic registration."""
        if not cls._loaded:
            with cls._lock:
                cls._loaded = True

    @classmethod
    def register(cls, name: str, compute_func: Callable, 
                 category: str = "custom", 
                 default_weight: float = 1.0, 
                 description: str = ""):
        """注册一个新因子 - Thread-safe
        
        Checks factors.yaml config for enabled/weight/category overrides.
        If the factor is disabled in config, skip registration entirely.
        """
        # Apply factors.yaml overrides if available. Configuration failures must
        # be visible; silently falling back to default factor weights can change
        # strategy behavior without any audit trail.
        try:
            from ...shared.config_loader import get_config
            cfg = get_config()
            factor_cfg = cfg.get(f"factors.{name}")
            if factor_cfg is not None:
                if not factor_cfg.get("enabled", True):
                    logger.info(f"⏭️ 因子 {name} 被 factors.yaml 禁用，跳过注册")
                    return
                if "weight" in factor_cfg:
                    default_weight = factor_cfg["weight"]
                if "category" in factor_cfg:
                    category = factor_cfg["category"]
        except ImportError as e:
            logger.warning("因子配置加载器不可用，使用默认注册参数: %s", e)
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as e:
            logger.error("因子 %s 配置读取失败: %s", name, e)
            raise

        with cls._lock:
            if name in cls._factors:
                logger.warning(f"因子 {name} 已存在，将覆盖")
            
            cls._factors[name] = FactorInfo(
                name=name,
                category=category,
                compute_func=compute_func,
                default_weight=default_weight,
                description=description
            )
            logger.info(f"✅ 因子注册成功: {name} ({category}) weight={default_weight}")

    @classmethod
    def get_all(cls) -> List[FactorInfo]:
        """获取所有因子 - Thread-safe"""
        cls._ensure_loaded()
        with cls._lock:
            return list(cls._factors.values())

    @classmethod
    def get_enabled(cls) -> List[FactorInfo]:
        """获取启用的因子 - Thread-safe。每个因子通过准入检查"""
        cls._ensure_loaded()
        with cls._lock:
            enabled = [f for f in cls._factors.values() if f.enabled]
        for f in enabled:
            cls.check_access(f.name)
        return enabled

    @classmethod
    def get_factor(cls, name: str) -> Optional[FactorInfo]:
        """获取指定因子 - Thread-safe。同时触发准入检查"""
        cls._ensure_loaded()
        cls.check_access(name)
        with cls._lock:
            return cls._factors.get(name)

    @classmethod
    def enable(cls, name: str):
        """启用因子 - Thread-safe"""
        with cls._lock:
            if name in cls._factors:
                cls._factors[name].enabled = True
                logger.info(f"因子 {name} 已启用")

    @classmethod
    def disable(cls, name: str):
        """禁用因子 - Thread-safe"""
        with cls._lock:
            if name in cls._factors:
                cls._factors[name].enabled = False
                logger.info(f"因子 {name} 已禁用")

    @classmethod
    def list_factors(cls) -> Dict[str, str]:
        """列出所有因子（用于调试） - Thread-safe"""
        cls._ensure_loaded()
        with cls._lock:
            return {f.name: f.description for f in cls._factors.values()}

    @classmethod
    def set_mode(cls, mode: FactorAccessLevel) -> None:
        """设置访问控制模式 - Thread-safe"""
        with cls._lock:
            cls._mode = mode

    @classmethod
    def get_mode(cls) -> FactorAccessLevel:
        """获取当前访问控制模式 - Thread-safe"""
        with cls._lock:
            return cls._mode

    @classmethod
    def has(cls, name: str) -> bool:
        """检查因子是否已注册 - Thread-safe"""
        cls._ensure_loaded()
        with cls._lock:
            return name in cls._factors

    @classmethod
    def check_access(cls, name: str) -> bool:
        """准入检查: 在 WARN/BLOCK 模式下拦截未注册因子的访问 - Thread-safe"""
        with cls._lock:
            if name in cls._factors:
                return True
            if cls._mode == FactorAccessLevel.BLOCK:
                raise ValueError(f"未注册因子被拦截: {name}")
            if cls._mode == FactorAccessLevel.WARN:
                logger.warning("未注册因子访问: %s (mode=warn)", name)
            return True
