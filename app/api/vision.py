import time
import math
import json
import base64
import asyncio
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal, List, Dict, Set
from fastapi import APIRouter, UploadFile, File, Form, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.database import get_db, SessionLocal
from app.models.session import CookingSession, SafetyLog
from app.api.websocket import manager
from vision.unattended import UnattendedTracker, TEST_LEVELS

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
    "last_flag_sync_at": 0.0, # DB 세션 플래그 캐싱 시각
}

# =====================================================================
# 모바일/웹 카메라 실시간 프레임 분석용 Lazy-Loaded 비전 엔진 (step6 알고리즘 호환)
# =====================================================================
_vision_engine = {
    "initialized": False,
    "yolo": None,
    "blade_ids": [],
    "person_ids": [],
    "landmarker": None,
}
_vision_lock = threading.Lock()
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
    person_ids = [k for k, v in yolo_model.names.items() if v == "person"]

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
    _vision_engine["person_ids"] = person_ids
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
    person_ids = _vision_engine["person_ids"]
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

    # 1. 칼(또는 가위) 및 사람(person) 탐지 (imgsz=320으로 추론 속도 2배 가속)
    r = yolo_model(frame_bgr, imgsz=320, conf=0.22, verbose=False)[0]
    blade = None
    person_detected = False
    if r.obb is not None:
        for poly, c, cls in zip(r.obb.xyxyxyxy.cpu().numpy(), r.obb.conf.tolist(), r.obb.cls.tolist()):
            if int(cls) in person_ids and c >= 0.45:
                person_detected = True
            if int(cls) in blade_ids and (blade is None or c > blade["conf"]):
                blade = {"conf": c, "name": yolo_model.names[int(cls)], "poly": poly.astype(np.float32)}
    elif r.boxes is not None:
        for i, b in enumerate(r.boxes):
            cls = int(b.cls[0])
            c = float(b.conf[0])
            if cls in person_ids and c >= 0.45:
                person_detected = True
            if cls not in blade_ids:
                continue
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
        "person_detected": person_detected,
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


def _sync_active_session_step_flags(db: Session, session_id: Optional[int] = None, force: bool = False) -> Optional[CookingSession]:
    """
    현재 진행 중인 조리 세션의 단계별 안전 모니터링 플래그(칼 감지 / 자리비움 감지)를 조회하여
    vision_state에 동기화하고 대상 세션을 반환합니다. (초당 수십 회 호출 시 DB 병목 방지를 위해 2초 캐싱)
    """
    now = time.time()
    if not force and (now - vision_state.get("last_flag_sync_at", 0.0) < 2.0):
        return None
    vision_state["last_flag_sync_at"] = now
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
                if not target_session:
                    target_session = _sync_active_session_step_flags(db, payload.session_id, force=True)
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


# 사용자(user_id)별 실시간 카메라 미러링 버퍼 및 WebSocket 뷰어 연결 풀
user_streams: Dict[int, dict] = {}
mirror_viewers: Dict[int, Set[WebSocket]] = {}


def _ensure_user_stream(uid: int) -> dict:
    if uid not in user_streams:
        user_streams[uid] = {
            "updated_at": 0.0,
            "status": "SAFE",
            "message": "[안전] 현재 주방은 안전합니다.",
            "frame_b64": None,
            "frame_w": 320,
            "frame_h": 240,
            "blade_poly": None,
            "hands": [],
            "nearest_line": None,
            "session_id": None,
            "current_step": 1,
            "fire_on": False,
            "ai_running": False,
            "last_ai_at": 0.0,
            "db_checked_at": 0.0,
            "unattended_tracker": UnattendedTracker(TEST_LEVELS),
        }
    return user_streams[uid]


async def _broadcast_to_viewers(uid: int, payload: dict):
    """동일 user_id로 접속 중인 모든 PC/뷰어 WebSocket에 프레임 또는 오버레이 좌표를 즉시 푸시합니다."""
    viewers = mirror_viewers.get(uid)
    if not viewers:
        return
    dead = []
    msg_text = json.dumps(payload, ensure_ascii=False)
    for ws in list(viewers):
        try:
            await asyncio.wait_for(ws.send_text(msg_text), timeout=0.35)
        except Exception:
            dead.append(ws)
    for ws in dead:
        viewers.discard(ws)


