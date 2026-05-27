import asyncio
import logging
from typing import List, Optional
import httpx
from sqlalchemy.orm import Session

from core.config import settings
from database.models import Course, CourseDetail, CourseEmbedding

logger = logging.getLogger(__name__)

import time

class APIRateLimiter:
    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm if rpm > 0 else 0
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()

    async def wait_if_needed(self):
        if self.interval <= 0:
            return
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
                logger.info(f"Rate limiter: sleeping {sleep_time:.2f}s to respect {60.0/self.interval:.1f} RPM limit")
                await asyncio.sleep(sleep_time)
            self.last_request_time = time.time()

llm_rate_limiter = APIRateLimiter(rpm=settings.gemini_llm_rpm_limit)
embedding_rate_limiter = APIRateLimiter(rpm=settings.gemini_embedding_rpm_limit)



# Constants for Gemini API
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
EMBEDDING_API_URL = "https://generativelanguage.googleapis.com/v1/models/{model}:embedContent?key={api_key}"


SYSTEM_INSTRUCTION = """你是一個大學課程資訊重組專家。請將原始課程資料簡化為高密度的搜尋索引與核心摘要。
請嚴格依據以下結構進行重組，直接輸出內容，絕對不得包含任何 markdown 標籤（如 ```）、問候語、前言、後記、分析過程、思考草稿（如 Drafting）或任何多餘說明。

課程核心：[一句話簡述這門課在學什麼，不超過 60 字。若資料不足，請以課程名稱與系所合理推測並註明「(推測)」]
主題標籤：[列出 5-8 個核心領域、技術、主題或工具之關鍵字，以半形逗號分隔]
學習目標：[以 2-3 個極短的條列句指出核心能力與學習成效，每點不超過 30 字]
評分特徵：[僅列出評分項目與比例，例如「出席與討論(30%)、實作紀錄(40%)、期末發表(30%)」，若無資料則寫「無詳細說明」]"""

USER_TEMPLATE = """【原始課程資料】
課程名稱：{title}
系所名稱：{department_name}
課程目標（原始）：{objectives}
授課內容（原始）：{content}
授課方式（原始）：{teaching_method}
評量配分（原始）：{grading_policy}"""


def build_prompt(course: Course, detail: CourseDetail) -> str:
    """
    Constructs the user prompt for the LLM using course and detail information.
    Handles None values gracefully.
    """
    return USER_TEMPLATE.format(
        title=course.title or "無",
        department_name=course.department_name or "無",
        objectives=detail.objectives or "無",
        content=detail.content or "無",
        teaching_method=detail.teaching_method or "無",
        grading_policy=detail.grading_policy or "無"
    )


async def generate_organized_description_api(
    client: httpx.AsyncClient,
    prompt: str,
    semaphore: asyncio.Semaphore
) -> Optional[str]:
    """
    Calls Gemini LLM API to generate normalized description.
    Includes concurrency limits and exponential backoff retry.
    """
    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY is not set. Skipping LLM generation.")
        return None

    url = GEMINI_API_URL.format(model=settings.gemini_llm_model, api_key=settings.gemini_api_key)
    body = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION}]
        },
        "generationConfig": {
            "temperature": 0.1
        }
    }

    async with semaphore:
        for attempt in range(3):
            try:
                await llm_rate_limiter.wait_if_needed()
                response = await client.post(url, json=body, timeout=120.0)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            # 1. Filter out parts that are explicitly marked as thoughts
                            text_parts = []
                            for part in parts:
                                if part.get("thought") is True:
                                    continue
                                text = part.get("text")
                                if text:
                                    text_parts.append(text)
                            
                            full_text = "".join(text_parts).strip() if text_parts else parts[0].get("text", "").strip()
                            
                            # 2. Extract final polish/output if the model embedded its thinking process in the text
                            import re
                            markers = [
                                r"\*\s*\*\s*Final\s*Polish\s*:\s*\*",
                                r"\*\s*Final\s*Polish\s*:\s*\*?",
                                r"Final\s*Polish\s*:",
                                r"\*\s*\*\s*Final\s*Output\s*:\s*\*",
                                r"Final\s*Output\s*:",
                            ]
                            latest_pos = -1
                            for marker in markers:
                                for m in re.finditer(marker, full_text, re.IGNORECASE):
                                    if m.end() > latest_pos:
                                        latest_pos = m.end()
                                        
                            if latest_pos != -1:
                                final_part = full_text[latest_pos:].strip()
                                if final_part:
                                    return final_part
                                    
                            return full_text
                    logger.warning(f"Unexpected response structure from Gemini LLM: {data}")
                    return None
                elif response.status_code in (429, 500, 502, 503, 504):
                    wait_time = 2.0 ** attempt
                    logger.warning(f"Transient error ({response.status_code}) during LLM generation. Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Gemini LLM API error: HTTP {response.status_code} - {response.text}")
                    return None
            except Exception as e:
                logger.warning(f"Exception during LLM generation (attempt {attempt + 1}): {repr(e)}")
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None


