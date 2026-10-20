# 비전 6단계-1: 위험 규칙 기본
# 쥔 손 / 보조 손 구분(칼 끝 규칙) + 손바닥 폭 정규화 거리 + 손가락 자세(고양이손)
# 사용: python step6_knifehand.py [영상경로] [box|obb|trained|hybrid]
#   box     : yolo11s.pt     → 일반 박스 (축에 평행한 사각형)
#   obb     : yolo11s-seg.pt → 칼 마스크를 감싼 회전 사각형 (OBB 대용, 느림)
#   trained : weights/knife_obb_v1.pt → 직접 학습한 OBB 모델 (8단계)
#   hybrid  : trained 먼저 → 칼을 못 찾은 프레임만 yolo11s-seg(obb 방식)로 다시 찾기 (폴백)
#   영상경로가 없으면 폰 /shot.jpg
# 키: [space] 일시정지  [ [ / ] ] margin -/+  [s] 캡처  [q] 종료

import sys
import csv
import math
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
import torch
from ultralytics import YOLO
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

torch.set_num_threads(2)

# ===== 설정 =====
SHOT_URL = "http://192.168.0.xxx:8080/shot.jpg"   # ← IP Webcam 주소
MODES = ("box", "obb", "trained", "hybrid")
VIDEO = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] not in MODES else None
MODE = next((m for m in ("hybrid", "trained", "obb") if m in sys.argv[1:]), "box")

TRAINED_PT = str(Path(__file__).resolve().parent / "weights" / "knife_obb_v1.pt")
MODEL_NAME = {"box": "yolo11s.pt",
              "obb": "yolo11s-seg.pt",
              "trained": TRAINED_PT,
              "hybrid": TRAINED_PT}[MODE]
FALLBACK_NAME = "yolo11s-seg.pt"                   # hybrid 에서만 사용
IMGSZ = 480
CONF = 0.25
TIPS = [4, 8, 12, 16, 20]                          # 엄지~새끼 손끝
FINGERS = [(6, 8), (10, 12), (14, 16), (18, 20)]   # (가운데 마디, 손끝): 검지·중지·약지·새끼
state = {"margin": 0.5, "paused": False}           # 위험 = 손끝~칼 거리 ≤ 손바닥 폭 × margin

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "weights" / "hand_landmarker.task"
LOG_DIR = BASE_DIR / "logs"
CAP_DIR = BASE_DIR / "captures"
LOG_DIR.mkdir(exist_ok=True)
CAP_DIR.mkdir(exist_ok=True)

# ===== 모델 =====
def blade_ids(m):
    return [k for k, v in m.names.items() if v in ("knife", "scissors")]


model = YOLO(MODEL_NAME)
BLADE_IDS = blade_ids(model)
fallback = YOLO(FALLBACK_NAME) if MODE == "hybrid" else None
FB_BLADE_IDS = blade_ids(fallback) if fallback else []

options = vision.HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.3,   # 기본 0.5 → 주먹 쥔 손도 잡히게
    min_hand_presence_confidence=0.3,
    min_tracking_confidence=0.3,
)
landmarker = vision.HandLandmarker.create_from_options(options)


# ===== 도형 도구 (칼 = 꼭짓점 4개 다각형) =====
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def box_to_poly(box):
    x1, y1, x2, y2 = box
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float32)


def dist_to_blade(p, poly):
    """점 ~ 칼 다각형 거리. 안쪽이면 0"""
    d = cv2.pointPolygonTest(poly.reshape(-1, 1, 2), (float(p[0]), float(p[1])), True)
    return max(0.0, -d)


def nearest_on_blade(p, poly):
    """그리기용: 칼 다각형 테두리에서 가장 가까운 점"""
    best, best_d = None, None
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ab = b - a
        t = np.clip(np.dot(np.array(p, np.float32) - a, ab) / max(np.dot(ab, ab), 1e-6), 0, 1)
        q = a + t * ab
        d = dist(p, q)
        if best_d is None or d < best_d:
            best, best_d = q, d
    return int(best[0]), int(best[1])


