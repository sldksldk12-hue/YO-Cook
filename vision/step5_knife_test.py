# 비전 5단계 준비: 수직 촬영 칼 인식 테스트 + 손끝-칼 거리 기록
# 키: [i] imgsz 320/640  [c] conf 0.4/0.2  [k] 칼만 찾기  [m] 모델 n/s
#     [0~4] 상황 태그  [s] 화면 캡처  [q] 종료

import cv2
import csv
import math
import time
import urllib.request
import numpy as np
import mediapipe as mp
import torch
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

torch.set_num_threads(2)  # MediaPipe와 CPU 다툼 줄이기 (4단계에서 비교 → 2)


# ===== 설정 (여기만 바꾸면 됨) =====
SHOT_URL = "http://172.30.1.17:8080/shot.jpg"
USE_WEBCAM = False                                # True면 노트북 웹캠으로 테스트

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "weights" / "hand_landmarker.task"
LOG_DIR = BASE_DIR / "logs"         # CSV 기록
CAP_DIR = BASE_DIR / "captures"     # 화면 캡처
LOG_DIR.mkdir(exist_ok=True)
CAP_DIR.mkdir(exist_ok=True)

TIP_IDS = [4, 8, 12, 16, 20]        # 손가락 끝 (엄지~새끼)

# 상황 태그 (화면에 한글이 안 나와서 영어로)
SITUATIONS = {
    ord("0"): "none",         # 태그 없음
    ord("1"): "grip",         # 칼 쥔 손 (정상)
    ord("2"): "cat_hand",     # 반대 손 고양이손 (안전)
    ord("3"): "near_blade",   # 반대 손 손가락 펴서 칼날 근처 (위험 흉내, 칼은 멈춘 상태로!)
    ord("4"): "far",          # 반대 손 멀리
}

# 실행 중 키로 바꾸는 값
state = {"model": "n", "imgsz": 320, "conf": 0.4, "only_knife": False, "situation": "none"}


# ===== 모델 준비 =====
models = {}

def get_model(size):
    """yolov8n / yolov8s를 처음 쓸 때 한 번만 불러와서 저장해 둠"""
    if size not in models:
        print(f"[모델 로딩] yolov8{size}.pt ...")
        models[size] = YOLO(f"yolov8{size}.pt")
    return models[size]

# 칼 클래스 번호를 이름으로 찾기 (보통 43)
KNIFE_ID = [k for k, v in get_model("n").names.items() if v == "knife"][0]

options = vision.HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.5,
    min_hand_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)
landmarker = vision.HandLandmarker.create_from_options(options)


# ===== 거리 계산 =====
def nearest_point_on_box(px, py, box):
    """점에서 가장 가까운 박스 위의 점 (점이 박스 안이면 자기 자신)"""
    x1, y1, x2, y2 = box
    return min(max(px, x1), x2), min(max(py, y1), y2)

def dist_to_box(px, py, box):
    """점과 박스 사이 거리(px). 박스 안이면 0"""
    nx, ny = nearest_point_on_box(px, py, box)
    return math.hypot(px - nx, py - ny)


# ===== 처리 함수 =====
def process(frame, timestamp_ms):
    model = get_model(state["model"])
    classes = [KNIFE_ID] if state["only_knife"] else None

    # 1) YOLO
    results = model(frame, conf=state["conf"], imgsz=state["imgsz"],
                    classes=classes, verbose=False)
    annotated = results[0].plot()

    # 칼 박스 중 확신도가 가장 높은 하나
    knife = None
    for box in results[0].boxes:
        if int(box.cls[0]) == KNIFE_ID:
            conf = float(box.conf[0])
            if knife is None or conf > knife["conf"]:
                knife = {"conf": conf, "bbox": [int(v) for v in box.xyxy[0].tolist()]}

    # 2) 손
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(mp_image, timestamp_ms)
    h, w, _ = frame.shape

    hands = []
    for hand in result.hand_landmarks:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand]
        for px, py in pts:
            cv2.circle(annotated, (px, py), 3, (0, 0, 255), -1)

        min_dist, min_tip = None, None
        if knife:
            for i in TIP_IDS:
                d = dist_to_box(*pts[i], knife["bbox"])
                if min_dist is None or d < min_dist:
                    min_dist, min_tip = d, i

            # 가장 가까운 손끝 ↔ 칼 박스를 노란 선으로
            tx, ty = pts[min_tip]
            nx, ny = nearest_point_on_box(tx, ty, knife["bbox"])
            cv2.line(annotated, (tx, ty), (nx, ny), (0, 255, 255), 2)
            cv2.circle(annotated, (tx, ty), 7, (0, 255, 255), 2)

        hands.append({"min_dist": min_dist, "min_tip": min_tip})

    return annotated, {"knife": knife, "hands": hands}


# ===== 입력 =====
cap = cv2.VideoCapture(0) if USE_WEBCAM else None

def read_frame():
    if USE_WEBCAM:
        ret, f = cap.read()
        return f if ret else None
    try:
        data = urllib.request.urlopen(SHOT_URL, timeout=2).read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"[폰 연결 실패] {e}")
        return None


