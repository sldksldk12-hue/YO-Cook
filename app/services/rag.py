import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv  

# DB 연동을 위한 SQLAlchemy 세션 및 모델 임포트
from app.models.database import SessionLocal
from app.models.recipe import Recipe

# 환경 변수 로드
load_dotenv()

def get_real_recipe_context(recipe_id: int = 1) -> str:
    """
    MySQL 데이터베이스에서 실제 레시피, 식재료, 조리 단계 정보를 조회하여 
    LLM이 분석할 수 있는 텍스트 형태(컨텍스트)로 변환합니다.
    (현재는 연결 테스트를 위해 기본값 recipe_id=1을 사용합니다)
    """
    db = SessionLocal()
    try:
        # 1. DB에서 레시피 정보(식재료, 단계 포함) 가져오기
        recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        
        if not recipe:
            return "요청하신 레시피 정보를 DB에서 찾을 수 없습니다."
        
        # 2. 식재료 데이터를 텍스트로 가공
        essential_ing = [f"{ing.name} {ing.amount}" for ing in recipe.ingredients if ing.is_essential]
        optional_ing = [f"{ing.name} {ing.amount}" for ing in recipe.ingredients if not ing.is_essential]
        
        ingredients_text = f"- 필수: {', '.join(essential_ing)}\n- 선택: {', '.join(optional_ing)}"
        
        # 3. 조리 단계 데이터를 텍스트로 가공
        steps_text = "\n".join([f"{step.step_number}단계: {step.instruction}" for step in recipe.steps])
        
        # 4. 3가지 정보를 조합하여 최종 프롬프트 컨텍스트 생성
        context = f"""
        [요리명]: {recipe.title} (조리시간: {recipe.cooking_time_minutes}분, 난이도: {recipe.difficulty}, {recipe.servings})
        
        [식재료]
        {ingredients_text}
        
        [조리 단계]
        {steps_text}
        """
        return context
    finally:
        db.close()

def generate_recipe_answer(user_question: str, intent: str) -> str:
    """사용자의 질문과 분류된 의도를 바탕으로 컨텍스트를 분석하여 최적의 답변을 생성합니다."""
    
    # 더미 데이터 함수 대신 실제 DB 조회 함수로 교체
    context = get_real_recipe_context(recipe_id=1) 
    
    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.1)
    
    prompt = PromptTemplate.from_template(
        """당신은 사용자의 안전하고 즐거운 요리를 돕는 스마트 AI 'YO-Cook'입니다.
        아래 제공된 [레시피 정보]만을 절대적인 기준으로 삼아 사용자의 질문에 답변하세요.
        
        사용자의 질문 의도는 {intent} 입니다.
        - [다음단계] 의도일 경우: 현재 맥락에 맞는 다음 조리 단계를 명확히 알려주세요.
        - [재료질문] 의도일 경우: [식재료] 목록을 확인하여 대체 가능 여부나 필요량을 안내하세요.
        - 정보가 부족한 경우: "제공된 레시피 정보에서는 해당 내용을 찾을 수 없습니다."라고 정중히 답하세요.
        
        [레시피 정보]:
        {context}
        
        사용자 질문: {question}
        
        답변 (친절하고 간결하게):"""
    )
    
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({
        "intent": intent,
        "context": context,
        "question": user_question
    })