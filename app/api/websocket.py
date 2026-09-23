from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict

router = APIRouter()

# 접속 중인 웹소켓 세션을 관리하는 매니저 클래스
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_code: str):
        """클라이언트의 웹소켓 연결을 수락하고 목록에 저장합니다."""
        await websocket.accept()
        self.active_connections[session_code] = websocket
        print(f"[시스템] 세션 {session_code} 연결 완료.")

    def disconnect(self, session_code: str):
        """클라이언트 연결이 끊어지면 목록에서 제거합니다."""
        if session_code in self.active_connections:
            del self.active_connections[session_code]
            print(f"[시스템] 세션 {session_code} 연결 해제됨.")

    async def send_message(self, session_code: str, message: dict):
        """특정 세션(session_code)으로 JSON 데이터를 푸시합니다."""
        if session_code in self.active_connections:
            websocket = self.active_connections[session_code]
            await websocket.send_json(message)

# 매니저 인스턴스 생성
manager = ConnectionManager()

@router.websocket("/ws/{session_code}")
async def websocket_endpoint(websocket: WebSocket, session_code: str):
    """
    프론트엔드와 실시간 통신을 수행하는 웹소켓 엔드포인트입니다.
    예: ws://localhost:8000/ws/session_1234
    """
    await manager.connect(websocket, session_code)
    try:
        while True:
            # 클라이언트로부터 텍스트 메시지 수신 대기
            data = await websocket.receive_text()
            
            # 수신된 데이터를 바탕으로 로직 처리 (추후 음성 텍스트나 비전 신호 연동)
            print(f"[{session_code} 님이 보낸 메시지]: {data}")
            
            # 테스트용 에코 응답 (받은 메시지를 그대로 다시 프론트엔드로 전달)
            await manager.send_message(session_code, {
                "type": "ECHO",
                "message": f"서버가 성공적으로 수신함: {data}"
            })
            
    except WebSocketDisconnect:
        manager.disconnect(session_code)