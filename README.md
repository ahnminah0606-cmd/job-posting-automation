# 채용공고 수집 자동화

신입이 지원할 수 있는 반도체, AX, 반도체 × AX 공고를 찾아 노션에 모으는 개인 프로젝트입니다.

현재는 8개 주소의 접속 상태를 확인하거나 R&D잡 첫 페이지에서 조건을 통과한 첫 공고의 회사명, 제목, 모집 구분, 상세 링크와 JD 본문을 출력합니다.

모집 구분이 `신입` 또는 `무관`인 공고를 살펴봅니다. 제목, 모집·학력 표시, 지원자격 값, JD 본문에서 `경력`이나 석사·박사 관련 표현이 나오면 제외합니다. `신입/경력`, `경력무관`, `경력기술서`, `석사 우대`도 제외합니다. 지원자격 양식에서 항목명이 `경력`이고 값이 `신입`이면 통과할 수 있습니다.

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