# ===== 화면 글자 =====
def put(img, text, row, color=(0, 255, 0)):
    cv2.putText(img, text, (10, 25 + row * 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)   # 검은 테두리
    cv2.putText(img, text, (10, 25 + row * 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)


# ===== 기록 준비 =====
run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
log_path = LOG_DIR / f"knife_test_{run_name}.csv"
log_file = open(log_path, "w", newline="", encoding="utf-8-sig")   # 엑셀에서 한글 안 깨지게
writer = csv.writer(log_file)
writer.writerow(["time", "model", "imgsz", "conf", "only_knife", "situation", "fps",
                 "knife_detected", "knife_conf", "n_hands", "hand1_dist", "hand2_dist"])
rows = []   # 종료 시 요약용


# ===== 메인 루프 =====
start = time.perf_counter()
prev = start
last_ts = -1
fps_avg = 0

print("키: [i]imgsz [c]conf [k]칼만 [m]모델 [0~4]상황 [s]캡처 [q]종료")

while True:
    frame = read_frame()
    if frame is None:
        if cv2.waitKey(100) & 0xFF == ord("q"):
            break
        continue

    now = time.perf_counter()
    dt = now - prev
    fps = 1 / dt if dt > 0 else 0
    fps_avg = fps_avg * 0.9 + fps * 0.1   # 이동 평균 (덜 흔들리게)
    prev = now

    timestamp_ms = int((now - start) * 1000)
    if timestamp_ms <= last_ts:
        timestamp_ms = last_ts + 1
    last_ts = timestamp_ms

    annotated, result = process(frame, timestamp_ms)
    knife, hands = result["knife"], result["hands"]

    # 화면 표시
    put(annotated, f"model:{state['model']} imgsz:{state['imgsz']} conf:{state['conf']} "
                   f"knife_only:{'on' if state['only_knife'] else 'off'}", 0)
    put(annotated, f"situation: {state['situation']}  [0-4]", 1, (255, 255, 0))
    put(annotated, f"knife: {knife['conf']:.2f}" if knife else "knife: -", 2,
        (0, 255, 0) if knife else (0, 0, 255))
    for i, hd in enumerate(hands):
        d = f"{hd['min_dist']:.0f}px (tip {hd['min_tip']})" if hd["min_dist"] is not None else "-"
        put(annotated, f"hand{i + 1} dist: {d}", 3 + i, (0, 255, 255))
    put(annotated, f"FPS: {fps_avg:.1f}", 5)

    cv2.imshow("knife test", annotated)

    # 기록
    d1 = hands[0]["min_dist"] if len(hands) > 0 else None
    d2 = hands[1]["min_dist"] if len(hands) > 1 else None
    row = [datetime.now().strftime("%H:%M:%S.%f")[:-3], state["model"], state["imgsz"],
           state["conf"], state["only_knife"], state["situation"], round(fps_avg, 1),
           knife is not None, round(knife["conf"], 3) if knife else "",
           len(hands),
           round(d1, 1) if d1 is not None else "",
           round(d2, 1) if d2 is not None else ""]
    writer.writerow(row)
    rows.append({"setting": (state["model"], state["imgsz"], state["conf"], state["only_knife"]),
                 "situation": state["situation"], "fps": fps_avg, "knife": knife,
                 "dists": [d for d in (d1, d2) if d is not None]})

    # 키 입력
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("i"):
        state["imgsz"] = 640 if state["imgsz"] == 320 else 320
    elif key == ord("c"):
        state["conf"] = 0.2 if state["conf"] == 0.4 else 0.4
    elif key == ord("k"):
        state["only_knife"] = not state["only_knife"]
    elif key == ord("m"):
        state["model"] = "s" if state["model"] == "n" else "n"
    elif key in SITUATIONS:
        state["situation"] = SITUATIONS[key]
    elif key == ord("s"):
        cap_path = CAP_DIR / f"{run_name}_{state['situation']}_{datetime.now().strftime('%H%M%S')}.jpg"
        cv2.imwrite(str(cap_path), annotated)
        print(f"[캡처] {cap_path.name}")


# ===== 종료 + 요약 =====
log_file.close()
if cap is not None:
    cap.release()
landmarker.close()
cv2.destroyAllWindows()

print(f"\n기록 파일: {log_path}")

print("\n[설정별 칼 인식]")
print("model imgsz conf  칼만  | 프레임  인식률  평균확신도  FPS")
settings = {}
for r in rows:
    settings.setdefault(r["setting"], []).append(r)
for (m, sz, cf, ok), rs in settings.items():
    found = [r["knife"]["conf"] for r in rs if r["knife"]]
    rate = len(found) / len(rs) * 100
    avg_conf = sum(found) / len(found) if found else 0
    avg_fps = sum(r["fps"] for r in rs) / len(rs)
    print(f"{m:>5} {sz:>5} {cf:>4}  {'on' if ok else 'off':>3}  | {len(rs):>5}  {rate:5.1f}%   {avg_conf:.2f}      {avg_fps:.1f}")

print("\n[상황별 손끝-칼 거리 (칼과 손이 둘 다 잡힌 프레임만)]")
print("상황         | 프레임  최소   평균   최대 (px)")
sits = {}
for r in rows:
    if r["dists"]:
        sits.setdefault(r["situation"], []).append(min(r["dists"]))
for s, ds in sits.items():
    print(f"{s:<12} | {len(ds):>5}  {min(ds):5.0f}  {sum(ds) / len(ds):5.0f}  {max(ds):5.0f}")  