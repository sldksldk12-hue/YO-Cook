import time
import math
import base64
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal, List
from fastapi import APIRouter, UploadFile, File, Form, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.database import get_db, SessionLocal
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
    "message": "[안전] 현재 주방은 안전합니다.",
    "ratio": None,
    "distance_px": None,
    "current_step": 1,
    "is_knife_monitoring": True,
    "is_unattended_monitoring": False,
    "active_hazards": ["KNIFE_PROXIMITY"],
    "latest_frame_b64": None,  # 실시간 중계용 최신 분석 프레임 (Base64 JPEG)
    "updated_at": 0.0,
    "last_db_log_at": 0.0,   # 마지막 DB 저장 시각 (디바운싱용)
}

# =====================================================================
# 모바일/웹 카메라 실시간 프레임 분석용 Lazy-Loaded 비전 엔진 (step6 알고리즘 호환)
# =====================================================================
_vision_engine = {
    "initialized": False,
    "yolo": None,
    "blade_ids": [],
    "landmarker": None,
}
TIPS = [4, 8, 12, 16, 20]
FINGERS = [(6, 8), (10, 12), (14, 16), (18, 20)]
MARGIN = 0.5


def _init_vision_engine():
    """첫 카메라 프레임 요청 시 YOLO 및 MediaPipe HandLandmarker를 1회 초기화합니다."""
    if _vision_engine["initialized"]:
        return
    import cv2
    import mediapipe as mp
    from ultralytics import YOLO
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision as mp_vision

    base_dir = Path(__file__).resolve().parent.parent.parent
    weights_dir = base_dir / "vision" / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)

    # 1. YOLO 모델 로드 (커스텀 OBB 모델이 있으면 우선 사용, 없으면 경량 seg 모델 사용)
    trained_pt = weights_dir / "knife_obb_v1.pt"
    model_path = str(trained_pt) if trained_pt.exists() else "yolo11n-seg.pt"
    yolo_model = YOLO(model_path)
    blade_ids = [k for k, v in yolo_model.names.items() if v in ("knife", "scissors")]

    # 2. MediaPipe HandLandmarker 로드 (없으면 자동 다운로드)
    task_path = weights_dir / "hand_landmarker.task"
    if not task_path.exists():
        urllib.request.urlretrieve(
            "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
            str(task_path)
        )
    options = mp_vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=task_path.read_bytes()),
        running_mode=mp_vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.3,
        min_hand_presence_confidence=0.3,
    )
    landmarker = mp_vision.HandLandmarker.create_from_options(options)

    _vision_engine["yolo"] = yolo_model
    _vision_engine["blade_ids"] = blade_ids
    _vision_engine["landmarker"] = landmarker
    _vision_engine["initialized"] = True


