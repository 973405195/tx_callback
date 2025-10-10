import os
import logging
from dotenv import load_dotenv
import tempfile

# 加载.env文件中的环境变量
load_dotenv()

# 配置管理
class Config:
    # 数据库配置
    MYSQL_CONFIG = {
        'host': os.getenv('MYSQL_HOST', 'sh-cynosdbmysql-grp-pbl95cyg.sql.tencentcdb.com'),
        'port': int(os.getenv('MYSQL_PORT', 23593)),
        'user': os.getenv('MYSQL_USER', 'root'),
        'password': os.getenv('MYSQL_PASSWORD', 'Junzhun123'),
        'database': os.getenv('MYSQL_DATABASE', 'video_auto'),
        'charset': 'utf8mb4',
        'connect_timeout': 60,
        'read_timeout': 90,
        'write_timeout': 90,
        'autocommit': True
    }
    
    # 腾讯云COS配置
    COS_CONFIG = {
        'secret_id': os.getenv('TENCENT_SECRET_ID', ''),
        'secret_key': os.getenv('TENCENT_SECRET_KEY', ''),
        'region': os.getenv('COS_REGION', 'ap-shanghai'),
        'bucket': os.getenv('COS_BUCKET', 'zh-video-1322637479')
    }
    
    # Gemini API配置
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyBd7URziO9fPooqaQcwPQpxqI62oIdz-p4')
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    
    # 服务配置
    FLASK_PORT = int(os.getenv('FLASK_PORT', 8787))
    MAX_CONCURRENT_TRANSLATIONS = int(os.getenv('MAX_CONCURRENT_TRANSLATIONS', 3))
    TEMP_DIR = os.getenv('TEMP_DIR', os.path.join(tempfile.gettempdir(), 'tx_callback_subtitles'))
    
    # 网络超时配置
    HTTP_DOWNLOAD_TIMEOUT = int(os.getenv('HTTP_DOWNLOAD_TIMEOUT', 120))
    GEMINI_API_TIMEOUT = int(os.getenv('GEMINI_API_TIMEOUT', 180))
    
    # COS基础URL
    COS_BASE_URL = f"https://{COS_CONFIG['bucket']}.cos.{COS_CONFIG['region']}.myqcloud.com"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tx_callback.log'),
        logging.StreamHandler()
    ]
)