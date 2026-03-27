from pathlib import Path
import os
from dotenv import load_dotenv
import logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Docker生产环境下,优先加载容器下环境变量,其次再加载开发时.env
logger = logging.getLogger("ClearNotify")
if not os.getenv("DOCKER_DEPLOYMENT"):
    print("==================== PRINT | Environment Variables From .env ====================")
    ENV_PATH = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=ENV_PATH)
else:
    print("==================== PRINT | Environment Variables From Docker-Compose ====================")
class GlobalConfig:
    DEFAULT_ADMIN_PASSWORD = "111111"
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_EMAIL = "unknown@email.com"
    DEFAULT_ADMIN_PHONE = None

    PROJECT_ROOT = PROJECT_ROOT

    DB_PATH = PROJECT_ROOT / "database.db"
    LOG_DIR = PROJECT_ROOT / "logs"
    LOG_FILE=LOG_DIR / "app.log"

    # 环境变量读取
    SECRET_KEY = os.getenv("SECRET_KEY")
    ALGORITHM = os.getenv("ALGORITHM")
    ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS"))

    PORT = int(os.getenv("PORT"))
    HOST = os.getenv("HOST")

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE")

    @staticmethod
    def _show_config():
        """
        调试专用：直接使用 print 输出所有配置成员，确保在 Docker 中可见。
        """
        import os
        source = "Docker-Compose" if os.getenv("DOCKER_DEPLOYMENT") else ".env"

        # 头部：美丽的分割线
        print(f"\n{'=' * 20} [DEBUG] GlobalConfig Members ({source}) {'=' * 20}")

        # 自动获取类成员
        # 过滤掉内置属性(__)和方法(callable)
        attrs = [attr for attr in dir(GlobalConfig) if
                 not attr.startswith('__') and not callable(getattr(GlobalConfig, attr))]

        for attr in sorted(attrs):
            val = getattr(GlobalConfig, attr)
            # 格式化输出：变量名左对齐占 35 位，中间用竖线分隔
            print(f"{attr:35} | {val}")

        # 底部：美丽的分割线
        print(f"{'=' * 75}\n")



# ===== DEBUG: 展示所有环境变量 =====
GlobalConfig._show_config()






