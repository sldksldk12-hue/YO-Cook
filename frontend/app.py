import streamlit as st
import streamlit.components.v1 as components
import requests
import importlib
import uuid
import base64
import hashlib
import time
import cv2  
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
if "audio_enabled" not in st.session_state:
    st.session_state.audio_enabled = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_audio_hash" not in st.session_state:
    st.session_state.last_audio_hash = None
if "wake_word_enabled" not in st.session_state:
    st.session_state.wake_word_enabled = True
if "wake_word" not in st.session_state:
    st.session_state.wake_word = "요쿡아"
# ----------------------------------------

def handle_voice_api_result(result: dict):
    if result.get("status") != "success":
        st.error(result.get("message", "음성 처리 중 오류가 발생했습니다."))
        return

    if "current_step" in result and result["current_step"] is not None:
        st.session_state.current_step = result["current_step"]
    if result.get("session_id"):
        st.session_state.active_session_id = result["session_id"]
    if result.get("session_code"):
        st.session_state.session_code = result["session_code"]

    st.session_state.chat_history.append({
        "user": result.get("recognized_text", ""),
        "intent": result.get("intent", ""),
        "ai": result.get("ai_response", ""),
        "audio_base64": result.get("audio_base64")
    })

st.title("🍳 YO-Cook: 스마트 AI 쿠킹메이트")
st.caption(f"AI 기반 실시간 비전 위험 감지 및 스마트 음성 요리 가이드 | 🔑 현재 세션: `{st.session_state.session_code}`")
st.markdown("---")

col_left, col_right = st.columns([1.1, 1], gap="large")

