import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.database import get_db
from app.models.recipe import Recipe, RecipeStep
from app.models.session import CookingSession, SafetyLog
from app.schemas.session_schema import (
    SessionStartRequest,
    SessionResponse,
    SessionDetailResponse,
    StepUpdateRequest,
    SafetyLogCreate,
    SafetyLogResponse,
    SessionCompleteResponse
)
from app.schemas.recipe_schema import RecipeStepResponse

router = APIRouter()

# 1. 요리 세션 시작 (POST /api/sessions/start)
@router.post(
    "/start",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="요리 세션 시작",
    description="선택한 레시피로 실시간 조리 세션을 생성하고 고유 session_id를 발급합니다."
)
def start_cooking_session(
    payload: SessionStartRequest,
    db: Session = Depends(get_db)
):
    # 1. 레시피 존재 여부 확인
    recipe = db.get(Recipe, payload.recipe_id)
    if not recipe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {payload.recipe_id}번에 해당하는 레시피를 찾을 수 없습니다."
        )

    # 2. 고유 세션 코드 생성 (예: COOK-A1B2C3D4)
    session_code = f"COOK-{uuid.uuid4().hex[:8].upper()}"

    # 3. CookingSession 레코드 생성
    new_session = CookingSession(
        session_code=session_code,
        user_id=payload.user_id,
        recipe_id=payload.recipe_id,
        current_step=1,
        is_completed=False,
        started_at=datetime.utcnow()
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    total_steps = len(recipe.steps)

    return SessionResponse(
        id=new_session.id,
        session_code=new_session.session_code,
        user_id=new_session.user_id,
        recipe_id=new_session.recipe_id,
        recipe_title=recipe.title,
        current_step=new_session.current_step,
        total_steps=total_steps,
        is_completed=new_session.is_completed,
        started_at=new_session.started_at,
        ended_at=new_session.ended_at
    )


# 2. 세션 현재 진행 상태 상세 조회 (GET /api/sessions/{session_id})
@router.get(
    "/{session_id}",
    response_model=SessionDetailResponse,
    summary="조리 세션 진행 상태 조회",
    description="현재 세션의 진행 단계 번호 및 해당 단계의 상세 조리 지침, 타이머, 안전 주의사항을 반환합니다."
)
def get_session_detail(
    session_id: int,
    db: Session = Depends(get_db)
):
    session = db.get(CookingSession, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {session_id}번에 해당하는 조리 세션을 찾을 수 없습니다."
        )

    recipe = session.recipe
    total_steps = len(recipe.steps) if recipe else 0

    # 현재 단계 상세 정보 조회
    current_step_obj = None
    if recipe and recipe.steps:
        for step in recipe.steps:
            if step.step_number == session.current_step:
                current_step_obj = step
                break

    step_detail = RecipeStepResponse.model_validate(current_step_obj) if current_step_obj else None

    return SessionDetailResponse(
        id=session.id,
        session_code=session.session_code,
        user_id=session.user_id,
        recipe_id=session.recipe_id,
        recipe_title=recipe.title if recipe else "",
        current_step=session.current_step,
        total_steps=total_steps,
        is_completed=session.is_completed,
        started_at=session.started_at,
        ended_at=session.ended_at,
        current_step_detail=step_detail,
        safety_logs_count=len(session.safety_logs)
    )


# 3. 조리 단계 이동 (PATCH /api/sessions/{session_id}/step)
@router.patch(
    "/{session_id}/step",
    response_model=SessionDetailResponse,
    summary="조리 단계 이동 (다음/이전/지정)",
    description="사용자의 음성 명령이나 버튼 클릭에 따라 조리 단계를 앞뒤로 이동합니다."
)
def update_session_step(
    session_id: int,
    payload: StepUpdateRequest,
    db: Session = Depends(get_db)
):
    session = db.get(CookingSession, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {session_id}번에 해당하는 조리 세션을 찾을 수 없습니다."
        )

    recipe = session.recipe
    total_steps = len(recipe.steps) if recipe else 1

    # 단계 변경 로직
    if payload.action == "NEXT":
        session.current_step = min(session.current_step + 1, total_steps)
    elif payload.action == "PREV":
        session.current_step = max(session.current_step - 1, 1)
    elif payload.action == "SET":
        if payload.target_step is not None:
            session.current_step = max(1, min(payload.target_step, total_steps))

    db.commit()
    db.refresh(session)

    # 갱신된 현재 단계 상세 정보 조회
    current_step_obj = None
    if recipe and recipe.steps:
        for step in recipe.steps:
            if step.step_number == session.current_step:
                current_step_obj = step
                break

    step_detail = RecipeStepResponse.model_validate(current_step_obj) if current_step_obj else None

    return SessionDetailResponse(
        id=session.id,
        session_code=session.session_code,
        user_id=session.user_id,
        recipe_id=session.recipe_id,
        recipe_title=recipe.title if recipe else "",
        current_step=session.current_step,
        total_steps=total_steps,
        is_completed=session.is_completed,
        started_at=session.started_at,
        ended_at=session.ended_at,
        current_step_detail=step_detail,
        safety_logs_count=len(session.safety_logs)
    )


# 4. 비전 AI 안전 위험 로그 기록 (POST /api/sessions/{session_id}/safety-logs)
@router.post(
    "/{session_id}/safety-logs",
    response_model=SafetyLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="비전 AI 안전 위험 이력 저장",
    description="카메라 비전 AI가 조리 중 위험(칼날 근접, 열원 방치 등)을 감지했을 때 세션에 기록합니다."
)
def record_safety_log(
    session_id: int,
    payload: SafetyLogCreate,
    db: Session = Depends(get_db)
):
    session = db.get(CookingSession, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {session_id}번에 해당하는 조리 세션을 찾을 수 없습니다."
        )

    log = SafetyLog(
        session_id=session_id,
        step_number=payload.step_number,
        hazard_type=payload.hazard_type,
        level=payload.level,
        message=payload.message,
        distance_px=payload.distance_px,
        duration_seconds=payload.duration_seconds,
        detected_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return log


# 5. 요리 세션 완료 및 리포트 (POST /api/sessions/{session_id}/complete)
@router.post(
    "/{session_id}/complete",
    response_model=SessionCompleteResponse,
    summary="요리 완료 및 안전 리포트",
    description="요리를 완료하고 총 소요 시간 및 감지되었던 안전 경고 통계 요약을 반환합니다."
)
def complete_cooking_session(
    session_id: int,
    db: Session = Depends(get_db)
):
    session = db.get(CookingSession, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {session_id}번에 해당하는 조리 세션을 찾을 수 없습니다."
        )

    now = datetime.utcnow()
    session.is_completed = True
    session.ended_at = now
    db.commit()
    db.refresh(session)

    # 소요 시간(초) 계산
    total_seconds = int((session.ended_at - session.started_at).total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    logs = [SafetyLogResponse.model_validate(log) for log in session.safety_logs]
    recipe_title = session.recipe.title if session.recipe else "요리"

    if len(logs) == 0:
        msg = f"🎉 축하합니다! '{recipe_title}' 요리를 경고 없이 매우 안전하게 완성하셨습니다!"
    else:
        msg = f"🎉 '{recipe_title}' 요리가 완성되었습니다! 총 {len(logs)}회의 안전 주의가 발생했으니 다음엔 더 주의해 보세요."

    return SessionCompleteResponse(
        session_id=session.id,
        session_code=session.session_code,
        recipe_title=recipe_title,
        started_at=session.started_at,
        ended_at=session.ended_at,
        total_cooking_seconds=total_seconds,
        total_warnings_count=len(logs),
        safety_logs=logs,
        message=msg
    )
