# 자리 비움(UNATTENDED) 판단 로직 — 카메라/화면/전송 없이 '판단'만
# step7_unattended.py(테스트 실행용)와 서버 /detect 에서 같이 사용
# 사용:
#   tracker = UnattendedTracker()
#   level, absent = tracker.update(present=사람또는손있음, now=time.time(), fire_on=True)

TEST_LEVELS = [(15, "DANGER"), (10, "WARNING"), (5, "INFO")]     # 테스트용 (초)
REAL_LEVELS = [(180, "DANGER"), (60, "WARNING"), (30, "INFO")]  # 실제용 (초)


class UnattendedTracker:
    def __init__(self, levels=TEST_LEVELS):
        self.levels = sorted(levels, reverse=True)   # 큰 값부터 확인하도록 정렬
        self.last_seen = None                        # 아직 시각을 모름

    def level_of(self, absent_sec):
        for sec, name in self.levels:
            if absent_sec >= sec:
                return name
        return "SAFE"

    def update(self, present, now, fire_on=True):
        """present: 사람 또는 손이 보이면 True / now: 현재 시각(초) / fire_on: 불 사용 중
        반환: (등급, 안 보인 시간(초))"""
        if self.last_seen is None or present:        # 첫 호출은 '방금 봤다'로
            self.last_seen = now
        absent = now - self.last_seen
        level = self.level_of(absent) if fire_on else "SAFE"
        return level, absent

    def reset(self):
        """불을 끄거나 단계가 바뀌었을 때 시간 다시 세기"""
        self.last_seen = None


# 직접 실행하면 간단한 자체 테스트
if __name__ == "__main__":
    t = UnattendedTracker()
    for sec, present in [(0, True), (3, False), (6, False), (11, False), (16, False), (17, True)]:
        print(sec, present, t.update(present, sec))
    print("불 꺼짐:", t.update(False, 40, fire_on=False))