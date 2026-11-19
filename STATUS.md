# 운영 현황과 이어하기

기준: 2026-11-20 00:36 KST. 기능 코드 기준 커밋: `a339055fa7cf820fe9e0c1ffac0a985e0847d0de`.

## 현재 상태

공개 채용공고 수집 → 이미지 OCR → 관심 직무 분류 → Notion 저장·중복 갱신을 구현하고 GitHub에 배포했다. 매일 한국시간 오전 9시(UTC 00:00)에 GitHub Actions가 실행하도록 예약했다. 컴퓨터와 Codex를 켜 둘 필요는 없다. 기존 Codex 예약은 `PAUSED` 상태다.

작성 시점에는 11월 20일 오전 9시가 아직 도래하지 않았다. 완료한 수동 시험 실행과 앞으로 실행될 정기 예약을 구분한다.

| 수집 주소 | 운영 상태 |
| --- | --- |
| R&D잡 | 정기 수집 대상 |
| SKALA 루핏 | 정기 수집 대상 |
| 사람인 홈 | 정기 수집 대상 |
| 사람인 강소기업 | 정기 수집 대상 |
| 잡코리아 신입 | 정기 수집 대상, 공개 상세요강 프레임 누락 수정 완료 |
| 자소설닷컴 | 정기 수집 대상 |
| 이공계모야 | 정기 수집 대상, 이미지의 직무별 분리 지원 |
| 캐치 | 사용자 요청으로 보류. GitHub 서버의 403 접근 제한으로 예약 대상에서 제외 |