async def _run_background_ai_on_stream(uid: int, frame_b64: str, sender_ws: WebSocket):
    """
    WebSocket으로 수신된 최신 프레임에 대해 백그라운드 워커 스레드에서 YOLO + MediaPipe + 자리비움 추론을 수행하고,
    완료 즉시 송신측(휴대폰)과 수신측(PC 뷰어) 모두에게 AI 오버레이 좌표를 브로드캐스트합니다.
    * 영상 미러링 루프를 단 1ms도 블로킹하지 않으며, HTTP 다중 요청 병목을 완전히 제거합니다!
    """
    import cv2
    import numpy as np

    stream = _ensure_user_stream(uid)
    try:
        def _decode_and_infer(b64_str: str):
            raw = base64.b64decode(b64_str)
            arr = np.frombuffer(raw, np.uint8)
            frm = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frm is None:
                return None
            with _vision_lock:
                return _analyze_mobile_frame(frm)

        analysis = await asyncio.to_thread(_decode_and_infer, frame_b64)
        if not analysis:
            return

        is_heat_mode = bool(stream.get("fire_on")) or bool(vision_state.get("is_unattended_monitoring"))
        tracker: UnattendedTracker = stream["unattended_tracker"]
        present = bool(analysis.get("person_detected") or analysis["hands_count"] > 0)
        u_level, absent_sec = tracker.update(present=present, now=time.time(), fire_on=is_heat_mode)

        final_status = analysis["status"]
        hazard_type = "KNIFE_PROXIMITY"
        if final_status == "DANGER":
            msg = "[위험] 칼날과 손가락이 너무 가깝습니다! 고양이 손을 유지하세요!"
        elif final_status == "WARNING":
            msg = "[주의] 칼날 근처에 손이 접근 중입니다. 주의하세요."
        else:
            msg = "[안전] 현재 주방은 안전합니다."

        if final_status == "SAFE" and is_heat_mode:
            if u_level in ("WARNING", "DANGER"):
                final_status = u_level
                hazard_type = "UNATTENDED"
                msg = f"[자리 비움] {int(absent_sec)}초째 자리에 없어요. 불을 확인하세요!"
            elif u_level == "INFO":
                msg = f"[자리 비움 감지 중] {int(absent_sec)}초째 자리에 없습니다. (10초 이상 시 주의 경고)"

        now = time.time()
        vision_state["status"] = final_status
        vision_state["hazard_type"] = hazard_type if final_status != "SAFE" else "NONE"
        vision_state["message"] = msg
        vision_state["ratio"] = analysis["ratio"]
        vision_state["distance_px"] = analysis["distance_px"]
        vision_state["updated_at"] = now

        stream["status"] = final_status
        stream["message"] = msg
        stream["frame_w"] = analysis["frame_w"]
        stream["frame_h"] = analysis["frame_h"]
        stream["blade_poly"] = analysis["blade_poly"]
        stream["hands"] = analysis["hands"]
        stream["nearest_line"] = analysis["nearest_line"]

        # WARNING/DANGER 발생 시 3초 디바운싱 DB 로깅 (백그라운드 세션)
        if final_status in ("WARNING", "DANGER") and (now - vision_state["last_db_log_at"] >= DEBOUNCE_COOLDOWN_SEC):
            vision_state["last_db_log_at"] = now

            def _log_hazard_sync():
                db = SessionLocal()
                try:
                    sess_id = stream.get("session_id")
                    target_sess = db.get(CookingSession, sess_id) if sess_id else (
                        db.query(CookingSession)
                        .filter(CookingSession.user_id == uid, CookingSession.is_completed == False)
                        .order_by(desc(CookingSession.started_at))
                        .first()
                    )
                    if target_sess:
                        new_log = SafetyLog(
                            session_id=target_sess.id,
                            step_number=target_sess.current_step or 1,
                            hazard_type=hazard_type,
                            level=final_status,
                            message=msg,
                            distance_px=analysis["distance_px"],
                            duration_seconds=round(float(absent_sec), 1) if hazard_type == "UNATTENDED" else None,
                            detected_at=datetime.utcnow(),
                        )
                        db.add(new_log)
                        db.commit()
                except Exception:
                    pass
                finally:
                    db.close()

            asyncio.create_task(asyncio.to_thread(_log_hazard_sync))

        overlay_payload = {
            "type": "OVERLAY",
            "is_streaming": True,
            "status": final_status,
            "vision_status": final_status,
            "message": msg,
            "frame_w": analysis["frame_w"],
            "frame_h": analysis["frame_h"],
            "blade_poly": analysis["blade_poly"],
            "hands": analysis["hands"],
            "nearest_line": analysis["nearest_line"],
            "active_session_id": stream.get("session_id"),
            "current_step": stream.get("current_step", 1),
        }

        # 1) 휴대폰(송신기) 화면의 오버레이 캔버스 즉시 갱신
        try:
            await asyncio.wait_for(sender_ws.send_text(json.dumps(overlay_payload, ensure_ascii=False)), timeout=0.25)
        except Exception:
            pass

        # 2) PC(뷰어) 화면의 오버레이 캔버스 즉시 갱신
        await _broadcast_to_viewers(uid, overlay_payload)
    except Exception:
        pass
    finally:
        stream["ai_running"] = False


