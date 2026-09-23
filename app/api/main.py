# uvicorn app.main:app --reload

from fastapi import FastAPI
from app.api import nlp, vision, websocket

app = FastAPI(
    title="YO-Cook AI Cooking Mate",
    description="음성 명령 인식 및 비전 탐지를 위한 백엔드 서버",
    version="1.0.0"
)

# REST API 라우터 등록
app.include_router(nlp.router, prefix="/api/nlp", tags=["NLP"])
app.include_router(vision.router, prefix="/api/vision", tags=["Vision"])

# WebSocket 라우터 등록
app.include_router(websocket.router, tags=["WebSocket"])

@app.get("/")
def read_root():
    return {"message": "YO-Cook 서버가 정상적으로 실행 중입니다!"}