def _analyze_mobile_frame(frame_bgr):
    """
    모바일/웹 카메라에서 전송된 프레임을 step6_knifehand.py와 동일한 규칙으로 분석하고
    칼 다각형과 손 관절이 그려진 이미지 및 판정 결과를 반환합니다.
    """
    import cv2
    import numpy as np
    import mediapipe as mp

    _init_vision_engine()
    yolo_model = _vision_engine["yolo"]
    blade_ids = _vision_engine["blade_ids"]
    landmarker = _vision_engine["landmarker"]

    h, w, _ = frame_bgr.shape

    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _dist_to_blade(p, poly):
        d = cv2.pointPolygonTest(poly.reshape(-1, 1, 2), (float(p[0]), float(p[1])), True)
        return max(0.0, -d)

    def _nearest_on_blade(p, poly):
        best, best_d = None, None
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            ab = b - a
            t = np.clip(np.dot(np.array(p, np.float32) - a, ab) / max(np.dot(ab, ab), 1e-6), 0, 1)
            q = a + t * ab
            d = _dist(p, q)
            if best_d is None or d < best_d:
                best, best_d = q, d
        return int(best[0]), int(best[1])

    def _at_end(p, poly, end_frac=0.25, side_frac=0.15):
        e0, e1 = poly[1] - poly[0], poly[2] - poly[1]
        long_e, short_e = (e0, e1) if np.linalg.norm(e0) >= np.linalg.norm(e1) else (e1, e0)
        L, S = np.linalg.norm(long_e), np.linalg.norm(short_e)
        if L < 1.3 * max(S, 1):
            return None
        u = long_e / L
        v = np.array([-u[1], u[0]], np.float32)
        d = np.array(p, np.float32) - poly.mean(axis=0)
        t = np.dot(d, u) / L
        s = abs(np.dot(d, v))
        return abs(t) > 0.5 - end_frac and s < S / 2 + L * side_frac

    # 1. 칼(또는 가위) 탐지
    r = yolo_model(frame_bgr, imgsz=480, conf=0.22, verbose=False)[0]
    blade = None
    if r.obb is not None:
        for poly, c, cls in zip(r.obb.xyxyxyxy.cpu().numpy(), r.obb.conf.tolist(), r.obb.cls.tolist()):
            if int(cls) in blade_ids and (blade is None or c > blade["conf"]):
                blade = {"conf": c, "name": yolo_model.names[int(cls)], "poly": poly.astype(np.float32)}
    elif r.boxes is not None:
        for i, b in enumerate(r.boxes):
            cls = int(b.cls[0])
            if cls not in blade_ids:
                continue
            c = float(b.conf[0])
            if blade is not None and c <= blade["conf"]:
                continue
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
            poly = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float32)
            if r.masks is not None and i < len(r.masks.xy):
                seg = r.masks.xy[i]
                if len(seg) >= 3:
                    poly = cv2.boxPoints(cv2.minAreaRect(seg.astype(np.float32))).astype(np.float32)
            blade = {"conf": c, "name": yolo_model.names[cls], "poly": poly}

    # 2. 손 관절 탐지
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    hands = []
    for hand in res.hand_landmarks:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand]
        palm_w = max(_dist(pts[5], pts[17]), 1.0)
        hands.append({"pts": pts, "palm_w": palm_w})

    grip = assist = ratio = tip_idx = None
    close = danger = False
    exposed = 0
    dist_px = None

    if blade is not None and hands:
        poly = blade["poly"]
        gaps = [_dist_to_blade(hd["pts"][9], poly) for hd in hands]
        ends = [_at_end(hd["pts"][9], poly) for hd in hands]

        if len(hands) >= 2:
            if ends[0] is True and ends[1] is not True:
                grip = 0
            elif ends[1] is True and ends[0] is not True:
                grip = 1
            else:
                grip = gaps.index(min(gaps))
            assist = 1 - grip
        elif ends[0] is True or (ends[0] is None and gaps[0] <= hands[0]["palm_w"] * 0.3):
            grip = 0
        else:
            assist = 0

        if assist is not None:
            a = hands[assist]
            ratios = [_dist_to_blade(a["pts"][i], poly) / a["palm_w"] for i in TIPS]
            k = ratios.index(min(ratios))
            ratio, tip_idx = ratios[k], TIPS[k]
            dist_px = round(float(ratio * a["palm_w"]), 1)
            close = ratio <= MARGIN

            for pip, tip in FINGERS:
                d_pip, d_tip = _dist_to_blade(a["pts"][pip], poly), _dist_to_blade(a["pts"][tip], poly)
                if not (d_pip == 0 and d_tip == 0) and (d_tip < d_pip - a["palm_w"] * 0.1):
                    exposed += 1
            danger = close and exposed >= 1

    # 3. 프론트엔드 투명 캔버스(60fps 무끊김 오버레이)용 경량 좌표 데이터 구성
    blade_poly_list = blade["poly"].astype(int).tolist() if blade else None
    hands_payload = []
    for i, hd in enumerate(hands):
        role = "grip" if i == grip else ("assist" if i == assist else "other")
        hands_payload.append({"role": role, "pts": hd["pts"]})

    nearest_line = None
    if ratio is not None and blade and assist is not None:
        tip_pt = hands[assist]["pts"][tip_idx]
        near_pt = _nearest_on_blade(tip_pt, blade["poly"])
        nearest_line = [list(tip_pt), list(near_pt)]

    status_str = "DANGER" if danger else ("WARNING" if close else "SAFE")
    return {
        "status": status_str,
        "blade_detected": blade is not None,
        "hands_count": len(hands),
        "ratio": round(float(ratio), 3) if ratio is not None else None,
        "distance_px": dist_px,
        "exposed_fingers": exposed,
        "frame_w": w,
        "frame_h": h,
        "blade_poly": blade_poly_list,
        "hands": hands_payload,
        "nearest_line": nearest_line,
    }


class VisionStatusReport(BaseModel):
    status: Literal["SAFE", "WARNING", "DANGER"] = Field(..., description="현재 위험 상태")
    hazard_type: str = Field("KNIFE_PROXIMITY", description="위험 유형 (KNIFE_PROXIMITY, UNATTENDED 등)")
    message: Optional[str] = Field(None, description="경고 메시지")
    ratio: Optional[float] = Field(None, description="손바닥 폭 대비 손끝-칼 정규화 거리 비율")
    distance_px: Optional[float] = Field(None, description="손끝-칼 픽셀 거리")
    session_id: Optional[int] = Field(None, description="특정 조리 세션 ID (생략 시 가장 최근 진행 중인 세션에 자동 연결)")
    step_number: Optional[int] = Field(None, description="현재 조리 단계 번호")


