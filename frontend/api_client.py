import os
import requests
from typing import List, Dict, Any, Optional

# 백엔드 서버 기본 주소 (환경 변수 또는 기본 로컬 주소)
API_BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

def get_recipes(
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    difficulty: Optional[str] = None
) -> List[Dict[str, Any]]:
    """FastAPI 백엔드에서 레시피 목록을 검색 및 조회합니다."""
    params = {}
    if keyword:
        params["keyword"] = keyword
    if category and category != "전체":
        params["category"] = category
    if difficulty and difficulty != "전체":
        params["difficulty"] = difficulty

    try:
        response = requests.get(f"{API_BASE_URL}/api/recipes", params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
        return []
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 레시피 목록 조회 실패: {e}")
        return []

def get_recipe_detail(recipe_id: int) -> Optional[Dict[str, Any]]:
    """특정 레시피의 상세 정보(재료 및 조리단계 포함)를 조회합니다."""
    try:
        response = requests.get(f"{API_BASE_URL}/api/recipes/{recipe_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 레시피 상세 조회 실패 (ID {recipe_id}): {e}")
        return None

def get_recipe_step(recipe_id: int, step_number: int) -> Optional[Dict[str, Any]]:
    """특정 레시피의 N번째 단계 정보를 단독 조회합니다."""
    try:
        response = requests.get(f"{API_BASE_URL}/api/recipes/{recipe_id}/steps/{step_number}", timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 조리 단계 조회 실패 (레시피 {recipe_id}, 단계 {step_number}): {e}")
        return None
