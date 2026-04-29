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


# ==================== OCR 识别函数 ====================
def ocr_only(image_paths: List[str], questions: List[dict]) -> Dict[int, dict]:
    """
    第一次识别：使用多模态模型提取学生手写答案，返回 { order: {"exists": True, "answer": str} }
    """
    if not image_paths:
        return {}

    num_questions = len(questions)
    prompt = (
        "你是一个严格的光学字符识别（OCR）工具。\n"
        f"本次发送了 {len(image_paths)} 张答题卡图片，请按顺序阅读所有图片，忽略印刷体题目描述、表格、得分栏等无关内容。\n"
        "请识别每个小题的学生答案。\n"
        f"一共有 {num_questions} 道小题，题号从 1 到 {num_questions}。\n"
        "小题的题号是普通数字加标点，例如“1.”、“2.”、“3.”。每个这样的题号代表一道独立的小题。\n"
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
        "输出一个JSON对象，键为题号（字符串），值为对应的学生答案。例如：{\"1\": \"答案1\", \"2\": \"答案2\\n第二分点\", \"3\": \"\"}\n"
        "同一道小题的多个分点（如带圈数字①、②、括号数字(1)、(2)等）必须合并为一个字符串，使用换行符分隔。\n"
        "输出的答案中不要包含题号本身（例如不要输出“2、负实轴单位圆”，只需要输出“负实轴单位圆”）。\n"
        "如果某道小题没有答案或无法识别，则对应键的值为空字符串。\n"
        "特别重要：对于**选择题**，你必须为每个题号单独输出一个键值对，严禁将多个选择题的答案合并到一个键中！\n"
        "例如，如果图片中有四道选择题，答案分别是 'A', 'B', 'C', 'D'，你必须输出："
        "{\"1\": \"A\", \"2\": \"B\", \"3\": \"C\", \"4\": \"D\"}，而不是 {\"1\": \"A B C D\"} 或 {\"1\": \"A2.B3.C4.D\"}。\n"
        "每个题号只能对应一个答案，不能把一个题号的答案字符串中包含其他题号的标识。\n"
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

    # 解析 JSON 对象（优先），若得到数组则降级按顺序映射
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            logger.warning("模型返回数组，将按顺序映射到题号")
            data = {str(i+1): val for i, val in enumerate(data)}
        elif not isinstance(data, dict):
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = {}
    except Exception as e:
        logger.error(f"OCR JSON解析失败: {e}, 原始内容: {raw_result}")
        data = {}

    def clean_answer(text: str) -> str:
        if not text:
            return ""
        placeholder_patterns = [
            r'^答案\d+$', r'^实际答案\d+$', r'^填空答案$', r'^示例答案$',
            r'^学生答案$', r'^答案$', r'^未识别$'
        ]
        for pat in placeholder_patterns:
            if re.match(pat, text.strip()):
                return ""
        return text

    result = {}
    for q in questions:
        order = q['question_order']
        key = str(order)
        answer = data.get(key, "")
        result[order] = {"exists": True, "answer": clean_answer(answer)}
    return result


# ==================== 纠错模型 ====================
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
        def normalize(s):
            s = s.strip().lower()
            s = re.sub(r'[^\w\u4e00-\u9fff\u0370-\u03ff\+\-\*/=<>≤≥≠√∑∫∂\|\[\]]', '', s)
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


# ==================== 辅助处理函数 ====================
def merge_subjective_answers(questions: List[dict], answers: Dict[int, str]) -> Dict[int, str]:
    """合并连续的非选择题、非判断题的主观题答案"""
    if not questions:
        return answers.copy()

    merged = {}
    i = 0
    n = len(questions)
    while i < n:
        q = questions[i]
        order = q['question_order']
        q_type = q.get('type', 'essay')
        logger.info(f"处理题目 {order}: type={q_type}")

        if q_type in ['choice', 'judge', 'fill_blank']:
            merged[order] = answers.get(order, "")
            i += 1
            continue

        block_orders = []
        j = i
        while j < n and questions[j].get('type', 'essay') not in ['choice', 'judge']:
            block_orders.append(questions[j]['question_order'])
            j += 1

        if block_orders:
            ans_texts = [answers.get(o, "") for o in block_orders]
            combined = "\n".join([t for t in ans_texts if t.strip()])
            first = block_orders[0]
            merged[first] = combined
            for other in block_orders[1:]:
                merged[other] = ""
        else:
            merged[order] = answers.get(order, "")
        i = j

    return merged


def reorder_answers_by_reference(questions: List[dict], answers: Dict[int, str]) -> Dict[int, str]:
    """根据参考答案重新分配答案顺序（主要用于填空题和选择题）"""
    new_answers = answers.copy()
    target_orders = []
    ref_map = {}
    for q in questions:
        q_type = q.get('type', '')
        if q_type in ['填空题', '选择题', 'fill_blank', 'choice']:
            order = q['question_order']
            target_orders.append(order)
            ref_map[order] = q.get('reference_answer', '').strip()

    if not target_orders:
        return new_answers

    candidate_answers = [answers.get(o, '').strip() for o in target_orders]
    used_indices = set()

    for order in target_orders:
        ref = ref_map.get(order, '')
        if not ref:
            continue

        best_match = None
        best_idx = -1
        for idx, cand in enumerate(candidate_answers):
            if idx in used_indices:
                continue
            if cand == ref:
                best_match = cand
                best_idx = idx
                break
            cand_clean = re.sub(r'[^\w\u4e00-\u9fff]', '', cand)
            ref_clean = re.sub(r'[^\w\u4e00-\u9fff]', '', ref)
            if cand_clean == ref_clean:
                best_match = cand
                best_idx = idx
                break
            if ref.isdigit() and cand.isdigit():
                best_match = cand
                best_idx = idx
                break

        if best_match is not None:
            new_answers[order] = best_match
            used_indices.add(best_idx)

    return new_answers


def split_combined_choices(questions: List[dict], answers: Dict[int, str]) -> Dict[int, str]:
    """将合并的选择题答案拆分为独立题号的答案"""
    new_answers = answers.copy()
    choice_orders = [q['question_order'] for q in questions if q.get('type') in ['选择题', 'choice']]
    for q in questions:
        if q.get('type') not in ['选择题', 'choice']:
            continue
        order = q['question_order']
        text = answers.get(order, '')
        if not text:
            continue

        # 1. 标准模式：数字+字母
        pattern = r'(\d+)[\.、，,\s]*([A-Za-z])'
        matches = list(re.finditer(pattern, text))
        if len(matches) > 1:
            for match in matches:
                num = int(match.group(1))
                letter = match.group(2).upper()
                if num in choice_orders:
                    new_answers[num] = letter
            continue

        # 2. 反向模式：字母+数字
        pattern2 = r'([A-Za-z])(\d+)'
        matches2 = list(re.finditer(pattern2, text))
        if matches2:
            for match in matches2:
                letter = match.group(1).upper()
                num = int(match.group(2))
                if num in choice_orders:
                    new_answers[num] = letter
            continue

        # 3. 纯字母点分隔
        if re.match(r'^[A-Za-z\.]+$', text):
            parts = text.split('.')
            for idx, part in enumerate(parts):
                if part and idx < len(choice_orders):
                    new_answers[choice_orders[idx]] = part.upper()
            continue

        # 4. 特定混合处理
        letters = re.findall(r'([A-Za-z])', text)
        numbers = re.findall(r'(\d+)', text)
        if letters and numbers:
            for num_str, letter in zip(numbers, letters):
                num = int(num_str)
                if num in choice_orders:
                    new_answers[num] = letter.upper()
            if len(letters) > len(numbers) and choice_orders:
                new_answers[choice_orders[0]] = letters[0].upper()
    return new_answers


def split_combined_fillblanks(questions: List[dict], answers: Dict[int, str]) -> Dict[int, str]:
    """将合并的填空题答案拆分为独立题号的答案"""
    new_answers = answers.copy()
    fill_orders = [q['question_order'] for q in questions if q.get('type') in ['填空题', 'fill_blank']]
    if not fill_orders:
        return new_answers

    for order in fill_orders:
        text = answers.get(order, '')
        if not text.strip():
            continue

        pattern = r'(\d+)[\.、:：）)\s]+([^0-9]+?(?=\s*\d+[\.、:：）)])|$)'
        matches = list(re.finditer(pattern, text, re.DOTALL))
        if len(matches) >= 2:
            for match in matches:
                num = int(match.group(1))
                ans = match.group(2).strip()
                if num in fill_orders:
                    new_answers[num] = ans
    return new_answers


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

            # 获取题目列表
            questions_result = conn.execute(
                text("""
                     SELECT q.id, q.type, q.content, q.reference_answer, q.scoring_rules,
                            q.score as max_score, eq.question_order, q.parent_id
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

            # 修改点：优先使用预处理后的图片
            with engine.connect() as conn:
                images = conn.execute(
                    text("""
                    SELECT COALESCE(processed_file_path, file_path) as file_path
                    FROM answer_sheets
                    WHERE exam_id = :exam_id AND student_id = :student_id
                    ORDER BY page_order
                    """),
                    {"exam_id": exam_id, "student_id": student_id}
                ).fetchall()

            logger.info(f"学生 {student_id} - {student['name']} 共有 {len(images)} 张答题卡图片")

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

            # 直接使用已有的图片路径（可能是预处理后的图片）
            image_paths = [row.file_path for row in images]

            # 第一次 OCR 识别
            ocr_result = ocr_only(image_paths, questions)
            if ocr_result is None:
                ocr_result = {}
                logger.warning("ocr_only 返回 None，使用空字典")
            original_answers = {order: info["answer"] for order, info in ocr_result.items()}

            # 如果全部为空，尝试使用原始图片再次识别（此逻辑保留）
            if all(len(ans) == 0 for ans in original_answers.values()):
                logger.warning("预处理图片OCR结果为空，尝试使用原始图片重新识别...")
                with engine.connect() as conn:
                    fallback_images = conn.execute(
                        text("""
                        SELECT file_path
                        FROM answer_sheets
                        WHERE exam_id = :exam_id AND student_id = :student_id
                        ORDER BY page_order
                        """),
                        {"exam_id": exam_id, "student_id": student_id}
                    ).fetchall()
                fallback_paths = [row.file_path for row in fallback_images]
                ocr_result = ocr_only(fallback_paths, questions)
                if ocr_result is None:
                    ocr_result = {}
                    logger.warning("第二次 ocr_only 返回 None")
                original_answers = {order: info["answer"] for order, info in ocr_result.items()}

            logger.info("已禁用纠错模型，直接使用OCR结果")

            # 拆分选择题答案
            split_answers = split_combined_choices(questions, {order: info["answer"] for order, info in ocr_result.items()})
            for order, new_ans in split_answers.items():
                if new_ans:
                    ocr_result[order]["answer"] = new_ans
                    logger.info(f"拆分选择题 {order}: 新答案 = {new_ans}")

            # 拆分填空题答案
            split_fill_answers = split_combined_fillblanks(questions, {order: info["answer"] for order, info in ocr_result.items()})
            for order, new_ans in split_fill_answers.items():
                if new_ans != ocr_result[order]["answer"]:
                    ocr_result[order]["answer"] = new_ans
                    logger.info(f"拆分填空题 {order}: 新答案 = {new_ans}")

            # 根据参考答案重排序
            reordered = reorder_answers_by_reference(questions,
                                                     {order: info["answer"] for order, info in ocr_result.items()})
            for order, ans in reordered.items():
                ocr_result[order]["answer"] = ans

            # 评分
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