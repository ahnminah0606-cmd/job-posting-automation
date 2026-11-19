"""등록한 채용 사이트의 목록 페이지를 차례로 읽는다."""

from http.client import HTTPException
from urllib.error import URLError
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


def main():
    for name, url in SITES.items():
        try:
            with urlopen(url, timeout=15) as response:
                size = len(response.read())
                print(f"{name} | HTTP {response.status} | {size:,}바이트")
        except (URLError, OSError, HTTPException) as error:
            print(f"{name} | 접속 실패 | {error}")


if __name__ == "__main__":
    main()
