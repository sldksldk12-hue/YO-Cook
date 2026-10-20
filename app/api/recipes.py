from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.models.database import get_db
from app.models.recipe import Recipe, Ingredient, RecipeStep
from app.schemas.recipe_schema import (
    RecipeSummaryResponse,
    RecipeDetailResponse,
    IngredientResponse,
    RecipeStepResponse
)

router = APIRouter()

# 1. 전체 레시피 목록 조회 (검색 및 필터링)
@router.get(
    "/",
    response_model=List[RecipeSummaryResponse],
    summary="레시피 목록 조회 및 검색",
    description="전체 레시피 목록을 반환하며 요리명/태그 검색 및 카테고리, 난이도 필터링을 지원합니다."
)
def get_recipes(
    keyword: Optional[str] = Query(None, description="요리명 또는 태그 검색어"),
    category: Optional[str] = Query(None, description="요리 분류 필터 (예: 한식, 분식, 일품 등)"),
    difficulty: Optional[str] = Query(None, description="난이도 필터 (초급, 중급, 고급)"),
    skip: int = Query(0, ge=0, description="건너뛸 항목 수 (페이징)"),
    limit: int = Query(50, ge=1, le=100, description="가져올 최대 항목 수"),
    db: Session = Depends(get_db)
):
    stmt = select(Recipe)

    # 검색어 조건 (요리명, 소개글, 태그)
    if keyword:
        keyword_pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                Recipe.title.ilike(keyword_pattern),
                Recipe.description.ilike(keyword_pattern),
                Recipe.tags.ilike(keyword_pattern)
            )
        )

    # 카테고리 필터
    if category:
        stmt = stmt.where(Recipe.category == category.strip())

    # 난이도 필터
    if difficulty:
        stmt = stmt.where(Recipe.difficulty == difficulty.strip())

    # 정렬 및 페이징 (기본 id 오름차순)
    stmt = stmt.order_by(Recipe.id.asc()).offset(skip).limit(limit)
    
    recipes = db.execute(stmt).scalars().all()
    return recipes


# 2. 특정 레시피 상세 조회 (재료 및 순서 포함)
@router.get(
    "/{recipe_id}",
    response_model=RecipeDetailResponse,
    summary="특정 레시피 상세 조회",
    description="특정 레시피의 기본 정보, 전체 식재료 목록, 단계별 조리 가이드를 모두 반환합니다."
)
def get_recipe_detail(
    recipe_id: int,
    db: Session = Depends(get_db)
):
    stmt = select(Recipe).where(Recipe.id == recipe_id)
    recipe = db.execute(stmt).scalar_one_or_none()

    if not recipe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {recipe_id}번에 해당하는 레시피를 찾을 수 없습니다."
        )

    # 조회수 1 증가
    recipe.view_count += 1
    db.commit()
    db.refresh(recipe)

    return recipe


# 3. 특정 레시피의 전체 식재료 목록 조회
@router.get(
    "/{recipe_id}/ingredients",
    response_model=List[IngredientResponse],
    summary="특정 레시피의 식재료 목록 조회"
)
def get_recipe_ingredients(
    recipe_id: int,
    db: Session = Depends(get_db)
):
    # 레시피 존재 여부 확인
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {recipe_id}번에 해당하는 레시피를 찾을 수 없습니다."
        )

    stmt = select(Ingredient).where(Ingredient.recipe_id == recipe_id).order_by(Ingredient.id.asc())
    ingredients = db.execute(stmt).scalars().all()
    return ingredients


# 4. 특정 레시피의 특정 조리 단계 단독 조회
@router.get(
    "/{recipe_id}/steps/{step_number}",
    response_model=RecipeStepResponse,
    summary="특정 조리 단계 단독 조회",
    description="요리 진행 중 특정 단계(1단계, 2단계 등)의 조리 지침, 타이머, 안전 주의사항을 조회합니다."
)
def get_recipe_step(
    recipe_id: int,
    step_number: int,
    db: Session = Depends(get_db)
):
    stmt = select(RecipeStep).where(
        RecipeStep.recipe_id == recipe_id,
        RecipeStep.step_number == step_number
    )
    step = db.execute(stmt).scalar_one_or_none()

    if not step:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"레시피 {recipe_id}번의 {step_number}번째 조리 단계를 찾을 수 없습니다."
        )

    return step