def _sync_active_session_step_flags(db: Session, session_id: Optional[int] = None) -> Optional[CookingSession]:
    """
    현재 진행 중인 조리 세션의 단계별 안전 모니터링 플래그(칼 감지 / 자리비움 감지)를 조회하여
    vision_state에 동기화하고 대상 세션을 반환합니다.
    """
    try:
        target_session = None
        if session_id:
            target_session = db.get(CookingSession, session_id)
        else:
            target_session = (
                db.query(CookingSession)
                .filter(CookingSession.is_completed == False)
                .order_by(desc(CookingSession.started_at))
                .first()
            )

        if target_session and target_session.recipe and target_session.recipe.steps:
            step_num = target_session.current_step or 1
            vision_state["current_step"] = step_num
            current_step_obj = next(
                (s for s in target_session.recipe.steps if s.step_number == step_num),
                None
            )
            if current_step_obj:
                vision_state["is_knife_monitoring"] = current_step_obj.is_knife_monitoring
                vision_state["is_unattended_monitoring"] = current_step_obj.is_unattended_monitoring
                vision_state["active_hazards"] = current_step_obj.active_hazards
        return target_session
    except Exception:
        return None


def get_current_vision_status() -> dict:
    """
    현재 주방의 실시간 안전 상태 및 현재 조리 단계의 안전 감지 모드를 반환합니다.
    비전 모듈로부터 일정 시간(STATE_EXPIRY_SEC) 동안 새로운 위험 신호가 없으면 SAFE로 자동 복귀합니다.
    """
    now = time.time()
    if vision_state["status"] != "SAFE" and (now - vision_state["updated_at"] > STATE_EXPIRY_SEC):
        vision_state["status"] = "SAFE"
        vision_state["hazard_type"] = "NONE"
        vision_state["message"] = "[안전] 현재 주방은 안전합니다."

    return {
        "status": vision_state["status"],
        "hazard_type": vision_state["hazard_type"],
        "message": vision_state["message"],
        "ratio": vision_state["ratio"],
        "distance_px": vision_state["distance_px"],
        "current_step": vision_state["current_step"],
        "is_knife_monitoring": vision_state["is_knife_monitoring"],
        "is_unattended_monitoring": vision_state["is_unattended_monitoring"],
        "active_hazards": vision_state["active_hazards"],
    }


@router.get("/status", summary="실시간 비전 안전 상태 및 단계별 감시 모드 조회")
def read_vision_status(db: Session = Depends(get_db)):
    """프론트엔드 및 비전 모듈에서 현재 주방 위험 여부(SAFE/WARNING/DANGER)와 단계별 감시 플래그를 확인합니다."""
    _sync_active_session_step_flags(db)
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
    - 응답에 현재 단계의 is_knife_monitoring / is_unattended_monitoring 정보를 함께 내려줍니다.
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

    # 활성 세션 및 단계별 모니터링 플래그 동기화
    target_session = _sync_active_session_step_flags(db, payload.session_id)
    logged_to_db = False

    # 2. WARNING / DANGER 발생 시 디바운싱(3초 쿨타임) 적용 후 DB 자동 기록
    if payload.status in ("WARNING", "DANGER"):
        if now - vision_state["last_db_log_at"] >= DEBOUNCE_COOLDOWN_SEC:
            vision_state["last_db_log_at"] = now
            try:
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
        "logged_to_db": logged_to_db,
        "current_step": vision_state["current_step"],
        "is_knife_monitoring": vision_state["is_knife_monitoring"],
        "is_unattended_monitoring": vision_state["is_unattended_monitoring"],
        "active_hazards": vision_state["active_hazards"],
    }


@router.post("/detect", summary="모바일/웹 카메라 실시간 프레임 비전 분석 API")
async def detect_objects(
    file: UploadFile = File(...),
    session_id: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    """
    모바일 앱(또는 웹캠)으로부터 실시간 프레임을 받아 step6 알고리즘(YOLO + MediaPipe Hands)으로
    칼 다각형과 고양이손 위험 여부를 판별하고, 오버레이된 이미지(Base64)와 위험 상태를 반환합니다.
    """
    import cv2
    import numpy as np

    raw_bytes = await file.read()
    arr = np.frombuffer(raw_bytes, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return {"status": "error", "message": "유효하지 않은 이미지 프레임입니다."}

    analysis = _analyze_mobile_frame(frame)

    # 상태 업데이트 및 디바운싱 DB 로깅 연동
    report = VisionStatusReport(
        status=analysis["status"],
        hazard_type="KNIFE_PROXIMITY",
        ratio=analysis["ratio"],
        distance_px=analysis["distance_px"],
        session_id=session_id
    )
    status_res = await update_vision_status(report, db)

    return {
        "status": "success",
        "vision_status": analysis["status"],
        "blade_detected": analysis["blade_detected"],
        "hands_count": analysis["hands_count"],
        "ratio": analysis["ratio"],
        "distance_px": analysis["distance_px"],
        "frame_w": analysis["frame_w"],
        "frame_h": analysis["frame_h"],
        "blade_poly": analysis["blade_poly"],
        "hands": analysis["hands"],
        "nearest_line": analysis["nearest_line"],
        "step_info": status_res,
        "message": vision_state["message"]
    }
