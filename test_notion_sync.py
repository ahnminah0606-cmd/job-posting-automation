import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from notion_sync import (FIELDS, SCHEMA, NotionClient, NotionError, canonical_url,
                         deadline_from_text, make_posting, properties_for, rich_text, save_postings)


def posting(**changes):
    args = dict(company="검증 회사", title="웨이퍼 결함 분류 모델 개발",
                url="https://example.com/jobs/42?utm_source=test", field="반도체×AX",
                evidence="웨이퍼 결함 분류 모델 개발", source="SKALA 루핏", source_id="42")
    args.update(changes)
    return make_posting(**args)


class MemoryNotion(NotionClient):
    """실제 HTTP payload를 읽는 테스트용 서버. 상태와 본문 보존을 확인한다."""
    def __init__(self):
        super().__init__(token="test-token")
        self.rows = []
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if method == "GET":
            props = {name: {"type": kind} for name, kind in SCHEMA.items()}
            props["관심 분야"]["select"] = {"options": [{"name": v} for v in FIELDS.values()]}
            props["지원 상태"]["status"] = {"options": [{"name": "검토 전"}]}
            return {"properties": props}
        if path.endswith("/query"):
            return {"results": copy.deepcopy(self.rows), "has_more": False}
        if method == "PATCH":
            row = next(row for row in self.rows if path.endswith(row["id"]))
            row["properties"].update(copy.deepcopy(payload["properties"]))
            return row
        row = dict(id=str(len(self.rows) + 1), url="https://example.com/page", body="사용자 메모",
                   properties=copy.deepcopy(payload["properties"]))
        self.rows.append(row)
        return row


class SyncTests(unittest.TestCase):
    def test_create_repeat_and_update_preserves_status_body_deadline(self):
        client = MemoryNotion()
        p = posting(deadline="2026-12-01")
        self.assertEqual(client.upsert(p)[0], "신규")
        client.rows[0]["properties"]["지원 상태"] = {"status": {"name": "지원 준비"}}
        p["deadline"] = None
        p["evidence"] = "변경된 업무 근거"
        self.assertEqual(client.upsert(p)[0], "갱신")
        self.assertEqual(len(client.rows), 1)
        row = client.rows[0]
        self.assertEqual(row["body"], "사용자 메모")
        self.assertEqual(row["properties"]["지원 상태"]["status"]["name"], "지원 준비")
        self.assertEqual(row["properties"]["마감일"]["date"]["start"], "2026-12-01")
        self.assertEqual(row["properties"]["관심 분야"]["select"]["name"], "반도체 × AX")

    def test_different_role_title_is_not_overwritten(self):
        client = MemoryNotion()
        client.upsert(posting())
        self.assertEqual(client.upsert(posting(title="다른 직무명"))[0], "신규")
        self.assertEqual(len(client.rows), 2)

    def test_cross_source_same_url_company_role_merges_and_retains_both_sources(self):
        client = MemoryNotion()
        first = posting()
        client.upsert(first)
        second = posting(source="R&D잡", source_id="99")
        self.assertEqual(client.upsert(second)[0], "갱신")
        self.assertEqual(client.upsert(first)[0], "갱신")
        self.assertEqual(len(client.rows), 1)
        props = client.rows[0]["properties"]
        self.assertIn("R&D잡", props["출처"]["rich_text"][0]["text"]["content"])
        self.assertNotIn("수집 키", props)
        self.assertNotIn("판단 근거", props)
        self.assertIn("SKALA 루핏", props["출처"]["rich_text"][0]["text"]["content"])

    def test_different_role_same_apply_link_stays_separate(self):
        client = MemoryNotion()
        client.upsert(posting())
        client.upsert(posting(title="다른 직무", source_id="43"))
        self.assertEqual(len(client.rows), 2)

    def test_no_link_uses_id_and_does_not_write_listing_url(self):
        p = posting(url="")
        self.assertNotIn("공고 링크", properties_for(p))
        client = MemoryNotion()
        client.upsert(p)
        self.assertEqual(client.upsert(p)[0], "갱신")

    def test_ambiguous_existing_rows_abort(self):
        client = MemoryNotion()
        client.upsert(posting())
        client.rows.append(copy.deepcopy(client.rows[0]))
        with self.assertRaises(NotionError):
            client.upsert(posting())

    def test_pagination_finds_later_match(self):
        client = NotionClient(token="test")
        row = {"id": "later", "properties": properties_for(posting())}
        with patch.object(client, "request", side_effect=[
                {"results": [], "has_more": True, "next_cursor": "opaque-cursor"},
                {"results": [row], "has_more": False}]) as request:
            self.assertEqual(client.find_existing(posting())["id"], "later")
            self.assertEqual(request.call_args.args[2]["start_cursor"], "opaque-cursor")

    def test_schema_mismatch_aborts_before_write(self):
        client = NotionClient(token="test")
        with patch.object(client, "request", return_value={"properties": {}}) as request:
            with self.assertRaises(NotionError):
                save_postings([posting()], client)
            self.assertEqual(request.call_count, 1)

    def test_deadline_requires_labeled_full_valid_date(self):
        self.assertEqual(deadline_from_text("마감일 : 2026.12.01"), "2026-12-01")
        for value in ("등록일 2026.11.19", "마감 12/01", "상시채용", "마감 2026-02-30"):
            self.assertIsNone(deadline_from_text(value))

    def test_urls_and_qualification_validation(self):
        self.assertEqual(canonical_url("https://EXAMPLE.com/a?b=2&utm_source=x&a=1#x"),
                         "https://example.com/a?a=1&b=2")
        with self.assertRaises(ValueError):
            posting(url="javascript:alert(1)")
        with self.assertRaises(ValueError):
            posting(field="자격 제외")
        self.assertEqual(len(rich_text("가" * 2001)), 2)

    def test_rate_limit_retry_and_auth_error_redaction(self):
        client = NotionClient(token="never-display-this")
        rate_limit = HTTPError("url", 429, "rate limited", {"Retry-After": "1"}, io.BytesIO())
        ok = io.BytesIO(json.dumps({"ok": True}).encode())
        with patch("notion_sync.urlopen", side_effect=[rate_limit, ok]), patch("notion_sync.time.sleep") as sleep:
            self.assertTrue(client.request("GET", "users/me")["ok"])
            sleep.assert_called_once_with(1)
        auth = HTTPError("url", 401, "never-display-this", {}, io.BytesIO())
        with patch("notion_sync.urlopen", side_effect=auth):
            with self.assertRaises(NotionError) as caught:
                client.request("POST", "pages", {})
            self.assertNotIn(client.token, str(caught.exception))

    def test_uncertain_create_is_not_retried(self):
        with patch("notion_sync.urlopen", side_effect=URLError("timeout")) as request:
            with self.assertRaises(NotionError):
                NotionClient(token="test").request("POST", "pages", {})
            self.assertEqual(request.call_count, 1)

    def test_zero_candidates_does_not_require_token(self):
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(io.StringIO()):
            save_postings([])


if __name__ == "__main__":
    unittest.main()
