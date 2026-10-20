from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.models.database import get_db
from app.models.recipe import Recipe
from app.models.user import User, UserFavorite
from app.schemas.favorite_schema import (
    FavoriteToggleRequest,
    FavoriteToggleResponse,
    FavoriteStatusResponse,
    UserFavoritesListResponse
)
from app.schemas.recipe_schema import RecipeSummaryResponse

router = APIRouter()

# 1. 레시피 찜하기 / 찜취소 토글 (POST /api/recipes/{recipe_id}/favorite)
@router.post(
    "/recipes/{recipe_id}/favorite",
    response_model=FavoriteToggleResponse,
    summary="레시피 찜하기 토글",
    description="레시피를 찜(즐겨찾기) 목록에 추가하거나 이미 찜한 경우 취소합니다."
)
def toggle_recipe_favorite(
    recipe_id: int,
    payload: FavoriteToggleRequest = FavoriteToggleRequest(),
    db: Session = Depends(get_db)
):
    # 1. 레시피 존재 여부 확인
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID {recipe_id}번에 해당하는 레시피를 찾을 수 없습니다."
        )

    # 2. 유저 존재 여부 확인 (없으면 기본 생성)
    user = db.get(User, payload.user_id)
    if not user:
        user = User(id=payload.user_id, username=f"user_{payload.user_id}", nickname="스마트 요리사")
        db.add(user)
        db.commit()

    # 3. 이미 찜했는지 확인
    stmt = select(UserFavorite).where(
        UserFavorite.user_id == payload.user_id,
        UserFavorite.recipe_id == recipe_id
    )
    existing_favorite = db.execute(stmt).scalar_one_or_none()

    if existing_favorite:
        # 이미 찜한 상태 -> 찜 취소 (DELETE)
        db.delete(existing_favorite)
        db.commit()
        is_favorited = False
        msg = f"'{recipe.title}' 찜을 취소했습니다 🤍"
    else:
        # 아직 찜하지 않은 상태 -> 찜 추가 (INSERT)
        new_fav = UserFavorite(user_id=payload.user_id, recipe_id=recipe_id)
        db.add(new_fav)
        db.commit()
        is_favorited = True
        msg = f"'{recipe.title}'을(를) 찜 목록에 저장했습니다 ❤️"

    # 총 찜 개수 집계
    count_stmt = select(func.count(UserFavorite.id)).where(UserFavorite.recipe_id == recipe_id)
    total_count = db.execute(count_stmt).scalar() or 0

    return FavoriteToggleResponse(
        recipe_id=recipe_id,
        is_favorited=is_favorited,
        total_favorites_count=total_count,
        message=msg
    )


# 2. 레시피 찜 상태 조회 (GET /api/recipes/{recipe_id}/favorite-status)
@router.get(
    "/recipes/{recipe_id}/favorite-status",
    response_model=FavoriteStatusResponse,
    summary="레시피 찜 상태 조회"
)
def get_favorite_status(
    recipe_id: int,
    user_id: int = Query(1, description="확인할 사용자 ID"),
    db: Session = Depends(get_db)
):
    stmt = select(UserFavorite).where(
        UserFavorite.user_id == user_id,
        UserFavorite.recipe_id == recipe_id
    )
    is_fav = db.execute(stmt).scalar_one_or_none() is not None

    count_stmt = select(func.count(UserFavorite.id)).where(UserFavorite.recipe_id == recipe_id)
    total_count = db.execute(count_stmt).scalar() or 0

    return FavoriteStatusResponse(
        recipe_id=recipe_id,
        is_favorited=is_fav,
        total_favorites_count=total_count
    )


# 3. 내가 찜한 레시피 전체 목록 조회 (GET /api/users/{user_id}/favorites)
@router.get(
    "/users/{user_id}/favorites",
    response_model=UserFavoritesListResponse,
    summary="사용자가 찜한 레시피 전체 목록 조회"
)
def get_user_favorite_recipes(
    user_id: int,
    db: Session = Depends(get_db)
):
    stmt = (
        select(Recipe)
        .join(UserFavorite, UserFavorite.recipe_id == Recipe.id)
        .where(UserFavorite.user_id == user_id)
        .order_by(UserFavorite.created_at.desc())
    )
    favorite_recipes = db.execute(stmt).scalars().all()

    return UserFavoritesListResponse(
        user_id=user_id,
        total_count=len(favorite_recipes),
        recipes=[RecipeSummaryResponse.model_validate(r) for r in favorite_recipes]
    )
