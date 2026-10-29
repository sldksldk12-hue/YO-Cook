from typing import List, Dict, Any, Optional
import re

def analyze_step_safety(
    instruction: Optional[str] = "",
    required_tools: Optional[str] = "",
    safety_warning: Optional[str] = "",
    step_number: Optional[int] = 1,
    total_steps: Optional[int] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    조리 단계 텍스트, 필요 도구, 안전 주의사항을 정밀 분석하여
    현재 단계에서 실제로 칼이나 화기(불)를 사용하는 단계일 때만 해당 위험 감지 모드를 활성화합니다.
    """
    text = f"{instruction or ''} {required_tools or ''}".strip()

    # 1. 칼날 위험 (KNIFE_PROXIMITY) 분석 키워드
    knife_keywords = [
        "식칼", "과도", "도마", "가위", "썰어", "썰고", "썬다", "썰기", "다져", "다진", "다지기",
        "깍둑", "어슷", "채썰", "자르", "잘라", "포를", "토막", "손질해", "칼질"
    ]
    is_knife = any(keyword in text for keyword in knife_keywords)

    # 2. 화기 방치/자리비움 (UNATTENDED) 분석 키워드
    #    - 주의: "참기름", "들기름", "불린", "불려", "물기를 빼" 등은 가열 조리가 아니므로 먼저 제외!
    clean_heat_text = text
    for non_heat in ["참기름", "들기름", "고추기름", "기름기", "불린", "불려", "불려서", "불리", "불을 끄", "불을 꺼"]:
        clean_heat_text = clean_heat_text.replace(non_heat, "")

    heat_keywords = [
        "가스", "인덕션", "레인지", "화구", "강불", "중불", "약불", "센불", "중약불", "중강불",
        "불에", "불을 켜", "불로", "달군", "달궈", "예열", "가열",
        "볶아", "볶고", "볶은", "볶기", "볶습",
        "끓여", "끓이", "끓기", "끓어", "끓는", "삶아", "삶고", "삶기",
        "구워", "굽고", "굽기", "데쳐", "데치", "튀겨", "튀기", "부쳐", "부치", "졸여", "졸이"
    ]
    is_heat = any(keyword in clean_heat_text for keyword in heat_keywords)

    active_hazards: List[str] = []
    if is_knife:
        active_hazards.append("KNIFE_PROXIMITY")
    if is_heat:
        active_hazards.append("UNATTENDED")

    return {
        "is_knife_monitoring": is_knife,
        "is_unattended_monitoring": is_heat,
        "active_hazards": active_hazards
    }
