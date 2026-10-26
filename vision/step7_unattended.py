# 비전 10단계: 자리 비움(UNATTENDED) 감지 — 테스트 실행용
# 판단 로직은 unattended.py(UnattendedTracker), 여기서는 카메라·감지·화면·전송만
# 사람(YOLO person) 또는 손(MediaPipe)이 보이면 '있음'
# 사용: python step7_unattended.py [영상경로 또는 http://폰IP:8080/video]   (없으면 웹캠)

import sys
import json
import time
import threading
import urllib.request
import cv2
import mediapipe as mp
import torch
from pathlib import Path
from ultralytics import YOLO
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from unattended import UnattendedTracker, TEST_LEVELS, REAL_LEVELS

torch.set_num_threads(2)

# ===== 설정 =====
VIDEO = sys.argv[1] if len(sys.argv) > 1 else 0
TEST = False                        # True: 5/10/15초, False: 30/60/180 초
PERSON_CONF = 0.5
IMGSZ = 320
COLORS = {"SAFE": (0, 200, 0), "INFO": (255, 160, 0), "WARNING": (0, 140, 255), "DANGER": (0, 0, 255)}

SEND_API = True                    # 서버 없이 테스트할 땐 False
BACKEND_URL = "http://localhost:8000/api/vision/status"
FIRE_ON = True                     # 임시: 나중에 음성("불 켰어/껐어") 값으로 교체

BASE_DIR = Path(__file__).resolve().parent
HAND_PATH = BASE_DIR / "weights" / "hand_landmarker.task"
if not HAND_PATH.exists():
    HAND_PATH.parent.mkdir(exist_ok=True)
    urllib.request.urlretrieve(
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        str(HAND_PATH))

# ===== 모델 (루프 밖에서 한 번) =====
model = YOLO("yolo11s.pt")
PERSON_ID = next(k for k, v in model.names.items() if v == "person")   # = 0
options = vision.HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_buffer=HAND_PATH.read_bytes()),
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2,
)
landmarker = vision.HandLandmarker.create_from_options(options)
tracker = UnattendedTracker(TEST_LEVELS if TEST else REAL_LEVELS)


def detect_presence(frame, ts):
    r = model(frame, conf=PERSON_CONF, imgsz=IMGSZ, classes=[PERSON_ID], verbose=False)[0]
    person = len(r.boxes) > 0
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
    hand = len(res.hand_landmarks) > 0
    return person, hand, r


# ===== 백엔드 전송 =====
# API는 SAFE/WARNING/DANGER만 받음 → INFO는 SAFE로 보냄 (화면 표시만 INFO)
sync = {"status": "SAFE", "sent": 0.0, "warned": False}


def notify_backend(level, absent):
    if not SEND_API:
        return
    status = level if level in ("WARNING", "DANGER") else "SAFE"
    now_t = time.time()
    # 상태가 바뀌었거나, 경고 중이면 1초마다 전송
    if status == sync["status"] and (status == "SAFE" or now_t - sync["sent"] < 1.0):
        return
    sync["status"], sync["sent"] = status, now_t
    payload = {
        "status": status,
        "hazard_type": "UNATTENDED",
        "message": (f"[자리 비움] {int(absent)}초째 자리에 없어요. 불을 확인하세요!"
                    if status != "SAFE" else None),
    }

    def _send():
        try:
            req = urllib.request.Request(
                BACKEND_URL, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=1.0).read()
        except Exception as e:
            if not sync["warned"]:          # 서버 꺼져 있으면 한 번만 알림
                print(f"[서버 전송 실패] {e}  (서버 없이 계속 진행)")
                sync["warned"] = True

    threading.Thread(target=_send, daemon=True).start()


# ===== 루프 =====
cap = cv2.VideoCapture(VIDEO)
if not cap.isOpened():
    sys.exit(f"[영상 열기 실패] {VIDEO}")
start = time.perf_counter()
last_ts = -1
prev_level = "SAFE"

while True:
    ret, frame = cap.read()
    if not ret:
        break

    now = time.perf_counter()
    ts = int((now - start) * 1000)
    if ts <= last_ts:
        ts = last_ts + 1
    last_ts = ts

    person, hand, r = detect_presence(frame, ts)
    level, absent = tracker.update(person or hand, now, FIRE_ON)

    if level != prev_level:        # 등급이 바뀌었을 때만
        print(f"[{absent:5.1f}s] {prev_level} -> {level}")
        prev_level = level
    notify_backend(level, absent)

    annotated = r.plot()
    cv2.putText(annotated, f"{level}  absent {absent:.1f}s", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, COLORS[level], 2)
    cv2.putText(annotated, f"person:{person}  hand:{hand}  fire:{FIRE_ON}", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.imshow("unattended", annotated)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
landmarker.close()
cv2.destroyAllWindows()