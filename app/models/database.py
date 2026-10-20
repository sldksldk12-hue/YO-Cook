import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# .env 파일의 환경 변수 불러오기
load_dotenv()

MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB = os.getenv("MYSQL_DB", "yocook_db")

# MySQL 연결 주소 (utf8mb4 인코딩 명시)
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"

# DB 엔진 및 세션 생성
# pool_pre_ping=True: 장시간 유휴 후 연결 끊김 자동 재연결
# pool_recycle=3600: 1시간마다 커넥션 자동 갱신
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=True,
    pool_pre_ping=True,
    pool_recycle=3600
) 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """FastAPI 의존성 주입을 위한 DB 세션 생성기"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()