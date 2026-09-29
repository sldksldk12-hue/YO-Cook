# 비전 1단계: 웹캠 + FPS 표시
# 모든 실시간 비전 코드는 열기 -> (읽기 -> 처리 -> 보여주기) 반복 -> 닫기 구조를 따름
# 1단계: 열기 → (읽기 → [FPS] → 보여주기) 반복 → 닫기

import cv2
import time


cap = cv2.VideoCapture(0)   # ① 0번 카메라 열기
printed = False             
prev = time.time()          # 이전 프레임 시각 (FPS 계산용)

while True:
    ret, frame = cap.read()  # ② 한 프레임 읽기. frame = NumPy 배열, ret = 성공 여부 True/False (return의 줄임말, 관례)
    if not ret:              # 실패하면 frame이 None이라 imshow에서 에러 > 먼저 걸러냄
        break

    # 해상도 확인: (높이, 너비, 채널) → (480, 640, 3)
    if not printed:
        print(frame.shape)
        printed = True       # 한번만 출력하기위해 True 바꿔 출력 x


    # ③ frame 처리 (탐지, 그리기 등)

    # FPS = 1 / (한 바퀴 걸린 시간)
    now = time.time()
    fps = 1 / (now - prev)
    prev = now               # 이번 바퀴 끝 = 다음 바퀴 시작 (틈 없이 이어지게)

    # FPS를 창 좌상단에 표시 (imshow 전에 그려야 화면에 보임)
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),     # f-string :.1f = 소수점 1자리 / (10, 30) = 글자 왼쪽 아래 좌표
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 1)   # 글꼴(가장 무난), 1(크기 배율), (0,255,0)(BGR 순 초록), 1(선 두께)

    cv2.imshow("cam", frame)  # ④ 창에 보여주기 imshow("창이름", 배열)

    # ⑤ q 누르면 종료
    # waitKey(1): 1ms 키 대기 + 창 갱신 / & 0xFF: 끝 8비트만 남김 (윈도우에선 없어도 동작, 일부 리눅스에서 필요) / ord("q"): 문자 → 코드 번호 113
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


cap.release()            # ⑥ 카메라 반납
cv2.destroyAllWindows()  # ⑦ 창 닫기