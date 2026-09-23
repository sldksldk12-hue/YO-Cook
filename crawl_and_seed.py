import os
import re
import sys
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import pymysql
from dotenv import load_dotenv

# 프로젝트 루트 경로 추가
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

from sqlalchemy import text
from app.models.database import engine, SessionLocal, Base
from app.models.recipe import Recipe, Ingredient, RecipeStep
import app.models.user
import app.models.session

# ==========================================
# 1. MySQL 데이터베이스 존재 여부 확인 및 자동 생성
# ==========================================
def ensure_database_exists():
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    db_name = os.getenv("MYSQL_DB", "yocook_db")

    print(f"[*] MySQL 서버 연결 확인 ({host}:{port}, User: {user})...")
    conn = pymysql.connect(host=host, user=user, password=password, port=port)
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    conn.commit()
    cursor.close()
    conn.close()
    print(f"[+] 데이터베이스 '{db_name}' 준비 완료!")

# ==========================================
# 2. 정규식 및 스마트 태깅 보조 함수
# ==========================================
SEASONING_KEYWORDS = [
    "간장", "진간장", "국간장", "양조간장", "소금", "맛소금", "꽃소금",
    "설탕", "올리고당", "물엿", "꿀", "고춧가루", "고추장", "된장", "쌈장",
    "식용유", "참기름", "들기름", "올리브유", "버터", "마요네즈", "케첩",
    "후추", "후춧가루", "다진마늘", "맛술", "미림", "식초", "굴소스", "참치액",
    "통깨", "깨소금", "전분가루", "밀가루", "카레가루"
]

def parse_cooking_time(time_str: str) -> int:
    """'15분 이내', '30분', '2시간 이내' 등의 문자열에서 분(minutes) 단위 정수 추출"""
    if not time_str:
        return 15
    if "시간" in time_str:
        hour_match = re.search(r"(\d+)\s*시간", time_str)
        hours = int(hour_match.group(1)) if hour_match else 1
        min_match = re.search(r"(\d+)\s*분", time_str)
        mins = int(min_match.group(1)) if min_match else 0
        return hours * 60 + mins
    match = re.search(r"(\d+)\s*분", time_str)
    return int(match.group(1)) if match else 15

def parse_timer_seconds(instruction: str) -> int:
    """조리 지침 텍스트에서 'N분', 'N초'를 찾아 초 단위로 변환"""
    # 분 단위 검출 (예: 3분, 1분 30초)
    min_match = re.search(r"(\d+)\s*분(?!\s*분량)", instruction)
    sec_match = re.search(r"(\d+)\s*초", instruction)
    
    total_seconds = 0
    if min_match:
        mins = int(min_match.group(1))
        if mins <= 60: # 60분 이하의 타이머만 추출
            total_seconds += mins * 60
    if sec_match:
        secs = int(sec_match.group(1))
        if secs <= 120:
            total_seconds += secs
            
    return total_seconds

def detect_safety_warning_and_tools(instruction: str) -> tuple[str | None, str | None]:
    """조리 텍스트 키워드 기반 안전 주의사항 및 필요 도구 자동 추출"""
    tools = []
    warning = None

    # 칼질 관련
    if any(k in instruction for k in ["썰", "다져", "깍둑", "어슷", "채썰", "자르", "칼"]):
        tools.append("식칼")
        tools.append("도마")
        warning = "칼질 시 손가락 끝을 안쪽으로 오므리는 '고양이 손' 자세를 유지하세요."

    # 가열 및 기름/팬 관련
    if any(k in instruction for k in ["기름", "볶", "팬에", "달군", "노릇"]):
        tools.append("프라이팬")
        tools.append("주걱")
        if not warning:
            warning = "달궈진 팬에 기름이나 양념이 튈 수 있으니 주의하세요."

    # 끓이기/냄비 관련
    if any(k in instruction for k in ["끓", "냄비", "국물", "삶", "육수"]):
        tools.append("냄비")
        tools.append("국자")
        if not warning:
            warning = "끓는 물이나 증기에 화상을 입지 않도록 주의하세요."

    tools_str = ", ".join(list(dict.fromkeys(tools))) if tools else None
    return warning, tools_str

