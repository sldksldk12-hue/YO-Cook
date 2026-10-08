from fastapi import APIRouter, UploadFile, File, Form
import whisper
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

load_dotenv()

router = APIRouter()

print("=> Whisper 'base' 모델 로딩 중...")
whisper_model = whisper.load_model("base")

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

@router.post("/process-audio")
async def process_audio(
    file: UploadFile = File(...),
    session_code: str = Form(...)  # 클라이언트로부터 세션 방 번호 받기
):
    """클라이언트로부터 오디오 파일을 받아 STT, 의도 분석, 그리고 세션 맞춤형 최종 답변(RAG) 및 음성 데이터를 반환합니다."""
    temp_file_path = f"temp_{file.filename}"
    
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        # 1. 음성 인식 (STT)
        result = whisper_model.transcribe(temp_file_path, language="ko")
        recognized_text = result["text"].strip()
        
        # 2. 의도 분류
        intent = classify_user_intent(recognized_text)
        
        # 3. 세션 정보와 함께 RAG 파이프라인 호출
        rag_result = generate_session_aware_answer(recognized_text, intent, session_code)
        ai_response_text = rag_result["answer"]
        
        # 4. TTS (텍스트 -> 음성) 변환
        # gTTS를 사용하여 AI의 답변 텍스트를 한국어 음성으로 변환
        tts = gTTS(text=ai_response_text, lang='ko', slow=False)
        
        # 하드디스크에 파일을 저장했다가 읽어오면 속도가 느려지므로 메모리(BytesIO)에 바로 저장
        audio_fp = BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0) # 커서를 처음으로 돌려서 읽을 준비를 합니다.
        
        # 5. 오디오 데이터를 Base64 문자열로 인코딩
        audio_base64 = base64.b64encode(audio_fp.read()).decode('utf-8')
        
        return {
            "status": "success",
            "recognized_text": recognized_text,
            "intent": intent,
            "current_step": rag_result["current_step"], # 현재 조리 단계 반환
            "ai_response": ai_response_text,            # AI의 안내 답변 반환
            "audio_base64": audio_base64                # 인코딩된 음성 데이터 추가
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)