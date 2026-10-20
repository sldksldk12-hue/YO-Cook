# 영상에서 원하는 구간만 잘라 저장
# 사용: python clip_video.py <영상> <시작 mm:ss> <끝 mm:ss> <저장경로>

import sys
import cv2

def to_sec(t):
    m, s = t.split(":")
    return int(m) * 60 + int(s)

src, start, end, out = sys.argv[1], to_sec(sys.argv[2]), to_sec(sys.argv[3]), sys.argv[4]

cap = cv2.VideoCapture(src)
fps = cap.get(cv2.CAP_PROP_FPS) or 30
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

writer = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * fps))

count = 0
for _ in range(int((end - start) * fps)):
    ok, f = cap.read()
    if not ok:
        break
    writer.write(f)
    count += 1

cap.release()
writer.release()
print(f"저장: {out}  ({count}프레임, {count / fps:.1f}초)")