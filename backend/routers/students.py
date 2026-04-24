from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Body
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
import logging
import os
import pandas as pd
import io

from backend.database import engine

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter()

# ==================== Pydantic模型定义 ====================

class StudentRequest(BaseModel):
    name: str
    student_number: Optional[str] = ""
    class_name: Optional[str] = ""
    contact_info: Optional[str] = ""

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    student_number: Optional[str] = None
    class_name: Optional[str] = None
    contact_info: Optional[str] = None

class BatchStudentRequest(BaseModel):
    """批量添加学生请求模型"""
    students: List[StudentRequest]

# ==================== 学生管理API ====================

@router.get("/api/students")
def get_students():
    """获取所有学生列表"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM students ORDER BY name"))
            students = [dict(row._mapping) for row in result.fetchall()]
            return {"code": 1, "msg": "获取成功", "data": students}
    except Exception as e:
        logger.error(f"获取学生列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取学生列表失败: {str(e)}")

@router.post("/api/students")
def create_student(student: StudentRequest):
    """添加新学生"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                INSERT INTO students (name, student_number, class, contact_info)
                VALUES (:name, :student_number, :class_name, :contact_info)
                """),
                {
                    "name": student.name,
                    "student_number": student.student_number,
                    "class_name": student.class_name,
                    "contact_info": student.contact_info
                }
            )
            conn.commit()
            student_id = result.lastrowid

            return {"code": 1, "msg": "添加成功", "data": {"student_id": student_id}}
    except Exception as e:
        logger.error(f"添加学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加学生失败: {str(e)}")

@router.put("/api/students/{student_id}")
def update_student(student_id: int, student: StudentUpdate):
    """更新学生信息"""
    try:
        with engine.connect() as conn:
            # Check if student number exists for another student
            if student.student_number is not None:
                existing = conn.execute(
                    text("SELECT student_id FROM students WHERE student_number = :student_number AND student_id != :student_id"),
                    {"student_number": student.student_number, "student_id": student_id}
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=400, detail=f"学号 {student.student_number} 已存在")

            update_fields = []
            update_params = {"student_id": student_id}

            if student.name is not None:
                update_fields.append("name = :name")
                update_params["name"] = student.name
            if student.student_number is not None:
                update_fields.append("student_number = :student_number")
                update_params["student_number"] = student.student_number
            if student.class_name is not None:
                update_fields.append("class = :class_name")
                update_params["class_name"] = student.class_name
            if student.contact_info is not None:
                update_fields.append("contact_info = :contact_info")
                update_params["contact_info"] = student.contact_info

            if not update_fields:
                return {"code": 0, "msg": "没有更新字段"}

            query = f"UPDATE students SET {', '.join(update_fields)} WHERE student_id = :student_id"
            conn.execute(text(query), update_params)
            conn.commit()

            return {"code": 1, "msg": "更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新学生失败: {str(e)}")

@router.delete("/api/students/{student_id}")
def delete_student(student_id: int):
    """删除学生"""
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM students WHERE student_id = :student_id"), {"student_id": student_id})
            conn.commit()
            return {"code": 1, "msg": "删除成功"}
    except Exception as e:
        logger.error(f"删除学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除学生失败: {str(e)}")

# ==================== 考试学生关联API ====================

@router.post("/api/exams/{exam_id}/batch-add-students")
async def batch_add_students_to_exam(exam_id: int, request: BatchStudentRequest):
    """批量添加学生到考试"""
    try:
        # 验证考试是否存在
        with engine.connect() as conn:
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

        added_count = 0
        errors = []

        with engine.connect() as conn:
            for student_data in request.students:
                try:
                    student_number = student_data.student_number
                    name = student_data.name
                    class_name = student_data.class_name
                    contact_info = student_data.contact_info

                    if not student_number:
                        errors.append(f"学号缺失: {student_data.name or '未知姓名'}")
                        continue
                    
                    if not name:
                        errors.append(f"姓名缺失: 学号 {student_number}")
                        continue

                    # 检查学生是否已存在
                    existing_student = conn.execute(
                        text("SELECT student_id, name FROM students WHERE student_number = :student_number"),
                        {"student_number": student_number}
                    ).fetchone()

                    if existing_student:
                        # 存在同名学号，检查姓名是否一致
                        db_student_id, db_name = existing_student
                        if db_name != name:
                            errors.append(f"学号冲突: 学号 {student_number} 已存在且属于学生 {db_name}，与当前 {name} 不符")
                            continue
                        student_id = db_student_id
                    else:
                        # 创建新学生
                        insert_result = conn.execute(
                            text("""
                                INSERT INTO students (name, student_number, class, contact_info)
                                VALUES (:name, :student_number, :class_name, :contact_info)
                            """),
                            {
                                "name": name,
                                "student_number": student_number,
                                "class_name": class_name,
                                "contact_info": contact_info
                            }
                        )
                        student_id = insert_result.lastrowid

                    # 检查是否已经在考试中
                    existing_exam_student = conn.execute(
                        text("SELECT * FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                        {"exam_id": exam_id, "student_id": student_id}
                    ).fetchone()

                    if not existing_exam_student:
                        # 添加学生到考试
                        conn.execute(
                           text("INSERT INTO exam_students (exam_id, student_id) VALUES (:exam_id, :student_id)"),
                            {"exam_id": exam_id, "student_id": student_id}
                        )
                        added_count += 1
                    else:
                        errors.append(f"重复添加: 学生 {name} ({student_number}) 已在考试中")

                except Exception as e:
                    errors.append(f"系统错误 {name}: {str(e)}")
                    continue

            conn.commit()

        return {
            "code": 1,
            "msg": f"批量添加成功，共添加 {added_count} 个学生",
            "data": {
                "added_count": added_count,
                "errors": errors
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量添加学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批量添加学生失败: {str(e)}")

@router.post("/api/exams/{exam_id}/students")
def add_student_to_exam(exam_id: int, student_id: int = Body(...)):
    """将学生添加到考试中"""
    try:
        with engine.connect() as conn:
            # 检查考试是否存在
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            # 检查学生是否存在
            student_result = conn.execute(text("SELECT student_id FROM students WHERE student_id = :student_id"), {"student_id": student_id}).fetchone()
            if not student_result:
                raise HTTPException(status_code=404, detail=f"学生 {student_id} 不存在")

            # 添加关联
            try:
                conn.execute(
                    text("INSERT INTO exam_students (exam_id, student_id) VALUES (:exam_id, :student_id)"),
                    {"exam_id": exam_id, "student_id": student_id}
                )
                conn.commit()
                return {"code": 1, "msg": "添加成功"}
            except:
                # 如果已存在，返回成功
                return {"code": 1, "msg": "学生已在该考试中"}
    except Exception as e:
        logger.error(f"添加学生到考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加学生到考试失败: {str(e)}")

@router.delete("/api/exams/{exam_id}/students/{student_id}")
def remove_student_from_exam(exam_id: int, student_id: int):
    """将学生从考试中移除"""
    try:
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                {"exam_id": exam_id, "student_id": student_id}
            )
            conn.commit()
            return {"code": 1, "msg": "移除成功"}
    except Exception as e:
        logger.error(f"移除学生从考试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"移除学生从考试失败: {str(e)}")

@router.get("/api/exams/{exam_id}/students")
def get_exam_students(exam_id: int):
    """获取考试的学生列表"""
    try:
        with engine.connect() as conn:
            # 检查考试是否存在
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            # 获取考试的所有学生
            result = conn.execute(
                text("""
                SELECT s.student_id, s.name, s.student_number, s.class as class_name, s.contact_info, s.created_at, s.updated_at, es.sort_order
                FROM students s
                INNER JOIN exam_students es ON s.student_id = es.student_id
                WHERE es.exam_id = :exam_id
                ORDER BY es.sort_order ASC, s.student_number ASC
                """),
                {"exam_id": exam_id}
            )
            students = []
            for row in result.fetchall():
                student = {
                    'student_id': row.student_id,
                    'name': row.name,
                    'student_number': row.student_number,
                    'class': row.class_name,
                    'contact_info': row.contact_info,
                    'created_at': row.created_at.isoformat() if row.created_at else None,
                    'updated_at': row.updated_at.isoformat() if row.updated_at else None,
                    'sort_order': row.sort_order
                }
                students.append(student)

            return {"code": 1, "msg": "获取成功", "data": students}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取考试学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取考试学生失败: {str(e)}")

@router.post("/api/exams/{exam_id}/students/reorder")
def reorder_exam_students(exam_id: int, student_ids: List[int] = Body(...)):
    """重新排序考试学生"""
    try:
        with engine.connect() as conn:
            # 检查考试是否存在
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            # 批量更新排序
            for index, student_id in enumerate(student_ids):
                conn.execute(
                    text("UPDATE exam_students SET sort_order = :sort_order WHERE exam_id = :exam_id AND student_id = :student_id"),
                    {"sort_order": index + 1, "exam_id": exam_id, "student_id": student_id}
                )
            
            conn.commit()
            return {"code": 1, "msg": "排序更新成功"}
    except Exception as e:
        logger.error(f"更新学生排序失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新学生排序失败: {str(e)}")

@router.get("/api/exams/{exam_id}/available-students")
def get_available_students(exam_id: int, search: Optional[str] = None):
    """获取未分配到该考试的学生列表"""
    try:
        with engine.connect() as conn:
            # 检查考试是否存在
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            # 构建查询条件
            where_clause = "WHERE s.student_id NOT IN (SELECT es.student_id FROM exam_students es WHERE es.exam_id = :exam_id)"
            params = {"exam_id": exam_id}

            if search:
                where_clause += " AND (s.name LIKE :search OR s.student_number LIKE :search OR s.class LIKE :search)"
                params.update({"search": f"%{search}%"})

            # 获取未分配到该考试的学生
            result = conn.execute(
                text(f"""
                SELECT s.student_id, s.name, s.student_number, s.class as class_name, s.contact_info
                FROM students s
                {where_clause}
                ORDER BY s.name
                """),
                params
            )
            students = []
            for row in result.fetchall():
                student = {
                    'student_id': row.student_id,
                    'name': row.name,
                    'student_number': row.student_number,
                    'class_name': row.class_name,
                    'contact_info': row.contact_info
                }
                students.append(student)

            return {"code": 1, "msg": "获取成功", "data": students}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取可用学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取可用学生失败: {str(e)}")

@router.post("/api/exams/{exam_id}/import-students")
async def import_students_from_file(exam_id: int, file: UploadFile = File(...)):
    """从文件导入学生信息到考试"""
    try:
        # 验证考试是否存在
        with engine.connect() as conn:
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

        # 验证文件类型
        file_extension = os.path.splitext(file.filename)[1].lower()
        allowed_extensions = {'.xlsx', '.xls', '.txt', '.csv'}
        if file_extension not in allowed_extensions:
            raise HTTPException(status_code=400, detail="不支持的文件格式。支持: xlsx, xls, txt, csv")

        # 读取文件内容
        content = await file.read()
        students_to_add = []

        try:
            if file_extension in {'.xlsx', '.xls'}:
                # 处理Excel文件
                df = pd.read_excel(io.BytesIO(content))
                # 假设列顺序为：学号, 班级, 姓名, 联系方式
                for _, row in df.iterrows():
                    if len(row) >= 3 and pd.notna(row.iloc[0]) and pd.notna(row.iloc[2]):
                        students_to_add.append({
                            "student_number": str(row.iloc[0]).strip(),
                            "class": str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else "",
                            "name": str(row.iloc[2]).strip(),
                            "contact_info": str(row.iloc[3]).strip() if len(row) > 3 and pd.notna(row.iloc[3]) else ""
                        })
            else:
                # 处理文本文件
                text_content = content.decode('utf-8')
                lines = text_content.strip().split('\n')

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # 支持逗号和制表符分隔
                    if '\t' in line:
                        parts = line.split('\t')
                    else:
                        parts = line.split(',')

                    if len(parts) >= 3 and parts[0].strip() and parts[2].strip():
                        students_to_add.append({
                            "student_number": parts[0].strip(),
                            "class": parts[1].strip(),
                            "name": parts[2].strip(),
                            "contact_info": parts[3].strip() if len(parts) > 3 else ""
                        })
        except Exception as parse_error:
            raise HTTPException(status_code=400, detail=f"文件解析失败: {str(parse_error)}")

        if not students_to_add:
            raise HTTPException(status_code=400, detail="文件中没有找到有效的学生信息")

        # 添加学生到数据库
        imported_count = 0
        with engine.connect() as conn:
            for student_data in students_to_add:
                try:
                    # 检查学号是否已存在
                    existing = conn.execute(
                        text("SELECT student_id FROM students WHERE student_number = :student_number"),
                        {"student_number": student_data["student_number"]}
                    ).fetchone()

                    student_id = None
                    if not existing:
                        # 创建新学生
                        result = conn.execute(
                            text("""INSERT INTO students (name, student_number, class, contact_info)
                                 VALUES (:name, :student_number, :class, :contact_info)"""),
                            {
                                "name": student_data["name"],
                                "student_number": student_data["student_number"],
                                "class": student_data.get("class", ""),
                                "contact_info": student_data.get("contact_info", "")
                            }
                        )
                        student_id = result.lastrowid
                    else:
                        student_id = existing[0]

                    # 将学生添加到考试（如果还没有）
                    existing_relation = conn.execute(
                       text("SELECT * FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                        {"exam_id": exam_id, "student_id": student_id}
                    ).fetchone()

                    if not existing_relation:
                        conn.execute(
                            text("INSERT INTO exam_students (exam_id, student_id) VALUES (:exam_id, :student_id)"),
                            {"exam_id": exam_id, "student_id": student_id}
                        )
                        imported_count += 1

                    conn.commit()
                except Exception as student_error:
                    logger.warning(f"添加学生失败 {student_data}: {str(student_error)}")
                    continue

        return {"code": 1, "msg": "导入成功", "data": {"imported_count": imported_count}}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件导入失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文件导入失败: {str(e)}")

@router.post("/api/exams/{exam_id}/add-existing-students")
def add_existing_students_to_exam(exam_id: int, student_ids: List[int] = Body(...)):
    """添加已存在的学生到考试"""
    try:
        with engine.connect() as conn:
            # 检查考试是否存在
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            added_count = 0
            already_in_exam = []

            for student_id in student_ids:
                try:
                    # 检查学生是否存在
                    student_result = conn.execute(
                        text("SELECT student_id FROM students WHERE student_id = :student_id"),
                        {"student_id": student_id}
                    ).fetchone()

                    if not student_result:
                        logger.warning(f"学生 {student_id} 不存在，跳过")
                        continue

                    # 检查是否已经在该考试中
                    existing_relation = conn.execute(
                        text("SELECT * FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                        {"exam_id": exam_id, "student_id": student_id}
                    ).fetchone()

                    if existing_relation:
                        already_in_exam.append(student_id)
                        continue

                    # 添加学生到考试
                    conn.execute(
                        text("INSERT INTO exam_students (exam_id, student_id) VALUES (:exam_id, :student_id)"),
                        {"exam_id": exam_id, "student_id": student_id}
                    )
                    added_count += 1

                except Exception as student_error:
                    logger.warning(f"添加学生失败 {student_id}: {str(student_error)}")
                    continue

            conn.commit()

            return {"code": 1, "msg": f"成功添加 {added_count} 个学生", "data": {"added_count": added_count}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加已存在学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加已存在学生失败: {str(e)}")

@router.post("/api/exams/{exam_id}/students/remove-batch")
def remove_students_batch(exam_id: int, student_ids: List[int] = Body(...)):
    """批量删除学生从考试"""
    try:
        with engine.connect() as conn:
            # 检查考试是否存在
            exam_result = conn.execute(text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"), {"exam_id": exam_id}).fetchone()
            if not exam_result:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            removed_count = 0

            for student_id in student_ids:
                try:
                    # 直接尝试删除关联
                    result = conn.execute(
                        text("DELETE FROM exam_students WHERE exam_id = :exam_id AND student_id = :student_id"),
                        {"exam_id": exam_id, "student_id": student_id}
                    )
                    if result.rowcount > 0:
                        removed_count += 1

                except Exception as student_error:
                    logger.warning(f"删除学生失败 {student_id}: {str(student_error)}")
                    continue

            conn.commit()

            return {"code": 1, "msg": "删除成功", "data": {"removed_count": removed_count}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除学生失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批量删除学生失败: {str(e)}")
