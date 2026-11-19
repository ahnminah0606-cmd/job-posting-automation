"""관심 공고를 기존 Notion 수집함에 저장한다. 토큰은 환경변수에서만 읽는다."""

import hashlib
import argparse
import json
import os
import re
import unicodedata
import time
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

DATA_SOURCE_ID = "41d92822-e109-819f-afd2-000b9d895be1"
FIELDS = {"반도체": "반도체", "AX": "AX", "반도체×AX": "반도체 × AX"}
SCHEMA = {"직무명": "title", "회사": "rich_text", "공고 링크": "url",
          "관심 분야": "select", "마감일": "date", "지원 상태": "status", "출처": "rich_text"}


class NotionError(RuntimeError):
    pass


def canonical_url(url):
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("공고 링크는 http 또는 https 주소여야 합니다.")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/",
                       urlencode(sorted(query)), ""))


def deadline_from_text(text):
    """연도가 명시된 마감일만 해석한다. 연도 없는 날짜/상시채용은 추정하지 않는다."""
    match = re.search(r"(?:마감(?:일)?|접수\s*마감)\s*[:：]?\s*(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", text)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def make_posting(company, title, url, field, evidence, source, source_id="", deadline=None):
    if field not in FIELDS:
        raise ValueError("관심 공고만 저장할 수 있습니다.")
    if not all(isinstance(v, str) and v.strip() for v in (company, title, evidence, source)):
        raise ValueError("회사·직무명·판단 근거·출처가 필요합니다.")
    url = canonical_url(url)
    identity = str(source_id) or url
    if not identity:
        raise ValueError("공고 ID나 개별 공고 링크가 필요합니다.")
    if deadline:
        date.fromisoformat(deadline)
    # 사이트의 개별 공고 ID를 우선 사용해 제목 수정 후에도 같은 행을 갱신한다.
    basis = [source, str(source_id)] if source_id else [source, identity, company.strip(), title.strip()]
    key = hashlib.sha256(json.dumps(basis, ensure_ascii=False).encode()).hexdigest()
    return dict(company=company.strip(), title=title.strip(), url=url, field=field,
                evidence=evidence.strip(), source=source.strip(), key=key, deadline=deadline)


def rich_text(value):
    # Notion의 텍스트 조각당 2,000자 제한을 지키며 조용히 잘라내지 않는다.
    if len(value) > 100000:
        raise ValueError("저장할 텍스트가 너무 깁니다.")
    return [{"type": "text", "text": {"content": value[i:i + 2000]}}
            for i in range(0, len(value), 2000)]


