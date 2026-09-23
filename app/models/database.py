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

# MySQL 연결 주소
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"

# DB 엔진 및 세션 생성
# echo=True를 설정하면 서버 콘솔에서 실행되는 실제 SQL 쿼리를 확인할 수 있습니다.
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True) 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """FastAPI 의존성 주입을 위한 DB 세션 생성기"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()