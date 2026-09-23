import streamlit as st
import requests

# 페이지 기본 설정
st.set_page_config(page_title="YO-Cook AI Cooking Mate", page_icon="🍳", layout="wide")

st.title("🍳 YO-Cook: 스마트 AI 쿠킹메이트")
st.markdown("---")

# 화면을 두 개의 컬럼으로 분할 (좌측: 비전, 우측: 자연어)
col1, col2 = st.columns([1, 1])

with col1:
    st.header("📷 실시간 주방 모니터링 (Vision)")
    st.info("이곳에 웹캠 기반 실시간 객체 탐지(YOLOv8) 및 위험 상황 경고 화면이 연동됩니다.")
    # 추후 백엔드의 실시간 영상 스트리밍 URL을 st.image() 등으로 띄울 예정입니다.
    st.image("https://via.placeholder.com/600x400?text=Webcam+Stream+Placeholder", use_column_width=True)

with col2:
    st.header("💬 AI 레시피 어시스턴트 (NLP/RAG)")
    st.info("음성 명령을 통해 다음 요리 단계나 대체 식재료를 질문해 보세요.")
    
    # 1. 테스트용 오디오 파일 업로드 UI
    uploaded_audio = st.file_uploader("음성 질문 파일 업로드 (.mp3, .wav)", type=["mp3", "wav"])
    
    if st.button("질문 전송", use_container_width=True):
        if uploaded_audio is not None:
            with st.spinner("AI가 레시피를 분석하고 답변을 고민 중입니다..."):
                # 2. FastAPI 백엔드로 오디오 파일 전송
                # 백엔드 서버가 http://localhost:8000 에서 실행 중이어야 합니다.
                files = {"file": (uploaded_audio.name, uploaded_audio.getvalue(), uploaded_audio.type)}
                try:
                    response = requests.post("http://localhost:8000/api/nlp/process-audio", files=files)
                    
                    if response.status_code == 200:
                        result = response.json()
                        
                        # 3. 백엔드 처리 결과 화면 출력
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