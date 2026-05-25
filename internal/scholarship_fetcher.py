import logging
import httpx
import json
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import asyncio

from database.models import Scholarship, SystemStatus

logger = logging.getLogger(__name__)

SCHOLARSHIP_URL = 'https://cis.ncu.edu.tw/Scholarship/'

async def fetch_scholarship_data():
    """
    Fetches the scholarship data from the HTML table on the NCU Scholarship page.
    Returns a list of dictionaries with the scraped data.
    """
    results = []
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(SCHOLARSHIP_URL)
        response.raise_for_status()

        # The site is encoded in UTF-8
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        table = soup.find('table', class_='news_list')
        if not table:
            logger.warning("Could not find table.news_list on the scholarship page.")
            return results

        rows = table.find_all('tr')
        # Skip header row (index 0)
        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) < 4:
                continue

            category = cols[1].get_text(strip=True)
            title = cols[2].get_text(strip=True)

            # Check for application link in the title column
            apply_link = None
            title_link_tag = cols[2].find('a')
            if title_link_tag and title_link_tag.get('href'):
                href = title_link_tag.get('href')
                if href.startswith('..'):
                    href = href.replace('..', 'https://cis.ncu.edu.tw', 1)
                elif href.startswith('/'):
                    href = f"https://cis.ncu.edu.tw{href}"
                apply_link = href

            # Parse label-value pairs from the column text
            content_summary_dict = {}
            text = cols[3].get_text(separator='\n', strip=True).replace('\n下載', ' 下載')
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                if ' :' in line:
                    parts = line.split(' :', 1)
                elif '：' in line:
                    parts = line.split('：', 1)
                elif ':' in line:
                    parts = line.split(':', 1)
                else:
                    parts = ["", line]

                label = parts[0].strip()
                value = parts[1].strip()
                content_summary_dict[label] = value

            # Check for download link in the last column
            download_link = None
            link_tag = cols[3].find('a')
            if link_tag and link_tag.get('href'):
                href = link_tag.get('href')
                if href.startswith('..'):
                    href = href.replace('..', 'https://cis.ncu.edu.tw', 1)
                elif href.startswith('/'):
                    href = f"https://cis.ncu.edu.tw{href}"
                download_link = href

            results.append({
                "category": category,
                "title": title,
                "content_summary": json.dumps(content_summary_dict, ensure_ascii=False),
                "download_link": download_link,
                "apply_link": apply_link
            })

    return results

async def sync_scholarships_to_db(db: Session):
    """
    Fetches the latest scholarships and updates the database.
    Because the site only displays active announcements without unique permanent IDs,
    we replace the current records with the freshly scraped ones to ensure it's up-to-date
    and stale announcements are removed.
    """
    logger.info("Starting scholarship fetch synchronization...")
    try:
        data = await fetch_scholarship_data()
        logger.info(f"Fetched {len(data)} scholarship records.")

        # Clear existing
        db.query(Scholarship).delete()

        # Insert new
        for item in data:
            db_scholarship = Scholarship(**item)
            db.add(db_scholarship)

        # Update system status
        status = db.query(SystemStatus).filter(SystemStatus.id == 1).first()
        if not status:
            status = SystemStatus(id=1, last_scholarship_sync=datetime.now(timezone.utc))
            db.add(status)
        else:
            status.last_scholarship_sync = datetime.now(timezone.utc)

        db.commit()
        logger.info("Scholarship synchronization completed successfully.")

    except Exception as e:
        logger.error(f"Error during scholarship sync: {e}")
        db.rollback()
