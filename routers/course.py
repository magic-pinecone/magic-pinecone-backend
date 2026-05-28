from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from database.db_connect import get_db
from database.models import Course, SystemStatus, CourseEmbedding
from internal.course_fetcher import sync_courses_to_db
from schemas.course_schema import CourseResult, SemanticSearchItem, CourseResponse
import logging


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/course",
    tags=['Courses']
)

async def run_sync_task():
    db = next(get_db())
    try:
        logger.info("Manual course sync started from endpoint.")
        await sync_courses_to_db(db)
    except Exception as e:
        logger.error(f"Error in manual sync task: {e}")
    finally:
        db.close()

@router.post('/sync',
             summary="Trigger Course Synchronization",
             description="手動觸發背景作業，將中央大學 (NCU) 的所有課程資料從遠端同步至本地資料庫。該操作不會阻塞連線。",
             response_description="回傳同步任務的啟動狀態")
async def manual_sync_courses(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_sync_task)
    return {"status": "sync_started", "message": "Course synchronization has started in the background."}

@router.get('',
            response_model=CourseResult,
            summary="Query Courses",
            description="透過各種自訂條件 (如課號、課程名稱、學院 ID、系所 ID) 來檢索資料庫中的所有課程。支援分頁功能 (利用 skip, limit) 以及關鍵字模糊搜尋。",
            response_description="包含所查詢之課程列表，以及符合該條件的資料總數。")
async def query_courses(
    title: Optional[str] = Query(None, description="以課程名稱進行模糊搜尋 (例如輸入 '程式' 將找出所有包含程式兩字的課程)"),
    class_no: Optional[str] = Query(None, description="以課號進行模糊搜尋 (包含系縮寫/數字代碼)"),
    serial_no: Optional[str] = Query(None, description="指定特定的課程流水號查尋單一課程 (五碼)"),
    department_name: Optional[str] = Query(None, description="過濾特定「系所」開設的課程名稱"),
    college_name: Optional[str] = Query(None, description="過濾特定「學院」開設的課程名稱"),
    course_type: Optional[str] = Query(None, description="依據修課類別搜尋，如 REQUIRED (必修), ELECTIVE (選修)"),
    credits: Optional[List[float]] = Query(None, description="過濾特定的學分數，支援多選 (例如 credits=2&credits=3)"),
    has_vacancy: Optional[bool] = Query(None, description="是否過濾有餘額的課程 (True: 有餘額, False: 已額滿)"),
    class_times: Optional[List[str]] = Query(None, description="過濾上課時間，支援多選。格式為 'Day-Period' 如 '1-1' (星期一第一節) 或 '5-A' (星期五 A 節)"),
    skip: int = Query(0, ge=0, description="跳過前 N 筆資料，用於分頁"),
    limit: int = Query(100, ge=1, le=1000, description="限制回傳的資料筆數 (最多一次 1000 筆)"),
    db: Session = Depends(get_db)
):
    query = db.query(Course)

    if title:
        query = query.filter(Course.title.ilike(f"%{title}%"))
    if class_no:
        query = query.filter(Course.class_no.ilike(f"%{class_no}%"))
    if serial_no:
        query = query.filter(Course.serial_no == serial_no)
    if department_name:
        query = query.filter(Course.department_name.ilike(f"%{department_name}%"))
    if college_name:
        query = query.filter(Course.college_name.ilike(f"%{college_name}%"))
    if course_type:
        query = query.filter(Course.course_type == course_type)
    if credits:
        query = query.filter(Course.credit.in_(credits))
    if has_vacancy is True:
        query = query.filter(
            or_(
                Course.limit_cnt == 0,
                Course.limit_cnt.is_(None),
                Course.admit_cnt.is_(None),
                Course.admit_cnt < Course.limit_cnt
            )
        )
    elif has_vacancy is False:
        query = query.filter(
            Course.limit_cnt > 0,
            Course.admit_cnt.is_not(None),
            Course.admit_cnt >= Course.limit_cnt
        )
    if class_times:
        time_filters = [Course.class_times.like(f'%"{time_slot}"%') for time_slot in class_times]
        query = query.filter(or_(*time_filters))

    total_count = query.count()
    courses = query.offset(skip).limit(limit).all()

    status = db.query(SystemStatus).filter(SystemStatus.id == 1).first()
    last_updated = status.last_course_sync if status else None

    return CourseResult(
        total_count=total_count,
        last_updated=last_updated,
        courses=courses
    )

async def run_embedding_sync_task(force_all: bool):
    db = next(get_db())
    try:
        logger.info("Manual course embedding RAG preprocessing started from endpoint.")
        from internal.rag_preprocessor import sync_course_normalizations, sync_course_embeddings
        await sync_course_normalizations(db, force_all=force_all)
        await sync_course_embeddings(db, force_all=force_all)
    except Exception as e:
        logger.error(f"Error in manual embedding sync task: {e}")
    finally:
        db.close()

@router.post('/sync-embeddings',
             summary="Trigger RAG Embeddings Preprocessing",
             description="手動觸發背景作業，對所有具有詳細大綱的課程進行 LLM 正規化與向量嵌入，並將結果存入資料庫。",
             response_description="回傳任務啟動狀態")
async def manual_sync_embeddings(
    background_tasks: BackgroundTasks,
    force_all: bool = Query(False, description="是否強制重刷所有課程的向量")
):
    background_tasks.add_task(run_embedding_sync_task, force_all)
    return {"status": "embedding_sync_started", "message": "Course embedding preprocessing has started in the background."}

@router.get('/search',
            response_model=List[SemanticSearchItem],
            summary="Semantic Search Courses (RAG)",
            description="透過自然語言 (RAG 語意搜尋) 尋找最符合的課程。系統會將您的 query 轉為向量後，至資料庫計算餘弦相似度排序。")
async def semantic_search_courses(
    query: str = Query(..., description="輸入你想搜尋的課程特徵或興趣，例如：『想學機器學習與 Python 實作』"),
    limit: int = Query(10, ge=1, le=50, description="限制回傳的課程筆數"),
    db: Session = Depends(get_db)
):
    from core.config import settings
    if not settings.gemini_api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is not configured. Semantic search is unavailable.")

    import httpx
    import asyncio
    from internal.rag_preprocessor import generate_embedding_api

    sem = asyncio.Semaphore(1)
    async with httpx.AsyncClient(verify=False) as client:
        query_vector = await generate_embedding_api(client, query, sem)

    if not query_vector:
        raise HTTPException(status_code=500, detail="Failed to generate embedding for the search query.")

    raw_results = db.query(
        Course,
        CourseEmbedding.organized_description,
        (1.0 - CourseEmbedding.embedding.cosine_distance(query_vector)).label("similarity")
    ).join(
        CourseEmbedding, Course.serial_no == CourseEmbedding.serial_no
    ).filter(
        CourseEmbedding.embedding.is_not(None)
    ).order_by(
        CourseEmbedding.embedding.cosine_distance(query_vector)
    ).limit(limit).all()

    results = []
    for course, desc, score in raw_results:
        course_data = CourseResponse.model_validate(course)
        results.append(
            SemanticSearchItem(
                course=course_data,
                similarity_score=float(score),
                organized_description=desc
            )
        )
    return results
