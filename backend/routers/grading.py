from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging
import asyncio
from sqlalchemy import text
from sqlalchemy.orm import Session
import os
import re
import requests
import base64
import json
from typing import List, Dict

# 新增导入
import cv2
import numpy as np

from backend.database import engine, get_db
from backend.config import MM_MODEL_CONFIG

logger = logging.getLogger(__name__)

router = APIRouter()


class GradingJobStatusResponse(BaseModel):
    job_id: int
    exam_id: int
    status: str
    total_students: int
    processed_students: int
    created_at: str
    updated_at: str


class StartGradingResponse(BaseModel):
    code: int
    msg: str
    data: dict


# ==================== 温和的图像预处理函数 ====================
def preprocess_image(image_path: str) -> str:
    """
    对答题卡图片进行温和预处理：灰度化 + CLAHE增强 + 轻量去噪 + 可选透视校正。
    不进行二值化和形态学操作，保留图像细节，适合多模态模型直接识别。
    生成临时文件，原始文件不变。
    """
    img = cv2.imread(image_path)
    if img is None:
        logger.warning(f"无法读取图片: {image_path}")
        return image_path

    # 1. 灰度化
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. CLAHE 增强对比度
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)

    # 3. 轻量去噪（双边滤波保留边缘）
    denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)

    # 4. 可选：透视校正（默认关闭，可通过参数开启）
    def apply_perspective_correction(img, enable=False):
        if not enable:
            return img
        try:
            _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                max_contour = max(contours, key=cv2.contourArea)
                epsilon = 0.02 * cv2.arcLength(max_contour, True)
                approx = cv2.approxPolyDP(max_contour, epsilon, True)
                if len(approx) == 4:
                    pts = approx.reshape(4, 2)
                    # 排序四个角点（左上、右上、右下、左下）
                    rect = np.zeros((4, 2), dtype=np.float32)
                    s = pts.sum(axis=1)
                    rect[0] = pts[np.argmin(s)]
                    rect[2] = pts[np.argmax(s)]
                    diff = np.diff(pts, axis=1)
                    rect[1] = pts[np.argmin(diff)]
                    rect[3] = pts[np.argmax(diff)]
                    # 计算目标尺寸
                    w1 = np.linalg.norm(rect[1] - rect[0])
                    w2 = np.linalg.norm(rect[2] - rect[3])
                    h1 = np.linalg.norm(rect[3] - rect[0])
                    h2 = np.linalg.norm(rect[2] - rect[1])
                    dst_w = int(max(w1, w2))
                    dst_h = int(max(h1, h2))
                    dst = np.array([[0, 0], [dst_w - 1, 0], [dst_w - 1, dst_h - 1], [0, dst_h - 1]], dtype=np.float32)
                    M = cv2.getPerspectiveTransform(rect, dst)
                    img = cv2.warpPerspective(img, M, (dst_w, dst_h))
        except Exception as e:
            logger.warning(f"透视校正失败: {e}")
        return img

    # 调用透视校正（此处 enable=False 关闭）
    denoised = apply_perspective_correction(denoised, enable=False)

    # 增加边缘填充（防止顶部信息丢失）
    border_size = 20
    denoised = cv2.copyMakeBorder(denoised, border_size, border_size, border_size, border_size, cv2.BORDER_CONSTANT,
                                  value=255)
    # 保存临时文件（灰度图，非二值）
    base, ext = os.path.splitext(image_path)
    processed_path = f"{base}_processed{ext}"
    cv2.imwrite(processed_path, denoised)
    logger.info(f"预处理完成: {processed_path}")
    return processed_path