def at_end(p, poly, end_frac=0.25, side_frac=0.15):
    """손바닥 중심이 칼의 '끝(짧은 변 쪽)'에 있나? 정사각형에 가까우면 None
    끝 = 칼 길이 방향으로 양 끝 25% 안쪽 또는 바깥 + 칼 축에서 옆으로 많이 벗어나지 않음"""
    e0, e1 = poly[1] - poly[0], poly[2] - poly[1]
    long_e, short_e = (e0, e1) if np.linalg.norm(e0) >= np.linalg.norm(e1) else (e1, e0)
    L, S = np.linalg.norm(long_e), np.linalg.norm(short_e)
    if L < 1.3 * max(S, 1):
        return None                                    # 판단 보류
    u = long_e / L                                     # 칼 길이 방향
    v = np.array([-u[1], u[0]], np.float32)            # 칼 옆 방향
    d = np.array(p, np.float32) - poly.mean(axis=0)
    t = np.dot(d, u) / L                               # 길이 방향 위치 (-0.5 ~ 0.5 가 칼 안)
    s = abs(np.dot(d, v))                              # 칼 축에서 옆으로 떨어진 px
    return abs(t) > 0.5 - end_frac and s < S / 2 + L * side_frac


def finger_check(pts, poly, palm_w, gap=0.1):
    """(펴진 손가락 수, 판정 불가 손가락 수)
    펴짐 = 손끝이 가운데 마디보다 칼에 (손바닥 폭 × gap) 이상 더 가까움
    판정 불가 = 마디·손끝 둘 다 칼 안 (거리 0)
    고양이손이면 가운데 마디가 손끝보다 칼에 가까움"""
    exposed = unknown = 0
    for pip, tip in FINGERS:
        d_pip, d_tip = dist_to_blade(pts[pip], poly), dist_to_blade(pts[tip], poly)
        if d_pip == 0 and d_tip == 0:
            unknown += 1
        elif d_tip < d_pip - palm_w * gap:
            exposed += 1
    return exposed, unknown


# ===== 탐지 + 판단 =====
def find_blade_obb(r, m, ids):
    """학습한 OBB 모델: 꼭짓점 4개가 바로 나옴"""
    best = None
    if r.obb is None:
        return None
    for poly, c, cls in zip(r.obb.xyxyxyxy.cpu().numpy(), r.obb.conf.tolist(), r.obb.cls.tolist()):
        if int(cls) in ids and (best is None or c > best["conf"]):
            best = {"conf": c, "name": m.names[int(cls)], "poly": poly.astype(np.float32)}
    return best


def find_blade_box(r, m, ids, use_mask):
    """기본 모델: 일반 박스, use_mask면 seg 마스크 → 회전 사각형"""
    best = None
    for i, b in enumerate(r.boxes):
        cls = int(b.cls[0])
        if cls not in ids:
            continue
        c = float(b.conf[0])
        if best is not None and c <= best["conf"]:
            continue
        poly = box_to_poly([float(v) for v in b.xyxy[0].tolist()])
        if use_mask and r.masks is not None:
            seg = r.masks.xy[i]
            if len(seg) >= 3:
                poly = cv2.boxPoints(cv2.minAreaRect(seg.astype(np.float32))).astype(np.float32)
        best = {"conf": c, "name": m.names[cls], "poly": poly}
    return best


def find_blade(frame):
    """칼 1개 찾기. 결과에 src(어느 모델이 찾았나) 표시"""
    r = model(frame, imgsz=IMGSZ, conf=CONF, verbose=False)[0]
    if MODE in ("trained", "hybrid"):
        blade = find_blade_obb(r, model, BLADE_IDS)
        src = "trained"
    else:
        blade = find_blade_box(r, model, BLADE_IDS, use_mask=(MODE == "obb"))
        src = MODE
    if blade is None and MODE == "hybrid":             # 못 찾았을 때만 기본 seg 모델로 한 번 더
        r2 = fallback(frame, imgsz=IMGSZ, conf=CONF, verbose=False)[0]
        blade = find_blade_box(r2, fallback, FB_BLADE_IDS, use_mask=True)
        src = "fallback"
    if blade is not None:
        blade["src"] = src
    return blade