async def generate_embedding_api(
    client: httpx.AsyncClient,
    text: str,
    semaphore: asyncio.Semaphore
) -> Optional[List[float]]:
    """
    Calls Gemini Embedding API to generate a 768-dimension vector.
    Includes concurrency limits and exponential backoff retry.
    """
    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY is not set. Skipping embedding generation.")
        return None

    url = EMBEDDING_API_URL.format(model=settings.gemini_embedding_model, api_key=settings.gemini_api_key)
    body = {
        "content": {
            "parts": [{"text": text}]
        },
        "outputDimensionality": 768
    }


    async with semaphore:
        for attempt in range(3):
            try:
                await embedding_rate_limiter.wait_if_needed()
                response = await client.post(url, json=body, timeout=25.0)
                if response.status_code == 200:
                    data = response.json()
                    embedding_values = data.get("embedding", {}).get("values")
                    if embedding_values:
                        return embedding_values
                    logger.warning(f"Unexpected response structure from Gemini Embedding: {data}")
                    return None
                elif response.status_code in (429, 500, 502, 503, 504):
                    wait_time = 2.0 ** attempt
                    logger.warning(f"Transient error ({response.status_code}) during embedding. Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Gemini Embedding API error: HTTP {response.status_code} - {response.text}")
                    return None
            except Exception as e:
                logger.warning(f"Exception during embedding generation (attempt {attempt + 1}): {repr(e)}")
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None


async def normalize_single_course(
    client: httpx.AsyncClient,
    course: Course,
    detail: CourseDetail,
    semaphore: asyncio.Semaphore
) -> Optional[dict]:
    """
    Phase 1: Calls Gemma 4 MoE LLM to generate normalized three-section description,
    safely parses teacher details, builds a metadata header, and returns the combined text.
    """
    prompt = build_prompt(course, detail)
    
    organized_desc = await generate_organized_description_api(client, prompt, semaphore)
    if not organized_desc:
        logger.warning(f"Failed to generate organized description for course: {course.serial_no}")
        return None
        
    # Safely parse teachers list for metadata header
    import json
    teachers_str = "無"
    if course.teachers:
        try:
            parsed = json.loads(course.teachers)
            if isinstance(parsed, list):
                teachers_str = ", ".join(parsed)
            else:
                teachers_str = str(course.teachers)
        except Exception:
            teachers_str = str(course.teachers)

    # Prepend basic info metadata header to optimize RAG search for course name, number, and teachers
    metadata_header = (
        f"課程基本資訊：\n"
        f"- 課號：{course.class_no}\n"
        f"- 課程名稱：{course.title}\n"
        f"- 授課教師：{teachers_str}\n"
        f"- 開課單位：{course.college_name or '無'} - {course.department_name or '無'}\n\n"
    )
    final_desc = metadata_header + organized_desc
    
    return {
        "serial_no": course.serial_no,
        "organized_description": final_desc
    }


