from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session
from database.db_connect import get_db
from database.models import Scholarship, SystemStatus
from internal.scholarship_fetcher import sync_scholarships_to_db
from schemas.scholarship_schema import ScholarshipResult
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/scholarship",
    tags=['Scholarships']
)

async def run_sync_task():
    db = next(get_db())
    try:
        logger.info("Manual scholarship sync started from endpoint.")
        await sync_scholarships_to_db(db)
    except Exception as e:
        logger.error(f"Error in manual scholarship sync task: {e}")
    finally:
        db.close()

@router.post('/sync', 
             summary="Trigger Scholarship Synchronization", 
             description="手動觸發背景作業，將中央大學獎學金暨工讀管理系統的最新資訊同步至本地資料庫。該操作不會阻塞連線。",
             response_description="回傳同步任務的啟動狀態")
async def manual_sync_scholarships(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_sync_task)
    return {"status": "sync_started", "message": "Scholarship synchronization has started in the background."}

@router.get('', 
            response_model=ScholarshipResult, 
            summary="Query Scholarships", 
            description="檢索資料庫中所有獎學金與招募(工讀)資訊。支援分頁功能 (利用 skip, limit) 以及依據類別與標題進行過濾。",
            response_description="包含所查詢之資訊列表，以及符合該條件的資料總數。")
async def query_scholarships(
    title: Optional[str] = Query(None, description="以標題進行模糊搜尋 (例如輸入 '新住民')"),
    category: Optional[str] = Query(None, description="過濾特定類別 (例如 '獎學金' 或 '招募資訊')"),
    skip: int = Query(0, ge=0, description="跳過前 N 筆資料，用於分頁"),
    limit: int = Query(100, ge=1, le=1000, description="限制回傳的資料筆數 (最多一次 1000 筆)"),
    db: Session = Depends(get_db)
):
    query = db.query(Scholarship)

    if title:
        query = query.filter(Scholarship.title.ilike(f"%{title}%"))
    if category:
        query = query.filter(Scholarship.category == category)

    total_count = query.count()
    scholarships = query.offset(skip).limit(limit).all()

    status = db.query(SystemStatus).filter(SystemStatus.id == 1).first()
    last_updated = status.last_scholarship_sync if status else None

    return ScholarshipResult(
        total_count=total_count,
        last_updated=last_updated,
        scholarships=scholarships
    )
