from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import List, Optional
import logging
import os
import time
import shutil
import cv2
import numpy as np
import json
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

# ==================== 答题卡预处理函数 ====================

def enhance_text_clarity(gray: np.ndarray) -> np.ndarray:
    """对比度增强 + 去噪"""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)
    return denoised

def detect_and_remove_strikethroughs(gray: np.ndarray) -> np.ndarray:
    """检测划线、涂抹区域并 inpaint 修复"""
    # 反色二值化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 检测水平长线
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_h)

    # 检测垂直线
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_v)

    # 检测大面积涂抹
    kernel_smear = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    smear = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_smear)

    # 合并所有划痕区域
    strikethrough = cv2.bitwise_or(horizontal, vertical)
    strikethrough = cv2.bitwise_or(strikethrough, smear)

    # 膨胀
    kernel_dilate = np.ones((3, 3), np.uint8)
    strikethrough = cv2.dilate(strikethrough, kernel_dilate, iterations=2)

    # 利用轮廓面积过滤
    contours, _ = cv2.findContours(strikethrough, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(gray)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 20:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = max(w/h, h/w) if h > 0 else 999
        if area > 500 or (aspect_ratio > 5 and area > 100):
            cv2.drawContours(mask, [cnt], -1, 255, -1)

    # inpaint 修复
    cleaned_gray = cv2.inpaint(gray, mask, 5, cv2.INPAINT_TELEA)
    return cleaned_gray

def draw_question_dividers(image: np.ndarray,
                           layout: Optional[List[dict]] = None,
                           questions_per_section: Optional[List[int]] = None) -> np.ndarray:
    """绘制大题分割线"""
    h, w = image.shape[:2]
    if not layout and questions_per_section:
        total_q = sum(questions_per_section)
        if total_q == 0:
            return image
        cum = 0
        for i, cnt in enumerate(questions_per_section[:-1]):
            cum += cnt
            y = int((cum / total_q) * h)
            cv2.line(image, (0, y), (w, y), (255, 100, 0), 2)
            cv2.putText(image, f'第{i+1}大题', (10, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 100, 0), 2)
    elif layout:
        for div in layout:
            y = div['y'] if isinstance(div['y'], int) else int(div['y'] * h)
            cv2.line(image, (0, y), (w, y), (255, 100, 0), 2)
            if div.get('label'):
                cv2.putText(image, div['label'], (10, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 100, 0), 2)
    else:
        # 默认三等分
        for i in range(1, 3):
            y = int(h * i / 3)
            cv2.line(image, (0, y), (w, y), (255, 100, 0), 2)
            cv2.putText(image, f'第{i}大题', (10, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 100, 0), 2)
    return image

def preprocess_answer_sheet(image_path: str,
                           layout: Optional[List[dict]] = None,
                           questions_per_section: Optional[List[int]] = None) -> Optional[np.ndarray]:
    """完整预处理：返回处理后的彩色图像"""
    img = cv2.imread(image_path)
    if img is None:
        logger.error(f"无法读取图片: {image_path}")
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = enhance_text_clarity(gray)
    gray = detect_and_remove_strikethroughs(gray)

    # 转回三通道
    result = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # 画分割线
    result = draw_question_dividers(result, layout, questions_per_section)
    return result

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
                    a.id, a.filename, a.file_path, a.processed_file_path,
                    a.uploaded_at, a.page_order,
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
                    "processed_file_path": row.processed_file_path or row.file_path,
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
    if len(student_ids) == 1 and len(files) > 1:
        student_ids = student_ids * len(files)
    elif len(student_ids) != len(files):
        raise HTTPException(status_code=400, detail="文件数量与学生ID数量不匹配")

    # 验证考试存在
    try:
        with engine.connect() as conn:
            exam = conn.execute(
                text("SELECT exam_id, answer_sheet_layout FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")
            exam_layout = exam.answer_sheet_layout
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail="验证考试失败")

    # 验证所有学生
    try:
        with engine.connect() as conn:
            for sid in set(student_ids):
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

    # 获取题目分布（用于分割线）
    questions_per_section = []
    try:
        with engine.connect() as conn:
            q_rows = conn.execute(
                text("""
                    SELECT eq.question_order, q.type
                    FROM exam_questions eq
                    JOIN questions q ON eq.question_id = q.id
                    WHERE eq.exam_id = :exam_id
                    ORDER BY eq.question_order
                """),
                {"exam_id": exam_id}
            ).fetchall()
            # 简单按题型分组（顺序保持）
            current_type = None
            for row in q_rows:
                if row.type != current_type:
                    questions_per_section.append(0)
                    current_type = row.type
                questions_per_section[-1] += 1
    except Exception as e:
        logger.warning(f"获取题目分布失败: {e}")

    # 解析布局配置
    layout = None
    if exam_layout:
        try:
            layout = json.loads(exam_layout)
            if not isinstance(layout, list):
                layout = None
        except:
            pass

    upload_dir = ensure_upload_dir(exam_id)
    uploaded_count = 0
    errors = []

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

            # ----- 图片预处理 -----
            base, ext = os.path.splitext(file_path)
            processed_path = f"{base}_processed.png"

            try:
                processed_img = preprocess_answer_sheet(file_path, layout, questions_per_section)
                if processed_img is not None:
                    cv2.imwrite(processed_path, processed_img)
                else:
                    processed_path = file_path  # 回退到原图
            except Exception as pp_err:
                logger.error(f"预处理失败 {file_path}: {pp_err}")
                processed_path = file_path
            # ---------------------

            with engine.connect() as conn:
                conn.execute(
                    text("""
                    INSERT INTO answer_sheets 
                    (exam_id, student_id, filename, file_path, processed_file_path, page_order)
                    VALUES (:exam_id, :student_id, :filename, :file_path, :processed_path, :page_order)
                    """),
                    {
                        "exam_id": exam_id,
                        "student_id": student_id,
                        "filename": file.filename,
                        "file_path": file_path,
                        "processed_path": processed_path,
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
                SELECT id, filename, file_path, processed_file_path, uploaded_at, page_order
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
                    "processed_file_path": row.processed_file_path or row.file_path,
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
                text("SELECT file_path, processed_file_path FROM answer_sheets WHERE id = :image_id AND exam_id = :exam_id"),
                {"image_id": image_id, "exam_id": exam_id}
            ).fetchone()
            if not img:
                raise HTTPException(status_code=404, detail="图片不存在")

            # 删除原图
            if os.path.exists(img.file_path):
                os.remove(img.file_path)
            # 删除预处理图（如果存在且不同于原图）
            if img.processed_file_path and img.processed_file_path != img.file_path and os.path.exists(img.processed_file_path):
                os.remove(img.processed_file_path)

            conn.execute(text("DELETE FROM answer_sheets WHERE id = :image_id"), {"image_id": image_id})
            conn.commit()

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
        img = db.execute(
            text("SELECT student_id, page_order FROM answer_sheets WHERE id = :image_id AND exam_id = :exam_id"),
            {"image_id": image_id, "exam_id": exam_id}
        ).fetchone()
        if not img:
            raise HTTPException(status_code=404, detail="图片不存在")

        target = db.execute(
            text("SELECT 1 FROM exam_students WHERE exam_id = :exam_id AND student_id = :target_student_id"),
            {"exam_id": exam_id, "target_student_id": target_student_id}
        ).fetchone()
        if not target:
            raise HTTPException(status_code=400, detail="目标学生未参加该考试")

        max_order = db.execute(
            text("SELECT COALESCE(MAX(page_order), -1) as max_order FROM answer_sheets WHERE exam_id = :exam_id AND student_id = :target_student_id"),
            {"exam_id": exam_id, "target_student_id": target_student_id}
        ).fetchone().max_order

        new_order = max_order + 1
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