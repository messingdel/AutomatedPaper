from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import List, Optional
import logging
import os
import time
import shutil
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import get_db

logger = logging.getLogger(__name__)

from backend.database import engine
from backend.config import UPLOAD_DIR

router = APIRouter()

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp'}

def is_allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def ensure_upload_dir(exam_id: int) -> str:
    target_dir = os.path.join(UPLOAD_DIR, "answer_sheets", str(exam_id))
    os.makedirs(target_dir, exist_ok=True)
    return target_dir

# ==================== 获取考试所有图片 ====================
@router.get("/api/exams/{exam_id}/images")
def get_exam_images(exam_id: int):
    try:
        with engine.connect() as conn:
            exam = conn.execute(
                text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            result = conn.execute(
                text("""
                SELECT 
                    a.id, a.filename, a.file_path, a.uploaded_at, a.page_order,
                    s.student_id, s.name as student_name, s.student_number, s.class as student_class
                FROM answer_sheets a
                JOIN students s ON a.student_id = s.student_id
                WHERE a.exam_id = :exam_id
                ORDER BY s.student_id, a.page_order
                """),
                {"exam_id": exam_id}
            )
            images = []
            for row in result.fetchall():
                images.append({
                    "id": row.id,
                    "filename": row.filename,
                    "file_path": row.file_path,
                    "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
                    "page_order": row.page_order,
                    "student": {
                        "student_id": row.student_id,
                        "name": row.student_name,
                        "student_number": row.student_number,
                        "class": row.student_class
                    }
                })
            return {"code": 1, "msg": "获取成功", "data": images}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取考试图片列表失败 (exam_id={exam_id}): {str(e)}")
        raise HTTPException(status_code=500, detail="获取图片列表失败")

# ==================== 上传图片（支持一个学生多张图片） ====================

@router.post("/api/exams/{exam_id}/images")
async def upload_exam_images(
    exam_id: int,
    files: List[UploadFile] = File(...),
    student_ids: List[int] = Form(...)
):
    # 智能处理 student_ids：如果只传了一个学生 ID，则自动复制到与文件数量相同
    if len(student_ids) == 1 and len(files) > 1:
        student_ids = student_ids * len(files)
    elif len(student_ids) != len(files):
        raise HTTPException(status_code=400, detail="文件数量与学生ID数量不匹配")

    # 验证考试存在
    try:
        with engine.connect() as conn:
            exam = conn.execute(
                text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail="验证考试失败")

    # 验证所有学生是否参加该考试
    try:
        with engine.connect() as conn:
            for sid in set(student_ids):  # 去重验证
                student_in_exam = conn.execute(
                    text("SELECT 1 FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                    {"exam_id": exam_id, "student_id": sid}
                ).fetchone()
                if not student_in_exam:
                    raise HTTPException(status_code=400, detail=f"学生 {sid} 未参加考试 {exam_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail="验证学生失败")

    upload_dir = ensure_upload_dir(exam_id)
    uploaded_count = 0
    errors = []

    # 按学生独立分配 page_order（每个学生的图片从0开始）
    student_counter = {}
    page_orders = []
    for sid in student_ids:
        cnt = student_counter.get(sid, 0)
        page_orders.append(cnt)
        student_counter[sid] = cnt + 1

    for idx, file in enumerate(files):
        student_id = student_ids[idx]
        page_order = page_orders[idx]

        if not is_allowed_file(file.filename):
            errors.append(f"文件 {file.filename} 类型不支持")
            continue

        timestamp = int(time.time())
        safe_filename = f"{timestamp}_{file.filename.replace('/', '_')}"
        file_path = os.path.join(upload_dir, safe_filename)

        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            with engine.connect() as conn:
                conn.execute(
                    text("""
                    INSERT INTO answer_sheets (exam_id, student_id, filename, file_path, page_order)
                    VALUES (:exam_id, :student_id, :filename, :file_path, :page_order)
                    """),
                    {
                        "exam_id": exam_id,
                        "student_id": student_id,
                        "filename": file.filename,
                        "file_path": file_path,
                        "page_order": page_order
                    }
                )
                conn.commit()

            uploaded_count += 1
            logger.info(f"上传成功: exam={exam_id}, student={student_id}, order={page_order}, file={file.filename}")
        except Exception as e:
            logger.error(f"上传失败 {file.filename}: {str(e)}")
            errors.append(f"{file.filename}: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
        finally:
            await file.close()

    return {
        "code": 1,
        "msg": f"成功上传 {uploaded_count} 个文件",
        "data": {"uploaded_count": uploaded_count, "errors": errors}
    }

# ==================== 获取某个学生的所有图片 ====================
@router.get("/api/exams/{exam_id}/students/{student_id}/images")
def get_student_images(exam_id: int, student_id: int):
    try:
        with engine.connect() as conn:
            check = conn.execute(
                text("SELECT 1 FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                {"exam_id": exam_id, "student_id": student_id}
            ).fetchone()
            if not check:
                raise HTTPException(status_code=404, detail="学生未参加该考试")

            result = conn.execute(
                text("""
                SELECT id, filename, file_path, uploaded_at, page_order
                FROM answer_sheets
                WHERE exam_id = :exam_id AND student_id = :student_id
                ORDER BY page_order
                """),
                {"exam_id": exam_id, "student_id": student_id}
            )
            images = []
            for row in result.fetchall():
                images.append({
                    "id": row.id,
                    "filename": row.filename,
                    "file_path": row.file_path,
                    "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
                    "page_order": row.page_order
                })
            return {"code": 1, "msg": "获取成功", "data": images}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取学生图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取学生图片失败")

# ==================== 删除图片 ====================
@router.delete("/api/exams/{exam_id}/images/{image_id}")
def delete_image(exam_id: int, image_id: int):
    try:
        with engine.connect() as conn:
            img = conn.execute(
                text("SELECT file_path FROM answer_sheets WHERE id = :image_id AND exam_id = :exam_id"),
                {"image_id": image_id, "exam_id": exam_id}
            ).fetchone()
            if not img:
                raise HTTPException(status_code=404, detail="图片不存在")

            file_path = img.file_path
            conn.execute(text("DELETE FROM answer_sheets WHERE id = :image_id"), {"image_id": image_id})
            conn.commit()

            if os.path.exists(file_path):
                os.remove(file_path)

            return {"code": 1, "msg": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail="删除图片失败")

# ==================== 更新图片顺序 ====================
@router.put("/api/exams/{exam_id}/images/{image_id}")
def update_image_order(
    exam_id: int,
    image_id: int,
    page_order: int = Form(...)
):
    try:
        with engine.connect() as conn:
            img = conn.execute(
                text("SELECT id FROM answer_sheets WHERE id = :image_id AND exam_id = :exam_id"),
                {"image_id": image_id, "exam_id": exam_id}
            ).fetchone()
            if not img:
                raise HTTPException(status_code=404, detail="图片不存在")

            conn.execute(
                text("UPDATE answer_sheets SET page_order = :page_order WHERE id = :image_id"),
                {"page_order": page_order, "image_id": image_id}
            )
            conn.commit()
            return {"code": 1, "msg": "更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新图片顺序失败: {str(e)}")
        raise HTTPException(status_code=500, detail="更新图片顺序失败")

# ==================== 图片拖拽逻辑 ====================
@router.put("/api/exams/{exam_id}/images/{image_id}/transfer")
def transfer_image(
        exam_id: int,
        image_id: int,
        target_student_id: int,
        db: Session = Depends(get_db)
):
    try:
        # 检查图片是否存在
        img = db.execute(
            text("SELECT student_id, page_order FROM answer_sheets WHERE id = :image_id AND exam_id = :exam_id"),
            {"image_id": image_id, "exam_id": exam_id}
        ).fetchone()
        if not img:
            raise HTTPException(status_code=404, detail="图片不存在")

        # 检查目标学生
        target = db.execute(
            text("SELECT 1 FROM exam_students WHERE exam_id = :exam_id AND student_id = :target_student_id"),
            {"exam_id": exam_id, "target_student_id": target_student_id}
        ).fetchone()
        if not target:
            raise HTTPException(status_code=400, detail="目标学生未参加该考试")

        # 获取目标学生当前最大 page_order
        max_order = db.execute(
            text("SELECT COALESCE(MAX(page_order), -1) as max_order FROM answer_sheets WHERE exam_id = :exam_id AND student_id = :target_student_id"),
            {"exam_id": exam_id, "target_student_id": target_student_id}
        ).fetchone().max_order
        new_order = max_order + 1

        # 更新图片归属和顺序
        db.execute(
            text("UPDATE answer_sheets SET student_id = :target_student_id, page_order = :new_order WHERE id = :image_id"),
            {"target_student_id": target_student_id, "new_order": new_order, "image_id": image_id}
        )
        db.commit()
        return {"code": 1, "msg": "图片移动成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移动图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"移动图片失败: {str(e)}")