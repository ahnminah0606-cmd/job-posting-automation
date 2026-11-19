"""채용 사이트의 접속을 확인하거나 R&D잡 공고 한 건을 읽는다."""

import argparse
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


def show_rndjob():
    listing_url = SITES["R&D잡"]
    listing = read_rndjob_page(listing_url)
    for card in listing.select(".job-card"):
        career_tag = card.select_one(".tag--dark")
        career = career_tag.get_text(strip=True) if career_tag else ""
        if "신입" not in career and "무관" not in career:
            continue
        company = card.select_one(".brand-logo")
        link = card.select_one(".card-title a[href]")
        if not company or not link:
            continue
        url = urljoin(listing_url, link["href"])
        parsed = urlsplit(url)
        if parsed.hostname != urlsplit(listing_url).hostname or parsed.scheme != "https":
            continue
        print(f"{company.get_text(strip=True)} | {link.get_text(strip=True)} | {career}")
        print(url)
        detail = read_rndjob_page(url)
        sections = []
        for section in detail.select(".basic_tab_con .sub_each2"):
            heading = section.select_one(".sub_tit2")
            body = section.select_one(".vin_dtl")
            if heading and body:
                text = body.get_text("\n", strip=True)
                if text:
                    sections.append(f"{heading.get_text(strip=True)}\n{text}")
        print("\n\n".join(sections) or "JD 본문을 읽지 못했습니다. 상세 링크를 확인하세요.")
        return
    print("첫 페이지에서 신입 지원 가능 표시가 있는 공고를 찾지 못했습니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rndjob", action="store_true", help="R&D잡에서 신입 지원 가능 공고 한 건 보기")
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
