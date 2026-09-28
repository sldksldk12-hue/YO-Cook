import streamlit as st
from typing import Optional, Dict, Any
from api_client import get_recipes, get_recipe_detail

def render_recipe_viewer() -> Optional[int]:
    """
    레시피 탐색, 검색 및 상세 정보(재료, 조리 순서)를 표시하는 컴포넌트 함수입니다.
    선택된 recipe_id를 반환하여 다른 모듈(AI 음성, 비전)에서 활용할 수 있도록 합니다.
    """
    st.subheader("📖 오늘의 요리 레시피")

    # 1. 검색 및 필터 UI
    col_search, col_diff = st.columns([2, 1])
    with col_search:
        keyword = st.text_input("🔍 레시피 검색", placeholder="예: 김치, 계란, 파스타...")
    with col_diff:
        difficulty = st.selectbox("난이도", ["전체", "초급", "중급", "고급"])

    # 2. 백엔드에서 레시피 목록 가져오기
    recipes = get_recipes(
        keyword=keyword if keyword else None,
        difficulty=difficulty if difficulty != "전체" else None
    )

    if not recipes:
        st.warning("조건에 맞는 레시피가 없습니다. 백엔드 서버가 실행 중인지 확인해주세요.")
        return None

    # 3. 레시피 선택 드롭다운
    recipe_options = {
        f"[{r['id']}] {r['title']} ({r['cooking_time_minutes']}분 / {r['difficulty']})": r['id']
        for r in recipes
    }

    selected_label = st.selectbox(
        "요리할 레시피를 선택하세요",
        options=list(recipe_options.keys())
    )
    selected_recipe_id = recipe_options[selected_label]

    # 4. 선택된 레시피 상세 정보 가져오기
    detail: Optional[Dict[str, Any]] = get_recipe_detail(selected_recipe_id)

    if not detail:
        st.error("레시피 상세 정보를 불러오지 못했습니다.")
        return selected_recipe_id

    # 5. 레시피 기본 정보 카드 표시
    st.markdown("---")
    
    col_info1, col_info2 = st.columns([1, 2])
    with col_info1:
        if detail.get("thumbnail_url"):
            st.image(detail["thumbnail_url"], width="stretch")
        else:
            st.image("https://via.placeholder.com/300x200?text=YO-Cook+Recipe", width="stretch")
            
    with col_info2:
        st.markdown(f"### {detail['title']}")
        if detail.get("description"):
            st.caption(f"📝 {detail['description']}")
            
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("분류", detail.get("category", "일반"))
        m2.metric("조리시간", f"{detail.get('cooking_time_minutes', 0)}분")
        m3.metric("난이도", detail.get("difficulty", "초급"))
        m4.metric("분량", detail.get("servings", "1인분"))

        if detail.get("tags"):
            st.markdown(f"🏷️ `{detail['tags']}`")

    st.markdown("---")

    # 6. 식재료 및 조리 순서 탭 분할
    tab_ing, tab_steps = st.tabs(["🥦 필요 식재료", "🍳 단계별 조리 순서"])

    # [식재료 탭]
    with tab_ing:
        ingredients = detail.get("ingredients", [])
        if not ingredients:
            st.info("등록된 재료 정보가 없습니다.")
        else:
            col_main_ing, col_sauce_ing = st.columns(2)
            
            # 주재료
            with col_main_ing:
                st.markdown("##### 🥗 필수 및 부재료")
                main_items = [i for i in ingredients if not i.get("is_seasoning")]
                for ing in main_items:
                    st.checkbox(f"**{ing['name']}** : {ing['amount']}", key=f"ing_{ing['id']}")
                    
            # 양념 및 조미료
            with col_sauce_ing:
                st.markdown("##### 🧂 양념 및 소스")
                sauce_items = [i for i in ingredients if i.get("is_seasoning")]
                if sauce_items:
                    for ing in sauce_items:
                        st.checkbox(f"**{ing['name']}** : {ing['amount']}", key=f"ing_{ing['id']}")
                else:
                    st.caption("별도 양념 재료 없음")

    # [조리 단계 탭]
    with tab_steps:
        steps = detail.get("steps", [])
        if not steps:
            st.info("등록된 조리 단계가 없습니다.")
        else:
            for step in steps:
                step_num = step.get("step_number")
                inst = step.get("instruction")
                timer = step.get("timer_seconds", 0)
                warning = step.get("safety_warning")
                tools = step.get("required_tools")
                step_img = step.get("image_url")

                with st.expander(f"📍 **{step_num}단계**", expanded=(step_num == 1)):
                    if step_img and "tab_" not in step_img and "mobile" not in step_img:
                        st.image(step_img, width=350)
                    st.write(inst)
                    
                    # 부가 메타데이터 배지
                    badges = []
                    if timer > 0:
                        badges.append(f"⏱️ 권장 타이머: `{timer}초`")
                    if tools:
                        badges.append(f"🔪 필요 도구: `{tools}`")
                    if badges:
                        st.markdown(" | ".join(badges))
                        
                    if warning:
                        st.warning(f"⚠️ **안전 주의사항:** {warning}")

    return selected_recipe_id
