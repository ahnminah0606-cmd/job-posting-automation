import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bs4 import BeautifulSoup
from collectors import (classify_body, collect_site, iso_deadline, job_schema,
                        labelled, listing_cards, qualification, scoped_body)


def soup(html):
    return BeautifulSoup(html, "html.parser")


class ParserTests(unittest.TestCase):
    def test_saramin_home_and_theme_share_canonical_id(self):
        home = soup('<li><a href="/zf_user/jobs/relay/pop-view?rec_idx=123"><span class="c_name">회사</span><span class="title">반도체 공정 개발 신입</span></a></li>')
        theme = soup('<div class="box_item"><div class="company_nm">회사</div><a title="반도체 공정 개발 신입" href="/zf_user/jobs/relay/view?rec_idx=123">반도체 공정 개발 신입</a><p class="career">신입</p></div>')
        a = listing_cards("saramin-home", home)[0]
        b = listing_cards("saramin-kangso", theme)[0]
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["url"], b["url"])
        self.assertEqual(b["company"], "회사")

    def test_jobkorea_card_excludes_navigation_and_duplicates(self):
        html = '<a href="/Recruit/GI/Recent_List">최근 공고</a><li><a class="coLink">회사</a><a title="개발 신입" href="/Recruit/GI_Read/42?sc=418">개발</a><div class="sDesc"><strong>신입</strong></div><a href="/Recruit/GI_Read/42">중복</a></li>'
        cards = listing_cards("jobkorea", soup(html))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["company"], "회사")
        self.assertEqual(cards[0]["career"], "신입")

    def test_qualification_preserves_strict_user_rules(self):
        self.assertIsNone(qualification("반도체 공정 개발", "신입", "대졸"))
        self.assertIsNone(qualification("반도체 공정 개발", "무관", "학력무관"))
        for career in ("경력무관", "신입/경력", "경력 3년", ""):
            self.assertEqual(qualification("개발", career)[0], "자격 제외")
        self.assertEqual(qualification("개발 석사 우대", "신입")[0], "자격 제외")

    def test_image_only_and_missing_duties_are_not_candidates(self):
        self.assertEqual(classify_body("반도체 개발 신입", '<img src="jd.png">')[0], "수집 제외")
        self.assertEqual(classify_body("반도체 개발 신입", '<p>채용 사이트 바로가기</p>')[0], "수집 제외")

    def test_real_duties_are_classified_but_preferences_do_not_create_ax(self):
        html = '<h2>담당업무</h2><p>웨이퍼 결함 분류 모델 개발 및 배포를 위한 AI 서비스 구축</p><h2>지원자격</h2><p>학사 졸업자 및 졸업예정자 지원 가능</p>'
        self.assertEqual(classify_body("개발 신입", html)[0], "반도체×AX")
        html = '<h2>담당업무</h2><p>일반 사무 문서 작성과 매출 정보 기록 업무를 담당합니다.</p><h2>우대사항</h2><p>AI 챗봇 구축 경험 보유자를 우대합니다.</p>'
        self.assertEqual(classify_body("사무 신입", html)[0], "직무 제외")

    def test_role_scoping_does_not_mix_qualifications(self):
        html = '<table><tr><td>AI 개발</td><td>담당업무: LLM 서비스 구축 및 운영. 지원자격: 학사 신입</td></tr><tr><td>연구직</td><td>석사 필수</td></tr></table>'
        scoped = scoped_body(html, "AI 개발")
        self.assertNotIn("석사", scoped)
        self.assertEqual(scoped_body(html, "정보보안"), "")

    def test_fixed_career_label_is_not_an_exclusion(self):
        html = '<table><tr><th>경력</th><td>신입</td></tr></table><h2>담당업무</h2><p>반도체 웨이퍼 공정 개발 및 공정 조건 평가 업무를 담당합니다.</p><h2>지원자격</h2><p>학사 졸업자 지원 가능</p>'
        self.assertEqual(classify_body("반도체 개발 신입", html)[0], "반도체")

    def test_deadline_utc_converts_to_korea_date(self):
        self.assertEqual(iso_deadline("2026-11-29T15:00:00Z"), "2026-11-30")
        self.assertEqual(iso_deadline("2026-12-04T18:00:00+09:00"), "2026-12-04")
        self.assertIsNone(iso_deadline("채용시"))

    def test_job_schema_graph_and_career_label(self):
        data = {"@graph": [{"@type": "Organization"}, {"@type": "JobPosting", "title": "공고"}]}
        self.assertEqual(next(job_schema(soup('<script type="application/ld+json">' + json.dumps(data) + '</script>')))["title"], "공고")
        self.assertEqual(labelled(soup('<dl><dt>경력</dt><dd>신입</dd></dl>'), "경력"), "신입")

    def test_catch_list_transport_failure_is_not_successful_zero(self):
        with patch("collectors.PublicReader.json", side_effect=OSError("network down")), redirect_stdout(io.StringIO()):
            postings, report = collect_site("catch", 5)
        self.assertEqual(postings, [])
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["failures"])

    def test_catch_public_list_filters_training_products_and_repeated_ids(self):
        items = [{"RecruitID": 1, "RecruitTitle": "개발 경력", "CompName": "회사", "CareerGubunCode": "경력"},
                 {"RecruitID": 2, "RecruitTitle": "교육", "CompName": "교육기관", "IsProduct": 1}]
        with patch("collectors.PublicReader.json", side_effect=[{"recruitData": items}, {"recruitData": items}, {"recruitData": []}]), redirect_stdout(io.StringIO()):
            postings, report = collect_site("catch", 5)
        self.assertEqual(report["postings_seen"], 1)
        self.assertEqual(report["counts"]["자격 제외"], 1)
        self.assertEqual(report["status"], "success")


if __name__ == "__main__":
    unittest.main()