@router.websocket("/ws/mirror/{user_id}")
async def ws_user_mirror(websocket: WebSocket, user_id: int, role: str = "viewer"):
    """
    초고속(20~30fps) 실시간 영상 및 AI 오버레이 통합 WebSocket:
    - role=sender (휴대폰): 카메라 JPEG 프레임(Base64)을 전송하면
      1) PC 뷰어에게 0ms 지연으로 즉시 중계하고 ACK를 반환하며,
      2) 백그라운드 스레드에서 AI 비전(칼/손/자리비움)을 비동기 실행해 완료 즉시 휴대폰과 PC 양쪽에 OVERLAY를 푸시합니다.
    - role=viewer (PC 홈페이지): 휴대폰이 보내는 영상 프레임과 AI 칼·손 좌표를 실시간 수신합니다.
    """
    await websocket.accept()
    uid = user_id or 1
    stream = _ensure_user_stream(uid)

    if role == "viewer":
        if uid not in mirror_viewers:
            mirror_viewers[uid] = set()
        mirror_viewers[uid].add(websocket)
        try:
            # 접속 직후 현재 스트림 상태 즉시 1회 전송
            now = time.time()
            if stream.get("frame_b64") and (now - stream.get("updated_at", 0) < 3.5):
                await websocket.send_text(json.dumps({
                    "type": "FULL",
                    "is_streaming": True,
                    "frame_b64": stream["frame_b64"],
                    "frame_w": stream["frame_w"],
                    "frame_h": stream["frame_h"],
                    "status": stream["status"],
                    "message": stream["message"],
                    "blade_poly": stream["blade_poly"],
                    "hands": stream["hands"],
                    "nearest_line": stream["nearest_line"],
                    "active_session_id": stream.get("session_id"),
                    "current_step": stream.get("current_step", 1),
                }, ensure_ascii=False))
            while True:
                msg = await websocket.receive_text()
                if msg == "PING":
                    await websocket.send_text('{"type":"PONG"}')
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if uid in mirror_viewers:
                mirror_viewers[uid].discard(websocket)
    else:
        # role=sender (휴대폰 카메라 송신기)
        try:
            while True:
                raw_msg = await websocket.receive_text()
                if raw_msg == "PING":
                    await websocket.send_text('{"type":"PONG"}')
                    continue
                data = json.loads(raw_msg)
                msg_type = data.get("type")
                if msg_type == "PING":
                    await websocket.send_text('{"type":"PONG"}')
                    continue
                if msg_type == "STOP":
                    stream["updated_at"] = 0.0
                    await _broadcast_to_viewers(uid, {"type": "STOP", "is_streaming": False})
                    continue

                frame_b64 = data.get("frame_b64")
                if frame_b64:
                    now_ts = time.time()
                    stream["updated_at"] = now_ts
                    stream["frame_b64"] = frame_b64
                    if data.get("frame_w"):
                        stream["frame_w"] = data["frame_w"]
                    if data.get("frame_h"):
                        stream["frame_h"] = data["frame_h"]
                    if data.get("session_id"):
                        stream["session_id"] = data["session_id"]
                    if "fire_on" in data and data["fire_on"] is not None:
                        stream["fire_on"] = bool(data["fire_on"])

                    # 1) 송신측(휴대폰)에 즉시 ACK부터 반환하여 네트워크 왕복 지연을 최소화
                    await websocket.send_text('{"type":"ACK"}')

                    # 2) PC 뷰어들에게 지연 없이 즉시 영상 프레임 + 최신 AI 오버레이 브로드캐스트
                    await _broadcast_to_viewers(uid, {
                        "type": "FRAME",
                        "is_streaming": True,
                        "frame_b64": frame_b64,
                        "frame_w": stream["frame_w"],
                        "frame_h": stream["frame_h"],
                        "status": stream["status"],
                        "message": stream["message"],
                        "blade_poly": stream["blade_poly"],
                        "hands": stream["hands"],
                        "nearest_line": stream["nearest_line"],
                        "active_session_id": stream.get("session_id"),
                        "current_step": stream.get("current_step", 1),
                    })

                    # 3) AI 추론이 현재 돌고 있지 않다면 즉시 백그라운드 태스크로 최신 프레임 AI 추론 시작 (HTTP 중복 업로드 제거!)
                    if not stream.get("ai_running"):
                        stream["ai_running"] = True
                        stream["last_ai_at"] = now_ts
                        asyncio.create_task(_run_background_ai_on_stream(uid, frame_b64, websocket))
        except WebSocketDisconnect:
            stream["updated_at"] = 0.0
            await _broadcast_to_viewers(uid, {"type": "STOP", "is_streaming": False})
        except Exception:
            pass


