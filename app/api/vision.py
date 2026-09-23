from fastapi import APIRouter, UploadFile, File

router = APIRouter()

@router.post("/detect")
async def detect_objects(file: UploadFile = File(...)):
    """
    클라이언트(웹캠)로부터 이미지를 받아 YOLOv8 모델로 주방 도구와 위험 상황을 탐지합니다.
    """
    # TODO: 이미지를 읽어 YOLOv8 모델에 통과시키는 로직 구현
    # TODO: 탐지된 바운딩 박스 좌표와 위험 상태(칼, 불꽃 등) 알림 반환
    
    return {
        "status": "success",
        "message": "비전 객체 탐지 API가 정상적으로 호출되었습니다.",
        "detected_objects": []  # 향후 탐지 결과가 담길 리스트
    }