async def sync_course_normalizations(db: Session, force_all: bool = False):
    """
    Loops through courses needing LLM preprocessing, runs the LLM,
    and saves the raw normalized text descriptions in the database (with embedding=None).
    """
    logger.info("Starting course RAG normalization pre-processing...")

    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set. RAG normalization is disabled.")
        return

    # 1. Fetch courses that have course details
    courses = db.query(Course).join(CourseDetail).all()
    if not courses:
        logger.info("No courses with details found in database to normalize.")
        return

    # 2. Determine which courses need LLM normalization
    existing_serials = set()
    if not force_all:
        existing_serials = {row.serial_no for row in db.query(CourseEmbedding.serial_no).all()}

    courses_to_process = [c for c in courses if c.serial_no not in existing_serials]
    logger.info(f"Total courses: {len(courses)}. Already normalized: {len(existing_serials)}. Needs LLM: {len(courses_to_process)}.")

    # Cap LLM runs to respect daily Gemma RPD limits (e.g. max 900)
    if settings.gemini_max_embeddings_per_run > 0 and len(courses_to_process) > settings.gemini_max_embeddings_per_run:
        courses_to_process = courses_to_process[:settings.gemini_max_embeddings_per_run]
        logger.info(f"Capping normalization to {settings.gemini_max_embeddings_per_run} courses in this run to respect daily RPD limits.")

    if not courses_to_process:
        logger.info("All course descriptions are up-to-date.")
        return

    semaphore = asyncio.Semaphore(5)

    async with httpx.AsyncClient(verify=False, timeout=50.0) as client:
        batch_size = 10
        for i in range(0, len(courses_to_process), batch_size):
            batch = courses_to_process[i : i + batch_size]
            logger.info(f"Normalizing batch {i // batch_size + 1}/{(len(courses_to_process) - 1) // batch_size + 1}...")

            tasks = [normalize_single_course(client, c, c.detail, semaphore) for c in batch]
            results = await asyncio.gather(*tasks)

            added_count = 0
            for res in results:
                if not res:
                    continue
                serial_no = res["serial_no"]
                db_emb = db.query(CourseEmbedding).filter(CourseEmbedding.serial_no == serial_no).first()
                if not db_emb:
                    db_emb = CourseEmbedding(
                        serial_no=serial_no,
                        organized_description=res["organized_description"],
                        embedding=None
                    )
                    db.add(db_emb)
                else:
                    db_emb.organized_description = res["organized_description"]
                added_count += 1

            try:
                db.commit()
                logger.info(f"Saved {added_count} course normalizations in this batch.")
            except Exception as e:
                db.rollback()
                logger.error(f"Error saving batch course normalizations: {e}")
                
            await asyncio.sleep(1.0)

    logger.info("Course RAG normalization complete.")


async def sync_course_embeddings(db: Session, force_all: bool = False):
    """
    Loops through CourseEmbedding records lacking embedding vectors (or all if force_all=True),
    calls the Gemini Embedding API, and saves the vectors in the database.
    """
    logger.info("Starting course RAG embedding generation...")

    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set. RAG embedding generation is disabled.")
        return

    # 1. Fetch records needing embeddings
    query = db.query(CourseEmbedding)
    if not force_all:
        query = query.filter(CourseEmbedding.embedding.is_(None))
    
    embeddings_to_generate = query.all()
    logger.info(f"Total stored normalizations needing vector embeddings: {len(embeddings_to_generate)}.")

    # Cap Embedding runs to respect daily RPD limits (e.g. max 900)
    if settings.gemini_max_embeddings_per_run > 0 and len(embeddings_to_generate) > settings.gemini_max_embeddings_per_run:
        embeddings_to_generate = embeddings_to_generate[:settings.gemini_max_embeddings_per_run]
        logger.info(f"Capping embedding to {settings.gemini_max_embeddings_per_run} courses in this run to respect daily RPD limits.")

    if not embeddings_to_generate:
        logger.info("All course vectors are up-to-date.")
        return

    semaphore = asyncio.Semaphore(5)

    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        batch_size = 20  # Embeddings are fast, batch size can be slightly larger
        for i in range(0, len(embeddings_to_generate), batch_size):
            batch = embeddings_to_generate[i : i + batch_size]
            logger.info(f"Embedding batch {i // batch_size + 1}/{(len(embeddings_to_generate) - 1) // batch_size + 1}...")

            tasks = [
                generate_embedding_api(client, emb_rec.organized_description, semaphore)
                for emb_rec in batch
            ]
            results = await asyncio.gather(*tasks)

            added_count = 0
            for emb_rec, vector in zip(batch, results):
                if not vector:
                    continue
                emb_rec.embedding = vector
                added_count += 1

            try:
                db.commit()
                logger.info(f"Saved {added_count} course vector embeddings in this batch.")
            except Exception as e:
                db.rollback()
                logger.error(f"Error saving batch course vector embeddings: {e}")
                
            await asyncio.sleep(0.5)

    logger.info("Course RAG embedding generation complete.")

