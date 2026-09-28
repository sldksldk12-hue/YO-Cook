import streamlit as st
from typing import Optional, Dict, Any
from api_client import (
    get_recipes,
    get_recipe_detail,
    start_session,
    get_session_detail,
    update_session_step,
    complete_session
)

def render_recipe_viewer() -> Optional[int]:
    """
    레시피 탐색, 검색 및 실시간 조리 세션 인터랙션을 제공하는 컴포넌트입니다.
    """
    st.subheader("📖 오늘의 요리 레시피")

    # 세션 상태 변수 초기화
    if "active_session_id" not in st.session_state:
        st.session_state.active_session_id = None
    if "session_report" not in st.session_state:
        st.session_state.session_report = None

    # [모드 1] 요리 완료 리포트 화면
    if st.session_state.session_report is not None:
        report = st.session_state.session_report
        st.success(report.get("message", "요리가 완료되었습니다!"))
        
        c1, c2 = st.columns(2)
        c1.metric("총 조리 시간", f"{report.get('total_cooking_seconds', 0)}초")
        c2.metric("안전 주의 발생", f"{report.get('total_warnings_count', 0)}회")

        if report.get("safety_logs"):
            st.warning("⚠️ 발생했던 안전 주의 내역")
            for log in report["safety_logs"]:
                st.caption(f"- [{log['step_number']}단계] {log['message']}")

        if st.button("🔄 다른 요리 하러 가기", use_container_width=True):
            st.session_state.session_report = None
            st.session_state.active_session_id = None
            st.rerun()
        return None

    # [모드 2] 실시간 요리 진행 모드 (세션 활성화 상태)
    if st.session_state.active_session_id is not None:
        session_id = st.session_state.active_session_id
        session_info = get_session_detail(session_id)

        if not session_info:
            st.error("세션 정보를 불러올 수 없습니다.")
            if st.button("세션 종료"):
                st.session_state.active_session_id = None
                st.rerun()
            return None

        recipe_title = session_info.get("recipe_title", "요리")
        current_step = session_info.get("current_step", 1)
        total_steps = session_info.get("total_steps", 1)
        step_detail = session_info.get("current_step_detail")

        # 진행 바 표시
        progress = current_step / max(total_steps, 1)
        st.markdown(f"### 🔥 [{recipe_title}] 조리 중")
        st.progress(progress, text=f"현재 진행률: {current_step} / {total_steps} 단계 ({int(progress*100)}%)")

        # 현재 조리 단계 카드
        if step_detail:
            st.info(f"📍 **{current_step}단계 가이드**")
            
            if step_detail.get("image_url") and "tab_" not in step_detail["image_url"]:
                st.image(step_detail["image_url"], width=320)

            st.markdown(f"#### {step_detail.get('instruction', '')}")

            # 타이머 / 도구 배지
            badges = []
            timer = step_detail.get("timer_seconds", 0)
            tools = step_detail.get("required_tools")
            if timer > 0:
                badges.append(f"⏱️ 권장 시간: `{timer}초`")
            if tools:
                badges.append(f"🔪 필요 도구: `{tools}`")
            if badges:
                st.markdown(" | ".join(badges))

            # 안전 주의사항
            if step_detail.get("safety_warning"):
                st.warning(f"⚠️ **안전 주의사항:** {step_detail['safety_warning']}")

        # 조리 제어 버튼 (이전 / 다음 / 완료)
        st.markdown("---")
        btn_col1, btn_col2, btn_col3 = st.columns(3)
        
        with btn_col1:
            if st.button("⬅️ 이전 단계", disabled=(current_step <= 1), use_container_width=True):
                update_session_step(session_id, action="PREV")
                st.rerun()

        with btn_col2:
            if current_step < total_steps:
                if st.button("➡️ 다음 단계", type="primary", use_container_width=True):
                    update_session_step(session_id, action="NEXT")
                    st.rerun()
            else:
                st.write("")

        with btn_col3:
            if current_step >= total_steps:
                if st.button("🎉 요리 완료!", type="primary", use_container_width=True):
                    res = complete_session(session_id)
                    st.session_state.session_report = res
                    st.session_state.active_session_id = None
                    st.balloons()
                    st.rerun()
            else:
                if st.button("⏹️ 조리 중단", use_container_width=True):
                    complete_session(session_id)
                    st.session_state.active_session_id = None
                    st.rerun()

        return session_info.get("recipe_id")

    # [모드 3] 레시피 검색 및 탐색 모드 (요리 시작 전)
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
    
    col_info1, col_info2 = st.columns([1, 2.5])
    with col_info1:
        if detail.get("thumbnail_url"):
            st.image(detail["thumbnail_url"], width=230)
        else:
            st.image("https://via.placeholder.com/230x160?text=YO-Cook+Recipe", width=230)
            
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

    # 🌟 요리 시작하기 크고 눈에 띄는 버튼 배치
    if st.button("🍳 이 레시피로 요리 시작하기 (실시간 조리 모드)", type="primary", use_container_width=True, key="start_cooking_btn"):
        new_session = start_session(selected_recipe_id)
        if new_session:
            st.session_state.active_session_id = new_session["id"]
            st.rerun()

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
                        st.image(step_img, width=240)
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
