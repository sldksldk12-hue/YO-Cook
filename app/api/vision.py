import time
from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, UploadFile, File, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.database import get_db
from app.models.session import CookingSession, SafetyLog
from app.api.websocket import manager

router = APIRouter()

# =====================================================================
# 실시간 비전 상태 메모리 저장소 & 디바운싱(Debouncing) 타이머
# =====================================================================
DEBOUNCE_COOLDOWN_SEC = 3.0  # 동일 위험 DB 중복 기록 방지 쿨타임 (3초)
STATE_EXPIRY_SEC = 4.0       # 비전 신호가 4초 이상 끊기면 SAFE로 자동 복귀

vision_state = {
    "status": "SAFE",        # "SAFE" | "WARNING" | "DANGER"
    "hazard_type": "NONE",
    "message": "현재 주방은 안전합니다.",
    "ratio": None,
    "distance_px": None,
    "updated_at": 0.0,
    "last_db_log_at": 0.0,   # 마지막 DB 저장 시각 (디바운싱용)
}


class VisionStatusReport(BaseModel):
    status: Literal["SAFE", "WARNING", "DANGER"] = Field(..., description="현재 위험 상태")
    hazard_type: str = Field("KNIFE_PROXIMITY", description="위험 유형 (KNIFE_PROXIMITY, UNATTENDED 등)")
    message: Optional[str] = Field(None, description="경고 메시지")
    ratio: Optional[float] = Field(None, description="손바닥 폭 대비 손끝-칼 정규화 거리 비율")
    distance_px: Optional[float] = Field(None, description="손끝-칼 픽셀 거리")
    session_id: Optional[int] = Field(None, description="특정 조리 세션 ID (생략 시 가장 최근 진행 중인 세션에 자동 연결)")
    step_number: Optional[int] = Field(None, description="현재 조리 단계 번호")


def get_current_vision_status() -> dict:
    """
    현재 주방의 실시간 안전 상태를 반환합니다.
    비전 모듈로부터 일정 시간(STATE_EXPIRY_SEC) 동안 새로운 위험 신호가 없으면 SAFE로 자동 복귀합니다.
    """
    now = time.time()
    if vision_state["status"] != "SAFE" and (now - vision_state["updated_at"] > STATE_EXPIRY_SEC):
        vision_state["status"] = "SAFE"
        vision_state["hazard_type"] = "NONE"
        vision_state["message"] = "현재 주방은 안전합니다."

    return {
        "status": vision_state["status"],
        "hazard_type": vision_state["hazard_type"],
        "message": vision_state["message"],
        "ratio": vision_state["ratio"],
        "distance_px": vision_state["distance_px"],
    }


@router.get("/status", summary="실시간 비전 안전 상태 조회")
def read_vision_status():
    """프론트엔드에서 주기적으로 폴링하여 주방 위험 여부(SAFE/WARNING/DANGER)를 확인합니다."""
    return get_current_vision_status()


@router.post("/status", summary="비전 AI 실시간 판정 수신 및 자동 DB 로깅 (디바운싱 적용)")
async def update_vision_status(
    payload: VisionStatusReport,
    db: Session = Depends(get_db)
):
    """
    비전 스크립트(step6_knifehand.py 등)로부터 실시간 위험 판정 결과를 수신합니다.
    - 메모리의 최신 상태를 즉시 갱신합니다.
    - WARNING 또는 DANGER 상태일 때 3초 디바운싱(쿨타임)을 거쳐 활성 조리 세션의 safety_logs 테이블에 자동 기록합니다.
    """
    now = time.time()

    # 기본 메시지 설정 (Windows cp949 콘솔 호환을 위해 이모지 제외)
    if not payload.message:
        if payload.status == "DANGER":
            msg = "[위험] 칼날과 손가락이 너무 가깝습니다! 고양이 손을 유지하세요!"
        elif payload.status == "WARNING":
            msg = "[주의] 칼날 근처에 손이 접근 중입니다. 주의하세요."
        else:
            msg = "[안전] 현재 주방은 안전합니다."
    else:
        msg = payload.message

    # 1. 실시간 상태 메모리 업데이트
    vision_state["status"] = payload.status
    vision_state["hazard_type"] = payload.hazard_type if payload.status != "SAFE" else "NONE"
    vision_state["message"] = msg
    vision_state["ratio"] = payload.ratio
    vision_state["distance_px"] = payload.distance_px
    vision_state["updated_at"] = now

    logged_to_db = False

    # 2. WARNING / DANGER 발생 시 디바운싱(3초 쿨타임) 적용 후 DB 자동 기록
    if payload.status in ("WARNING", "DANGER"):
        if now - vision_state["last_db_log_at"] >= DEBOUNCE_COOLDOWN_SEC:
            vision_state["last_db_log_at"] = now
            try:
                # 대상 세션 찾기: 지정된 session_id가 없으면 현재 진행 중(미완료)인 가장 최신 세션 조회
                target_session = None
                if payload.session_id:
                    target_session = db.get(CookingSession, payload.session_id)
                else:
                    target_session = (
                        db.query(CookingSession)
                        .filter(CookingSession.is_completed == False)
                        .order_by(desc(CookingSession.started_at))
                        .first()
                    )

                if target_session:
                    step_num = payload.step_number or target_session.current_step or 1
                    new_log = SafetyLog(
                        session_id=target_session.id,
                        step_number=step_num,
                        hazard_type=payload.hazard_type,
                        level=payload.status,
                        message=msg,
                        distance_px=payload.distance_px,
                        duration_seconds=None,
                        detected_at=datetime.utcnow()
                    )
                    db.add(new_log)
                    db.commit()
                    db.refresh(new_log)
                    logged_to_db = True

                    # 웹소켓 연결 클라이언트가 있다면 실시간 푸시
                    await manager.send_message(target_session.session_code, {
                        "type": "SAFETY_ALERT",
                        "status": payload.status,
                        "hazard_type": payload.hazard_type,
                        "message": msg,
                        "step_number": step_num,
                        "distance_px": payload.distance_px
                    })
            except Exception as db_err:
                print(f"[비전 DB 로깅 알림] 활성 세션 저장 건너뜀: {db_err}")

    return {
        "result": "ok",
        "current_status": vision_state["status"],
        "logged_to_db": logged_to_db
    }


@router.post("/detect")
async def detect_objects(file: UploadFile = File(...)):
    """
    클라이언트(웹캠)로부터 이미지를 받아 주방 도구와 위험 상황을 탐지합니다.
    """
    return {
        "status": "success",
        "message": "비전 객체 탐지 API가 정상적으로 호출되었습니다.",
        "detected_objects": [],
        "vision_state": get_current_vision_status()
    }
