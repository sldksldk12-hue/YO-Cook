from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class UserSettingsUpdate(BaseModel):
    """사용자 환경설정 수정 요청 DTO"""
    wake_word_enabled: Optional[bool] = Field(default=None, description="호출어 인식 활성화 여부 (True: ON, False: OFF)")
    wake_word: Optional[str] = Field(default=None, max_length=50, description="사용자 지정 호출어 (예: '요쿡아', '시리야')")
    nickname: Optional[str] = Field(default=None, max_length=50, description="사용자 닉네임")

class UserSettingsResponse(BaseModel):
    """사용자 환경설정 응답 DTO"""
    user_id: int
    username: str
    nickname: str
    wake_word_enabled: bool
    wake_word: str

    model_config = ConfigDict(from_attributes=True)

class UserResponse(BaseModel):
    """사용자 전체 프로필 응답 DTO"""
    id: int
    username: str
    nickname: str
    wake_word_enabled: bool
    wake_word: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
