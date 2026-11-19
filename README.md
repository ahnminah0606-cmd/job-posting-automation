# 채용공고 수집 자동화

## 매일 자동 실행 — GitHub Actions

`.github/workflows/collect-jobs.yml`은 GitHub 서버에서 매일 한국시간 오전 9시(UTC 00:00)에 수집과 Notion 저장을 실행합니다. 집 컴퓨터와 Codex 앱을 켜 둘 필요가 없습니다. GitHub 예약은 서버 부하에 따라 지연될 수 있으며, 공개 저장소는 60일간 활동이 없으면 예약 실행이 자동 비활성화될 수 있습니다.

저장소 Settings → Secrets and variables → Actions에 `NOTION_TOKEN`이라는 Repository secret을 등록합니다. 로컬 `.env`와 토큰은 코드에 커밋하지 않습니다. 저장소 기본 브랜치 `main`에 워크플로와 Notion 저장 코드가 있어야 합니다. 기존 Codex 예약은 중단해 두 방식이 동시에 실행되지 않게 합니다.

Actions → Daily job collection → Run workflow에서 수동 실행도 가능합니다. `--all`로 등록된 8개 주소를 실행합니다. 실행 결과에서 사이트별 집계와 Notion 신규·갱신 수를 확인할 수 있으며, 후보 JSON·수집 로그·사이트별 판정 보고서는 실행별 artifact로 7일 보관됩니다. 전체 `.env`나 인증 정보는 업로드하지 않습니다. 동시 실행은 큐로 직렬화하며 실행 중인 작업을 강제로 취소하지 않습니다.

실패한 실행은 Actions 화면에서 확인할 수 있습니다. 알림 수신 여부는 GitHub 계정의 Actions 알림 설정을 따릅니다. 저장 도중 실패했으면 artifact의 `postings.json`을 내려받아 기존 `notion_sync.py --input` 명령으로 재처리할 수 있습니다. 같은 수집 키는 기존 행을 갱신합니다. 관심 공고가 0건이면 정상 종료하며 테스트 행을 만들지 않습니다.

