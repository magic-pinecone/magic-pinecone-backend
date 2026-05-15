from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class ScholarshipResponse(BaseModel):
    id: int = Field(..., description="內部資料庫流水號")
    category: str = Field(..., description="類別 (例如：獎學金、招募資訊)")
    title: str = Field(..., description="名稱/標題")
    content_summary: Optional[str] = Field(None, description="內容摘要 (包含日期與申請資格)")
    download_link: Optional[str] = Field(None, description="相關檔案下載連結")

    model_config = ConfigDict(from_attributes=True)

class ScholarshipResult(BaseModel):
    total_count: int = Field(..., description="符合條件的總筆數")
    last_updated: Optional[datetime] = Field(None, description="資料庫最後更新時間")
    scholarships: List[ScholarshipResponse] = Field(..., description="查詢到的資訊列表")
