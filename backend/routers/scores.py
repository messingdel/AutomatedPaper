from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import logging
from typing import Dict
from pydantic import BaseModel
from backend.database import engine, get_db
from fastapi.responses import StreamingResponse
import pandas as pd
import io

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/exams/{exam_id}/scores")
def get_exam_scores(exam_id: int):
    try:
        with engine.connect() as conn:
            # 1. 考试信息
            exam = conn.execute(
                text("SELECT exam_id, exam_name, total_score, total_questions FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            # 动态计算考试总分
            if exam.total_score is None:
                total_score_result = conn.execute(
                    text("""
                        SELECT COALESCE(SUM(q.score), 0) 
                        FROM questions q 
                        INNER JOIN exam_questions eq ON q.id = eq.question_id 
                        WHERE eq.exam_id = :exam_id
                    """),
                    {"exam_id": exam_id}
                ).scalar()
                exam_total = float(total_score_result) if total_score_result is not None else None
            else:
                exam_total = float(exam.total_score)

            exam_info = {
                "exam_id": exam.exam_id,
                "exam_name": exam.exam_name,
                "total_score": exam_total,
                "total_questions": exam.total_questions
            }

            # 2. 学生列表
            students_result = conn.execute(
                text("""
                SELECT s.student_id, s.name, s.student_number, s.class
                FROM students s
                INNER JOIN exam_students es ON s.student_id = es.student_id
                WHERE es.exam_id = :exam_id
                ORDER BY es.sort_order ASC, s.student_number ASC
                """),
                {"exam_id": exam_id}
            )
            students_list = [dict(row._mapping) for row in students_result.fetchall()]
            if not students_list:
                return {"code": 1, "msg": "获取成功", "data": {"exam_info": exam_info, "students": []}}

            # 3. 题目列表（包含满分）
            questions_result = conn.execute(
                text("""
                SELECT q.id, q.content, q.score as max_score, eq.question_order
                FROM questions q
                INNER JOIN exam_questions eq ON q.id = eq.question_id
                WHERE eq.exam_id = :exam_id
                ORDER BY eq.question_order
                """),
                {"exam_id": exam_id}
            )
            questions = [dict(row._mapping) for row in questions_result.fetchall()]

            # 4. 得分明细
            scores_result = conn.execute(
                text("""
                SELECT DISTINCT student_id, question_id, score, student_answer, updated_at
                FROM student_scores
                WHERE exam_id = :exam_id
                """),
                {"exam_id": exam_id}
            )
            scores_by_student: Dict[int, Dict[int, dict]] = {}
            graded_at_map = {}
            for row in scores_result.fetchall():
                sid = row.student_id
                if sid not in scores_by_student:
                    scores_by_student[sid] = {}
                scores_by_student[sid][row.question_id] = {
                    "score": float(row.score),
                    "student_answer": row.student_answer,
                    "updated_at": row.updated_at
                }
                if sid not in graded_at_map or (row.updated_at and row.updated_at > graded_at_map[sid]):
                    graded_at_map[sid] = row.updated_at

            # 5. 组装学生数据
            student_data_list = []
            for student in students_list:
                sid = student["student_id"]
                student_scores = scores_by_student.get(sid, {})

                question_scores = []
                total_score = 0.0
                for q in questions:
                    qid = q["id"]
                    score_info = student_scores.get(qid)
                    score = score_info["score"] if score_info else None
                    if score is not None:
                        total_score += score
                    question_scores.append({
                        "question_id": qid,
                        "question_order": q["question_order"],
                        "content": q["content"],
                        "score": score,
                        "max_score": float(q["max_score"]) if q["max_score"] is not None else None,
                        "student_answer": score_info["student_answer"] if score_info else None
                    })

                if exam_total is not None and total_score > exam_total:
                    logger.warning(f"学生 {student['name']} 总分 {total_score} 超过考试总分 {exam_total}，已截断")
                    total_score = exam_total

                student_data = {
                    "student_id": sid,
                    "name": student["name"],
                    "student_number": student["student_number"],
                    "class": student["class"],
                    "total_score": total_score if total_score > 0 else None,
                    "question_scores": question_scores,
                    "graded_at": graded_at_map.get(sid).isoformat() if graded_at_map.get(sid) else None
                }
                student_data_list.append(student_data)

            # 6. 排名计算
            scored_students = [s for s in student_data_list if s["total_score"] is not None]
            scored_students.sort(key=lambda x: x["total_score"], reverse=True)
            rank = 1
            for i, s in enumerate(scored_students):
                if i > 0 and s["total_score"] != scored_students[i-1]["total_score"]:
                    rank = i + 1
                s["rank"] = rank
            for s in student_data_list:
                if s["total_score"] is None:
                    s["rank"] = None

            return {
                "code": 1,
                "msg": "获取成功",
                "data": {
                    "exam_info": exam_info,
                    "students": student_data_list
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取考试成绩失败 (exam_id={exam_id}): {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取考试成绩失败: {str(e)}")


class ScoreUpdate(BaseModel):
    score: float


@router.put("/api/exams/{exam_id}/scores/{student_id}/{question_id}")
def update_question_score(
    exam_id: int,
    student_id: int,
    question_id: int,
    data: ScoreUpdate,
    db: Session = Depends(get_db)
):
    try:
        with db as session:
            # 删除重复记录（保留最新）
            session.execute(
                text("""
                DELETE FROM student_scores
                WHERE exam_id = :exam_id AND student_id = :student_id AND question_id = :question_id
                AND id NOT IN (
                    SELECT * FROM (
                        SELECT MIN(id) FROM student_scores
                        WHERE exam_id = :exam_id AND student_id = :student_id AND question_id = :question_id
                    ) AS tmp
                )
                """),
                {"exam_id": exam_id, "student_id": student_id, "question_id": question_id}
            )
            session.execute(
                text("""
                INSERT INTO student_scores (exam_id, student_id, question_id, score)
                VALUES (:exam_id, :student_id, :question_id, :score)
                ON DUPLICATE KEY UPDATE score = VALUES(score), updated_at = CURRENT_TIMESTAMP
                """),
                {"exam_id": exam_id, "student_id": student_id, "question_id": question_id, "score": data.score}
            )
            session.commit()
            return {"code": 1, "msg": "分数更新成功"}
    except Exception as e:
        logger.error(f"更新分数失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新分数失败: {str(e)}")


@router.get("/api/exams/{exam_id}/export")
def export_exam_scores(exam_id: int):
    """导出考试成绩为 Excel 文件"""
    try:
        with engine.connect() as conn:
            exam = conn.execute(
                text("SELECT exam_id, exam_name, total_score FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise HTTPException(status_code=404, detail="考试不存在")

            students_result = conn.execute(
                text("""
                    SELECT s.student_id, s.student_number, s.name, s.class,
                           COALESCE(SUM(ss.score), 0) as total_score
                    FROM students s
                    INNER JOIN exam_students es ON s.student_id = es.student_id
                    LEFT JOIN student_scores ss ON ss.student_id = s.student_id AND ss.exam_id = :exam_id
                    WHERE es.exam_id = :exam_id
                    GROUP BY s.student_id
                    ORDER BY total_score DESC
                """),
                {"exam_id": exam_id}
            )
            students = []
            for row in students_result:
                students.append({
                    "student_id": row.student_id,
                    "student_number": row.student_number,
                    "name": row.name,
                    "class": getattr(row, 'class'),
                    "total_score": row.total_score
                })

            questions_result = conn.execute(
                text("""
                    SELECT q.id, q.content, eq.question_order, q.score as max_score
                    FROM questions q
                    INNER JOIN exam_questions eq ON q.id = eq.question_id
                    WHERE eq.exam_id = :exam_id
                    ORDER BY eq.question_order
                """),
                {"exam_id": exam_id}
            )
            questions = [dict(row._mapping) for row in questions_result.fetchall()]

            scores_result = conn.execute(
                text("""
                    SELECT student_id, question_id, score
                    FROM student_scores
                    WHERE exam_id = :exam_id
                """),
                {"exam_id": exam_id}
            )
            score_map = {}
            for row in scores_result:
                sid = row.student_id
                qid = row.question_id
                if sid not in score_map:
                    score_map[sid] = {}
                score_map[sid][qid] = row.score

            rows = []
            for student in students:
                row_data = {
                    "学号": student["student_number"],
                    "姓名": student["name"],
                    "班级": student["class"],
                    "总分": student["total_score"]
                }
                for q in questions:
                    qid = q["id"]
                    score = score_map.get(student["student_id"], {}).get(qid, "")
                    row_data[f"第{q['question_order']}题 ({q['max_score']}分)"] = score
                rows.append(row_data)

            df = pd.DataFrame(rows)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name="成绩表", index=False)
                worksheet = writer.sheets["成绩表"]
                for i, col in enumerate(df.columns):
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, min(max_len, 30))
            output.seek(0)

            filename = f"exam_{exam.exam_name}_{exam_id}_scores.xlsx"
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
            )
    except Exception as e:
        logger.error(f"导出成绩失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")