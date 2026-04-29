from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
import logging
import os
import shutil
import time
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from backend.database import engine


# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter()

# ==================== Pydantic模型定义 ====================

class ExamRequest(BaseModel):
    exam_name: str
    description: Optional[str] = ""
    exam_date: Optional[str] = None
    total_questions: Optional[int] = None
    total_score: Optional[int] = None

    @field_validator('exam_date', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """将空字符串转换为 None"""
        if v == "":
            return None
        return v


class ExamUpdate(BaseModel):
    exam_name: Optional[str] = None
    description: Optional[str] = None
    exam_date: Optional[str] = None
    total_questions: Optional[int] = None
    total_score: Optional[int] = None
    status: Optional[str] = None
    images_per_student: Optional[int] = None   # 新增

    @field_validator('exam_date', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


# ==================== 考试管理API ====================

@router.get("/api/exams")
def get_exams():
    """获取所有考试列表"""
    try:
        with engine.connect() as conn:
            # 如果原查询是 SELECT *，则 images_per_student 会自动包含
            result = conn.execute(text("SELECT * FROM exams ORDER BY created_at DESC"))
            rows = result.fetchall()
            exams = []
            for row in rows:
                exam = {
                    'exam_id': row.exam_id,
                    'exam_name': row.exam_name,
                    'description': row.description,
                    'exam_date': row.exam_date.isoformat() if row.exam_date else None,
                    'created_at': row.created_at.isoformat() if row.created_at else None,
                    'updated_at': row.updated_at.isoformat() if row.updated_at else None,
                    'status': row.status,
                    'total_questions': row.total_questions,
                    'total_score': row.total_score,
                    'images_per_student': row.images_per_student   # 新增，若 SELECT * 则已存在，否则需显式添加
                }
                exams.append(exam)

            # 获取每个考试的学生数量（可选）
            for exam in exams:
                student_count = conn.execute(
                    text("SELECT COUNT(*) FROM exam_students WHERE exam_id = :exam_id"),
                    {"exam_id": exam['exam_id']}
                ).scalar()
                exam['student_count'] = student_count

            return {"code": 1, "msg": "获取成功", "data": exams}
    except Exception as e:
        logger.error(f"获取考试列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取考试列表失败: {str(e)}")

@router.post("/api/exams")
def create_exam(exam: ExamRequest):
    """创建新考试"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                INSERT INTO exams (exam_name, description, exam_date, total_questions, total_score, status)
                VALUES (:exam_name, :description, :exam_date, :total_questions, :total_score, 'created')
                """),
                {
                    "exam_name": exam.exam_name,
                    "description": exam.description,
                    "exam_date": exam.exam_date,
                    "total_questions": exam.total_questions,
                    "total_score": exam.total_score
                }
            )
            conn.commit()
            exam_id = result.lastrowid

            return {"code": 1, "msg": "创建成功", "data": {"exam_id": exam_id}}
    except Exception as e:
        logger.error(f"创建考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建考试失败: {str(e)}")

@router.put("/api/exams/{exam_id}")
def update_exam(exam_id: int, exam: ExamUpdate):
    """更新考试信息"""
    try:
        with engine.connect() as conn:
            update_fields = []
            update_params = {"exam_id": exam_id}

            if exam.exam_name is not None:
                update_fields.append("exam_name = :exam_name")
                update_params["exam_name"] = exam.exam_name
            if exam.description is not None:
                update_fields.append("description = :description")
                update_params["description"] = exam.description
            if exam.exam_date is not None:
                update_fields.append("exam_date = :exam_date")
                update_params["exam_date"] = exam.exam_date
            if exam.total_questions is not None:
                update_fields.append("total_questions = :total_questions")
                update_params["total_questions"] = exam.total_questions
            if exam.total_score is not None:
                update_fields.append("total_score = :total_score")
                update_params["total_score"] = exam.total_score
            if exam.status is not None:
                update_fields.append("status = :status")
                update_params["status"] = exam.status
            # 新增：处理 images_per_student
            if exam.images_per_student is not None:
                update_fields.append("images_per_student = :images_per_student")
                update_params["images_per_student"] = exam.images_per_student

            # 添加更新时间戳（如果表中没有自动更新）
            update_fields.append("updated_at = CURRENT_TIMESTAMP")

            if not update_fields:
                return {"code": 0, "msg": "没有更新字段"}

            query = f"UPDATE exams SET {', '.join(update_fields)} WHERE exam_id = :exam_id"
            conn.execute(text(query), update_params)
            conn.commit()

            return {"code": 1, "msg": "更新成功"}
    except Exception as e:
        logger.error(f"更新考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新考试失败: {str(e)}")

@router.delete("/api/exams/{exam_id}")
def delete_exam(exam_id: int):
    """删除考试"""
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id})
            conn.commit()
            return {"code": 1, "msg": "删除成功"}
    except Exception as e:
        logger.error(f"删除考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除考试失败: {str(e)}")