@router.post("/push-frame", summary="초경량 실시간 영상 프레임 전용 푸시 (AI 추론 대기 없음)")
async def push_live_frame(
    file: UploadFile = File(...),
    user_id: Optional[int] = Form(1),
    session_id: Optional[int] = Form(None),
    frame_w: Optional[int] = Form(320),
    frame_h: Optional[int] = Form(240),
):
    """WebSocket 연결이 제한된 환경에서도 AI 추론 대기 없이 영상 프레임만 즉시 중계합니다."""
    raw_bytes = await file.read()
    uid = user_id or 1
    stream = _ensure_user_stream(uid)
    b64 = base64.b64encode(raw_bytes).decode("utf-8")
    stream["updated_at"] = time.time()
    stream["frame_b64"] = b64
    stream["frame_w"] = frame_w or 320
    stream["frame_h"] = frame_h or 240
    if session_id:
        stream["session_id"] = session_id

    await _broadcast_to_viewers(uid, {
        "type": "FRAME",
        "is_streaming": True,
        "frame_b64": b64,
        "frame_w": stream["frame_w"],
        "frame_h": stream["frame_h"],
        "status": stream["status"],
        "message": stream["message"],
        "blade_poly": stream["blade_poly"],
        "hands": stream["hands"],
        "nearest_line": stream["nearest_line"],
        "active_session_id": stream.get("session_id"),
        "current_step": stream.get("current_step", 1),
    })
    return {"ok": True}


@router.get("/mirror", summary="동일 로그인 사용자의 휴대폰 카메라 및 조리 상태 PC 실시간 미러링")
def get_user_live_mirror(
    user_id: int = 1,
    db: Session = Depends(get_db)
):
    """
    같은 아이디(user_id)로 로그인한 다른 기기(PC 등)에서 휴대폰이 촬영 중인 실시간 영상,
    AI 칼/손 인식 좌표, 그리고 현재 요리 진행 단계를 실시간으로 함께 볼 수 있게 반환합니다.
    """
    now = time.time()
    stream = _ensure_user_stream(user_id)
    is_streaming = bool(stream.get("frame_b64") and (now - stream.get("updated_at", 0) < 3.5))

    # DB 세션 조회는 1.5초에 최대 1회만 수행하여 프레임 조회 속도를 극대화
    if now - stream.get("db_checked_at", 0) > 1.5:
        stream["db_checked_at"] = now
        active_sess = (
            db.query(CookingSession)
            .filter(CookingSession.user_id == user_id, CookingSession.is_completed == False)
            .order_by(desc(CookingSession.started_at))
            .first()
        )
        if active_sess:
            stream["session_id"] = active_sess.id
            stream["current_step"] = active_sess.current_step

    if not is_streaming:
        return {
            "is_streaming": False,
            "status": "SAFE",
            "message": "[안전] 현재 주방은 안전합니다.",
            "active_session_id": stream.get("session_id"),
            "current_step": stream.get("current_step", 1),
        }

    return {
        "is_streaming": True,
        "status": stream["status"],
        "message": stream["message"],
        "frame_b64": stream["frame_b64"],
        "frame_w": stream["frame_w"],
        "frame_h": stream["frame_h"],
        "blade_poly": stream["blade_poly"],
        "hands": stream["hands"],
        "nearest_line": stream["nearest_line"],
        "active_session_id": stream.get("session_id"),
        "current_step": stream.get("current_step", 1),
    }


