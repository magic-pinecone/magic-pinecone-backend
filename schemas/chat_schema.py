from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from schemas.course_schema import CourseResponse


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's query or statement to the chatbot.")


class DocumentResponse(BaseModel):
    id: int
    title: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EnrollCoursesRequest(BaseModel):
    serial_nos: List[str] = Field(..., description="List of 5-digit course serial numbers to enroll in.")


class UserCourseResponse(BaseModel):
    id: int
    serial_no: str
    course: Optional[CourseResponse] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