예약 관련 동작: [GitHub 공식 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

신입이 지원할 수 있는 반도체, AX, 반도체 × AX 공고를 찾아 노션에 모으는 개인 프로젝트입니다.

등록된 8개 주소에서 공개 공고를 수집·분류합니다. 같은 사이트 공고 번호가 반복되면 기존 행을 갱신합니다. 관심 공고는 회사명, 분야, 제목, 근거, 상세 링크 순으로 출력하고, 제외된 공고는 마지막 집계에 건수로 표시합니다.

| 주소 | 수집 범위/방식 |
| --- | --- |
| R&D잡 | 기존 목록 1~5페이지 및 HTML 상세 |
| SKALA 루핏 | 기존 목록 최대 5페이지 및 브라우저 상세 팝업 |
| 사람인 홈 | 홈에 노출된 개별 공고 최대 50개 및 공개 상세/상세요강 iframe |
| 사람인 강소기업 | 해당 채용관에 노출된 개별 공고 최대 50개 및 공개 상세/상세요강 iframe |
| 잡코리아 신입 | 신입·공채 목록에 노출된 개별 공고 최대 50개 및 브라우저 상세요강 |
| 자소설닷컴 | 검색 목록 최대 5페이지/50개 공고, 상세의 개별 직무 ID로 분리 |
| 이공계모야 | 공개 채용 게시판 최대 5페이지/50개 공고, 공지·로그인 필요 게시물 제외 |
| 캐치 | 공개 검색 목록 최대 5페이지/50개 공고 및 상세요강 iframe. 서버 접근 제한 시 공개 HTML 대표 공고만 수집하고 일부 수집으로 표시 |

전 사이트의 모든 공고를 전수 수집하는 것은 아닙니다. 추가 사이트별 한도는 `--limit`(1~200)으로 조정합니다. 자소설닷컴의 한 공고에 여러 직무가 있으면 직무별로 분류하므로 직무 집계가 공고 한도를 넘을 수 있습니다. 다직무 공고에서 직무별 요강 구획을 확실히 나누지 못하면 저장하지 않습니다. 사람인 홈과 강소기업은 동일한 `사람인 + 공고 ID` 수집 키를 사용합니다.

상세요강이 이미지·첨부파일로만 제공되거나 담당업무 구획이 불명확하면 `수집 제외`로 집계합니다. OCR은 구현하지 않았습니다. 목록 접속 실패·상세 HTTP 오류는 별도 실패로 보고하며, 해당 사이트가 실패해도 다른 사이트 결과는 계속 보관·저장합니다. 하나 이상 실패하면 최종 종료 코드는 1이어서 GitHub에서 성공 0건과 구분됩니다. `collection-report.json`에서 추가 사이트의 개별 제외 근거·원문 링크·오류를 확인할 수 있습니다.

캐치는 공개 API가 403/429를 반환하면 일반 공개 검색 화면을 브라우저로 읽습니다. 로그인·CAPTCHA·보안 확인을 우회하지 않습니다. GitHub 서버에서 API와 동적 목록이 모두 거절될 때는 서버가 공개 HTML에 직접 제공한 대표 공고(검증 당시 6개)만 읽습니다. 이는 전체 검색 결과가 아니므로 보고서에 `status: partial`, `coverage: featured-only` 및 경고를 남깁니다. 이 공개 목록조차 없거나 상세 요청에 오류가 있으면 실패입니다. 429/일시적 서버 오류는 `Retry-After`를 지켜 제한된 횟수로 재시도합니다. 수동 Run workflow의 `site` 선택으로 특정 사이트만 재검증할 수 있으며 예약 실행은 항상 `all`입니다. 로그를 파일에 남길 때에도 `pipefail`을 사용해 수집 실패 코드가 가려지지 않게 합니다.

모집 구분에 신입 지원이 명시된 공고 또는 단독 `무관`인 공고를 살펴봅니다. **`신입/경력`, `신입 및 경력`, `신입·경력`, `경력/신입`은 신입도 지원 가능하므로 허용합니다(2026-11-19 사용자 기준 변경).** 혼합 모집 표기를 제외한 실제 경력 전용 요건이나 석사·박사 관련 표현은 기존 기준대로 제외합니다. 독립적인 `경력무관`, `경력기술서`, `석사 우대` 제외 기준은 유지합니다. 지원자격 양식에서 항목명이 `경력`이고 값이 `신입`이면 통과할 수 있습니다.

직무는 제목과 담당업무의 키워드 조합으로 판정합니다. AX 업무는 산업과 관계없이 선택하고, 같은 업무 문장에 반도체와 AI 적용 근거가 함께 있으면 `반도체×AX`로 분류합니다. 연구·개발 공고는 연구 대상과 상세 페이지의 업종 표시를 확인합니다. 반도체 소재 연구는 선택하고, 문구잉크 신제품 개발은 직무 제외로 표시합니다. 일반 소재 연구나 단순 연구보조처럼 반도체·AX 업무 근거가 부족한 공고도 직무 제외로 처리합니다. 신입 지원 여부가 불분명하면 자격 제외, 상세 링크 오류나 접속 실패는 해당 실행에서 수집 제외로 기록합니다.

## 실행

Python 3가 설치된 컴퓨터에서 이 폴더를 열고 실행하세요.

- macOS 또는 Linux: `python3 main.py`
- Windows: `py main.py`

8개 주소의 접속 상태는 `python3 fetch_page.py`로 확인합니다.

```sh
# 전체 수집 및 노션 저장 (.env 또는 GitHub Secret의 NOTION_TOKEN 사용)
.venv/bin/python -u fetch_page.py --all --notion --output postings.json

# 추가 사이트만 선택해 쓰기 없이 확인
.venv/bin/python -u fetch_page.py --site saramin-home --site jasoseol --dry-run

# 모든 파서/저장 테스트 (외부 쓰기 없음)
.venv/bin/python -m unittest discover -v
```

R&D잡 본문을 읽으려면 프로젝트 폴더에서 아래 명령을 실행하세요.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python fetch_page.py --rndjob
```

Windows에서는 `py -m venv .venv`로 환경을 만들고, 나머지 두 명령의 `.venv/bin/python`을 `.venv\Scripts\python.exe`로 바꾸세요. 두 번째 실행부터는 마지막 명령만 사용합니다.

## SKALA 루핏

루핏의 전체 채용정보 목록에서 최대 5페이지를 확인합니다. 브라우저가 공고의 상세창을 열고 상세요강의 자격과 담당업무에 기존 필터를 적용합니다. 관심 공고에는 회사명과 근거, 화면에 제공된 지원 링크를 표시합니다. 이미지 전용 상세나 읽지 못한 상세창은 수집 제외에 집계합니다.

가상환경을 활성화한 뒤 최초 한 번 준비합니다.

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
```

루핏은 `python fetch_page.py --loofit`으로 실행합니다. 두 사이트를 연속해서 확인하려면 `python fetch_page.py --rndjob --loofit`을 사용합니다.

## Notion 수집함에 저장

기존 [채용공고 수집함](https://app.notion.com/p/41d92822e1098190868cd93820c1c8ce)에 관심 공고만 저장합니다. 회사 열을 앞에 둔 기존 표 구성을 사용하며, 직무명·회사·공고 링크·관심 분야·확인된 마감일·판단 근거·출처·수집 키를 기록합니다. 새 공고의 지원 상태는 `검토 전`입니다.

같은 사이트의 개별 공고 ID로 재실행 시 기존 행을 갱신합니다. 제목이 바뀌어도 ID가 같으면 갱신하며, 사이트가 다를 때는 회사·직무명·지원 URL이 모두 일치할 때만 합칩니다. 출처별 수집 키를 함께 보관합니다. URL에 추적용 `utm_*`, `fbclid`, `gclid`만 다른 경우는 동일하게 처리합니다. 다른 링크나 다른 제목으로 올라온 공고는 자동으로 같은 채용이라고 추정하지 않습니다. 동시에 여러 수집 프로세스를 실행하지 마세요. 조회와 생성은 하나의 원자적 연산이 아닙니다.

갱신할 때 기존 `지원 준비` 등의 지원 상태와 페이지 본문 메모는 보존합니다. 마감일은 `마감일: 2026.12.01`처럼 연도를 포함한 명확한 표시만 추출합니다. 연도 없는 날짜·상시채용·미확인 마감일은 추정하지 않으며, 이번에 읽지 못한 날짜로 기존 값을 지우지 않습니다. 루핏에 기업 지원 링크가 없으면 링크를 비워 두고 공고 ID로 중복을 확인합니다. 공용 목록 URL을 개별 공고 링크로 저장하지 않습니다.

### 연결된 Notion 도구로 사용할 때

토큰 없이 수집 후보 파일을 만들 수 있습니다.

```sh
.venv/bin/python -u fetch_page.py --rndjob --loofit --output postings.json
```

Codex에서 “postings.json의 관심 공고를 기존 노션 수집함에 저장해줘”라고 요청하면 연결된 Notion 도구로 처리할 수 있습니다. 이 명령 자체는 파일만 만들며 Notion에 쓰지 않습니다. 파일에는 선택된 공고만 들어갑니다. 0건일 때는 빈 목록이며 저장할 행이 없습니다.

### 터미널에서 직접 저장할 때: 최초 한 번 연결

프로젝트의 `.env` 파일에 `NOTION_TOKEN=발급받은토큰`을 입력하고 저장하면 프로그램이 자동으로 읽습니다. `.env`는 Git에서 제외됩니다. 이미 터미널에 `NOTION_TOKEN`을 설정했다면 그 값이 우선하므로, `.env` 값으로 바꾸려면 `unset NOTION_TOKEN`을 실행하세요. `.env` 사용 시 아래의 `read`와 `export` 단계는 생략하고 수집 명령만 실행하면 됩니다.

Codex의 Notion 연결 인증은 로컬 Python 프로세스와 공유되지 않습니다. Python에서 직접 저장하려면 [Notion 연결 관리](https://app.notion.com/developers/connections)에서 읽기·삽입·수정 권한을 가진 연결을 만들고, 채용공고 수집함 페이지의 연결 메뉴에서 그 연결을 추가합니다. 토큰은 채팅이나 코드에 넣지 않습니다.

macOS의 VS Code 터미널(zsh)에서 다음 명령으로 토큰을 숨김 입력합니다. `export`까지 실행한 뒤 같은 터미널에서 수집합니다. 터미널을 새로 열면 다시 입력합니다.

```sh
read -s 'NOTION_TOKEN?Notion 연결 토큰: '
export NOTION_TOKEN
.venv/bin/python -u fetch_page.py --rndjob --loofit --notion
```

기본 데이터 소스 ID는 기존 수집함의 `41d92822-e109-819f-afd2-000b9d895be1`입니다. 다른 수집함을 쓸 때만 환경변수 `NOTION_DATA_SOURCE_ID`로 바꿉니다. 필요한 열/옵션은 쓰기 전에 검사하며, 스키마가 다르면 중단합니다. 이 프로그램은 스키마를 자동 변경하지 않습니다.

### 미리 보기와 저장 재시도

```sh
# 토큰 없이 수집·분류 및 JSON 결과 확인. Notion에 쓰지 않습니다.
.venv/bin/python -u fetch_page.py --rndjob --loofit --notion --dry-run --output postings.json

# 저장 오류 후 보관한 결과만 다시 저장 (NOTION_TOKEN 필요)
.venv/bin/python notion_sync.py --input postings.json

# 저장·중복·오류 처리 테스트 (실제 Notion에 쓰지 않음)
.venv/bin/python -m unittest -v test_notion_sync
```

`--notion`은 쓰기 전에 수집 결과를 `postings.json` 또는 `--output`으로 지정한 파일에 보관합니다. 일부 저장 후 실패하면 명령이 실패 코드로 끝나며, 재실행 시 수집 키를 먼저 조회합니다. 서버 반영 여부가 불분명한 생성 요청은 자동으로 반복하지 않습니다. 429 응답은 `Retry-After`를 따라 제한된 횟수로 재시도합니다. 같은 공고가 기존 수집함에 여러 행으로 발견되면 임의로 고르거나 삭제하지 않고 중단합니다.

구현은 Notion 공식 API의 [데이터 소스 조회](https://developers.notion.com/reference/query-a-data-source), [페이지 생성](https://developers.notion.com/reference/post-page), [페이지 갱신](https://developers.notion.com/reference/patch-page)을 사용합니다. API 버전은 `2026-03-11`로 고정합니다.
