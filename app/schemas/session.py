import uuid
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.recipe import RecipeStepResponse

# 1. 안전 경고 로그 스키마 (SafetyLog)
class SafetyLogCreate(BaseModel):
    step_number: int = Field(..., description="위험이 감지된 조리 단계")
    hazard_type: str = Field(..., description="위험 유형 (예: KNIFE_PROXIMITY, HEAT_ABSENCE, OIL_SPLASH)")
    level: Literal["INFO", "WARNING", "DANGER"] = Field("WARNING", description="위험 등급")
    message: str = Field(..., description="사용자 경고 문구")
    distance_px: Optional[float] = Field(None, description="손-칼날 간 거리 (픽셀)")

class SafetyLogResponse(BaseModel):
    id: int
    session_id: int
    step_number: int
    hazard_type: str
    level: str
    message: str
    distance_px: Optional[float] = None
    detected_at: datetime

    model_config = ConfigDict(from_attributes=True)


# 2. 세션 생성 및 응답 스키마 (CookingSession)
class SessionStartRequest(BaseModel):
    recipe_id: int = Field(..., description="요리를 시작할 레시피 ID")
    user_id: Optional[int] = Field(None, description="사용자 ID (비회원은 생략 가능)")

class SessionResponse(BaseModel):
    id: int
    session_code: str
    user_id: Optional[int] = None
    recipe_id: int
    recipe_title: Optional[str] = None
    current_step: int
    total_steps: int
    is_completed: bool
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# 3. 현재 세션 상세 조회 스키마 (진행 중인 단계 정보 포함)
class SessionDetailResponse(SessionResponse):
    current_step_detail: Optional[RecipeStepResponse] = None
    safety_logs_count: int = 0


# 4. 단계 이동 요청 스키마
class StepUpdateRequest(BaseModel):
    action: Literal["NEXT", "PREV", "SET"] = Field(..., description="이동 방식: NEXT(다음), PREV(이전), SET(지정)")
    target_step: Optional[int] = Field(None, description="action이 'SET'일 때 이동할 단계 번호")


# 5. 요리 완료 리포트 스키마
class SessionCompleteResponse(BaseModel):
    session_id: int
    session_code: str
    recipe_title: str
    started_at: datetime
    ended_at: datetime
    total_cooking_seconds: int
    total_warnings_count: int
    safety_logs: List[SafetyLogResponse] = []
    message: str
