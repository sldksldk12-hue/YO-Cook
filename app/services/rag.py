import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv  # 환경 변수 로드용 라이브러리 추가

load_dotenv()

def get_dummy_recipe_context() -> str:
    """
    TODO: 추후 하석님이 완성할 MySQL DB 조회 로직으로 교체될 부분입니다.
    현재는 ERD 구조(RECIPES, INGREDIENTS, RECIPE_STEPS)를 모방한 가상 데이터를 반환합니다.
    """
    return """
    [요리명]: 백종원 초간단 김치볶음밥 (조리시간: 15분, 난이도: 초급, 1인분)
    
    [식재료]
    - 필수: 밥 1공기, 신김치 1/2컵, 대파 1/2대, 식용유 2큰술, 간장 1/2큰술
    - 선택: 계란 1개, 참기름 1큰술, 양파 1/4개 (대파 대체 가능)
    
    [조리 단계]
    1단계: 대파를 송송 썰어 식용유를 두른 팬에 볶아 파기름을 냅니다. (타이머: 60초)
    2단계: 파향이 올라오면 신김치를 넣고 함께 볶아줍니다. 
    3단계: 간장을 팬 가장자리에 부어 불맛을 입힌 후, 밥을 넣고 골고루 볶습니다.
    4단계: 완성된 볶음밥 위에 계란 프라이를 올리고 참기름을 두릅니다.
    
    [안전 주의사항]
    - 기름이 튈 수 있으니 불을 중불로 조절하세요.
    - 식칼 사용 시 손가락을 둥글게 말아 쥐세요.
    """

def generate_recipe_answer(user_question: str, intent: str) -> str:
    """사용자의 질문과 분류된 의도를 바탕으로 컨텍스트를 분석하여 최적의 답변을 생성합니다."""
    context = get_dummy_recipe_context()
    
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