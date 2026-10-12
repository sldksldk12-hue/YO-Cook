# 영상 파일로 칼 인식 테스트 (step5는 수정 안 함)
# 사용: python step5-1_video_test.py <영상경로> [모델] [imgsz]
# 키: [space] 일시정지  [s] 캡처  [q] 종료

import sys
import cv2
import time
from pathlib import Path
from ultralytics import YOLO

if len(sys.argv) < 2:
    print("사용: python step5-1_video_test.py <영상경로> [모델] [imgsz]")
    sys.exit()

VIDEO = sys.argv[1]
MODEL = sys.argv[2] if len(sys.argv) > 2 else "yolov8n.pt"
IMGSZ = int(sys.argv[3]) if len(sys.argv) > 3 else 640          # 이미지 크기 (320/480/640)

BASE_DIR = Path(__file__).resolve().parent
CAP_DIR = BASE_DIR / "captures"
CAP_DIR.mkdir(exist_ok=True)

model = YOLO(MODEL)
if "world" in MODEL:                                             # YOLO-World는 글자로 클래스 지정
    model.set_classes(["knife", "kitchen knife"])

# 모델마다 칼 이름이 다름: COCO "knife", Open Images "Kitchen knife"/"Knife", World "kitchen knife"
KNIFE_NAMES = {"knife", "Knife", "Kitchen knife", "kitchen knife"}
KNIFE_IDS = [k for k, v in model.names.items() if v in KNIFE_NAMES]
# 칼을 가위로 잘못 잡는 경우가 많아서 같이 셈 → "날붙이(BLADE)"
SCISSORS_IDS = [k for k, v in model.names.items() if v == "scissors"]
BLADE_IDS = KNIFE_IDS + SCISSORS_IDS
print(f"[{MODEL} {IMGSZ}] 칼: {[model.names[k] for k in KNIFE_IDS]}  가위: {[model.names[k] for k in SCISSORS_IDS]}")

cap = cv2.VideoCapture(VIDEO)
if not cap.isOpened():
    print(f"[영상 열기 실패] {VIDEO}")
    sys.exit()

total = hit = hit_blade = 0
infer_ms = []
confs = []
paused = False
annotated = None

def put(img, text, row, color=(0, 255, 0)):
    cv2.putText(img, text, (10, 40 + row * 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4)
    cv2.putText(img, text, (10, 40 + row * 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)

while True:
    if not paused:
        ok, frame = cap.read()
        if not ok:
            break
        total += 1

        t0 = time.perf_counter()
        r = model(frame, imgsz=IMGSZ, conf=0.25, verbose=False)[0]
        infer_ms.append((time.perf_counter() - t0) * 1000)

        knives = [float(b.conf[0]) for b in r.boxes if int(b.cls[0]) in KNIFE_IDS]
        blades = [float(b.conf[0]) for b in r.boxes if int(b.cls[0]) in BLADE_IDS]
        if knives:
            hit += 1
            confs.append(max(knives))
        if blades:
            hit_blade += 1

        annotated = r.plot()
        put(annotated, f"knife: {max(knives):.2f}" if knives else "knife: -", 0,
            (0, 255, 0) if knives else (0, 0, 255))
        put(annotated, f"blade: {max(blades):.2f}" if blades else "blade: -", 1,
            (0, 255, 0) if blades else (0, 0, 255))
        put(annotated, f"frame {total}  knife {hit / total:.0%}  blade {hit_blade / total:.0%}", 2)

    # 화면 표시만 축소 (캡처는 원본 크기)
    scale = min(1.0, 960 / annotated.shape[1])
    show = cv2.resize(annotated, None, fx=scale, fy=scale) if scale < 1 else annotated
    cv2.imshow("video test", show)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord(" "):
        paused = not paused
    elif key == ord("s"):
        name = f"{Path(VIDEO).stem}_{Path(MODEL).stem}_{IMGSZ}_f{total}.jpg"
        cv2.imwrite(str(CAP_DIR / name), annotated)
        print(f"[캡처] {name}")

cap.release()
cv2.destroyAllWindows()

avg = sum(confs) / len(confs) if confs else 0
rate = hit / total if total else 0
rate_blade = hit_blade / total if total else 0
avg_ms = sum(infer_ms[1:]) / len(infer_ms[1:]) if len(infer_ms) > 1 else 0   # 첫 프레임(워밍업) 제외
print(f"\n{Path(VIDEO).name} [{Path(MODEL).stem} {IMGSZ}]  프레임 {total}  "
      f"칼 {rate:.0%}  칼+가위 {rate_blade:.0%}  평균conf {avg:.2f}  추론 {avg_ms:.0f}ms")