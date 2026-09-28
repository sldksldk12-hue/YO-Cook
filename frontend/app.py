import streamlit as st
import requests
import importlib
import api_client
import recipe_viewer

# 모듈 수정사항 실시간 즉시 반영 (Streamlit 모듈 캐싱 방지)
importlib.reload(api_client)
importlib.reload(recipe_viewer)

from recipe_viewer import render_recipe_viewer

# 페이지 기본 설정
st.set_page_config(
    page_title="YO-Cook AI Cooking Mate",
    page_icon="🍳",
    layout="wide"
)

st.title("🍳 YO-Cook: 스마트 AI 쿠킹메이트")
st.caption("AI 기반 실시간 비전 위험 감지 및 스마트 음성 요리 가이드")
st.markdown("---")

# 화면을 2개의 큰 컬럼으로 분할 (좌측: 레시피 가이드, 우측: AI 비전 & 음성 어시스턴트)
col_left, col_right = st.columns([1.1, 1], gap="large")

# [좌측 영역] 레시피 검색, 선택, 식재료 및 단계별 가이드 (하석님 담당 모듈)
with col_left:
    selected_recipe_id = render_recipe_viewer()

# [우측 영역] AI 실시간 인터랙션 (비전 + 자연어)
with col_right:
    # 1. 비전 섹션
    st.header("📷 실시간 주방 모니터링 (Vision)")
    st.info("웹캠 기반 실시간 객체 탐지(YOLOv8) 및 위험 상황 경고 화면이 연동됩니다.")
    st.image("https://via.placeholder.com/600x320?text=Webcam+Stream+Placeholder", width="stretch")

    st.markdown("---")

    # 2. NLP / 음성 섹션
    st.header("💬 AI 레시피 어시스턴트 (NLP/RAG)")
    st.info("음성 명령을 통해 다음 요리 단계나 대체 식재료를 질문해 보세요.")
    
    uploaded_audio = st.file_uploader("음성 질문 파일 업로드 (.mp3, .wav)", type=["mp3", "wav"])
    
    if st.button("질문 전송", use_container_width=True):
        if uploaded_audio is not None:
            with st.spinner("AI가 레시피를 분석하고 답변을 고민 중입니다..."):
                files = {"file": (uploaded_audio.name, uploaded_audio.getvalue(), uploaded_audio.type)}
                try:
                    response = requests.post("http://localhost:8000/api/nlp/process-audio", files=files)
                    
                    if response.status_code == 200:
                        result = response.json()
                        st.success("분석 완료!")
                        st.write(f"🗣️ **인식된 질문:** {result.get('recognized_text')}")
                        st.write(f"🧠 **파악된 의도:** {result.get('intent')}")
                        st.info(f"🤖 **YO-Cook의 답변:**\n\n{result.get('ai_response')}")
                    else:
                        st.error(f"서버 에러가 발생했습니다. (상태 코드: {response.status_code})")
                except Exception as e:
                    st.error(f"백엔드 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.\n에러 내용: {e}")
        else:
            st.warning("먼저 음성 파일을 업로드해 주세요.")