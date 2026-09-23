from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Integer, Text, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.recipe import Recipe

# ==========================================
# 1. COOKING_SESSIONS (실시간 조리 세션)
# ==========================================
class CookingSession(Base):
    """
    사용자가 '요리 시작하기'를 눌렀을 때 생성되는 1회 조리 진행 세션
    - WebSocket 실시간 무전기 연결 채널 및 현재 진행 단계를 추적합니다.
    """
    __tablename__ = "cooking_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False) # 고유 접속 UUID 방 번호
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True) # 사용자 ID (비회원 가능)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)       # 진행 중인 레시피 ID
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)                   # 현재 진행 단계 (1단계, 2단계...)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)              # 조리 완료 여부
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False) # 시작 일시
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)                  # 종료 일시

    # N:1 부모 관계 (User, Recipe)
    user: Mapped[Optional["User"]] = relationship("User", back_populates="cooking_sessions")
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="cooking_sessions")

    # 1:N 자식 관계 (해당 세션에서 발생한 안전 경고 로그들)
    safety_logs: Mapped[List["SafetyLog"]] = relationship(
        "SafetyLog", back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )


# ==========================================
# 2. SAFETY_LOGS (비전 안전 경고 이력)
# ==========================================
class SafetyLog(Base):
    """
    비전 AI가 조리 도중 감지한 위험 상황(칼질 근접, 열원 방치 등)의 발생 이력
    - 조리 완료 후 안전 분석 리포트 및 통계 데이터로 활용됩니다.
    """
    __tablename__ = "safety_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("cooking_sessions.id", ondelete="CASCADE"), nullable=False, index=True) # 조리 세션 ID
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)          # 경고 발생 당시의 조리 단계
    hazard_type: Mapped[str] = mapped_column(String(50), nullable=False)       # 위험 유형 (KNIFE_PROXIMITY, HEAT_ABSENCE, OIL_SPLASH)
    level: Mapped[str] = mapped_column(String(20), default="WARNING", nullable=False) # 위험 등급 (INFO, WARNING, DANGER)
    message: Mapped[str] = mapped_column(String(255), nullable=False)         # 사용자에게 전달된 경고 문구
    distance_px: Mapped[Optional[float]] = mapped_column(Float, nullable=True) # 손-칼날 간 거리 (px)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False) # 감지 일시

    # N:1 부모 세션 관계
    session: Mapped["CookingSession"] = relationship("CookingSession", back_populates="safety_logs")
