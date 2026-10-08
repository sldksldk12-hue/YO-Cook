from typing import List, Dict, Any, Optional

def analyze_step_safety(
    instruction: Optional[str] = "",
    required_tools: Optional[str] = "",
    safety_warning: Optional[str] = "",
    step_number: Optional[int] = 1,
    total_steps: Optional[int] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    조리 단계 텍스트, 필요 도구, 안전 주의사항을 3중 분석하여
    현재 단계에서 활성화해야 할 위험 감지 모드(칼/화기)를 반환합니다.

    💡 [도구/키워드 미감지 시 안전 폴백(Fallback) 규칙]:
    - 텍스트가 모호해서 칼/불 키워드를 모두 찾지 못한 경우:
      1) 1단계(초반): 재료 손질일 확률이 95% 이상이므로 칼 감지(is_knife) 기본 ON!
      2) 2단계~마지막 전 단계(중반): 가열/볶기일 확률이 90% 이상이므로 화기 감지(is_heat) 기본 ON!
      3) 마지막 단계: 그릇 담기 및 완성이므로 둘 다 OFF (완전 안전)
      (단, 카테고리가 '샐러드/무침' 등 비가열 요리인 경우 화기 감지 제외)
    """
    corpus = f"{instruction or ''} {required_tools or ''} {safety_warning or ''}".lower()

    # 1. 칼날 위험 (KNIFE_PROXIMITY) 분석 키워드 (명사 + 조리 동사)
    knife_keywords = [
        "칼", "도마", "가위", "썰", "다지", "깍둑", "자르", "채썰", "포를", "토막", "발라", "껍질"
    ]
    is_knife = any(keyword in corpus for keyword in knife_keywords)

    # 2. 화기 방치/자리비움 (UNATTENDED) 분석 키워드 (명사 + 가열 동사)
    heat_keywords = [
        "불", "팬", "냄비", "가열", "볶", "끓", "굽", "데치", "튀기", "익히", 
        "달군", "센불", "중불", "약불", "프라이팬", "기름", "졸이", "뜸"
    ]
    is_heat = any(keyword in corpus for keyword in heat_keywords)

    # 3. [안전 폴백 규칙 (Safe Default)]: 텍스트가 모호하여 칼/불 키워드가 모두 없을 때
    if not is_knife and not is_heat:
        is_cold_dish = category and any(c in category.lower() for c in ["샐러드", "salad", "무침", "회", "raw", "디저트", "dessert", "음료"])
        
        step_num = step_number or 1
        tot_steps = total_steps or 4

        if step_num == 1:
            # 1단계는 키워드가 없어도 재료 손질일 확률이 높으므로 칼 감지 기본 활성화!
            is_knife = True
        elif 1 < step_num < tot_steps:
            # 중간 단계는 비가열 요리가 아니면 가열 조리일 확률이 높으므로 화기 감지 기본 활성화!
            if not is_cold_dish:
                is_heat = True
        elif step_num >= tot_steps and tot_steps > 1:
            # 마지막 단계는 그릇에 담거나 완성하는 단계이므로 둘 다 OFF
            pass

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