def analyze(frame, timestamp_ms):
    h, w, _ = frame.shape
    blade = find_blade(frame)

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
    hands = []
    for hand in res.hand_landmarks:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand]
        palm_w = max(dist(pts[5], pts[17]), 1.0)   # 손바닥 폭 = 검지 뿌리 ~ 새끼 뿌리
        hands.append({"pts": pts, "palm_w": palm_w})

    out = {"blade": blade, "hands": hands, "grip": None, "assist": None,
           "ratio": None, "tip": None, "close": False,
           "exposed": None, "unknown": None, "danger": False}
    if blade is None or not hands:
        return out
    poly = blade["poly"]

    # ① 쥔 손 / 보조 손: 칼 '끝(짧은 변 쪽)'에 있는 손 = 쥔 손
    gaps = [dist_to_blade(hd["pts"][9], poly) for hd in hands]
    ends = [at_end(hd["pts"][9], poly) for hd in hands]

    if len(hands) >= 2:
        if ends[0] is True and ends[1] is not True:
            grip = 0
        elif ends[1] is True and ends[0] is not True:
            grip = 1
        else:
            grip = gaps.index(min(gaps))   # 둘 다 끝 / 판단 보류 → 칼에 더 가까운 손
        assist = 1 - grip
    elif ends[0] is True or (ends[0] is None and gaps[0] <= hands[0]["palm_w"] * 0.3):
        out["grip"] = 0                    # 손 1개가 칼 끝에 있음 = 쥔 손
        return out
    else:
        grip, assist = None, 0             # 칼 옆에 있는 손 1개 = 보조 손 (쥔 손은 화면 밖·미탐)
    out["grip"], out["assist"] = grip, assist
    a = hands[assist]

    # ② 정규화 거리 = 손끝~칼 px / 손바닥 폭 px
    ratios = [dist_to_blade(a["pts"][i], poly) / a["palm_w"] for i in TIPS]
    k = ratios.index(min(ratios))
    out["ratio"], out["tip"] = ratios[k], TIPS[k]
    out["close"] = out["ratio"] <= state["margin"]

    # ③ 손가락 자세: 가까움 + 펴진 손가락 1개 이상 → DANGER (고양이손이면 안전)
    out["exposed"], out["unknown"] = finger_check(a["pts"], poly, a["palm_w"])
    out["danger"] = out["close"] and out["exposed"] >= 1
    return out


