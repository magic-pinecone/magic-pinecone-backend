import asyncio
import logging
from typing import List, Optional
import httpx
from sqlalchemy.orm import Session

from core.config import settings
from database.db_connect import db_session
from database.models import User, UserCourse, Course, CourseEmbedding, UserDocument, UserDocumentChunk
from internal.rag_preprocessor import generate_embedding_api

logger = logging.getLogger(__name__)


def text_splitter(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Split text into chunks of chunk_size characters with chunk_overlap characters overlap.
    """
    chunks = []
    if not text:
        return chunks
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        # Move start by step
        start += chunk_size - chunk_overlap
    return chunks


async def background_vector_pipeline(doc_id: int, raw_text: str, user_id: str):
    """
    Background worker task to split document text, generate embeddings using the Gemini API,
    and save chunks to pgvector database.
    """
    logger.info(f"Background indexing started for document ID {doc_id} (user: {user_id}).")
    chunks = text_splitter(raw_text, chunk_size=500, chunk_overlap=50)
    
    if not chunks:
        with db_session() as db:
            db.query(UserDocument).filter(UserDocument.id == doc_id).update({"status": "ready"})
            db.commit()
        return

    semaphore = asyncio.Semaphore(5)
    
    # 1. Generate embeddings using Gemini API
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [generate_embedding_api(client, chunk, semaphore) for chunk in chunks]
        embeddings = await asyncio.gather(*tasks)

    # 2. Write to db
    with db_session() as db:
        doc = db.query(UserDocument).filter(UserDocument.id == doc_id).first()
        if not doc:
            logger.error(f"Document ID {doc_id} not found in database during background index.")
            return

        try:
            # Delete any existing chunks just in case
            db.query(UserDocumentChunk).filter(UserDocumentChunk.doc_id == doc_id).delete()

            for chunk, emb in zip(chunks, embeddings):
                chunk_rec = UserDocumentChunk(
                    doc_id=doc_id,
                    user_id=user_id,
                    content=chunk,
                    embedding=emb
                )
                db.add(chunk_rec)
            
            doc.status = "ready"
            db.commit()
            logger.info(f"Background indexing completed successfully for document ID {doc_id}.")
        except Exception as e:
            db.rollback()
            doc.status = "error"
            db.commit()
            logger.error(f"Error in background_vector_pipeline for document ID {doc_id}: {e}")


async def classify_intent(user_query: str) -> str:
    """
    Classifies the user query intent to route the request:
    - 'A': Structured course schedule queries.
    - 'B': Semantic personal document queries.
    - 'C': Hybrid course/career recommendation and general queries.
    """
    q = user_query.lower()
    
    # 1. Instant regex-based matching for performance
    if any(k in q for k in ["課表", "下午有什麼課", "修了什麼課", "我的課表", "下午的課", "早上的課", "今天的課", "修課清單"]):
        return "A"
    
    if any(k in q for k in ["考古題", "筆記", "講義", "上傳的文件", "文檔", "我的講義", "上傳的考古題"]):
        return "B"
        
    if not settings.gemini_api_key:
        return "C"

    # 2. LLM-based classification fallback
    prompt = (
        "請根據使用者的提問，將其意圖分類為以下三類之一：\n"
        "A: 查詢個人課表、修課清單或當天/下午上課行程 (例如：『我下午有什麼課？』、『我這學期修什麼課？』)。\n"
        "B: 查詢上傳的個人文件、考古題、筆記內容 (例如：『通訊原理考古題寫了什麼？』、『幫我查我上傳的筆記』)。\n"
        "C: 詢問課程推薦、專題方向、職涯建議、系所資訊等混合或開放式問題 (例如：『幫我推薦通訊系專題方向』、『適合大二的選修課有哪些』)。\n\n"
        f"使用者提問：\"{user_query}\"\n\n"
        "請僅輸出一個字母 (A, B, 或 C)，不要包含任何其他文字、標點符號或 markdown。"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_llm_model}:generateContent?key={settings.gemini_api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body)
            if response.status_code == 200:
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
                if text in ["A", "B", "C"]:
                    logger.info(f"LLM routed query to Intent '{text}'")
                    return text
    except Exception as e:
        logger.error(f"Error classifying intent via LLM: {e}")
        
    return "C"


async def build_chat_context(db: Session, user: User, user_query: str, intent: str) -> str:
    """
    Gathers academic and vector context based on user intent and student profile.
    """
    profile_parts = [
        f"姓名: {user.chinese_name or user.english_name or '學生'}",
        f"學系/單位: {user.department or '未註冊'}",
        f"學制: {user.study_system or '學生'}",
        f"身分/角色: {user.role or 'student'}"
    ]
    profile_str = "、".join(profile_parts)

    context = f"【使用者基本背景】: {profile_str}\n"

    # Intent A: Structured Course Schedule query
    if intent == "A":
        user_courses = db.query(UserCourse).filter(UserCourse.user_id == user.id).all()
        if user_courses:
            schedule_list = []
            for uc in user_courses:
                course = uc.course
                if course:
                    teachers_str = "、".join(course.teachers) if course.teachers else "無"
                    times_str = "、".join(course.class_times) if course.class_times else "無"
                    schedule_list.append(
                        f"- 課程: {course.title} (課號: {course.class_no}, 流水號: {course.serial_no})，學分: {course.credit}，老師: {teachers_str}，時間: {times_str}"
                    )
            schedule_str = "\n".join(schedule_list)
            context += f"【目前選課/課表】:\n{schedule_str}\n"
        else:
            context += "【目前選課/課表】: 學生目前無選課紀錄。\n"

    # Intent B: Semantic Document Search
    elif intent == "B":
        if not settings.gemini_api_key:
            context += "【警告】: 向量庫搜尋不可用，因為 API Key 未設定。\n"
            return context

        semaphore = asyncio.Semaphore(1)
        async with httpx.AsyncClient() as client:
            query_vector = await generate_embedding_api(client, user_query, semaphore)

        if query_vector:
            # Query similarities in user's documents
            similar_chunks = db.query(
                UserDocumentChunk.content,
                (1.0 - UserDocumentChunk.embedding.cosine_distance(query_vector)).label("similarity")
            ).filter(
                UserDocumentChunk.user_id == user.id,
                UserDocumentChunk.embedding.is_not(None)
            ).order_by(
                UserDocumentChunk.embedding.cosine_distance(query_vector)
            ).limit(5).all()

            if similar_chunks:
                chunk_contents = [f"- {c.content} (相似度: {c.similarity:.4f})" for c in similar_chunks]
                context += "【相關上傳文件內容分段】:\n" + "\n".join(chunk_contents) + "\n"
            else:
                context += "【相關上傳文件內容分段】: 找不到相關文件段落，可能使用者尚未上傳文件或內容無關。\n"
        else:
            context += "【系統提示】: 無法產生查詢向量。\n"

    # Intent C: Hybrid / Recommendation Queries
    else:
        # 1. Fetch user's enrolled courses to know what they are taking
        user_courses = db.query(UserCourse).filter(UserCourse.user_id == user.id).all()
        if user_courses:
            schedule_list = [f"- {uc.course.title}" for uc in user_courses if uc.course]
            context += "【目前已選修課程】:\n" + "\n".join(schedule_list) + "\n"

        # 2. Semantic search in school's course database catalog (pgvector)
        if settings.gemini_api_key:
            semaphore = asyncio.Semaphore(1)
            async with httpx.AsyncClient() as client:
                query_vector = await generate_embedding_api(client, user_query, semaphore)

            if query_vector:
                # Similarity search in Course Catalog embeddings
                catalog_courses = db.query(
                    Course,
                    CourseEmbedding.organized_description,
                    (1.0 - CourseEmbedding.embedding.cosine_distance(query_vector)).label("similarity")
                ).join(
                    CourseEmbedding, Course.serial_no == CourseEmbedding.serial_no
                ).filter(
                    CourseEmbedding.embedding.is_not(None)
                ).order_by(
                    CourseEmbedding.embedding.cosine_distance(query_vector)
                ).limit(5).all()

                if catalog_courses:
                    course_details = []
                    for course, desc, sim in catalog_courses:
                        teachers = course.teachers if course.teachers else "[]"
                        course_details.append(
                            f"- {course.title} ({course.class_no}): {desc[:200]}... (相似度: {sim:.4f})"
                        )
                    context += "【相關開課資訊】:\n" + "\n".join(course_details) + "\n"
                
                # Fetch relevant personal documents to combine
                personal_chunks = db.query(
                    UserDocumentChunk.content,
                    (1.0 - UserDocumentChunk.embedding.cosine_distance(query_vector)).label("similarity")
                ).filter(
                    UserDocumentChunk.user_id == user.id,
                    UserDocumentChunk.embedding.is_not(None)
                ).order_by(
                    UserDocumentChunk.embedding.cosine_distance(query_vector)
                ).limit(3).all()

                if personal_chunks:
                    personal_strs = [f"- {pc.content} (相似度: {pc.similarity:.4f})" for pc in personal_chunks]
                    context += "【個人資料與文件匹配】:\n" + "\n".join(personal_strs) + "\n"

    return context


async def stream_gemini_content(system_prompt: str, user_query: str, chat_history: List[dict]):
    """
    Streams a completion from the Gemini LLM API as Server-Sent Events (SSE).
    """
    if not settings.gemini_api_key:
        yield "系統偵測到未設定 GEMINI_API_KEY。請在環境變數中設定您的金鑰。"
        return

    contents = []
    # Convert chat history to Gemini structure (user/model roles)
    for msg in chat_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}]
        })
    
    # Append latest user query
    contents.append({
        "role": "user",
        "parts": [{"text": user_query}]
    })

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_llm_model}:streamGenerateContent?key={settings.gemini_api_key}&alt=sse"
    
    body = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "temperature": 0.7
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", url, json=body) as response:
                if response.status_code != 200:
                    error_detail = await response.aread()
                    logger.error(f"Gemini Streaming error: {response.status_code} - {error_detail.decode()}")
                    yield f"連線至 AI 引擎失敗 (HTTP {response.status_code})。"
                    return

                import json
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            data_str = line[len("data:"):].strip()
                            if not data_str:
                                continue
                            data = json.loads(data_str)
                            candidates = data.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                if parts:
                                    # Filter out thoughts
                                    text_parts = []
                                    for part in parts:
                                        if part.get("thought") is True:
                                            continue
                                        text = part.get("text")
                                        if text:
                                            text_parts.append(text)
                                    chunk_text = "".join(text_parts)
                                    if chunk_text:
                                        yield chunk_text
                        except Exception as e:
                            logger.error(f"Error parsing Gemini stream chunk: {e}")
        except Exception as e:
            logger.error(f"Network error in stream_gemini_content: {e}")
            yield "串流回答時發生網路連線異常。"
