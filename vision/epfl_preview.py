# 폴더 안 영상들의 중간 장면을 한 장에 모아서 각도 비교
# 사용: python epfl_preview.py <영상폴더>

import sys
import cv2
import numpy as np
from pathlib import Path

folder = Path(sys.argv[1])
tiles = []

for p in sorted(folder.glob("*.mp4")):
    cap = cv2.VideoCapture(str(p))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, n // 2)       # 영상 중간으로 이동
    ok, f = cap.read()
    cap.release()
    print(f"{p.name:<16} {'OK  ' if ok else '실패'}  {n}프레임  {n / fps / 60:.1f}분")
    if not ok:
        continue
    f = cv2.resize(f, (480, 270))
    cv2.putText(f, p.stem, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 4)
    cv2.putText(f, p.stem, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
    tiles.append(f)

if tiles:
    cols = 4
    while len(tiles) % cols:                        # 빈 칸 채우기
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    grid = np.vstack(rows)
    out = folder / "preview.jpg"
    cv2.imwrite(str(out), grid)
    print(f"\n저장: {out}")
    cv2.imshow("preview", grid)
    cv2.waitKey(0)                                  # 아무 키 누르면 닫힘
    cv2.destroyAllWindows()