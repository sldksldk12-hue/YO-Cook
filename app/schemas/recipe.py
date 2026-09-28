from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime

# 1. 재료 스키마 (Ingredient)
class IngredientResponse(BaseModel):
    id: int
    name: str
    amount: str
    unit: Optional[str] = None
    is_seasoning: bool
    is_essential: bool

    model_config = ConfigDict(from_attributes=True)


# 2. 조리 단계 스키마 (RecipeStep)
class RecipeStepResponse(BaseModel):
    id: int
    step_number: int
    instruction: str
    timer_seconds: int
    image_url: Optional[str] = None
    tip: Optional[str] = None
    safety_warning: Optional[str] = None
    required_tools: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# 3. 레시피 요약 스키마 (목록 조회용)
class RecipeSummaryResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    category: str
    tags: Optional[str] = None
    cooking_time_minutes: int
    difficulty: str
    servings: str
    thumbnail_url: Optional[str] = None
    view_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# 4. 레시피 상세 스키마 (재료 + 조리순서 포함)
class RecipeDetailResponse(RecipeSummaryResponse):
    source_url: Optional[str] = None
    ingredients: List[IngredientResponse] = []
    steps: List[RecipeStepResponse] = []

    model_config = ConfigDict(from_attributes=True)
