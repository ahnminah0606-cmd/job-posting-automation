# 채용공고 수집 자동화

신입이 지원할 수 있는 반도체, AX, 반도체 × AX 공고를 찾아 노션에 모으는 개인 프로젝트입니다.

현재는 8개 주소의 접속 상태를 확인하거나 R&D잡 첫 페이지에서 신입 또는 경력무관 표시가 있는 공고 한 건을 읽을 수 있습니다. 회사명, 공고 제목, 경력, 상세 링크와 JD 본문을 터미널에 출력합니다.

## 실행

Python 3가 설치된 컴퓨터에서 이 폴더를 열고 실행하세요.

- macOS 또는 Linux: `python3 main.py`
- Windows: `py main.py`

8개 주소의 접속 상태는 `python3 fetch_page.py`로 확인합니다.

R&D잡 본문을 읽으려면 프로젝트 폴더에서 아래 명령을 실행하세요.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python fetch_page.py --rndjob
```

Windows에서는 `py -m venv .venv`로 환경을 만들고, 나머지 두 명령의 `.venv/bin/python`을 `.venv\Scripts\python.exe`로 바꾸세요. 두 번째 실행부터는 마지막 명령만 사용합니다.
