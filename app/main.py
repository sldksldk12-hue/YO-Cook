# uvicorn app.main:app --reload

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import recipes, sessions, favorites, nlp, vision, websocket

app = FastAPI(
    title="YO-Cook AI Cooking Mate",
    description="음성 명령 인식 및 비전 탐지를 위한 백엔드 서버",
    version="1.0.0"
)

# CORS 미들웨어 등록 (모바일 기기, 외부 IP, 모든 프론트엔드 출처 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API 라우터 등록
app.include_router(recipes.router, prefix="/api/recipes", tags=["Recipes"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(favorites.router, prefix="/api/favorites", tags=["Favorites"])
app.include_router(nlp.router, prefix="/api/nlp", tags=["NLP"])
app.include_router(vision.router, prefix="/api/vision", tags=["Vision"])

# WebSocket 라우터 등록
app.include_router(websocket.router, tags=["WebSocket"])

@app.get("/")
def read_root():
    return {"message": "YO-Cook 서버가 정상적으로 실행 중입니다!"}