"""채용 사이트의 접속을 확인하거나 R&D잡 첫 페이지의 공고를 분류한다."""

import argparse
import re
from collections import Counter
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen


SITES = {
    "SKALA 루핏": "https://inface.ai/skala/loofit",
    "자소설닷컴": "https://jasoseol.com/search",
    "사람인 강소기업": "https://www.saramin.co.kr/zf_user/jobs/theme/kangso",
    "사람인 홈": "https://www.saramin.co.kr/zf_user/",
    "R&D잡": "https://www.rndjob.or.kr/info/entire_notice.asp",
    "잡코리아 신입": "https://www.jobkorea.co.kr/starter/",
    "이공계모야": "https://egongmoya.letuin.com/CommunityBoard/list/11",
    "캐치": "https://www.catch.co.kr/NCS/RecruitSearch",
}


def check_sites():
    for name, url in SITES.items():
        try:
            with urlopen(url, timeout=15) as response:
                size = len(response.read())
                print(f"{name} | HTTP {response.status} | {size:,}바이트")
        except (URLError, OSError, HTTPException) as error:
            print(f"{name} | 접속 실패 | {error}")


def read_rndjob_page(url):
    from bs4 import BeautifulSoup

    with urlopen(url, timeout=15) as response:
        content = response.read()
        charset = response.headers.get_content_charset()
    return BeautifulSoup(content, "html.parser", from_encoding=charset)


EXCLUDED_QUALIFICATION = re.compile(
    r"경력|석사|박사|석[·ㆍ/･・-]?박(?:통합|사)?|대학원졸|대학원석|대학원박"
    r"|(?<![a-z])(?:ph\.?\s*d\.?|master['’]s|masters?\s+degree|doctorate|doctoral)(?![a-z])",
    re.IGNORECASE,
)


def excluded_qualification(text):
    # 한글 공고에는 '경 력', '석 · 박사'처럼 글자 사이에 공백이 들어가기도 한다.
    compact = re.sub(r"(?<=[가-힣·ㆍ/･・-])\s+(?=[가-힣·ㆍ/･・-])", "", text)
    return EXCLUDED_QUALIFICATION.search(compact)


# 직무 분류에는 모집 제목과 담당업무를 사용한다. 우대사항의 도구명은 근거로 쓰지 않는다.
SEMICONDUCTOR = re.compile(
    r"반도체|웨이퍼|포토리소그래피|semiconductor|wafer|(?<![a-z])(?:dram|nand|hbm|finfet)(?![a-z])", re.I
)
TECHNICAL_WORK = re.compile(
    r"연구|설계|개발|공정|제조|소자|장비|패키징|계측|분석|평가|테스트|엔지니어|검사|정비|"
    r"셋업|셋팅|세팅|유지보수|수율|품질|식각|증착|기술지원|불량|예측|이상탐지|engineer|process", re.I
)
AI_TECH = re.compile(
    r"(?<![a-z])(?:rag|llm|mlops|ai|ax|ml)(?![a-z])|생성형ai|인공지능|머신러닝|딥러닝|"
    r"컴퓨터비전|비전모델|이상탐지모델|예측모델|분류모델", re.I
)
AI_WORK = re.compile(
    r"모델(?:개발|학습|운영|구축|배포)|구축|도입|구현|학습|파인튜닝|배포|업무자동화|"
    r"(?:기반|활용|이용|통한|으로).{0,28}(?:자동화|최적화|예측|추천)|"
    r"(?:검색|예측|분류|탐지|분석|추천|에이전트|챗봇|서비스|솔루션|시스템|모델|파이프라인).{0,15}(?:개발|운영)|"
    r"(?:rag|llm|mlops|에이전트|챗봇)(?:기반)?(?:개발|운영)", re.I
)
OUTSIDE_WORK = re.compile(
    r"(?:기어|감속기|차체|동력전달장치|액추에이터기구).{0,20}(?:설계|개발)|"
    r"(?:공동주택|토목공사|건축현장).{0,12}(?:시공|감리|품질관리)|"
    r"(?:문구용?잉크|필기구용?잉크).{0,24}(?:연구|개발|제조|생산)|"
    r"(?:cnc선반조작|밀링가공|용접[·및]?제관|보험영업|매장판매|급여.{0,3}근태관리|전표입력)", re.I
)
AMBIGUOUS = re.compile(r"자동화|품질검사|소재|연구보조|연구개발|데이터분석|python|로봇", re.I)
RESEARCH_WORK = re.compile(r"연구|개발|r\s*&\s*d", re.I)
# 포괄적인 '제조업', '화학'에는 반도체 소재·장비 업체도 포함될 수 있다.
OTHER_INDUSTRY = re.compile(r"문구|필기구|완구|의류|봉제|음료|식품|화장품|가구제조")
INTERESTS = ("반도체", "AX", "반도체×AX")