@router.post("/detect", summary="모바일/웹 카메라 실시간 프레임 비전 분석 API (칼 위험 + 화구 자리 비움 통합)")
async def detect_objects(
    file: UploadFile = File(...),
    session_id: Optional[int] = Form(None),
    user_id: Optional[int] = Form(1),
    fire_on: Optional[bool] = Form(None),
    db: Session = Depends(get_db)
):
    """
    모바일 앱(또는 웹캠)으로부터 실시간 프레임을 받아:
    1) step6 알고리즘(YOLO + MediaPipe Hands)으로 칼 다각형과 고양이손 위험 여부를 판별하고,
    2) step7 알고리즘(UnattendedTracker)으로 화구 감시(fire_on / is_unattended_monitoring) 단계에서
       사람(person)과 손(hand)이 모두 화면에서 사라진 시간(5/10/15초)을 추적해 자리 비움 경고를 발생시킵니다.
    * 무거운 YOLO/MediaPipe 추론을 별도 워커 스레드(asyncio.to_thread)에서 실행하여 영상 미러링 프레임이 절대 끊기지 않도록 보장합니다.
    """
    import cv2
    import numpy as np

    raw_bytes = await file.read()

    def _decode_and_analyze(b: bytes):
        with _vision_lock:
            arr = np.frombuffer(b, np.uint8)
            frm = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frm is None:
                return None
            return _analyze_mobile_frame(frm)

    analysis = await asyncio.to_thread(_decode_and_analyze, raw_bytes)
    if analysis is None:
        return {"status": "error", "message": "유효하지 않은 이미지 프레임입니다."}

    uid = user_id or 1
    stream = _ensure_user_stream(uid)

    # 현재 조리 세션 단계의 감시 플래그 확인 (칼 감시 / 화구 자리비움 감시)
    _sync_active_session_step_flags(db, session_id)
    is_heat_mode = fire_on if fire_on is not None else bool(vision_state["is_unattended_monitoring"])

    # 화구 자리 비움(UnattendedTracker) 업데이트: 사람(person) 또는 손(hand)이 보이면 present=True
    tracker: UnattendedTracker = stream["unattended_tracker"]
    present = bool(analysis.get("person_detected") or analysis["hands_count"] > 0)
    u_level, absent_sec = tracker.update(present=present, now=time.time(), fire_on=is_heat_mode)

    final_status = analysis["status"]
    hazard_type = "KNIFE_PROXIMITY"
    custom_msg = None

    # 칼 위험이 없을 때 화구 자리 비움 경고가 발생하면 자리 비움 상태 반영
    if final_status == "SAFE" and is_heat_mode:
        if u_level in ("WARNING", "DANGER"):
            final_status = u_level
            hazard_type = "UNATTENDED"
            custom_msg = f"[자리 비움] {int(absent_sec)}초째 자리에 없어요. 불을 확인하세요!"
        elif u_level == "INFO":
            custom_msg = f"[자리 비움 감지 중] {int(absent_sec)}초째 자리에 없습니다. (10초 이상 시 주의 경고)"

    # 상태 업데이트 및 디바운싱 DB 로깅 연동
    report = VisionStatusReport(
        status=final_status,
        hazard_type=hazard_type,
        message=custom_msg,
        ratio=analysis["ratio"],
        distance_px=analysis["distance_px"],
        session_id=session_id
    )
    status_res = await update_vision_status(report, db)

    # 최신 AI 좌표 및 위험 상태를 사용자 스트림 버퍼에 갱신 후 PC 뷰어들에게 즉시 브로드캐스트
    now_ts = time.time()
    # WebSocket 송신 채널이 이미 최신 프레임을 보내고 있다면 200ms 전의 과거 프레임으로 덮어쓰지 않음
    if not stream.get("frame_b64") or (now_ts - stream.get("updated_at", 0) > 0.6):
        stream["frame_b64"] = base64.b64encode(raw_bytes).decode("utf-8")
    stream["updated_at"] = now_ts
    stream["status"] = final_status
    stream["message"] = vision_state["message"]
    stream["frame_w"] = analysis["frame_w"]
    stream["frame_h"] = analysis["frame_h"]
    stream["blade_poly"] = analysis["blade_poly"]
    stream["hands"] = analysis["hands"]
    stream["nearest_line"] = analysis["nearest_line"]
    if session_id:
        stream["session_id"] = session_id

    await _broadcast_to_viewers(uid, {
        "type": "OVERLAY",
        "is_streaming": True,
        "status": stream["status"],
        "message": stream["message"],
        "frame_w": stream["frame_w"],
        "frame_h": stream["frame_h"],
        "blade_poly": stream["blade_poly"],
        "hands": stream["hands"],
        "nearest_line": stream["nearest_line"],
        "active_session_id": stream.get("session_id"),
        "current_step": status_res.get("current_step", 1),
    })

    return {
        "status": "success",
        "vision_status": final_status,
        "hazard_type": hazard_type,
        "blade_detected": analysis["blade_detected"],
        "person_detected": analysis["person_detected"],
        "hands_count": analysis["hands_count"],
        "unattended_level": u_level,
        "absent_seconds": round(float(absent_sec), 1),
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