# ==================== 第一次识别：OCR ====================
def ocr_only(image_paths: List[str], questions: List[dict]) -> Dict[int, dict]:
    """
    第一次识别：使用多模态模型提取学生手写答案，返回 { order: {"exists": True, "answer": str} }
    """
    if not image_paths:
        return {}

    num_questions = len(questions)
    # 修改提示词，强调不要输出题号
    prompt = (
        "你是一个严格的光学字符识别（OCR）工具。\n"
        "请分析图片中的学生答题卡。注意：请务必从第一道小题开始识别，不要跳过任何题号。\n"
        "即使题目靠近表格或印刷体标题，也要尝试提取学生手写答案。\n"
        "请分析图片中的学生答题卡，忽略所有印刷体题目描述、表格、得分栏等无关内容。\n"
        f"请按顺序识别每个小题的学生答案。一共有 {num_questions} 道小题。\n"
        "小题的题号是普通数字加标点，例如“1.”、“2.”、“3.”。每个这样的题号代表一道独立的小题。\n"
        "同一道小题的答案内部可能包含分点，分点符号通常是带圈数字“①”、“②”、“③”或括号数字“(1)”、“(2)”。这些分点属于同一道小题，必须合并为一个答案字符串，使用换行符分隔各个分点。\n"
        "注意：填空题的答案通常很短，可能是单个数字、字母或词语，请务必提取，不要忽略。\n"
        "重要：你需要准确识别学生手写答案中的数学符号和公式，包括但不限于：\n"
        "  - 绝对值：|x|、||x||、|a-b| 等，用竖线表示，不要写成 abs(x) 或 abs()\n"
        "  - 范数：||x||、||x||_p\n"
        "  - 基本运算：+、-、×、÷、=、≈、≠、≤、≥、±、√、∛、∞\n"
        "  - 希腊字母：α、β、γ、δ、ε、λ、μ、π、σ、τ、ω\n"
        "  - 上下标：x^2、y_n、a^{b}、e^{x}（用 ^ 和 _ 表示）\n"
        "  - 分数：a/b 或水平分数线（写作 (分子)/(分母)）\n"
        "  - 积分：∫、∬、∮\n"
        "  - 求和连乘：∑、∏\n"
        "  - 集合符号：∈、∉、⊂、⊆、∪、∩、∅\n"
        "  - 逻辑符号：⇒、⇔、∀、∃\n"
        "  - 矩阵：用方括号表示，如 [a b; c d]\n"
        "输出一个JSON数组，按题号顺序（1,2,3...）包含每个小题的学生答案。\n"
        "重要：输出的答案中不要包含题号本身（例如不要输出“2、负实轴单位圆”，只需要输出“负实轴单位圆”）。\n"
        "如果某道小题没有答案或无法识别，则对应位置输出空字符串。\n"
        "严禁将多个小题的答案合并到一个数组元素中！\n"
        "严禁将一道小题的多个分点拆分成多个数组元素！\n"
        "不要输出任何其他解释或标记。"
    )

    content = [{"text": prompt}]
    for path in image_paths:
        with open(path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
        mime_type = "image/jpeg" if not path.lower().endswith('.png') else "image/png"
        content.append({"image": f"data:{mime_type};base64,{img_base64}"})

    body = {
        "model": MM_MODEL_CONFIG["model"],
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"result_format": "message", "temperature": 0.0}
    }
    headers = {
        "Authorization": f"Bearer {MM_MODEL_CONFIG['api_key']}",
        "Content-Type": "application/json"
    }

    raw_result = ""
    for attempt in range(MM_MODEL_CONFIG["max_retries"]):
        try:
            resp = requests.post(MM_MODEL_CONFIG["api_url"], headers=headers, json=body, timeout=MM_MODEL_CONFIG["timeout"])
            resp.raise_for_status()
            result = resp.json()
            raw_result = result["output"]["choices"][0]["message"]["content"][0]["text"]
            logger.info(f"OCR原始结果（完整）: {raw_result}")
            break
        except Exception as e:
            if attempt == MM_MODEL_CONFIG["max_retries"] - 1:
                logger.error(f"OCR API 调用最终失败: {e}")
                return {}
            logger.warning(f"OCR 重试 {attempt+1}: {e}")

    if not raw_result:
        return {}

    # 去除 Markdown 代码块标记
    cleaned = re.sub(r'^```json\s*', '', raw_result.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    logger.info(f"清理后的内容: {cleaned}")

    # 解析 JSON 数组
    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            match = re.search(r'\[.*\]', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = []
    except Exception as e:
        logger.error(f"OCR JSON解析失败: {e}, 原始内容: {raw_result}")
        data = []

    # 确保长度与题目数一致
    while len(data) < num_questions:
        data.append("")
    data = data[:num_questions]

    # ========== 修改点：增强清洗函数，移除题号前缀（包括数字加顿号） ==========
    def clean_answer(text: str) -> str:
        if not text:
            return ""
        # 过滤明显的占位符
        placeholder_patterns = [
            r'^答案\d+$', r'^实际答案\d+$', r'^填空答案$', r'^示例答案$',
            r'^学生答案$', r'^答案$', r'^未识别$'
        ]
        for pat in placeholder_patterns:
            if re.match(pat, text.strip()):
                logger.warning(f"检测到占位符文本，清空: {text}")
                return ""
        # 移除题号前缀（支持：数字加点、数字加顿号、带圈数字、括号数字）
        pattern = r'(?:^|\n)\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\(\d+\)|\d+[\.、])\s*'
        text = re.sub(pattern, '\n', text)
        text = re.sub(r'\n+', '\n', text).strip()
        return text

    cleaned_data = [clean_answer(ans) for ans in data]

    result = {}
    for i, q in enumerate(questions):
        order = q['question_order']
        result[order] = {"exists": True, "answer": cleaned_data[i] if i < len(cleaned_data) else ""}
    return result


# ==================== 第二次识别：纠错模型 ====================
def correct_answers_with_image(image_paths: List[str], original_answers: Dict[int, str], questions: List[dict]) -> Dict[int, str]:
    """使用多模态模型对OCR答案进行纠错，返回纠正后的答案字典"""
    if not image_paths:
        return {}

    num_questions = len(questions)
    answers_text = "\n".join([f"第{q['question_order']}题: {original_answers.get(q['question_order'], '')}" for q in questions])
    prompt = (
        f"以下是OCR工具从答题卡图片中识别出的学生答案，可能包含错误。请根据图片中实际的学生手写内容，纠正这些答案。\n"
        f"原始识别结果：\n{answers_text}\n"
        "请按题号顺序输出纠正后的答案，格式为JSON数组，例如：[\"纠正后的答案1\", \"纠正后的答案2\", ...]。\n"
        "如果原始答案正确，则保持不变；如果无法识别，输出空字符串。注意保留数学符号和公式（包括绝对值竖线）。不要输出其他内容。"
    )

    content = [{"text": prompt}]
    for path in image_paths:
        with open(path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
        mime_type = "image/jpeg" if not path.lower().endswith('.png') else "image/png"
        content.append({"image": f"data:{mime_type};base64,{img_base64}"})

    body = {
        "model": MM_MODEL_CONFIG["model"],
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"result_format": "message", "temperature": 0.1}
    }
    headers = {
        "Authorization": f"Bearer {MM_MODEL_CONFIG['api_key']}",
        "Content-Type": "application/json"
    }

    raw_result = ""
    for attempt in range(MM_MODEL_CONFIG["max_retries"]):
        try:
            resp = requests.post(MM_MODEL_CONFIG["api_url"], headers=headers, json=body, timeout=MM_MODEL_CONFIG["timeout"])
            resp.raise_for_status()
            result = resp.json()
            raw_result = result["output"]["choices"][0]["message"]["content"][0]["text"]
            logger.info(f"纠错模型返回: {raw_result}")
            break
        except Exception as e:
            if attempt == MM_MODEL_CONFIG["max_retries"] - 1:
                logger.error(f"纠错API调用最终失败: {e}")
                return {}
            logger.warning(f"纠错重试 {attempt+1}: {e}")

    if not raw_result:
        return {}

    cleaned = re.sub(r'^```json\s*', '', raw_result.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            match = re.search(r'\[.*\]', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = []
    except Exception as e:
        logger.error(f"纠错JSON解析失败: {e}, 原始内容: {raw_result}")
        data = []

    while len(data) < num_questions:
        data.append("")
    data = data[:num_questions]

    corrected = {}
    for i, q in enumerate(questions):
        corrected[q['question_order']] = data[i] if i < len(data) else ""
    return corrected


# ==================== 评分 ====================
def score_only(question: dict, student_answer: str) -> float:
    """返回百分制分数（0-100）"""
    if not student_answer or student_answer.strip() == "":
        logger.warning(f"题目 {question['id']} 学生答案为空，返回0分")
        return 0.0

    q_type = question.get('type', '主观题')
    reference = question.get('reference_answer', '')

    if q_type in ['选择题', '填空题', '判断题']:
        # ========== 修改点：保留数学符号（包括竖线） ==========
        def normalize(s):
            s = s.strip().lower()
            # 保留字母、数字、汉字、常用数学符号、竖线（绝对值）、方括号等
            s = re.sub(r'[^\w\u4e00-\u9fff\+\-\*/=<>≤≥≠√∑∫∂\|\[\]]', '', s)
            return s
        std_ref = normalize(reference)
        std_ans = normalize(student_answer)
        if std_ans == std_ref:
            return 100.0
        else:
            logger.info(f"客观题匹配失败: 参考'{std_ref}' vs 学生'{std_ans}'")
            return 0.0

    # 主观题：调用模型评分
    prompt = f"""你是一位阅卷教师。请根据以下信息对学生的答案进行评分：

题目：{question['content']}
参考答案：{reference}
评分标准：{question.get('scoring_rules', '根据答案准确性给分')}
学生答案：{student_answer}

请只返回一个0-100之间的数字分数，不要有其他文字。"""

    body = {
        "model": MM_MODEL_CONFIG["model"],
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {"result_format": "message", "temperature": 0.1}
    }
    headers = {
        "Authorization": f"Bearer {MM_MODEL_CONFIG['api_key']}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(MM_MODEL_CONFIG["api_url"], headers=headers, json=body, timeout=MM_MODEL_CONFIG["timeout"])
        resp.raise_for_status()
        result = resp.json()
        output_text = result["output"]["choices"][0]["message"]["content"][0]["text"]
        logger.info(f"评分模型返回: {output_text}")
        numbers = re.findall(r"\d+(?:\.\d+)?", output_text)
        if numbers:
            score = float(numbers[0])
            score = min(max(score, 0), 100)
            if score == 0.0 and student_answer.strip():
                logger.warning(f"题目 {question['id']} 模型返回0分但学生答案非空，使用默认分50")
                return 50.0
            return score
        else:
            match = re.search(r'"score":\s*(\d+(?:\.\d+)?)', output_text)
            if match:
                score = float(match.group(1))
                return min(max(score, 0), 100)
            logger.error(f"无法解析分数，返回默认分50")
            return 50.0
    except Exception as e:
        logger.error(f"评分调用失败: {e}")
        return 0.0


# ==================== 后台阅卷任务 ====================
async def process_grading(exam_id: int, job_id: int):
    logger.info(f"开始阅卷任务：exam_id={exam_id}, job_id={job_id}")
    try:
        with engine.connect() as conn:
            exam = conn.execute(
                text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise Exception(f"考试 {exam_id} 不存在")

            exam_total_score = conn.execute(
                text("SELECT total_score FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).scalar()

            students_result = conn.execute(
                text("""
                SELECT s.student_id, s.name
                FROM students s
                INNER JOIN exam_students es ON s.student_id = es.student_id
                WHERE es.exam_id = :exam_id
                """),
                {"exam_id": exam_id}
            )
            students = [dict(row._mapping) for row in students_result.fetchall()]
            total_students = len(students)

            conn.execute(
                text("UPDATE grading_jobs SET total_students = :total, status = 'processing' WHERE id = :job_id"),
                {"total": total_students, "job_id": job_id}
            )
            conn.commit()

            questions_result = conn.execute(
                text("""
                     SELECT q.id, q.type, q.content, q.reference_answer, q.scoring_rules, q.score as max_score, eq.question_order
                     FROM questions q
                     INNER JOIN exam_questions eq ON q.id = eq.question_id
                     WHERE eq.exam_id = :exam_id
                     ORDER BY eq.question_order
                     """),
                {"exam_id": exam_id}
            )
            questions = [dict(row._mapping) for row in questions_result.fetchall()]

            if not questions:
                logger.warning(f"考试 {exam_id} 没有题目")
                conn.execute(
                    text("UPDATE grading_jobs SET status = 'failed' WHERE id = :job_id"),
                    {"job_id": job_id}
                )
                conn.commit()
                return

        processed = 0
        for student in students:
            student_id = student["student_id"]
            logger.info(f"处理学生 {student_id} - {student['name']}")

            with engine.connect() as conn:
                images = conn.execute(
                    text("""
                    SELECT file_path
                    FROM answer_sheets
                    WHERE exam_id = :exam_id AND student_id = :student_id
                    ORDER BY page_order
                    """),
                    {"exam_id": exam_id, "student_id": student_id}
                ).fetchall()

            if not images:
                logger.warning(f"学生 {student_id} 无答题卡图片，跳过")
                processed += 1
                with engine.connect() as conn:
                    conn.execute(
                        text("UPDATE grading_jobs SET processed_students = :processed WHERE id = :job_id"),
                        {"processed": processed, "job_id": job_id}
                    )
                    conn.commit()
                continue

            original_paths = [row.file_path for row in images]
            processed_paths = [preprocess_image(p) for p in original_paths]

            ocr_result = ocr_only(processed_paths, questions)
            original_answers = {order: info["answer"] for order, info in ocr_result.items()}

            if all(len(ans) == 0 for ans in original_answers.values()):
                logger.warning("预处理后OCR结果为空，尝试使用原始图片重新识别...")
                ocr_result = ocr_only(original_paths, questions)
                original_answers = {order: info["answer"] for order, info in ocr_result.items()}

            need_correct = any(len(ans) < 2 for ans in original_answers.values())
            if need_correct:
                logger.info("检测到可能错误的答案，启动纠错模型...")
                corrected_answers = correct_answers_with_image(original_paths, original_answers, questions)
                for order, new_ans in corrected_answers.items():
                    if new_ans:
                        ocr_result[order]["answer"] = new_ans
                        logger.info(f"纠正题目 {order}: {original_answers[order]} -> {new_ans}")
            else:
                logger.info("OCR结果可信，跳过纠错步骤")

            for proc_path in processed_paths:
                if "_processed" in proc_path and os.path.exists(proc_path):
                    try:
                        os.remove(proc_path)
                    except:
                        pass

            total_score = 0.0
            for q in questions:
                qid = q["id"]
                order = q['question_order']
                student_answer = ocr_result.get(order, {}).get("answer", "")
                percent_score = score_only(q, student_answer)
                max_score = float(q.get("max_score", 100))
                actual_score = round((percent_score / 100.0) * max_score)
                actual_score = min(actual_score, max_score)
                total_score += actual_score

                with engine.connect() as conn:
                    conn.execute(
                        text("""
                        INSERT INTO student_scores (exam_id, student_id, question_id, score, student_answer)
                        VALUES (:exam_id, :student_id, :question_id, :score, :student_answer)
                        ON DUPLICATE KEY UPDATE
                        score = VALUES(score), student_answer = VALUES(student_answer), updated_at = CURRENT_TIMESTAMP
                        """),
                        {
                            "exam_id": exam_id,
                            "student_id": student_id,
                            "question_id": qid,
                            "score": actual_score,
                            "student_answer": student_answer
                        }
                    )
                    conn.commit()

            if exam_total_score is not None and total_score > exam_total_score:
                logger.warning(f"学生 {student_id} ({student['name']}) 总分 {total_score} 超过考试总分 {exam_total_score}")

            processed += 1
            with engine.connect() as conn:
                conn.execute(
                    text("UPDATE grading_jobs SET processed_students = :processed WHERE id = :job_id"),
                    {"processed": processed, "job_id": job_id}
                )
                conn.commit()

        with engine.connect() as conn:
            conn.execute(
                text("UPDATE grading_jobs SET status = 'completed' WHERE id = :job_id"),
                {"job_id": job_id}
            )
            conn.commit()
        logger.info(f"阅卷任务完成：exam_id={exam_id}, job_id={job_id}")

    except Exception as e:
        logger.exception(f"阅卷任务失败：exam_id={exam_id}, job_id={job_id}")
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE grading_jobs SET status = 'failed' WHERE id = :job_id"),
                {"job_id": job_id}
            )
            conn.commit()


# ==================== API 端点 ====================
@router.post("/api/exams/{exam_id}/grade")
async def start_grading(exam_id: int):
    try:
        with engine.connect() as conn:
            exam = conn.execute(
                text("SELECT exam_id FROM exams WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).fetchone()
            if not exam:
                raise HTTPException(status_code=404, detail=f"考试 {exam_id} 不存在")

            existing_job = conn.execute(
                text("SELECT id FROM grading_jobs WHERE exam_id = :exam_id AND status IN ('pending', 'processing')"),
                {"exam_id": exam_id}
            ).fetchone()
            if existing_job:
                raise HTTPException(status_code=400, detail="该考试已有阅卷任务正在进行中")

            result = conn.execute(
                text("INSERT INTO grading_jobs (exam_id, status) VALUES (:exam_id, 'pending')"),
                {"exam_id": exam_id}
            )
            conn.commit()
            job_id = result.lastrowid

        asyncio.create_task(process_grading(exam_id, job_id))

        return {
            "code": 1,
            "msg": "阅卷任务已启动",
            "data": {"job_id": job_id, "exam_id": exam_id, "status": "pending"}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动阅卷失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动阅卷失败: {str(e)}")


@router.get("/api/grading/jobs/{job_id}")
async def get_grading_job_status(job_id: int):
    try:
        with engine.connect() as conn:
            job = conn.execute(
                text("""
                SELECT id, exam_id, status, total_students, processed_students, created_at, updated_at
                FROM grading_jobs
                WHERE id = :job_id
                """),
                {"job_id": job_id}
            ).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")

            return {
                "code": 1,
                "msg": "获取成功",
                "data": {
                    "job_id": job.id,
                    "exam_id": job.exam_id,
                    "status": job.status,
                    "total_students": job.total_students,
                    "processed_students": job.processed_students,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "updated_at": job.updated_at.isoformat() if job.updated_at else None
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")


@router.get("/api/exams/{exam_id}/grading-progress")
def get_grading_progress(exam_id: int):
    try:
        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM exam_students WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).scalar()
            graded = conn.execute(
                text("SELECT COUNT(DISTINCT student_id) FROM student_scores WHERE exam_id = :exam_id"),
                {"exam_id": exam_id}
            ).scalar()
        return {"code": 1, "data": {"total": total, "graded": graded}}
    except Exception as e:
        logger.error(f"获取阅卷进度失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))