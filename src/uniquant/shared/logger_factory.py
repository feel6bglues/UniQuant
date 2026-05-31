"""
Logger工厂模块
提供统一的Logger创建和管理
"""

import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import Dict, Optional


class LoggerFactory:
    """
    Logger工厂类
    统一管理所有模块的Logger创建和配置
    """

    # 单例实例
    _instance: Optional["LoggerFactory"] = None
    _initialized: bool = False
    _lock = threading.RLock()

    # 已创建的logger缓存
    _loggers: Dict[str, logging.Logger] = {}

    # 默认配置
    DEFAULT_LEVEL = logging.INFO
    DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if LoggerFactory._initialized:
            return

        self._load_config()
        self._setup_root_logger()
        LoggerFactory._initialized = True

    def _load_config(self):
        """从配置文件加载日志配置"""
        from .config_loader import get_config

        config = get_config()

        self.log_level = getattr(
            logging, config.get("logging.level", "INFO").upper(), logging.INFO
        )
        self.log_format = config.get("logging.format", self.DEFAULT_FORMAT)
        self.date_format = config.get("logging.date_format", self.DEFAULT_DATE_FORMAT)
        self.log_dir = config.get("logging.directory", "logs")
        self.max_bytes = config.get("logging.max_bytes", 10 * 1024 * 1024)  # 10MB
        self.backup_count = config.get("logging.backup_count", 5)
        self.console_output = config.get("logging.console", True)
        self.file_output = config.get("logging.file", True)

    def _setup_root_logger(self):
        """配置根Logger"""
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        # 清除现有处理器
        root_logger.handlers = []

        # 创建格式化器
        formatter = logging.Formatter(self.log_format, self.date_format)

        # 控制台处理器
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.log_level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # 文件处理器 - 使用线程安全的处理方式
        if self.file_output:
            log_path = Path(self.log_dir)
            log_path.mkdir(parents=True, exist_ok=True)

            # 使用 QueueHandler + QueueListener 实现线程安全的日志写入
            from logging.handlers import QueueHandler, QueueListener
            import queue
            
            self._log_queue = queue.Queue(-1)
            self._log_file_handler = logging.handlers.RotatingFileHandler(
                log_path / "alpha_tactician.log",
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8",
            )
            self._log_file_handler.setLevel(self.log_level)
            self._log_file_handler.setFormatter(formatter)
            
            # 创建队列监听器
            self._log_listener = QueueListener(
                self._log_queue, 
                self._log_file_handler,
                respect_handler_level=True
            )
            self._log_listener.start()
            
            # 使用队列处理器
            file_handler = QueueHandler(self._log_queue)
            file_handler.setLevel(self.log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

    def get_logger(self, name: str) -> logging.Logger:
        """
        获取或创建Logger

        Args:
            name: Logger名称

        Returns:
            logging.Logger: 配置好的Logger
        """
        if name in self._loggers:
            return self._loggers[name]

        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)

        # 缓存logger
        self._loggers[name] = logger

        return logger

    def update_level(self, level: int):
        """
        更新所有Logger的日志级别

        Args:
            level: 新的日志级别
        """
        self.log_level = level
        for logger in self._loggers.values():
            logger.setLevel(level)

    @classmethod
    def reset(cls):
        """重置工厂状态（用于测试）"""
        cls._instance = None
        cls._initialized = False
        cls._loggers = {}


# 全局工厂实例
_factory: Optional[LoggerFactory] = None
_factory_lock = threading.Lock()


def get_logger(name: str) -> logging.Logger:
    """
    获取Logger的便捷函数

    Args:
        name: Logger名称

    Returns:
        logging.Logger: 配置好的Logger

    Example:
        >>> from src.shared.logger_factory import get_logger
        >>> logger = get_logger("MyModule")
        >>> logger.info("This is an info message")
    """
    global _factory
    if _factory is None:
        with _factory_lock:
            if _factory is None:
                _factory = LoggerFactory()
    return _factory.get_logger(name)


def setup_logger(name: str) -> logging.Logger:
    """
    设置Logger的兼容函数（保持向后兼容）

    Args:
        name: Logger名称

    Returns:
        logging.Logger: 配置好的Logger
    """
    return get_logger(name)
