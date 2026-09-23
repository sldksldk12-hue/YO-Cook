from fastapi import APIRouter, UploadFile, File
import whisper
import os
import shutil
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv  # 환경 변수 로드용 라이브러리 추가
from app.services.rag import generate_recipe_answer

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
async def process_audio(file: UploadFile = File(...)):
    """클라이언트로부터 오디오 파일을 받아 STT, 의도 분석, 그리고 최종 답변(RAG)을 반환합니다."""
    temp_file_path = f"temp_{file.filename}"
    
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        result = whisper_model.transcribe(temp_file_path, language="ko")
        recognized_text = result["text"].strip()
        
        intent = classify_user_intent(recognized_text)
        final_answer = generate_recipe_answer(recognized_text, intent)
        
        return {
            "status": "success",
            "recognized_text": recognized_text,
            "intent": intent,
            "ai_response": final_answer
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)