# ==========================================
# 3. 만개의레시피 크롤러 본체
# ==========================================
def crawl_and_seed_recipes(target_count: int = 20):
    print(f"\n[*] 만개의레시피 인기 목록에서 상위 {target_count}개 레시피 수집 시작...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 1. 목록 페이지에서 레시피 링크 수집
    list_url = "https://www.10000recipe.com/recipe/list.html?order=reco&page=1"
    res = requests.get(list_url, headers=headers, timeout=10)
    if res.status_code != 200:
        print(f"[!] 목록 페이지 요청 실패: Status {res.status_code}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    items = soup.select("ul.rcp_m_list2 li.common_sp_list_li")
    
    recipe_links = []
    for li in items:
        link_tag = li.select_one("a.common_sp_link")
        if link_tag and link_tag.get("href"):
            href = link_tag["href"]
            if href.startswith("/recipe/"):
                recipe_links.append(f"https://www.10000recipe.com{href}")
        if len(recipe_links) >= target_count:
            break

    print(f"[+] 총 {len(recipe_links)}개의 레시피 링크 확보 완료!")

    # 2. DB 세션 생성 및 기존 데이터 TRUNCATE (ID를 1번부터 시작하도록 초기화)
    db = SessionLocal()
    success_count = 0

    try:
        # 기존 크롤링 데이터 초기화 및 AUTO_INCREMENT = 1 리셋
        print("[*] 기존 레시피 데이터 TRUNCATE (ID 1번 리셋)...")
        # 기존 데이터를 지우지 않고 추가만 하고 싶을 때는 아래 7줄 앞에 # 을 붙여 비활성화
        with engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            conn.execute(text("TRUNCATE TABLE recipe_steps;"))
            conn.execute(text("TRUNCATE TABLE ingredients;"))
            conn.execute(text("TRUNCATE TABLE recipes;"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            conn.commit()

        for idx, url in enumerate(recipe_links, 1):
            try:
                time.sleep(0.8) # 서버 과부하 방지 텀
                detail_res = requests.get(url, headers=headers, timeout=10)
                if detail_res.status_code != 200:
                    continue

                detail_soup = BeautifulSoup(detail_res.text, "html.parser")

                # 제목
                title_tag = detail_soup.select_one("div.view2_summary h3")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)

                # 요리 소개
                desc_tag = detail_soup.select_one("div.view2_summary_in")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                # 분량, 시간, 난이도
                servings_tag = detail_soup.select_one("span.view2_summary_info1")
                servings = servings_tag.get_text(strip=True) if servings_tag else "1인분"

                time_tag = detail_soup.select_one("span.view2_summary_info2")
                time_str = time_tag.get_text(strip=True) if time_tag else "15분"
                cooking_time_minutes = parse_cooking_time(time_str)

                diff_tag = detail_soup.select_one("span.view2_summary_info3")
                difficulty = diff_tag.get_text(strip=True) if diff_tag else "초급"

                # 썸네일 이미지
                thumb_tag = detail_soup.select_one("#main_thumbs, div.centeredcrop img")
                thumbnail_url = thumb_tag["src"] if thumb_tag and thumb_tag.get("src") else None

                # Recipe 객체 생성
                recipe = Recipe(
                    title=title,
                    description=description,
                    category="인기요리",
                    tags="#만개의레시피 #인기요리 #홈쿡",
                    cooking_time_minutes=cooking_time_minutes,
                    difficulty=difficulty,
                    servings=servings,
                    thumbnail_url=thumbnail_url,
                    source_url=url,
                    view_count=0
                )
                db.add(recipe)
                db.flush() # recipe.id 발급

                # 식재료 추출
                ingre_items = detail_soup.select("div.ready_ingre3 ul li, div.cont_ingre ul li")
                for item in ingre_items:
                    text_parts = [t.strip() for t in item.stripped_strings if t.strip()]
                    if not text_parts:
                        continue
                    ingre_name = text_parts[0]
                    ingre_amount = text_parts[1] if len(text_parts) > 1 else "적당량"

                    is_seasoning = any(kw in ingre_name for kw in SEASONING_KEYWORDS)
                    
                    ingredient = Ingredient(
                        recipe_id=recipe.id,
                        name=ingre_name,
                        amount=ingre_amount,
                        is_seasoning=is_seasoning,
                        is_essential=not is_seasoning
                    )
                    db.add(ingredient)

                # 조리 단계 추출 (중복 방지: div.view_step_cont 단일 셀렉터 사용)
                step_items = detail_soup.select("div.view_step_cont")
                if not step_items:
                    step_items = detail_soup.select("div.view_step div.media-body")

                step_num = 1
                for s_item in step_items:
                    # 지침 텍스트
                    instruction = s_item.get_text(" ", strip=True)
                    if not instruction or len(instruction) < 3:
                        continue

                    # 타이머 및 안전팁 추출
                    timer_seconds = parse_timer_seconds(instruction)
                    safety_warning, required_tools = detect_safety_warning_and_tools(instruction)

                    # 단계 사진
                    parent = s_item.find_parent("div", class_="view_step")
                    step_img_tag = parent.find("img") if parent else None
                    step_img_url = step_img_tag["src"] if step_img_tag and step_img_tag.get("src") else None

                    recipe_step = RecipeStep(
                        recipe_id=recipe.id,
                        step_number=step_num,
                        instruction=instruction,
                        timer_seconds=timer_seconds,
                        image_url=step_img_url,
                        safety_warning=safety_warning,
                        required_tools=required_tools
                    )
                    db.add(recipe_step)
                    step_num += 1

                db.commit()
                success_count += 1
                print(f"  [{idx:02d}/{target_count}] [OK] {title} (재료 {len(ingre_items)}개, 단계 {step_num-1}단계)")

            except Exception as e:
                db.rollback()
                print(f"  [{idx:02d}/{target_count}] [Error] {url}: {e}")

        print(f"\n[+] 크롤링 완료: 총 {success_count}개의 레시피가 MySQL(yocook_db)에 성공적으로 적재되었습니다!")

    finally:
        db.close()

# ==========================================
# 4. 메인 실행 함수
# ==========================================
if __name__ == "__main__":
    # 1. DB 준비
    ensure_database_exists()
    
    # 2. 테이블 생성
    print("[*] SQLAlchemy 테이블 생성 (Base.metadata.create_all)...")
    Base.metadata.create_all(bind=engine)
    print("[+] 모든 테이블 생성 완료!")

    # 3. 크롤링 및 적재 실행
    # target_count = x -> x의 값을 변경하면 크롤링할 데이터의 수량을 변경할 수 있음
    crawl_and_seed_recipes(target_count=20)
