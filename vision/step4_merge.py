# 비전 4단계: YOLO + MediaPipe


import cv2
import time
import mediapipe as mp
from ultralytics import YOLO
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pathlib import Path
import torch
torch.set_num_threads(2)  # MediaPipe와 CPU 다툼 줄이기 (18/8/4/2 비교 → 2가 가장 빠름)

# 모델을 vision파일 밖에서도 찾을수 있게하는 설정
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "weights" / "hand_landmarker.task"

# MediaPipe 랜드마커 옵션 지정
options = vision.HandLandmarkerOptions(
    # 한글경로문제를 파이썬이 파일을 읽어서 내용을 직접 넘기는방식
    base_options=python.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
    # 비디오 모드를사용해서 처음이아닌 이전 프레임기반으로 손위치를 찾음
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.5,  # 처음에 손을 찾을 때
    min_hand_presence_confidence=0.5,   # 손이 아직 화면에 있는지 판단할 때
    min_tracking_confidence=0.5,        # 프레임 사이에 손을 계속 추적할 때
)
landmarker = vision.HandLandmarker.create_from_options(options)
model = YOLO("yolov8n.pt")      # 모델은 루프 밖에서 한 번만 (처음 실행 시 자동 다운로드)


# ★ 처리 함수: 프레임을 받아서 탐지 + 그리기 → 그림을 돌려줌
#   입력(웹캠/폰)이나 출력(imshow/JSON)이 바뀌어도 이 함수는 그대로
def process(frame, timestamp_ms):
    # YOLO 탐지 (★ 루프에서 옮겨옴)
    results = model(frame, conf=0.4, imgsz=320, verbose=False)
    annotated = results[0].plot()   # 박스가 그려진 새 이미지 (원본 frame은 그대로)

    # 손 추적
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(mp_image, timestamp_ms)
    h, w, _ = frame.shape

    for hand in result.hand_landmarks:      # 손 개수만큼 (0~2번)
        for lm in hand:                     # 점 21개
            px = int(lm.x * w)
            py = int(lm.y * h)
            cv2.circle(annotated, (px, py), 4, (0, 0, 255), -1)

    return annotated


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

    # FPS 계산 (★ 함수에서 꺼내옴)
    now = time.perf_counter()
    dt = now - prev
    fps = 1 / dt if dt > 0 else 0       # 0으로 나누기 방지
    prev = now

    # timestamp: 항상 이전 값보다 크게 (★ 함수에서 꺼내옴)
    timestamp_ms = int((now - start) * 1000)
    if timestamp_ms <= last_ts:
        timestamp_ms = last_ts + 1
    last_ts = timestamp_ms

    # ★ 탐지 + 그리기는 함수 한 줄로
    annotated = process(frame, timestamp_ms)

    # FPS 표시
    cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 1)

    cv2.imshow("cam", annotated)    # 박스 + FPS + 손점(미디어파이프 랜드마커)이미지 보여주기

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


cap.release()
landmarker.close()
cv2.destroyAllWindows()