def normalized_title(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def property_text(properties, name):
    prop = properties.get(name, {})
    kind = prop.get("type") or ("title" if "title" in prop else "rich_text")
    return "".join(item.get("plain_text", item.get("text", {}).get("content", ""))
                   for item in prop.get(kind, []))


def properties_for(posting, existing=None):
    props = existing.get("properties", {}) if existing else {}
    sources = property_text(props, "출처").splitlines()
    if posting["source"] not in sources:
        sources.append(posting["source"])
    result = {
        "직무명": {"title": rich_text(posting["title"])},
        "회사": {"rich_text": rich_text(posting["company"])},
        "관심 분야": {"select": {"name": FIELDS[posting["field"]]}},
        "출처": {"rich_text": rich_text("\n".join(filter(None, sources)))},
    }
    # 이번에 읽지 못한 링크·마감일로 기존 값을 지우지 않는다.
    if posting["url"]:
        result["공고 링크"] = {"url": posting["url"]}
    if posting.get("deadline"):
        result["마감일"] = {"date": {"start": posting["deadline"]}}
    if not existing:
        result["지원 상태"] = {"status": {"name": "검토 전"}}
    return result


class NotionClient:
    def __init__(self, token=None, data_source_id=None):
        load_dotenv(Path(__file__).with_name(".env"), override=False)
        self.token = token or os.environ.get("NOTION_TOKEN", "")
        if not self.token:
            raise NotionError("NOTION_TOKEN 환경변수가 없습니다. README의 최초 연결 안내를 확인하세요.")
        self.data_source_id = data_source_id or os.environ.get("NOTION_DATA_SOURCE_ID", DATA_SOURCE_ID)

    def request(self, method, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        for attempt in range(4):
            request = Request("https://api.notion.com/v1/" + path, data=data, method=method,
                              headers={"Authorization": "Bearer " + self.token,
                                       "Notion-Version": "2026-03-11",
                                       "Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=30) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 429 and attempt < 3:
                    try:
                        delay = float(error.headers.get("Retry-After", "1"))
                    except ValueError:
                        delay = 1
                    time.sleep(max(1, min(delay, 60)))
                    continue
                hints = {401: "토큰을 확인하세요.", 403: "연결의 읽기·삽입·수정 권한을 확인하세요.",
                         404: "수집함에 연결을 추가하고 데이터 소스 ID를 확인하세요."}
                # 생성 요청은 서버 반영 여부가 불명확할 수 있어 자동 재시도하지 않는다.
                raise NotionError(f"Notion HTTP {error.code}. " + hints.get(error.code,
                                  "저장 중단. 다시 실행하면 공고 링크·회사·직무명으로 기존 행을 먼저 확인합니다.")) from None
            except (URLError, OSError, ValueError):
                raise NotionError("Notion 응답 확인 실패. 저장이 반영됐을 수 있으므로 재실행 시 기존 행을 먼저 조회합니다.") from None

    def validate_schema(self):
        schema = self.request("GET", "data_sources/" + self.data_source_id)["properties"]
        invalid = [name for name, kind in SCHEMA.items() if schema.get(name, {}).get("type") != kind]
        options = {o["name"] for o in schema.get("관심 분야", {}).get("select", {}).get("options", [])}
        statuses = {o["name"] for o in schema.get("지원 상태", {}).get("status", {}).get("options", [])}
        if invalid or not set(FIELDS.values()) <= options or "검토 전" not in statuses:
            raise NotionError("수집함 열/옵션이 예상과 다릅니다: " + ", ".join(invalid))

    def find_existing(self, posting):
        filters = [{"property": "회사", "rich_text": {"equals": posting["company"]}}]
        rows = []
        cursor = None
        while True:
            payload = {"filter": {"or": filters}, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            page = self.request("POST", f"data_sources/{self.data_source_id}/query", payload)
            rows.extend(page["results"])
            if not page.get("has_more"):
                break
            cursor = page["next_cursor"]
        matches = []
        for row in rows:
            props = row["properties"]
            if (property_text(props, "회사") != posting["company"]
                    or normalized_title(property_text(props, "직무명")) != normalized_title(posting["title"])):
                continue
            # 회사·직무가 같고 링크도 같으면 같은 행이다. 추가 속성 열은 필요 없다.
            old_url = props.get("공고 링크", {}).get("url") or ""
            same_url = posting["url"] and old_url and canonical_url(old_url) == posting["url"]
            same_source_without_url = (not posting["url"] or not old_url) and posting["source"] in property_text(props, "출처").splitlines()
            if same_url or same_source_without_url:
                matches.append(row)
        if len(matches) > 1:
            raise NotionError("동일 공고에 해당하는 기존 행이 여러 개입니다. 수집함에서 중복을 확인하세요.")
        return matches[0] if matches else None

    def upsert(self, posting):
        if posting.get("field") not in FIELDS or not re.fullmatch(r"[0-9a-f]{64}", posting.get("key", "")):
            raise ValueError("저장할 공고의 관심 분야 또는 수집 키가 유효하지 않습니다.")
        existing = self.find_existing(posting)
        payload = {"properties": properties_for(posting, existing)}
        if existing:
            page = self.request("PATCH", "pages/" + existing["id"], payload)
            return "갱신", page
        payload["parent"] = {"type": "data_source_id", "data_source_id": self.data_source_id}
        return "신규", self.request("POST", "pages", payload)


def save_postings(postings, client=None):
    if not postings:
        print("Notion 저장 대상 0건 | 신규 0건 | 갱신 0건")
        return
    client = client or NotionClient()
    client.validate_schema()
    counts = {"신규": 0, "갱신": 0}
    for posting in postings:
        action, page = client.upsert(posting)
        counts[action] += 1
        print(f"Notion {action} | {posting['company']} | {posting['title']} | {page.get('url', '')}")
    print(f"Notion 저장 완료 | 신규 {counts['신규']}건 | 갱신 {counts['갱신']}건")


def main():
    parser = argparse.ArgumentParser(description="보관한 관심 공고 JSON을 Notion 수집함에 저장/재시도")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        postings = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(postings, list):
            raise ValueError("JSON 최상위 값은 공고 목록이어야 합니다.")
        for posting in postings:
            if not isinstance(posting, dict):
                raise ValueError("각 공고는 JSON 객체여야 합니다.")
            make_posting(posting["company"], posting["title"], posting["url"], posting["field"],
                         posting["evidence"], posting["source"], posting["key"], posting.get("deadline"))
            if not re.fullmatch(r"[0-9a-f]{64}", posting["key"]):
                raise ValueError("수집 키 형식이 잘못됐습니다.")
        save_postings(postings)
    except (OSError, ValueError, KeyError, TypeError, NotionError) as error:
        parser.exit(1, f"저장 중단: {error}\n")


if __name__ == "__main__":
    main()
