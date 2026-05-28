import base64
import httpx
from urllib.parse import urlencode, urlparse
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core.config import settings
from core.security import create_access_token
from database.db_connect import get_db
from database.models import User
from dependencies import get_current_user
from internal.ncu_portal import NCUPortalClient

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/login")
def login(state: str | None = Query(None, description="Optional URL to redirect back to after authentication")):
    """
    Redirects the user to the NCU Portal OAuth 2.0 authorization page.
    """
    params = {
        "response_type": "code",
        "client_id": settings.ncu_oauth_client_id,
        "redirect_uri": settings.ncu_oauth_redirect_uri,
        "scope": "identifier chinese-name english-name student-id academy-records faculty-records"
    }
    if state:
        params["state"] = state
    url = f"https://portal.ncu.edu.tw/oauth2/authorization?{urlencode(params)}"
    return RedirectResponse(url)

@router.get("/callback")
async def callback(
    code: str = Query(..., description="Authorization code from NCU Portal"),
    state: str | None = Query(None, description="Redirect URL or state string passed during login"),
    db: Session = Depends(get_db)
):
    """
    Callback endpoint that exchanges the authorization code for an access token,
    queries the user's profile from NCU Portal, upserts the user record,
    and issues an application-specific JWT access token.
    """
    # 1. Exchange code for access token
    credentials = f"{settings.ncu_oauth_client_id}:{settings.ncu_oauth_client_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Accept": "application/json"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.ncu_oauth_redirect_uri
    }
    
    async with httpx.AsyncClient() as client:
        try:
            token_response = await client.post(
                "https://portal.ncu.edu.tw/oauth2/token",
                data=data,
                headers=headers
            )
            token_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange token with NCU Portal: {exc}"
            )
            
    token_json = token_response.json()
    access_token = token_json.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access token not found in NCU Portal response"
        )
        
    # 2. Retrieve user profile info
    async with httpx.AsyncClient() as client:
        try:
            info_response = await client.get(
                "https://portal.ncu.edu.tw/apis/oauth/v1/info",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            info_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch user info from NCU Portal: {exc}"
            )
            
    user_info = info_response.json()
    print(f"DEBUG: User Info from NCU Portal: {user_info}", flush=True)
    identifier = user_info.get("identifier")
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User identifier not found in profile"
        )
        
    chinese_name = user_info.get("chineseName") or user_info.get("chinese-name")
    english_name = user_info.get("englishName") or user_info.get("english-name")
    email = None
    student_id = user_info.get("studentId") or user_info.get("student-id")
    
    # Initialize NCU Portal Client for lookup resolution
    portal_client = NCUPortalClient()
    
    # Determine role & extract fields using lookup tables
    role = "student"
    department = None
    study_system = None
    student_status = None
    employee_type = None
    employee_status = None
    title = None
    
    academy_records = user_info.get("academyRecords") or user_info.get("academy-records")
    faculty_records = user_info.get("facultyRecords") or user_info.get("faculty-records")
    
    if academy_records:
        role = "student"
        record = academy_records[0] if isinstance(academy_records, list) and len(academy_records) > 0 else academy_records
        if isinstance(record, dict):
            resolved = await portal_client.resolve_student_info(record)
            department = resolved.get("department")
            study_system = resolved.get("study_system")
            student_status = resolved.get("student_status")
    elif faculty_records:
        role = "faculty"
        record = faculty_records[0] if isinstance(faculty_records, list) and len(faculty_records) > 0 else faculty_records
        if isinstance(record, dict):
            resolved = await portal_client.resolve_faculty_info(record)
            department = resolved.get("department")
            employee_type = resolved.get("employee_type")
            employee_status = resolved.get("employee_status")
            title = resolved.get("title")
            
    # Fallback for student student_id if not present in user_info but role is student
    if role == "student" and not student_id:
        student_id = identifier
        
    # 3. Create or update user in database
    user = db.query(User).filter(User.id == identifier).first()
    if not user:
        user = User(id=identifier)
        db.add(user)
        
    user.chinese_name = chinese_name
    user.english_name = english_name
    user.email = email
    user.student_id = student_id
    user.role = role
    user.department = department
    user.study_system = study_system
    user.student_status = student_status
    user.employee_type = employee_type
    user.employee_status = employee_status
    user.title = title
    
    db.commit()
    db.refresh(user)
    
    # 4. Generate local JWT access token
    jwt_data = {"sub": user.id, "role": user.role}
    app_access_token = create_access_token(data=jwt_data)
    
    # 5. Handle response / redirection
    if state:
        # Check if state is a valid absolute/relative URL to redirect
        parsed_state = urlparse(state)
        if parsed_state.scheme in ("http", "https") or state.startswith("/"):
            # Redirect to state URL with token
            separator = "&" if "?" in state else "?"
            redirect_url = f"{state}{separator}token={app_access_token}"
            return RedirectResponse(redirect_url)
            
    return {
        "access_token": app_access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "chinese_name": user.chinese_name,
            "english_name": user.english_name,
            "student_id": user.student_id,
            "department": user.department,
            "role": user.role,
            "study_system": user.study_system,
            "student_status": user.student_status,
            "employee_type": user.employee_type,
            "employee_status": user.employee_status,
            "title": user.title
        }
    }

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    """
    Get the currently logged-in user profile.
    """
    return {
        "id": current_user.id,
        "chinese_name": current_user.chinese_name,
        "english_name": current_user.english_name,
        "student_id": current_user.student_id,
        "department": current_user.department,
        "role": current_user.role,
        "study_system": current_user.study_system,
        "student_status": current_user.student_status,
        "employee_type": current_user.employee_type,
        "employee_status": current_user.employee_status,
        "title": current_user.title,
        "created_at": current_user.created_at,
        "updated_at": current_user.updated_at
    }
