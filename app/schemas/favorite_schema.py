from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.recipe_schema import RecipeSummaryResponse

# 1. 찜하기 토글 요청 및 응답 스키마
class FavoriteToggleRequest(BaseModel):
    user_id: int = Field(1, description="사용자 ID (기본값: 1)")

class FavoriteToggleResponse(BaseModel):
    recipe_id: int
    is_favorited: bool
    total_favorites_count: int
    message: str

class FavoriteStatusResponse(BaseModel):
    recipe_id: int
    is_favorited: bool
    total_favorites_count: int

class UserFavoritesListResponse(BaseModel):
    user_id: int
    total_count: int
    recipes: List[RecipeSummaryResponse] = []
