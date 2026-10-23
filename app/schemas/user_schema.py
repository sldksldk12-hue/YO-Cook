from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class UserAuthRequest(BaseModel):
    """회원가입 및 로그인 요청 DTO"""
    username: str = Field(..., min_length=2, max_length=50, description="로그인 아이디 (화면 표시명)")
    password: str = Field(..., min_length=1, max_length=255, description="로그인 비밀번호")


class UserAuthResponse(BaseModel):
    """회원가입 및 로그인 성공 응답 DTO (진행 중인 세션 자동 매칭 포함)"""
    user_id: int
    username: str
    wake_word_enabled: bool
    wake_word: str
    active_session_id: Optional[int] = None
    active_session_code: Optional[str] = None
    message: str


class UserSettingsUpdate(BaseModel):
    """사용자 환경설정 수정 요청 DTO"""
    wake_word_enabled: Optional[bool] = Field(default=None, description="호출어 인식 활성화 여부 (True: ON, False: OFF)")
    wake_word: Optional[str] = Field(default=None, max_length=50, description="사용자 지정 호출어 (예: '요쿡아', '시리야')")
    password: Optional[str] = Field(default=None, max_length=255, description="비밀번호 변경 (선택)")


class UserSettingsResponse(BaseModel):
    """사용자 환경설정 응답 DTO"""
    user_id: int
    username: str
    wake_word_enabled: bool
    wake_word: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """사용자 전체 프로필 응답 DTO"""
    id: int
    username: str
    wake_word_enabled: bool
    wake_word: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
