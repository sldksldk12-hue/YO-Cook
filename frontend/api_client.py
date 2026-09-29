import os
import requests
from typing import List, Dict, Any, Optional

# 백엔드 서버 기본 주소 (환경 변수 또는 기본 로컬 주소)
API_BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# 1. 레시피 관련 API 클라이언트
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


# 2. 실시간 조리 세션 관련 API 클라이언트
def start_session(recipe_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """새로운 요리 조리 세션을 시작합니다."""
    payload = {"recipe_id": recipe_id, "user_id": user_id}
    try:
        response = requests.post(f"{API_BASE_URL}/api/sessions/start", json=payload, timeout=5)
        if response.status_code in [200, 201]:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 세션 시작 실패: {e}")
        return None

def get_session_detail(session_id: int) -> Optional[Dict[str, Any]]:
    """현재 세션의 진행 상태와 현재 단계 상세 정보를 조회합니다."""
    try:
        response = requests.get(f"{API_BASE_URL}/api/sessions/{session_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 세션 조회 실패 (ID {session_id}): {e}")
        return None

def update_session_step(session_id: int, action: str = "NEXT", target_step: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """세션의 단계를 앞/뒤로 이동하거나 특정 단계로 변경합니다."""
    payload = {"action": action, "target_step": target_step}
    try:
        response = requests.patch(f"{API_BASE_URL}/api/sessions/{session_id}/step", json=payload, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 세션 단계 변경 실패 (ID {session_id}): {e}")
        return None

def record_safety_log(
    session_id: int,
    step_number: int,
    hazard_type: str,
    message: str,
    level: str = "WARNING",
    distance_px: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """비전 AI에서 감지한 위험 상황을 세션에 기록합니다."""
    payload = {
        "step_number": step_number,
        "hazard_type": hazard_type,
        "level": level,
        "message": message,
        "distance_px": distance_px
    }
    try:
        response = requests.post(f"{API_BASE_URL}/api/sessions/{session_id}/safety-logs", json=payload, timeout=5)
        if response.status_code in [200, 201]:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 안전 로그 기록 실패 (세션 {session_id}): {e}")
        return None

def complete_session(session_id: int) -> Optional[Dict[str, Any]]:
    """요리 세션을 완료 처리하고 결과 리포트를 반환합니다."""
    try:
        response = requests.post(f"{API_BASE_URL}/api/sessions/{session_id}/complete", timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 세션 완료 처리 실패 (ID {session_id}): {e}")
        return None


# 3. 레시피 찜하기(즐겨찾기) 관련 API 클라이언트
def toggle_favorite(recipe_id: int, user_id: int = 1) -> Optional[Dict[str, Any]]:
    """레시피 찜하기/찜취소 토글 요청을 전송합니다."""
    payload = {"user_id": user_id}
    try:
        response = requests.post(f"{API_BASE_URL}/api/favorites/recipes/{recipe_id}/favorite", json=payload, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 찜하기 토글 실패 (레시피 {recipe_id}): {e}")
        return None

def get_favorite_status(recipe_id: int, user_id: int = 1) -> Dict[str, Any]:
    """해당 레시피의 찜 여부 및 총 찜 수를 조회합니다."""
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/favorites/recipes/{recipe_id}/favorite-status",
            params={"user_id": user_id},
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
        return {"is_favorited": False, "total_favorites_count": 0}
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 찜 상태 조회 실패 (레시피 {recipe_id}): {e}")
        return {"is_favorited": False, "total_favorites_count": 0}

def get_user_favorites(user_id: int = 1) -> List[Dict[str, Any]]:
    """사용자가 찜한 레시피 목록을 조회합니다."""
    try:
        response = requests.get(f"{API_BASE_URL}/api/favorites/users/{user_id}/favorites", timeout=5)
        if response.status_code == 200:
            return response.json().get("recipes", [])
        return []
    except requests.exceptions.RequestException as e:
        print(f"[API Error] 찜 목록 조회 실패: {e}")
        return []