# ===== 그리기 =====
def put(img, text, row, color=(0, 255, 0)):
    y = 30 + row * 30
    cv2.putText(img, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(img, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


def draw(frame, out, fps):
    img = frame.copy()
    blade = out["blade"]
    red, yellow, green, cyan = (0, 0, 255), (0, 255, 255), (0, 200, 0), (255, 200, 0)

    if blade:
        color = red if out["danger"] else (yellow if out["close"] else cyan)
        cv2.polylines(img, [blade["poly"].astype(np.int32)], True, color, 2)

    for i, hd in enumerate(out["hands"]):
        color = green if i == out["grip"] else (red if i == out["assist"] else (200, 200, 200))
        for p in hd["pts"]:
            cv2.circle(img, p, 3, color, -1)

    if out["ratio"] is not None and blade:
        tip = out["hands"][out["assist"]]["pts"][out["tip"]]
        cv2.line(img, tip, nearest_on_blade(tip, blade["poly"]), yellow, 2)
        cv2.circle(img, tip, 8, yellow, 2)

    put(img, f"[{MODE}] blade: {blade['name']} {blade['conf']:.2f} ({blade['src']})" if blade else f"[{MODE}] blade: -", 0,
        green if blade else red)
    put(img, f"hands: {len(out['hands'])}  grip: {out['grip']}  assist: {out['assist']}", 1, cyan)
    if out["ratio"] is not None:
        put(img, f"ratio: {out['ratio']:.2f} (tip {out['tip']})  margin: {state['margin']:.1f}", 2, yellow)
        state_txt = "DANGER" if out["danger"] else ("CLOSE" if out["close"] else "ok")
        put(img, f"{state_txt}  fingers: exposed {out['exposed']} / unknown {out['unknown']}", 3,
            red if out["danger"] else (yellow if out["close"] else green))
    else:
        put(img, f"ratio: -  margin: {state['margin']:.1f}", 2, yellow)
    put(img, f"FPS: {fps:.1f}", 4)
    return img


# ===== 입력 =====
cap = cv2.VideoCapture(VIDEO) if VIDEO else None
if cap is not None and not cap.isOpened():
    print(f"[영상 열기 실패] {VIDEO}  → dir test_videos 로 파일 이름 확인")
    sys.exit()
video_fps = (cap.get(cv2.CAP_PROP_FPS) or 30) if cap is not None else None


def read_frame():
    if cap is not None:
        ok, f = cap.read()
        return f if ok else "END"
    try:
        data = urllib.request.urlopen(SHOT_URL, timeout=2).read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"[폰 연결 실패] {e}")
        return None


# ===== 기록 =====
run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
src_name = Path(VIDEO).stem if VIDEO else "phone"
log_path = LOG_DIR / f"hazard_{MODE}_{src_name}_{run_name}.csv"
log_file = open(log_path, "w", newline="", encoding="utf-8-sig")
writer = csv.writer(log_file)
writer.writerow(["frame", "mode", "blade", "blade_conf", "n_hands", "grip", "assist",
                 "palm_w", "ratio", "tip", "margin", "close", "exposed", "unknown", "danger", "src"])


def cell(v, nd=None):
    if v is None:
        return ""
    return round(v, nd) if nd is not None else v


# ===== 메인 루프 =====
start = time.perf_counter()
prev = start
last_ts = -1
fps_avg = 0.0
n_frame = 0
annotated = None
stats = {"blade": 0, "two_hands": 0, "judged": 0, "close": 0, "ratios": [],
         "danger": 0, "all_unknown": 0, "fallback": 0}

print(f"모드: {MODE} ({MODEL_NAME})" + (f" + 폴백 {FALLBACK_NAME}" if fallback else ""))
print("키: [space]일시정지  [ / ] margin  [s]캡처  [q]종료")

while True:
    if not state["paused"]:
        frame = read_frame()
        if isinstance(frame, str):          # 영상 끝
            break
        if frame is None:                   # 폰 연결 실패
            blank = np.zeros((480, 640, 3), np.uint8)
            put(blank, "NO SIGNAL - check SHOT_URL / wifi", 0, (0, 0, 255))
            put(blank, "[q] quit", 1, (0, 0, 255))
            cv2.imshow("hazard", blank)
            if cv2.waitKey(500) & 0xFF == ord("q"):
                break
            continue

        n_frame += 1
        now = time.perf_counter()
        dt = now - prev
        fps_avg = fps_avg * 0.9 + (1 / dt if dt > 0 else 0) * 0.1
        prev = now

        # 영상은 프레임 번호 기준, 폰은 실제 시간 기준 (항상 증가해야 함)
        ts = int(n_frame * 1000 / video_fps) if cap is not None else int((now - start) * 1000)
        if ts <= last_ts:
            ts = last_ts + 1
        last_ts = ts

        out = analyze(frame, ts)
        annotated = draw(frame, out, fps_avg)

        b = out["blade"]
        a_palm = out["hands"][out["assist"]]["palm_w"] if out["assist"] is not None else None
        writer.writerow([n_frame, MODE, b["name"] if b else "", cell(b["conf"] if b else None, 3),
                         len(out["hands"]), cell(out["grip"]), cell(out["assist"]),
                         cell(a_palm, 1), cell(out["ratio"], 3), cell(out["tip"]), state["margin"],
                         int(out["close"]), cell(out["exposed"]), cell(out["unknown"]), int(out["danger"]),
                         b["src"] if b else ""])
        stats["blade"] += b is not None
        stats["fallback"] += b is not None and b["src"] == "fallback"
        stats["two_hands"] += len(out["hands"]) >= 2
        if out["ratio"] is not None:
            stats["judged"] += 1
            stats["close"] += out["close"]
            stats["ratios"].append(out["ratio"])
            if out["close"]:
                stats["danger"] += out["danger"]
                stats["all_unknown"] += out["unknown"] == 4

    scale = min(1.0, 960 / annotated.shape[1])
    show = cv2.resize(annotated, None, fx=scale, fy=scale) if scale < 1 else annotated
    cv2.imshow("hazard", show)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord(" "):
        state["paused"] = not state["paused"]
    elif key == ord("["):
        state["margin"] = max(0.1, round(state["margin"] - 0.1, 1))
    elif key == ord("]"):
        state["margin"] = min(2.0, round(state["margin"] + 0.1, 1))
    elif key == ord("s"):
        p = CAP_DIR / f"hazard_{MODE}_{src_name}_f{n_frame}.jpg"
        cv2.imwrite(str(p), annotated)
        print(f"[캡처] {p.name}")

# ===== 종료 + 요약 =====
log_file.close()
if cap is not None:
    cap.release()
landmarker.close()
cv2.destroyAllWindows()

n = max(n_frame, 1)
rs = stats["ratios"]
print(f"\n[{MODE}] 기록 파일: {log_path}")
print(f"프레임 {n_frame}  칼 {stats['blade'] / n:.0%}  양손 {stats['two_hands'] / n:.0%}  "
      f"판단 가능 {stats['judged'] / n:.0%}")
if MODE == "hybrid":
    nb = max(stats["blade"], 1)
    print(f"칼 찾은 모델: trained {(stats['blade'] - stats['fallback']) / nb:.0%} / "
          f"fallback {stats['fallback'] / nb:.0%}")
if rs:
    print(f"CLOSE {stats['close']}프레임 ({stats['close'] / len(rs):.0%})  "
          f"ratio 최소 {min(rs):.2f} / 평균 {sum(rs) / len(rs):.2f} / 최대 {max(rs):.2f}")
    c = max(stats["close"], 1)
    print(f"CLOSE 중 DANGER {stats['danger']}프레임 ({stats['danger'] / c:.0%})  "
          f"손가락 4개 모두 판정 불가 {stats['all_unknown']}프레임 ({stats['all_unknown'] / c:.0%})")