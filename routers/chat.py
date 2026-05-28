from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import logging

from database.db_connect import get_db, db_session
from database.models import User, ChatMessage, UserDocument, UserCourse, Course
from dependencies import get_current_user
from schemas.chat_schema import (
    ChatRequest, MessageResponse, DocumentResponse, 
    EnrollCoursesRequest, UserCourseResponse
)
from internal.chat_service import (
    classify_intent, build_chat_context, 
    stream_gemini_content, background_vector_pipeline
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["RAG Chatbot"])


@router.post("/message", 
             summary="Send Message to Chatbot (SSE Stream)",
             description="與智慧助理進行對話。後端會進行意圖路由 (A: 課表查詢, B: 文件檢索, C: 混合推薦)，從資料庫注入 Context 與歷史對話後，串流回傳 Gemini 回答。")
async def send_chat_message(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Fetch user's recent chat history (last 5 rounds = 10 messages)
    db_history = db.query(ChatMessage)\
        .filter(ChatMessage.user_id == current_user.id)\
        .order_by(ChatMessage.created_at.desc())\
        .limit(10)\
        .all()
    
    # Reverse to restore chronological order
    db_history.reverse()
    chat_history = [{"role": msg.role, "content": msg.content} for msg in db_history]

    # 2. Save user message to database
    user_msg = ChatMessage(user_id=current_user.id, role="user", content=req.message)
    db.add(user_msg)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving user message to database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record your message."
        )

    # 3. Classify intent (A: Structured schedule, B: Personal document search, C: Hybrid recommendation)
    intent = await classify_intent(req.message)
    logger.info(f"User query routed to intent '{intent}' for user {current_user.id}")

    # 4. Gather context
    context = await build_chat_context(db, current_user, req.message, intent)

    # 5. Format system instruction / prompt
    system_prompt = (
        "你是一位精通中央大學 (NCU) 選課、課務、學務與職涯發展的 AI 導師 (智慧代理 Agent)。\n"
        "請根據你所擁有的後台結構化數據及向量知識庫 (Business Context) 來精確、親切地回答學生的問題。\n"
        "回答時應結合學生的學術背景與選課現況，若學生詢問選課或專題推薦，請優先提供與其背景高度相關的建議，切忌給出籠統的套話。\n\n"
        f"【目前對話的學生背景與知識庫 (Business Context)】:\n{context}\n\n"
        "注意事項：\n"
        "1. 請直接、自然、口語化地以第一人稱回答問題，不要寫前言如「根據背景資料...」。\n"
        "2. 如果問題是有關『我下午有什麼課』或『我這學期修什麼課』，請務必基於【目前選課/課表】來完整、精確地報告課程與時間。\n"
        "3. 請使用繁體中文 (Traditional Chinese) 回答學生。"
    )

    # 6. Stream Gemini completion using SSE
    async def event_generator():
        accumulated_text = ""
        try:
            async for chunk in stream_gemini_content(system_prompt, req.message, chat_history):
                accumulated_text += chunk
                yield f"data: {chunk}\n\n"
        except Exception as e:
            logger.error(f"Error in stream generator: {e}")
            yield "data: [串流發生錯誤]\n\n"
        finally:
            # Save assistant response to history in background session to avoid thread conflict
            if accumulated_text.strip():
                with db_session() as local_db:
                    assistant_msg = ChatMessage(
                        user_id=current_user.id,
                        role="assistant",
                        content=accumulated_text
                    )
                    local_db.add(assistant_msg)
                    try:
                        local_db.commit()
                        logger.info(f"Saved assistant response to history for user {current_user.id}")
                    except Exception as ex:
                        local_db.rollback()
                        logger.error(f"Error saving assistant response: {ex}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/history", 
            response_model=List[MessageResponse],
            summary="Retrieve Chat History",
            description="獲取當前使用者的所有歷史對話記錄。")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    history = db.query(ChatMessage)\
        .filter(ChatMessage.user_id == current_user.id)\
        .order_by(ChatMessage.created_at.asc())\
        .all()
    return history


@router.delete("/history", 
               summary="Clear Chat History",
               description="刪除當前使用者的所有歷史對話記錄。")
async def clear_chat_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        db.query(ChatMessage).filter(ChatMessage.user_id == current_user.id).delete()
        db.commit()
        return {"status": "success", "message": "Chat history cleared successfully."}
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing chat history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear chat history."
        )


@router.post("/upload-doc", 
             response_model=DocumentResponse,
             summary="Upload Personal Document (Async Vectorizing)",
             description="上傳課程大綱、筆記或考古題。系統會先儲存文檔並返回 'processing' 狀態，並在背景執行文字切塊與向量索引建置。")
async def upload_document(
    title: str,
    content: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_doc = UserDocument(
        user_id=current_user.id,
        title=title,
        raw_content=content,
        status="processing"
    )
    db.add(new_doc)
    try:
        db.commit()
        db.refresh(new_doc)
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving document to database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload document."
        )

    # Trigger heavy vectorization in background
    background_tasks.add_task(
        background_vector_pipeline, 
        new_doc.id, 
        content, 
        current_user.id
    )

    return new_doc


@router.get("/documents", 
            response_model=List[DocumentResponse],
            summary="List Uploaded Documents",
            description="列出使用者上傳的所有個人文件與其處理狀態 (processing, ready, error)。")
async def get_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    docs = db.query(UserDocument).filter(UserDocument.user_id == current_user.id).all()
    return docs


@router.post("/enroll", 
             summary="Enroll User in Courses (Simulation)",
             description="模擬將使用者選課資料寫入資料庫，以測試個人課表查詢 (Intent A) 功能。")
async def enroll_courses(
    req: EnrollCoursesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify courses exist
    for serial in req.serial_nos:
        course = db.query(Course).filter(Course.serial_no == serial).first()
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Course with serial_no {serial} not found in catalog."
            )

    enrolled = []
    try:
        for serial in req.serial_nos:
            exists = db.query(UserCourse)\
                .filter(UserCourse.user_id == current_user.id, UserCourse.serial_no == serial)\
                .first()
            if not exists:
                uc = UserCourse(user_id=current_user.id, serial_no=serial)
                db.add(uc)
                enrolled.append(serial)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error enrolling courses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save course enrollment."
        )

    return {"status": "success", "message": f"Successfully enrolled in courses: {enrolled}"}


@router.get("/enroll", 
            response_model=List[UserCourseResponse],
            summary="Get Enrolled Courses",
            description="查詢使用者模擬選修的課程清單。")
async def get_enrolled_courses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_courses = db.query(UserCourse).filter(UserCourse.user_id == current_user.id).all()
    return user_courses
