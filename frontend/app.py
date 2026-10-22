import streamlit as st
import requests
import importlib
import uuid
import base64
import time  # [추가] 실시간 모니터링 대기 시간을 위해 임포트
import api_client
import recipe_viewer

# 모듈 수정사항 실시간 즉시 반영
importlib.reload(api_client)
importlib.reload(recipe_viewer)

from recipe_viewer import render_recipe_viewer

# 페이지 기본 설정
st.set_page_config(
    page_title="YO-Cook AI Cooking Mate",
    page_icon="🍳",
    layout="wide"
)

# --- [세션 상태(Session State) 초기화] ---
if "session_code" not in st.session_state:
    st.session_state.session_code = str(uuid.uuid4())
if "current_step" not in st.session_state:
    st.session_state.current_step = 1
# ----------------------------------------

st.title("🍳 YO-Cook: 스마트 AI 쿠킹메이트")
st.caption(f"AI 기반 실시간 비전 위험 감지 및 스마트 음성 요리 가이드 | 🔑 현재 세션: `{st.session_state.session_code}`")
st.markdown("---")

col_left, col_right = st.columns([1.1, 1], gap="large")

# [우측 영역] AI 실시간 인터랙션 (비전 + 자연어)
# (음성 질문으로 단계 변경 시 좌측 레시피 뷰어에 즉시 반영되도록 상태 업데이트 연동)
with col_right:
    # 1. 비전 섹션
    st.header("📷 실시간 주방 모니터링 (Vision)")
    st.info("웹캠 기반 실시간 객체 탐지(YOLOv8) 및 위험 상황 경고 화면이 연동됩니다.")
    
    # 웹캠 스트리밍 임시 화면
    st.image("https://via.placeholder.com/600x320?text=Webcam+Stream+Placeholder", width="stretch")

    # [신규 추가] 실시간 위험 모니터링 스위치 및 경고 로직
    is_monitoring = st.toggle("🚨 실시간 위험 감지 켜기", value=False)
    
    if is_monitoring:
        # 백엔드 API에서 현재 안전 상태를 가져오기
        try:
            res = requests.get("http://localhost:8000/api/nlp/vision-status")
            if res.status_code == 200:
                vision_data = res.json()
                current_status = vision_data.get("status", "SAFE")
                
                # 상태에 따른 UI 경고 표시
                if current_status == "DANGER":
                    st.error("🚨 [위험] 칼과 손이 너무 가깝거나 빈 화구가 켜져 있습니다! 즉시 확인하세요!", icon="🔥")
                    st.toast("위험 상황 감지!", icon="🚨")
                elif current_status == "WARNING":
                    st.warning("⚠️ [주의] 위험 요인이 감지되었습니다. 조심하세요.", icon="⚠️")
                else:
                    st.success("✅ 현재 주방은 안전합니다.", icon="🛡️")
        except Exception as e:
            st.error("비전 서버와 연결할 수 없습니다.")
            
        # 2초 대기 후 화면을 자동으로 새로고침하여 지속적으로 상태를 체크
        time.sleep(2)
        st.rerun()

    st.markdown("---")

    # 2. NLP / 음성 섹션
    st.header("💬 AI 레시피 어시스턴트 (NLP/RAG)")
    st.metric(label="현재 요리 단계", value=f"{st.session_state.current_step} 단계 진행 중")
    st.info("음성 명령을 통해 다음 요리 단계나 대체 식재료를 질문해 보세요.")
    
    uploaded_audio = st.file_uploader("음성 질문 파일 업로드 (.mp3, .wav)", type=["mp3", "wav"])
    
    if st.button("질문 전송", use_container_width=True):
        if uploaded_audio is not None:
            with st.spinner("AI가 답변을 준비 중입니다..."):
                files = {"file": (uploaded_audio.name, uploaded_audio.getvalue(), uploaded_audio.type)}
                data = {"session_code": st.session_state.session_code}
                
                try:
                    response = requests.post("http://localhost:8000/api/nlp/process-audio", files=files, data=data)
                    
                    if response.status_code == 200:
                        result = response.json()
                        if "current_step" in result:
                            st.session_state.current_step = result["current_step"]
                        if result.get("session_id"):
                            st.session_state.active_session_id = result["session_id"]
                        if result.get("session_code"):
                            st.session_state.session_code = result["session_code"]
                            
                        st.success("분석 완료!")
                        st.write(f"🗣️ **질문:** {result.get('recognized_text')}")
                        st.write(f"🧠 **의도:** {result.get('intent')}")
                        st.info(f"🤖 **답변:**\n\n{result.get('ai_response')}")
                        
                        if "audio_base64" in result:
                            audio_bytes = base64.b64decode(result["audio_base64"])
                            st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                    else:
                        st.error(f"서버 에러가 발생했습니다. (상태 코드: {response.status_code})")
                except Exception as e:
                    st.error("백엔드 서버에 연결할 수 없습니다.\n에러 내용: " + str(e))
        else:
            st.warning("먼저 음성 파일을 업로드해 주세요.")

# [좌측 영역] 레시피 가이드 (우측 음성 명령에 의한 단계 변경이 같은 화면 렌더링에 즉시 반영됨)
with col_left:
    selected_recipe_id = render_recipe_viewer()
