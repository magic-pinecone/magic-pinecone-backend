import json
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, model_validator, ConfigDict

class ScholarshipResponse(BaseModel):
    id: int = Field(..., description="內部資料庫流水號")
    category: str = Field(..., description="類別 (例如：獎學金、招募資訊)")
    title: str = Field(..., description="名稱/標題")
    content_summary: Optional[dict[str, str]] = Field(None, description="內容摘要 (包含日期與申請資格)")
    download_link: Optional[str] = Field(None, description="相關檔案下載連結")
    apply_link: Optional[str] = Field(None, description="申請連結")

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def _parse_json_fields(cls, data: Any) -> Any:
        if hasattr(data, '__dict__'):
            target = data
            is_dict = False
        elif isinstance(data, dict):
            target = data
            is_dict = True
        else:
            return data

        def _parse(val):
            if not val:
                return {}
            parsed = val
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                except json.JSONDecodeError:
                    return {}
            if isinstance(parsed, list):
                res = {}
                for item in parsed:
                    if isinstance(item, dict):
                        if "label" in item and "value" in item:
                            res[item["label"]] = item["value"]
                        else:
                            for k, v in item.items():
                                res[k] = v
                return res
            if isinstance(parsed, dict):
                return parsed
            return {}

        if is_dict:
            target['content_summary'] = _parse(target.get('content_summary'))
        else:
            if hasattr(target, 'content_summary'):
                target.content_summary = _parse(target.content_summary)

        return data

class ScholarshipResult(BaseModel):
    total_count: int = Field(..., description="符合條件的總筆數")
    last_updated: Optional[datetime] = Field(None, description="資料庫最後更新時間")
    scholarships: List[ScholarshipResponse] = Field(..., description="查詢到的資訊列表")
