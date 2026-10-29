from fastapi import APIRouter, UploadFile, File, Form, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from pathlib import Path
import whisper
import uuid
import os
import shutil
import base64                  # 오디오 데이터를 텍스트 형태로 변환
from io import BytesIO         # 오디오 파일을 메모리에서 바로 처리
from gtts import gTTS          # 텍스트를 음성으로 변환하는 라이브러리
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

# 기존 함수 대신 세션을 인식하는 새로운 RAG 함수 불러오기
from app.services.rag import generate_session_aware_answer
from app.models.database import get_db
from app.models.user import User
from app.api.vision import get_current_vision_status, _sync_active_session_step_flags

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

router = APIRouter()

print("=> Whisper 'base' 모델 로딩 중...")
whisper_model = whisper.load_model("base")


class TextQueryRequest(BaseModel):
    text: str
    session_code: str
    user_id: Optional[int] = 1


def _strip_wake_word(text: str, wake_word: str = "요쿡아") -> tuple[bool, str]:
    """
    발화 텍스트에서 호출어('요쿡아' 및 Whisper 유사 오인식 발음)를 감지하고
    호출어 뒷부분의 실제 질문만 깔끔하게 분리합니다.
    """
    cleaned = text.strip()
    candidates = [wake_word, "요쿡아", "요쿠가", "요쿡", "요국아", "요코가", "여쿡아", "유쿡아", "요쿡이"]
    detected = False
    for w in candidates:
        if w and w in cleaned:
            detected = True
            idx = cleaned.find(w) + len(w)
            remainder = cleaned[idx:].lstrip(" ,.!?~")
            if remainder:
                cleaned = remainder
            break
    return detected, cleaned


# Whisper가 무음/백색소음 구간에서 습관적으로 생성하는 환각(Hallucination) 문구 필터
WHISPER_HALLUCINATIONS = (
    "시청해주셔서", "시청해 주셔서", "구독과 좋아요", "MBC 뉴스", "SBS 뉴스", "KBS 뉴스",
    "자막 제공", "한글자막", "감사합니다.", "다음 영상에서", "알림 설정", "소금, 간장, 고추장"
)


def classify_user_intent(user_text: str) -> str:
    """LangChain을 활용하여 텍스트의 의도를 4가지 중 하나로 분류합니다."""
    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)
    
    prompt = PromptTemplate.from_template(
        """당신은 AI 요리 도우미입니다. 사용자의 입력 텍스트를 바탕으로 의도를 다음 중 하나로만 분류하세요.
        - [다음단계]: 다음 요리 순서를 물어볼 때
        - [재료질문]: 대체 재료나 남은 재료에 대해 물어볼 때
        - [진행상황]: 요리 시간이나 현재 상태를 물어볼 때
        - [기타]: 위 세 가지에 해당하지 않을 때
        
        사용자 입력: {text}
        
        분류 결과:"""
    )
    
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"text": user_text})


