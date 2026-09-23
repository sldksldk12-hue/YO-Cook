from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.user import UserFavorite
    from app.models.session import CookingSession

# ==========================================
# 1. RECIPES (레시피 마스터 정보)
# ==========================================
class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False)               # 요리명
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)                   # 요리 한 줄 소개
    category: Mapped[str] = mapped_column(String(50), default="일반", index=True, nullable=False) # 요리 분류
    tags: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)                    # 대표 해시태그
    cooking_time_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)     # 조리시간 (분)
    difficulty: Mapped[str] = mapped_column(String(50), default="초급", nullable=False)         # 난이도
    servings: Mapped[str] = mapped_column(String(50), default="1인분", nullable=False)          # 기준 분량
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)          # 대표 사진 URL
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)             # 원본 출처 링크
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)                # 조회수
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # 1:N 자식 관계 설정
    ingredients: Mapped[List["Ingredient"]] = relationship(
        "Ingredient", back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )
    steps: Mapped[List["RecipeStep"]] = relationship(
        "RecipeStep", back_populates="recipe", cascade="all, delete-orphan", 
        order_by="RecipeStep.step_number", lazy="selectin"
    )
    cooking_sessions: Mapped[List["CookingSession"]] = relationship(
        "CookingSession", back_populates="recipe"
    )
    favorited_by: Mapped[List["UserFavorite"]] = relationship(
        "UserFavorite", back_populates="recipe", cascade="all, delete-orphan"
    )


# ==========================================
# 2. INGREDIENTS (레시피 식재료)
# ==========================================
class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True) # 소속 레시피 ID
    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)                 # 식재료명 (예: 신김치, 대파)
    amount: Mapped[str] = mapped_column(String(100), nullable=False)                           # 분량 (예: 1공기, 1/2대)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)                     # 단위 (g, ml, 개 등)
    is_seasoning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)         # 양념/조미료 여부
    is_essential: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)          # 필수 재료 여부

    # N:1 부모 레시피 관계
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="ingredients")


# ==========================================
# 3. RECIPE_STEPS (조리 단계 및 안전 가이드)
# ==========================================
class RecipeStep(Base):
    __tablename__ = "recipe_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True) # 소속 레시피 ID
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)                          # 단계 번호 (1, 2, 3...)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)                             # 조리 지침 본문
    timer_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)             # 타이머 시간 (초)
    image_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)             # 단계별 사진 URL
    tip: Mapped[Optional[str]] = mapped_column(Text, nullable=True)                             # 셰프 조리 꿀팁
    safety_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)                 # 안전 주의사항
    required_tools: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)         # 필요 도구 (식칼, 도마, 팬 등)

    # N:1 부모 레시피 관계
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="steps")