사람인 홈과 강소기업은 별도 진입 주소다. 전 사이트의 모든 공고를 전수 수집하는 방식은 아니며, 추가 사이트는 기본 최대 50개 공고, 최대 5페이지 범위다. 세부 범위는 [README](https://github.com/ahnminah0606-cmd/job-posting-automation/blob/main/README.md)를 따른다.

## 분류·이미지 처리 기준

- `신입/경력`, `신입 및 경력`, `신입·경력`, `경력/신입`처럼 신입 지원이 명시된 혼합 모집은 허용한다.
- 실제 경력 전용 요건과 석사·박사 관련 표현은 기존 제외 기준을 유지한다.
- 관심 분야는 반도체, AX, 반도체 × AX다. 제목과 실제 담당업무의 근거로 분류하며 우대 도구명만으로 AX로 선택하지 않는다.
- Mac과 GitHub 서버에서 같은 RapidOCR 3.10.0 한국어 PP-OCRv5 모델과 ONNX Runtime CPU 엔진을 사용한다. 외부 AI API로 이미지를 보내지 않는다.
- 긴 이미지를 나눠 읽고 위치 정보를 이용해 표의 읽기 순서를 보존한다. 직무별 업무·개별 자격·공통 자격이 명확하면 각각 분리한다.
- 판독 실패, 평균 신뢰도 60% 미만, 불명확한 직무 구획은 제외 사유를 남긴다. 평균 신뢰도는 정확도 보증이 아니다. PDF 첨부와 SVG 판독은 현재 지원하지 않는다.

## Notion 반영 결과

[채용공고 수집함](https://app.notion.com/p/41d92822e1098190868cd93820c1c8ce)에 실제 이미지 공고 2개에서 고른 관심 직무 3개를 반영했다.

| 회사 | 저장된 직무 | 관심 분야 |
| --- | --- | --- |
| 퀄리타스반도체 | [반도체 IP 실리콘 검증 Engineer(신입)](https://app.notion.com/p/41d92822e10981ca9f39e4e535e7d8bb) | 반도체 |
| LS ITC | [AI 서비스 기획 및 개발 (채용형 인턴)](https://app.notion.com/p/41d92822e109812fa109fca5194e7d37) | AX |
| LS ITC | [AI 서비스 시스템 운영 (채용형 인턴)](https://app.notion.com/p/41d92822e10981648110e4aa1fc26b48) | AX |

LS ITC의 6개 직무 중 관련 직무 2개만 선택했다. 처음 생성된 묶음 행은 기존 페이지 ID를 유지해 AI 기획·개발 직무로 수정했다. 퀄리타스반도체의 다른 직무는 석박사 표현으로 제외했다.

재실행 결과는 **신규 0건·기존 3건 갱신**이었다. 같은 두 원문 링크에 관심 직무 3개만 존재하는 것을 확인했다. 기존 지원 상태와 본문 메모를 보존한다.

속성은 회사·직무명·공고 링크·관심 분야·마감일·지원 상태·출처 7개다. 사용자 요청으로 삭제한 `수집 키`와 `판단 근거` 열은 다시 만들지 않는다. 공고 링크·회사·직무명으로 중복을 확인하고 OCR의 공백·대소문자·전각 문자 차이를 정규화한다. 실제 직무명이 달라지면 별도 행이 될 수 있다.

## 검증 기록과 범위

| 검증 | 결과 | 근거 |
| --- | --- | --- |
| 7개 주소 전체 서버 수집 | 성공, 사이트 오류 0곳 | [Daily job collection #8](https://github.com/ahnminah0606-cmd/job-posting-automation/actions/runs/44542138875) |
| 서버 Notion Secret과 재실행 갱신 | 성공, 당시 기존 행 1건 갱신 | [Daily job collection #9](https://github.com/ahnminah0606-cmd/job-posting-automation/actions/runs/44543299085) |
| 최종 코드의 OCR·분류·저장 테스트 | 서버 테스트 44개 통과 | [Collector checks #3](https://github.com/ahnminah0606-cmd/job-posting-automation/actions/runs/44551206858) |
| 최종 모델의 실제 이미지 검증 | 잡코리아 이미지 판독 및 두 포스터에서 관심 직무 3개 분류 성공, Mac·서버 결과 일치 | [Collector checks #3](https://github.com/ahnminah0606-cmd/job-posting-automation/actions/runs/44551206858) |
| 최종 3개 직무의 실제 Notion 재실행 | 신규 0건·갱신 3건 | 로컬에서 동일 저장 코드로 API 실행 및 수집함 재조회 확인 |

전체 7개 주소 시험은 초기 OCR 버전으로 수행했다. 최종 `a339055`는 이후 잡코리아·실제 이미지·44개 테스트로 서버 회귀 검증했으며, 최종 모델로 7개 주소 전체를 다시 돌린 기록과는 구분한다. `Collector checks`는 읽기 전용 검증으로 Notion에 쓰지 않는다.

## 운영과 다시 실행하기

정기 실행: GitHub Actions → **Daily job collection**. 수동 실행은 Run workflow에서 `all` 또는 특정 주소를 선택한다. 한 사이트가 실패해도 다른 사이트 결과는 저장하고, 전체 실행에는 실패를 표시한다. 로그·후보 JSON·분류 보고서·OCR JSON은 실행별 artifact에서 확인한다. 토큰이나 `.env`는 문서·저장소·artifact에 올리지 않는다.

로컬 수집·저장:

```sh
.venv/bin/python -u fetch_page.py --all --notion --output postings.json
```

로컬 테스트:

```sh
OCR_INTEGRATION=1 .venv/bin/python -m unittest discover -v
```

## 다음 확인·개발

- 다음 오전 9시 정기 실행의 성공 여부와 저장 결과 확인. 아직 정기 실행 완료를 확인한 것은 아니다.
- 신규 이미지와 제외 사유를 표본 점검하고 필요한 분류 기준 조정.
- 다음 개발 후보: `지원 준비` 공고의 JD·지원서 문항·글자 수를 받아 경험 근거 검색과 자기소개서 초안 작성으로 연결. 이 단계는 아직 구현하지 않았다.
- 캐치는 재개 요청 전까지 보류한다.

[Notion 프로젝트 이어하기](https://app.notion.com/p/41d92822e109811cac0fdb6c68b58ffc) · [GitHub 운영 현황](https://github.com/ahnminah0606-cmd/job-posting-automation/blob/main/STATUS.md)