def classify_role(title, duties, industry=""):
    examples = {}
    outside = unclear = None
    if not duties:
        return "직무 제외", "담당업무 본문을 확인할 수 없음"
    for line in [*duties, title]:
        compact = "".join(line.split())
        semi = SEMICONDUCTOR.search(compact) and TECHNICAL_WORK.search(compact)
        ax = AI_TECH.search(compact) and AI_WORK.search(compact)
        if semi and ax:
            return "반도체×AX", line
        if semi:
            examples.setdefault("반도체", line)
        if ax:
            examples.setdefault("AX", line)
        if not outside and OUTSIDE_WORK.search(compact):
            outside = line
        if not unclear and AMBIGUOUS.search(compact):
            unclear = line
    # AX 업무는 기업 업종과 별도로 선택한다. 교집합은 같은 업무에 두 근거가 있을 때만 선택한다.
    if "AX" in examples:
        return "AX", examples["AX"]
    if examples and outside:
        return "직무 제외", "업무 근거 혼재 | " + " / ".join(dict.fromkeys([examples["반도체"], outside]))
    if examples:
        return next(iter(examples.items()))
    if outside:
        return "직무 제외", outside
    research = next((line for line in [*duties, title] if RESEARCH_WORK.search(line)), None)
    if research and industry:
        sector = "".join(industry.split())
        evidence = f"업종: {industry} | {research}"
        if SEMICONDUCTOR.search(sector) and not OTHER_INDUSTRY.search(sector):
            return "반도체", evidence
        if OTHER_INDUSTRY.search(sector) and not SEMICONDUCTOR.search(sector):
            return "직무 제외", evidence
    return "직무 제외", "관심 분야 근거 부족 | " + (unclear or duties[0])


def classify_detail(detail, title):
    # '경력'은 신입 공고에도 있는 양식 항목명이다. 지원자격에서는 입력값만 검사한다.
    for block in detail.select(".notice_info_box .con"):
        label = block.select_one(".tit")
        if label and label.get_text(strip=True) == "지원자격":
            for item in block.select("dd"):
                value = item.get_text(" ", strip=True)
                if excluded_qualification(value):
                    return "자격 제외", value
    duties = []
    for section in detail.select(".basic_tab_con .sub_each2"):
        heading = section.select_one(".sub_tit2")
        body = section.select_one(".vin_dtl")
        if not heading or not body:
            continue
        name = heading.get_text(strip=True)
        lines = body.get_text("\n", strip=True).splitlines()
        if excluded_qualification(name + " " + " ".join(lines)):
            return "자격 제외", next((line for line in lines if excluded_qualification(line)), name)
        if name in {"담당업무", "주요업무", "직무내용", "직무소개"}:
            duties.extend(line.strip() for line in lines if line.strip())
    industry = ""
    for label in detail.select("dt, th"):
        if "".join(label.stripped_strings).replace(" ", "") in {"산업(업종)", "산업", "업종"}:
            value = label.find_next_sibling(["dd", "td"])
            if value:
                industry = value.get_text(" ", strip=True)
                break
    return classify_role(title, duties, industry)


def classify_card(card, listing_url):
    company = card.select_one(".brand-logo")
    link = card.select_one(".card-title a[href]")
    company_name = company.get_text(" ", strip=True) if company else "회사명 미확인"
    title = link.get_text(" ", strip=True) if link else "제목 미확인"
    url = urljoin(listing_url, link["href"]) if link else ""
    labels = [tag.get_text(" ", strip=True) for tag in card.select(".card-tag")]
    career_tag = card.select_one(".tag--dark")
    career = career_tag.get_text(strip=True) if career_tag else ""
    for value in [title, career, *labels]:
        if excluded_qualification(value):
            return company_name, title, url, "자격 제외", value
    if "신입" not in career and career != "무관":
        return company_name, title, url, "자격 제외", f"신입 지원 근거 부족 | {career or '표시 없음'}"
    parsed = urlsplit(url)
    if parsed.hostname != urlsplit(listing_url).hostname or parsed.scheme != "https":
        return company_name, title, "", "수집 제외", "유효한 상세 링크 없음"
    try:
        result, evidence = classify_detail(read_rndjob_page(url), title)
    except (URLError, OSError, HTTPException) as error:
        result, evidence = "수집 제외", f"상세 페이지 접속 실패 | {error}"
    return company_name, title, url, result, evidence


def show_rndjob():
    listing_url = SITES["R&D잡"]
    listing = read_rndjob_page(listing_url)
    counts = Counter()
    for card in listing.select(".job-card"):
        company, title, url, result, evidence = classify_card(card, listing_url)
        counts[result] += 1
        print(f"{company} | {result} | {title}")
        print(f"근거: {evidence}")
        if url:
            print(url)
        print()
    total = sum(counts.values())
    if not total:
        print("목록에서 공고 카드를 읽지 못했습니다. 목록 화면을 확인하세요.")
    selected = sum(counts[key] for key in INTERESTS)
    print(f"첫 페이지 {total}건 | 관심 공고 {selected}건")
    print(" | ".join(f"{key} {counts[key]}건" for key in (*INTERESTS, "직무 제외", "자격 제외", "수집 제외")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rndjob", action="store_true", help="R&D잡 첫 페이지의 공고별 판정과 근거 보기")
    if parser.parse_args().rndjob:
        try:
            show_rndjob()
        except ModuleNotFoundError as error:
            if error.name != "bs4":
                raise
            parser.exit(1, "먼저 python -m pip install -r requirements.txt 를 실행하세요.\n")
        except (URLError, OSError, HTTPException) as error:
            parser.exit(1, f"R&D잡 접속 실패 | {error}\n")
    else:
        check_sites()


if __name__ == "__main__":
    main()
