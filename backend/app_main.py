import os
import sys

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
import logging

from backend.routers import auth, exams, students, questions, answers, grading, scores
from backend.database import engine
from sqlalchemy import text

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(title="考试管理平台API", version="1.0.0", description="试卷图片分析和AI阅卷实验平台")

# 允许本地前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该指定具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
# 把本地 uploads 文件夹挂载到 http://xxx:8001/uploads/
os.makedirs("uploads", exist_ok=True)  # 自动创建目录，防止报错
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# 注册路由
app.include_router(auth.router, tags=["认证"])
app.include_router(exams.router, tags=["考试管理"])
app.include_router(students.router, tags=["学生管理"])
app.include_router(questions.router, tags=["题目管理"])
app.include_router(answers.router, tags=["答题卡管理"])
app.include_router(grading.router, tags=["AI阅卷"])
app.include_router(scores.router, tags=["成绩管理"])

# ==================== 系统健康检查 ====================

@app.get("/api/health")
def health_check():
    """系统健康检查接口"""
    try:
        # 检查数据库连接
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return {
            "code": 1,
            "msg": "系统正常",
            "data": {
                "database": "connected",
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"健康检查失败: {str(e)}")
        return {
            "code": 0,
            "msg": "系统异常",
            "data": {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
