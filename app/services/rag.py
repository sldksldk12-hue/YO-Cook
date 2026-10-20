import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv  

# DB 연동을 위한 SQLAlchemy 세션 및 모델 임포트
from app.models.database import SessionLocal
from app.models.session import CookingSession

# 환경 변수 로드
load_dotenv()

def generate_session_aware_answer(user_question: str, intent: str, session_code: str) -> dict:
    """세션 정보를 바탕으로 사용자의 현재 요리 단계를 추적하고 맞춤형 답변을 생성합니다."""
    db = SessionLocal()
    try:
        # 1. 세션 조회
        session = db.query(CookingSession).filter(CookingSession.session_code == session_code).first()
        if not session:
            return {"answer": "유효한 요리 세션을 찾을 수 없습니다. 요리를 먼저 시작해 주세요.", "current_step": 0}
        
        # 세션에 연결된 레시피 데이터와 현재 단계 가져오기
        recipe = session.recipe
        current_step_num = session.current_step
        
        # 2. 의도(Intent)에 따른 세션 상태(현재 단계) 업데이트 로직
        if intent == "[다음단계]":
            # 전체 조리 단계 중 다음 단계가 존재하는지 확인
            next_step = next((s for s in recipe.steps if s.step_number == current_step_num + 1), None)
            if next_step:
                session.current_step += 1
                current_step_num += 1
                db.commit() # 변경된 단계를 MySQL DB에 확정 저장
            else:
                session.is_completed = True
                db.commit()

        # 3. 현재 단계의 조리 지침 텍스트 가져오기
        current_step_info = next((s for s in recipe.steps if s.step_number == current_step_num), None)
        step_instruction = current_step_info.instruction if current_step_info else "모든 요리 단계가 완료되었습니다."
        
        # 4. 프롬프트 구성을 위한 식재료 컨텍스트 가공 (필수/선택 분리 유지)
        essential_ing = [f"{ing.name} {ing.amount}" for ing in recipe.ingredients if ing.is_essential]
        optional_ing = [f"{ing.name} {ing.amount}" for ing in recipe.ingredients if not ing.is_essential]
        ingredients_text = f"- 필수: {', '.join(essential_ing)}\n- 선택: {', '.join(optional_ing)}"
        
        # LLM에게 넘겨줄 실시간 맞춤형 컨텍스트
        context = f"""
        [요리명]: {recipe.title}
        [현재 진행 단계]: {current_step_num}단계 - {step_instruction}
        [식재료]
        {ingredients_text}
        """
        
        llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.1)
        
        prompt = PromptTemplate.from_template(
            """당신은 사용자의 요리를 돕는 스마트 AI 'YO-Cook'입니다.
            제공된 [현재 진행 단계]와 [식재료] 정보를 바탕으로 사용자의 질문에 답하세요.
            
            사용자 질문 의도: {intent}
            - [다음단계]: [현재 진행 단계]의 지침을 읽기 편하게 안내하세요.
            - [재료질문]: [식재료]를 참고하여 대체 가능 여부나 분량을 안내하세요.
            - 그 외: 현재 맥락에 맞춰 친절하고 간결하게 답하세요.
            
            [레시피 정보]
            {context}
            
            사용자 질문: {question}
            
            답변:"""
        )
        
        chain = prompt | llm | StrOutputParser()
        answer = chain.invoke({
            "intent": intent,
            "context": context,
            "question": user_question
        })
        
        # 프론트엔드 UI 업데이트를 위해 답변과 함께 현재 단계 숫자도 반환
        return {
            "answer": answer,
            "current_step": current_step_num
        }
    finally:
        db.close()