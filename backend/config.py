import os

# 数据库配置
DATABASE_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Root@123456',  # 请根据实际情况修改，如果无密码则留空
    'database': 'exam_platform'
}


# 上传目录
UPLOAD_DIR = "./uploads"

# 多模态模型 API 配置
MM_MODEL_CONFIG = {
    "provider": "qwen",
    "api_key": "sk-27dbe63ba53a4bde8d7f2040bc52c004",  # 替换为你的 API Key
    "api_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "model": "qwen-vl-plus",        # 或 qwen-vl-max
    "timeout": 30,
    "max_retries": 2
}