def _build_voice_response(
    recognized_text: str,
    session_code: str,
    db: Session,
    user_id: int = 1,
    require_wake_word: bool = False,
) -> dict:
    """인식된 텍스트에 대해 호출어 처리, 의도 분류, RAG 답변 생성 및 TTS 음성 합성을 수행합니다."""
    if not recognized_text or not recognized_text.strip():
        return {
            "status": "empty",
            "message": "음성이 인식되지 않았습니다. 다시 말씀해 주세요."
        }

    # DB에서 사용자 호출어 설정 조회
    wake_word = "요쿡아"
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.wake_word:
            wake_word = user.wake_word
    except Exception:
        pass

    wake_detected, query_text = _strip_wake_word(recognized_text, wake_word)

    # 핸즈프리 모드에서 호출어('요쿡아') 필수 옵션이 켜져 있는데 호출어가 없는 경우 LLM 호출 생략
    if require_wake_word and not wake_detected:
        return {
            "status": "ignored_wake",
            "recognized_text": recognized_text,
            "wake_word_detected": False,
            "message": f"('요쿡아'를 붙여 말씀해 주세요) \"{recognized_text}\""
        }

    # 호출어만 부르고 뒷말이 없는 경우 ("요쿡아!")
    if wake_detected and query_text in ("", wake_word):
        ai_response_text = "네, 요쿡 듣고 있어요! 다음 단계나 궁금한 재료를 말씀해 주세요."
        intent = "[호출응답]"
        current_step = None
        session_id = None
    else:
        intent = classify_user_intent(query_text)
        rag_result = generate_session_aware_answer(query_text, intent, session_code, user_id=user_id)
        ai_response_text = rag_result["answer"]
        current_step = rag_result["current_step"]
        session_id = rag_result.get("session_id")
        session_code = rag_result.get("session_code") or session_code

    # TTS (텍스트 -> 음성) 변환
    tts = gTTS(text=ai_response_text, lang='ko', slow=False)
    audio_fp = BytesIO()
    tts.write_to_fp(audio_fp)
    audio_fp.seek(0)
    audio_base64 = base64.b64encode(audio_fp.read()).decode('utf-8')

    res = {
        "status": "success",
        "recognized_text": recognized_text,
        "cleaned_query": query_text,
        "wake_word_detected": wake_detected,
        "intent": intent,
        "session_code": session_code,
        "ai_response": ai_response_text,
        "audio_base64": audio_base64
    }
    if current_step is not None:
        res["current_step"] = current_step
    if session_id is not None:
        res["session_id"] = session_id
    return res


@router.post("/process-audio")
async def process_audio(
    file: UploadFile = File(...),
    session_code: str = Form(...),  # 클라이언트로부터 세션 방 번호 받기
    user_id: Optional[int] = Form(1),
    require_wake_word: Optional[bool] = Form(False),
    db: Session = Depends(get_db)
):
    """클라이언트로부터 실시간 마이크 음성(또는 오디오 파일)을 받아 STT, 의도 분석, 세션 맞춤형 답변(RAG) 및 TTS 음성을 반환합니다."""
    ext = Path(file.filename or "audio.wav").suffix or ".wav"
    temp_file_path = str(BASE_DIR / f"temp_audio_{uuid.uuid4().hex[:8]}{ext}")
    
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        # 1. 음성 인식 (STT) - 무음 구간 환각(Hallucination) 원천 차단 옵션 적용
        result = whisper_model.transcribe(
            temp_file_path,
            language="ko",
            temperature=0.0,
            no_speech_threshold=0.45,
            logprob_threshold=-0.8,
            condition_on_previous_text=False,
        )
        # 세그먼트의 무음 확률(no_speech_prob)이 높으면 빈 문자열 처리
        segments = result.get("segments") or []
        valid_texts = [
            seg.get("text", "").strip()
            for seg in segments
            if seg.get("no_speech_prob", 0.0) < 0.55 and seg.get("avg_logprob", 0.0) > -1.0
        ]
        recognized_text = " ".join(valid_texts).strip()

        # 무음 환각 상투어이거나 1글자 이하 노이즈면 무시
        if len(recognized_text) <= 1 or any(h in recognized_text for h in WHISPER_HALLUCINATIONS):
            recognized_text = ""

        return _build_voice_response(
            recognized_text,
            session_code,
            db,
            user_id=user_id or 1,
            require_wake_word=bool(require_wake_word),
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@router.post("/process-text", summary="실시간 음성/텍스트 즉시 대화 API")
async def process_text_conversation(
    payload: TextQueryRequest,
    db: Session = Depends(get_db)
):
    """브라우저 실시간 음성 인식(Web Speech) 또는 텍스트 질문에 대해 즉시 RAG 답변과 TTS 음성을 반환합니다."""
    try:
        return _build_voice_response(payload.text, payload.session_code, db, payload.user_id or 1)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/vision-status", summary="실시간 비전 위험 상태 조회 (프론트엔드 연동용)")
def get_nlp_vision_status(db: Session = Depends(get_db)):
    """프론트엔드(app.py)의 실시간 위험 감지 토글에서 호출하는 비전 안전 상태 엔드포인트입니다."""
    _sync_active_session_step_flags(db)
    return get_current_vision_status()
