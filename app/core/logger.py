import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from .config import GlobalConfig

# 1. 确保日志目录存在
GlobalConfig.LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logger(name="MetaWeave"):
    """
    配置全局 Logger：同时输出到控制台和本地文件
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 如果已经有 handler 说明已经初始化过，直接返回
    if logger.handlers:
        return logger

    # 2. 定义统一的日志格式 (包含时间、级别、模块名和具体消息)
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | [%(filename)s:%(lineno)d] | %(message)s'
    )

    # 3. 控制台 Handler (用于开发调试)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 4. 文件滚动 Handler (用于生产持久化)
    # when="midnight" 表示每天午夜滚动，backupCount=30 表示保留最近30天的日志
    file_handler = TimedRotatingFileHandler(
        GlobalConfig.LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# 初始化单例 global_logger 供全局调用
global_logger = setup_logger()