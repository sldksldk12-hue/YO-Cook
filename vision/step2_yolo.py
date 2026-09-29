# 비전 2단계: YOLO 물체 탐지
# 1단계 뼈대 + (루프 밖) 모델 준비 + (루프 안 ③) 탐지
# 2단계: 열기 + 모델 → (읽기 → [YOLO 탐지] → [FPS] → 보여주기) 반복 → 닫기
# 3단계: 열기 + 모델 + 손 탐지기 → (읽기 → [YOLO] → [손] → [FPS] → 보여주기) 반복 → 닫기

import cv2
import time
from ultralytics import YOLO


cap = cv2.VideoCapture(0)
model = YOLO("yolov8n.pt")      # 모델은 루프 밖에서 한 번만 (처음 실행 시 자동 다운로드)
printed = False
prev = time.time()
fps_list = []                   # 최근 FPS 값 모음 (평균 계산용)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    if not printed:
        print(frame.shape)
        printed = True

    # ③ YOLO 탐지 (imgsz=320: 640은 15~18 FPS, 320은 약 30 FPS)
    results = model(frame, conf=0.4, imgsz=320, verbose=False)
    annotated = results[0].plot()   # 박스가 그려진 새 이미지 (원본 frame은 그대로)

    now = time.time()
    fps = 1 / (now - prev)
    prev = now

    # 최근 10개 평균으로 흔들림 줄이기
    fps_list.append(fps)            # 끝에 추가
    if len(fps_list) > 10:
        fps_list.pop(0)             # 가장 오래된 값 버리기
    avg_fps = sum(fps_list) / len(fps_list)

    # FPS 표시 (박스 그려진 annotated에 그려야 둘 다 보임)
    cv2.putText(annotated, f"FPS: {avg_fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 1)

    cv2.imshow("cam", annotated)    # 박스 + FPS 이미지 보여주기

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


cap.release()
cv2.destroyAllWindows()