import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from internal.course_fetcher import sync_courses_to_db
from internal.scholarship_fetcher import sync_scholarships_to_db
from database.db_connect import SessionLocal
import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def run_sync_job():
    logger.info("Scheduler triggered background course sync.")
    # Run sync in background safely
    db = SessionLocal()
    try:
        # Since sync_courses_to_db is async, wait for it
        # Actually APScheduler can run async functions directly if configured correctly
        # We can just define an async wrapper
        pass
    except Exception as e:
        logger.error(e)
    finally:
        db.close()

async def async_run_sync_job():
    logger.info("Scheduler triggered background course sync (Async).")
    db = SessionLocal()
    try:
        await sync_courses_to_db(db)
    except Exception as e:
        logger.error(f"Failed sync job: {e}")
    finally:
        db.close()

async def async_run_scholarship_sync_job():
    logger.info("Scheduler triggered background scholarship sync (Async).")
    db = SessionLocal()
    try:
        await sync_scholarships_to_db(db)
    except Exception as e:
        logger.error(f"Failed scholarship sync job: {e}")
    finally:
        db.close()

def start_scheduler():
    # Run once a day at 4:00 AM
    scheduler.add_job(async_run_sync_job, 'cron', hour=4, minute=0)
    # Run once a day at 4:30 AM for scholarships
    scheduler.add_job(async_run_scholarship_sync_job, 'cron', hour=4, minute=30)
    scheduler.start()
    logger.info("APScheduler started: Daily sync at 04:00 AM (Course) and 04:30 AM (Scholarship).")
