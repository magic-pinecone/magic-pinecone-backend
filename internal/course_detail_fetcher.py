import asyncio
import logging
import copy
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from database.models import Course, CourseDetail

logger = logging.getLogger(__name__)

DETAIL_URL_TEMPLATE = "https://cis.ncu.edu.tw/Course/main/support/courseDetail.html?crs={}"
COURSE_HEADER = {
    'Accept-Language': 'zh-TW',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def clean_text_with_newlines(element) -> str:
    """
    Extracts text from a BeautifulSoup element while preserving line breaks
    and removing consecutive empty lines or leading/trailing whitespace.
    """
    if not element:
        return ""
    
    # Clone the element to prevent modifying the original parse tree
    el_copy = copy.copy(element)
    for br in el_copy.find_all(['br', 'br/']):
        br.replace_with('\n')
        
    text = el_copy.get_text()
    
    # Clean line-by-line
    lines = []
    for line in text.split('\n'):
        line_clean = line.strip()
        # Collapse multiple empty lines
        if line_clean == '' and lines and lines[-1] == '':
            continue
        lines.append(line_clean)
        
    return '\n'.join(lines).strip()

def parse_course_detail(html_content: bytes) -> dict:
    """
    Parses course detail fields from HTML bytes.
    Only extracts the requested fields: objectives, content, books, teaching_method, and grading_policy.
    """
    # Use response content directly so BS can detect encoding (usually UTF-8 or Big5)
    soup = BeautifulSoup(html_content, 'html.parser')
    rows = soup.select('table.classBase tr')
    
    data = {
        'objectives': None,
        'content': None,
        'books': None,
        'teaching_method': None,
        'grading_policy': None
    }
    
    for row in rows:
        tds = row.find_all('td', recursive=False)
        if len(tds) < 2:
            continue
            
        title_td = tds[0]
        value_td = tds[1]
        
        # Ensure it is a label row (usually td has subTitle class)
        title_classes = title_td.get('class', [])
        if not title_classes or 'subTitle' not in title_classes:
            continue
            
        title = title_td.get_text(strip=True)
        cleaned_val = clean_text_with_newlines(value_td)
        
        if not cleaned_val or cleaned_val.lower() == 'no data':
            continue
            
        if title == '課程目標':
            data['objectives'] = cleaned_val
        elif title == '授課內容':
            data['content'] = cleaned_val
        elif title == '教科書/參考書':
            data['books'] = cleaned_val
        elif title == '授課方式':
            data['teaching_method'] = cleaned_val
        elif title in ('評量配分比例', '評量配分比重'):
            data['grading_policy'] = cleaned_val
            
    return data

async def fetch_course_detail(client: httpx.AsyncClient, serial_no: str, semaphore: asyncio.Semaphore) -> Optional[dict]:
    """
    Fetches and parses a single course's details.
    Uses a semaphore to limit concurrency.
    """
    url = DETAIL_URL_TEMPLATE.format(serial_no)
    async with semaphore:
        for attempt in range(3):  # retry up to 3 times
            try:
                response = await client.get(url, headers=COURSE_HEADER, timeout=10.0)
                # If we get a successful response, parse and return it
                if response.status_code == 200:
                    return parse_course_detail(response.content)
                else:
                    logger.warning(f"Failed to fetch details for course {serial_no} (HTTP {response.status_code})")
                    return None
            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"Error fetching course details for {serial_no} (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))  # linear backoff
                else:
                    logger.error(f"Max retries reached for fetching course details: {serial_no}")
        return None

async def sync_course_details(db: Session, force_all: bool = False):
    """
    Finds courses needing detail synchronization, crawls them in chunks,
    and saves the course details in the database.
    """
    logger.info("Starting course details synchronization background job...")
    
    # 1. Fetch all courses currently stored in the DB
    courses = db.query(Course).all()
    if not courses:
        logger.info("No courses found in database to synchronize details for.")
        return
        
    # 2. Check which courses already have course_details
    existing_serials = set()
    if not force_all:
        existing_serials = {row.serial_no for row in db.query(CourseDetail.serial_no).all()}
        
    courses_to_fetch = [c for c in courses if c.serial_no not in existing_serials]
    logger.info(f"Total courses: {len(courses)}. Already synchronized: {len(existing_serials)}. Needs fetch: {len(courses_to_fetch)}.")
    
    if not courses_to_fetch:
        logger.info("All course details are up-to-date. Skipping detail sync.")
        return
        
    semaphore = asyncio.Semaphore(15)  # Fetch up to 15 courses concurrently
    
    async with httpx.AsyncClient(verify=False, timeout=12.0) as client:
        batch_size = 50
        for i in range(0, len(courses_to_fetch), batch_size):
            batch = courses_to_fetch[i : i + batch_size]
            logger.info(f"Fetching course details batch {i // batch_size + 1}/{(len(courses_to_fetch) - 1) // batch_size + 1} (size: {len(batch)})...")
            
            tasks = [fetch_course_detail(client, c.serial_no, semaphore) for c in batch]
            results = await asyncio.gather(*tasks)
            
            added_count = 0
            for course, detail_dict in zip(batch, results):
                if detail_dict and any(detail_dict.values()):  # only save if at least one field is not None
                    # Update or insert record
                    db_detail = db.query(CourseDetail).filter(CourseDetail.serial_no == course.serial_no).first()
                    if not db_detail:
                        db_detail = CourseDetail(
                            serial_no=course.serial_no,
                            objectives=detail_dict.get('objectives'),
                            content=detail_dict.get('content'),
                            books=detail_dict.get('books'),
                            teaching_method=detail_dict.get('teaching_method'),
                            grading_policy=detail_dict.get('grading_policy')
                        )
                        db.add(db_detail)
                    else:
                        db_detail.objectives = detail_dict.get('objectives')
                        db_detail.content = detail_dict.get('content')
                        db_detail.books = detail_dict.get('books')
                        db_detail.teaching_method = detail_dict.get('teaching_method')
                        db_detail.grading_policy = detail_dict.get('grading_policy')
                    added_count += 1
            
            try:
                db.commit()
                logger.info(f"Database sync successful for batch: saved {added_count} course detail records.")
            except Exception as e:
                db.rollback()
                logger.error(f"Error saving course details batch to database: {e}")
                
    logger.info("Course details synchronization complete.")