# [우측 영역] AI 실시간 인터랙션 (비전 + 자연어)
with col_right:
    st.header("📷 실시간 주방 모니터링 (Vision)")
    st.info("웹캠 기반 실시간 객체 탐지(YOLOv8) 및 위험 상황 경고 화면이 연동됩니다.")
    
    is_monitoring = st.toggle("🚨 실시간 위험 감지 켜기", value=False)
    
    vision_placeholder = st.empty()
    alert_placeholder = st.empty()

    if is_monitoring:
        cap = cv2.VideoCapture(0)
        
        # [안정화 1] 모바일 화면 및 레이아웃 유지를 위한 웹캠 해상도 고정
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # [안정화 2] 서버 과부하 방지를 위한 FPS 제한 설정 (초당 10프레임 전송)
        FPS_LIMIT = 10
        last_request_time = 0
        
        while is_monitoring:
            ret, frame = cap.read()
            if not ret:
                alert_placeholder.error("웹캠을 찾을 수 없습니다. 카메라 연결을 확인해 주세요.")
                break
                
            current_time = time.time()
            
            # 지정된 FPS 주기에 도달했을 때만 백엔드에 프레임 전송
            if current_time - last_request_time >= (1.0 / FPS_LIMIT):
                last_request_time = current_time
                
                _, buffer = cv2.imencode('.jpg', frame)
                files = {"file": ("frame.jpg", buffer.tobytes(), "image/jpeg")}
                
                try:
                    res = requests.post("http://localhost:8000/api/vision/detect", files=files)
                    
                    if res.status_code == 200:
                        vision_data = res.json()
                        status = vision_data.get("vision_status", "SAFE")
                        msg = vision_data.get("message", "안전합니다.")
                        
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        vision_placeholder.image(frame_rgb, channels="RGB", use_container_width=True)
                        
                        if status == "DANGER":
                            alert_placeholder.error(f"🚨 {msg}", icon="🔥")
                        elif status == "WARNING":
                            alert_placeholder.warning(f"⚠️ {msg}", icon="⚠️")
                        else:
                            alert_placeholder.success(f"✅ {msg}", icon="🛡️")
                except Exception as e:
                    alert_placeholder.error("비전 서버와 연결이 지연되고 있습니다. 잠시만 기다려주세요.")
                    time.sleep(1) # 에러 시 추가 과부하 방지
                
        cap.release()
    else:
        vision_placeholder.image("https://via.placeholder.com/640x480?text=Webcam+Off", use_container_width=True)
        alert_placeholder.empty()

    st.markdown("---")

    # 2. NLP / 음성 섹션
    st.header("💬 AI 레시피 어시스턴트 (NLP/RAG)")

    if not st.session_state.audio_enabled:
        st.info("💡 브라우저 정책상 핸즈프리 음성 안내를 위해 최초 1회 클릭이 필요합니다.")
        if st.button("🍳 요리 시작 및 음성 안내 켜기", use_container_width=True, type="primary"):
            st.session_state.audio_enabled = True
            st.rerun()
    else:
        top_c1, top_c2 = st.columns([1.2, 1])
        with top_c1:
            st.metric(label="현재 요리 단계", value=f"{st.session_state.current_step} 단계 진행 중")
        with top_c2:
            wake_toggle = st.toggle(
                f"🗣️ 호출어('{st.session_state.wake_word}') 모드",
                value=st.session_state.wake_word_enabled,
                help="켜두면 핸즈프리 대화 시 '요쿡아'라고 부를 때 반응합니다."
            )
            if wake_toggle != st.session_state.wake_word_enabled:
                st.session_state.wake_word_enabled = wake_toggle
                try:
                    requests.patch(
                        "http://localhost:8000/api/users/1/settings",
                        json={"wake_word_enabled": wake_toggle},
                        timeout=2
                    )
                except Exception:
                    pass

        st.info("음성 명령을 통해 다음 요리 단계나 대체 식재료를 질문해 보세요.")

        hands_free = st.toggle(
            "🟢 핸즈프리 연속 음성 대화 켜기 (손 안 대고 말하기)",
            value=False,
            help="켜두면 마이크 버튼을 누르지 않아도 상시 음성을 듣고 자동으로 AI가 음성으로 대답합니다."
        )

        if hands_free:
            wake_js_flag = "true" if st.session_state.wake_word_enabled else "false"
            wake_word_str = st.session_state.wake_word
            hands_free_html = f"""
            <div style="padding:14px; border-radius:12px; background:#f0fdf4; border:1px solid #86efac; font-family:sans-serif;">
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
                    <span id="mic-dot" style="width:12px; height:12px; border-radius:50%; background:#22c55e; display:inline-block; animation: pulse 1.2s infinite;"></span>
                    <strong id="status-title" style="color:#166534; font-size:15px;">
                        🎙️ 상시 음성 대기 중... {f'("{wake_word_str} 다음 단계 알려줘" 라고 말해 보세요!)' if st.session_state.wake_word_enabled else '(편하게 바로 질문해 보세요!)'}
                    </strong>
                </div>
                <div id="live-transcript" style="font-size:14px; color:#374151; min-height:22px; margin-top:4px;">
                    대기 중...
                </div>
                <div id="ai-reply-box" style="display:none; margin-top:10px; padding:10px; border-radius:8px; background:#ffffff; border:1px solid #d1fae5; font-size:14px; color:#111827;">
                </div>
            </div>
            <style>
                @keyframes pulse {{
                    0% {{ transform: scale(0.95); opacity: 0.7; }}
                    50% {{ transform: scale(1.2); opacity: 1; }}
                    100% {{ transform: scale(0.95); opacity: 0.7; }}
                }}
            </style>
            <script>
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                const statusTitle = document.getElementById("status-title");
                const transcriptBox = document.getElementById("live-transcript");
                const replyBox = document.getElementById("ai-reply-box");
                const micDot = document.getElementById("mic-dot");
                const requireWake = {wake_js_flag};
                const wakeVariants = ["{wake_word_str}", "요쿡아", "요쿠가", "요쿡", "요국아", "요코가", "여쿡아"];
                let isSpeaking = false;

                if (!SpeechRecognition) {{
                    statusTitle.innerText = "⚠️ 이 브라우저는 실시간 음성 인식을 지원하지 않습니다 (Chrome/Edge 권장)";
                }} else {{
                    const recognition = new SpeechRecognition();
                    recognition.lang = "ko-KR";
                    recognition.continuous = true;
                    recognition.interimResults = true;

                    recognition.onresult = async (event) => {{
                        if (isSpeaking) return;
                        let interim = "";
                        let finalTxt = "";
                        for (let i = event.resultIndex; i < event.results.length; ++i) {{
                            if (event.results[i].isFinal) {{
                                finalTxt += event.results[i][0].transcript.trim();
                            }} else {{
                                interim += event.results[i][0].transcript;
                            }}
                        }}
                        if (interim) {{
                            transcriptBox.innerText = "🗣️ 듣는 중: " + interim;
                        }}
                        if (finalTxt) {{
                            const hasWake = wakeVariants.some(w => finalTxt.includes(w));
                            if (requireWake && !hasWake) {{
                                transcriptBox.innerText = "💤 ('{wake_word_str}' 호출어를 먼저 말씀해 주세요) 인식됨: " + finalTxt;
                                return;
                            }}
                            isSpeaking = true;
                            micDot.style.background = "#f59e0b";
                            transcriptBox.innerText = "🗣️ 내 질문: " + finalTxt + " (AI 답변 생성 중...)";

                            try {{
                                const res = await fetch("http://localhost:8000/api/nlp/process-text", {{
                                    method: "POST",
                                    headers: {{ "Content-Type": "application/json" }},
                                    body: JSON.stringify({{
                                        text: finalTxt,
                                        session_code: "{st.session_state.session_code}",
                                        user_id: 1
                                    }})
                                }});
                                const data = await res.json();
                                if (data.status === "success") {{
                                    replyBox.style.display = "block";
                                    replyBox.innerHTML = "<strong>🤖 YO-Cook (" + data.intent + "):</strong><br/>" + data.ai_response;
                                    if (data.audio_base64) {{
                                        const audio = new Audio("data:audio/mp3;base64," + data.audio_base64);
                                        audio.onended = () => {{
                                            isSpeaking = false;
                                            micDot.style.background = "#22c55e";
                                        }};
                                        await audio.play();
                                    }} else {{
                                        isSpeaking = false;
                                        micDot.style.background = "#22c55e";
                                    }}
                                }} else {{
                                    isSpeaking = false;
                                    micDot.style.background = "#22c55e";
                                }}
                            }} catch (err) {{
                                transcriptBox.innerText = "❌ 백엔드 통신 오류: " + err;
                                isSpeaking = false;
                                micDot.style.background = "#ef4444";
                            }}
                        }}
                    }};

                    // 권한 거부/차단 시에는 자동 재시작을 멈춰 팝업이 반복되지 않게 함
                    let fatal = false;
                    let restartDelay = 800;
                    recognition.onstart = () => {{ restartDelay = 800; }};
                    recognition.onerror = (e) => {{
                        if (e.error === "not-allowed" || e.error === "service-not-allowed") {{
                            fatal = true;
                            statusTitle.innerText = "🔇 마이크 권한이 필요합니다. 아래 버튼을 눌러 허용해 주세요.";
                            micDot.style.background = "#ef4444";
                            const b = document.createElement("button");
                            b.innerText = "🎤 음성 인식 켜기";
                            b.style.cssText = "margin-top:6px;padding:8px 14px;border-radius:8px;border:0;background:#2563eb;color:#fff;font-size:14px;";
                            b.onclick = () => {{ fatal = false; b.remove(); try {{ recognition.start(); }} catch (err) {{}} }};
                            transcriptBox.appendChild(b);
                        }}
                    }};
                    // 모바일 Chrome은 말이 끝날 때마다 onend가 발생하므로, 즉시 재시작하지 않고 간격을 두고 재시작
                    recognition.onend = () => {{
                        if (fatal) return;
                        setTimeout(() => {{
                            try {{ recognition.start(); }} catch (e) {{}}
                        }}, restartDelay);
                        restartDelay = Math.min(restartDelay * 1.5, 5000);
                    }};
                    try {{ recognition.start(); }} catch (e) {{}}
                }}
            </script>
            """
            components.html(hands_free_html, height=165)

        live_audio = st.audio_input("🎤 마이크로 바로 말하기 (말이 끝나면 자동 전송됩니다)")
        if live_audio is not None:
            audio_bytes_raw = live_audio.getvalue()
            audio_hash = hashlib.md5(audio_bytes_raw).hexdigest()
            if audio_hash != st.session_state.last_audio_hash:
                st.session_state.last_audio_hash = audio_hash
                with st.spinner("🎙️ 음성을 인식하고 답변을 준비 중입니다..."):
                    files = {"file": ("live_voice.wav", audio_bytes_raw, "audio/wav")}
                    data = {"session_code": st.session_state.session_code}
                    try:
                        response = requests.post("http://localhost:8000/api/nlp/process-audio", files=files, data=data)
                        if response.status_code == 200:
                            handle_voice_api_result(response.json())
                        else:
                            st.error(f"서버 에러가 발생했습니다. (상태 코드: {response.status_code})")
                    except Exception as e:
                        st.error(f"백엔드 서버에 연결할 수 없습니다.\n에러 내용: {e}")

        if st.session_state.chat_history:
            latest = st.session_state.chat_history[-1]
            with st.container(border=True):
                st.markdown(f"🗣️ **질문:** {latest['user']}")
                st.markdown(f"🧠 **의도:** {latest['intent']}")
                st.info(f"🤖 **답변:**\n\n{latest['ai']}")
                if latest.get("audio_base64"):
                    audio_bytes = base64.b64decode(latest["audio_base64"])
                    st.audio(audio_bytes, format="audio/mp3", autoplay=True)

        with st.expander("📂 음성 질문 파일 업로드 (.mp3, .wav)", expanded=False):
            uploaded_audio = st.file_uploader("음성 질문 파일 업로드 (.mp3, .wav)", type=["mp3", "wav"])
            if st.button("질문 전송", use_container_width=True):
                if uploaded_audio is not None:
                    with st.spinner("AI가 답변을 준비 중입니다..."):
                        files = {"file": (uploaded_audio.name, uploaded_audio.getvalue(), uploaded_audio.type)}
                        data = {"session_code": st.session_state.session_code}
                        
                        try:
                            response = requests.post("http://localhost:8000/api/nlp/process-audio", files=files, data=data)
                            if response.status_code == 200:
                                handle_voice_api_result(response.json())
                                st.rerun()
                            else:
                                st.error(f"서버 에러가 발생했습니다. (상태 코드: {response.status_code})")
                        except Exception as e:
                            st.error(f"백엔드 서버에 연결할 수 없습니다.\n에러 내용: {e}")
                else:
                    st.warning("먼저 음성 파일을 업로드해 주세요.")

with col_left:
    selected_recipe_id = render_recipe_viewer()