from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List

from app.models.database import get_db
from app.models.user import User
from app.models.session import CookingSession
from app.schemas.user_schema import (
    UserAuthRequest,
    UserAuthResponse,
    UserResponse,
    UserSettingsUpdate,
    UserSettingsResponse
)

router = APIRouter()


@router.post("/register", response_model=UserAuthResponse, status_code=status.HTTP_201_CREATED, summary="회원가입 (아이디 + 비밀번호)")
def register_user(payload: UserAuthRequest, db: Session = Depends(get_db)):
    """
    새로운 사용자를 등록합니다. 별도 닉네임 없이 가입한 아이디(username)가 화면 표시명으로 사용됩니다.
    """
    uname = payload.username.strip()
    existing = db.query(User).filter(User.username == uname).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"이미 사용 중인 아이디입니다: '{uname}'"
        )

    new_user = User(
        username=uname,
        password=payload.password.strip(),
        wake_word_enabled=True,
        wake_word="요쿡아"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return UserAuthResponse(
        user_id=new_user.id,
        username=new_user.username,
        wake_word_enabled=new_user.wake_word_enabled,
        wake_word=new_user.wake_word,
        active_session_id=None,
        active_session_code=None,
        message=f"환영합니다, {new_user.username}님! 회원가입이 완료되었습니다."
    )


@router.post("/login", response_model=UserAuthResponse, summary="로그인 및 진행 중인 요리 세션 자동 연동")
def login_user(payload: UserAuthRequest, db: Session = Depends(get_db)):
    """
    아이디와 비밀번호로 로그인합니다.
    동일 아이디로 다른 기기(휴대폰/PC)에서 진행 중인 조리 세션이 있다면 자동으로 active_session_id를 매칭해 반환합니다.
    """
    uname = payload.username.strip()
    user = db.query(User).filter(User.username == uname).first()
    if not user or user.password != payload.password.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 일치하지 않습니다."
        )

    # 현재 해당 유저가 진행 중인 미완료 세션 조회 (휴대폰 <-> PC 1:1 자동 동기화용)
    active_sess = (
        db.query(CookingSession)
        .filter(CookingSession.user_id == user.id, CookingSession.is_completed == False)
        .order_by(desc(CookingSession.started_at))
        .first()
    )

    return UserAuthResponse(
        user_id=user.id,
        username=user.username,
        wake_word_enabled=user.wake_word_enabled,
        wake_word=user.wake_word,
        active_session_id=active_sess.id if active_sess else None,
        active_session_code=active_sess.session_code if active_sess else None,
        message=f"반갑습니다, {user.username}님!"
    )


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
        wake_word_enabled=user.wake_word_enabled,
        wake_word=user.wake_word
    )


@router.patch("/{user_id}/settings", response_model=UserSettingsResponse, summary="사용자 호출어 및 비밀번호 환경설정 변경")
def update_user_settings(
    user_id: int,
    settings_update: UserSettingsUpdate,
    db: Session = Depends(get_db)
):
    """
    사용자의 호출어 활성화 여부(ON/OFF), 호출어(Wake Word) 또는 비밀번호를 수정합니다.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User ID {user_id} not found"
        )
    
    if settings_update.wake_word_enabled is not None:
        user.wake_word_enabled = settings_update.wake_word_enabled
    if settings_update.wake_word is not None and settings_update.wake_word.strip():
        user.wake_word = settings_update.wake_word.strip()
    if settings_update.password is not None and settings_update.password.strip():
        user.password = settings_update.password.strip()
        
    db.commit()
    db.refresh(user)

    return UserSettingsResponse(
        user_id=user.id,
        username=user.username,
        wake_word_enabled=user.wake_word_enabled,
        wake_word=user.wake_word
    )
