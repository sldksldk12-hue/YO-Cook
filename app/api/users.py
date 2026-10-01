from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.models.database import get_db
from app.models.user import User
from app.schemas.user_schema import UserResponse, UserSettingsUpdate, UserSettingsResponse

router = APIRouter()

@router.get("", response_model=List[UserResponse], summary="전체 사용자 목록 조회")
def get_users(db: Session = Depends(get_db)):
    """등록된 사용자 전체 목록을 조회합니다."""
    users = db.query(User).all()
    return users

@router.get("/{user_id}", response_model=UserResponse, summary="사용자 프로필 조회")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    """특정 사용자의 기본 프로필 및 설정 정보를 조회합니다."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User ID {user_id} not found"
        )
    return user

@router.get("/{user_id}/settings", response_model=UserSettingsResponse, summary="사용자 호출어 환경설정 조회")
def get_user_settings(user_id: int, db: Session = Depends(get_db)):
    """사용자의 음성 호출어(Wake Word) 활성화 여부 및 호출어 키워드 설정을 조회합니다."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User ID {user_id} not found"
        )
    return UserSettingsResponse(
        user_id=user.id,
        username=user.username,
        nickname=user.nickname,
        wake_word_enabled=user.wake_word_enabled,
        wake_word=user.wake_word
    )

@router.patch("/{user_id}/settings", response_model=UserSettingsResponse, summary="사용자 호출어 환경설정 변경 (ON/OFF 및 호출어 수정)")
def update_user_settings(
    user_id: int,
    settings_update: UserSettingsUpdate,
    db: Session = Depends(get_db)
):
    """
    사용자의 호출어 활성화 여부(ON/OFF) 및 호출어(Wake Word)를 수정합니다.
    - `wake_word_enabled`: True (ON), False (OFF)
    - `wake_word`: '요쿡아', '시리야' 등 커스텀 호출어
    - `nickname`: 사용자 닉네임 변경
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User ID {user_id} not found"
        )
    
    # 전달된 필드만 선택적 갱신
    if settings_update.wake_word_enabled is not None:
        user.wake_word_enabled = settings_update.wake_word_enabled
    if settings_update.wake_word is not None and settings_update.wake_word.strip():
        user.wake_word = settings_update.wake_word.strip()
    if settings_update.nickname is not None and settings_update.nickname.strip():
        user.nickname = settings_update.nickname.strip()
        
    db.commit()
    db.refresh(user)

    return UserSettingsResponse(
        user_id=user.id,
        username=user.username,
        nickname=user.nickname,
        wake_word_enabled=user.wake_word_enabled,
        wake_word=user.wake_word
    )
