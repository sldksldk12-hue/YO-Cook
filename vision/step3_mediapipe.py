import cv2
import time
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "weights" / "hand_landmarker.task"

# 루프 밖: 설정 + 탐지기 만들기
options = vision.HandLandmarkerOptions(
    # 한글 경로 문제 → 파이썬이 파일을 읽어서 내용(bytes)을 직접 넘김
    base_options=python.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.5,  # 처음에 손을 찾을 때
    min_hand_presence_confidence=0.5,   # 손이 아직 화면에 있는지 판단할 때
    min_tracking_confidence=0.5,        # 프레임 사이에 손을 계속 추적할 때
)
landmarker = vision.HandLandmarker.create_from_options(options)

cap = cv2.VideoCapture(0)
printed = False
start = time.perf_counter()
prev = start
last_ts = -1

while True:
    ret, frame = cap.read()
    if not ret:
        break

    if not printed:
        print(frame.shape)
        printed = True

    # FPS 계산
    now = time.perf_counter()
    dt = now - prev
    fps = 1 / dt if dt > 0 else 0       # 0으로 나누기 방지
    prev = now

    # timestamp: 항상 이전 값보다 크게
    timestamp_ms = int((now - start) * 1000)
    if timestamp_ms <= last_ts:
        timestamp_ms = last_ts + 1
    last_ts = timestamp_ms

    # 손 추적
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(mp_image, timestamp_ms)
    h, w, _ = frame.shape

    for hand in result.hand_landmarks:      # 손 개수만큼 (0~2번)
        for lm in hand:                     # 점 21개
            px = int(lm.x * w)
            py = int(lm.y * h)
            cv2.circle(frame, (px, py), 4, (0, 0, 255), -1)
    # 화면 표시
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 1)
    cv2.imshow("cam", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
landmarker.close()
cv2.destroyAllWindows()