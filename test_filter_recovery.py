import json
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from collectors import egong_roles, qualification, poster_deadline
from fetch_page import excluded_qualification, classify_loofit_jd
from ocr import enrich_html, split_ocr_grid

CASES=json.loads(Path(__file__).with_name('fixtures').joinpath('recovery-posters.json').read_text())

def fixture_html(case):
    with patch('ocr.image_bytes',return_value=b'fixture'), patch('ocr.recognize',side_effect=case['documents']):
        return enrich_html(''.join('<img src="https://example.org/%s.png">'%i for i in range(len(case['documents']))))

class CareerContextTests(unittest.TestCase):
    def test_labels_awards_documents_and_no_experience_are_allowed(self):
        for value in ['경력: 신입','경력구분: 신입','경력무관(신입포함)','수상 경력이 있으신 분','운전경력 및 법규 준수','경력증명서 제출','경력기술서 제출','경력 개발 기회','무경력의 경우 수습 적용']:
            self.assertIsNone(excluded_qualification(value),value)
        self.assertIsNone(qualification('AI 개발','경력무관(신입포함)'))

    def test_actual_experience_and_degree_still_block(self):
        for value in ['경력','연구 경력','경력직 채용','경력자 우대','해당 직무 경력 3년 필수','신입/경력 채용. 해당 직무 경력 3년 필수','석사 우대','학사/석사/박사','석 사 이상']:
            self.assertIsNotNone(excluded_qualification(value),value)

    def test_non_requirement_does_not_hide_later_real_requirement(self):
        for value in ['수상 경력 우대. 해당 직무 경력 3년 필수','경력무관. 석사 필수','경력증명서 제출. 경력직 채용']:
            self.assertIsNotNone(excluded_qualification(value),value)

class ActualPosterRecoveryTests(unittest.TestCase):
    def test_soc_sip_table_separates_qualification_from_duties(self):
        case=CASES[0];html=fixture_html(case);roles=split_ocr_grid(html)
        self.assertEqual(len(roles),1)
        self.assertEqual(roles[0][0],'Process Engineer (신입)')
        self.assertEqual(egong_roles(case['title'],html,case['url'])[0][1][0],'반도체')
        body=BeautifulSoup(roles[0][1],'html.parser')
        self.assertNotIn('학사',body.select_one('h3').find_next_sibling().get_text())
        self.assertEqual(poster_deadline(roles[0][1]),'2026-11-29')

    def test_soulbrain_document_word_is_not_work_experience(self):
        case=CASES[1];html=fixture_html(case)
        roles=egong_roles(case['title'],html,case['url'])
        self.assertEqual(len(roles),1)
        self.assertEqual(roles[0][1][0],'AX',roles)
        self.assertEqual(poster_deadline(html),'2026-11-22')

    def test_independent_naver_posters_have_independent_roles(self):
        case=CASES[2];html=fixture_html(case)
        roles=egong_roles(case['title'],html,case['url'])
        self.assertEqual(len(roles),2)
        self.assertEqual([decision[0] for _,decision in roles],['AX','직무 제외'])
        self.assertIn('국방',roles[0][0])
        self.assertIn('글로벌',roles[1][0])

    def test_missing_coordinates_do_not_guess_table(self):
        html=fixture_html(CASES[0]).replace('data-x=','removed-x=')
        self.assertEqual(split_ocr_grid(html),[])

    def test_common_degree_not_dropped_and_unassigned_qualification_blocks_split(self):
        html=fixture_html(CASES[0])
        # Common qualification is outside the table and applies to the selected role.
        html=html.replace('토익스피킹140점','석사 이상 토익스피킹140점')
        roles=egong_roles(CASES[0]['title'],html,'')
        self.assertEqual(roles[0][1][0],'자격 제외')
        self.assertEqual(split_ocr_grid(html+'<p>공통 지원자격: 박사 필수</p>'),[])

    def test_degree_in_other_role_never_leaks_into_selected_role(self):
        html=fixture_html(CASES[2]).replace('국내/외 정규대학(학사)재학생 또는 기졸업지','국내/외 정규대학(학사)재학생 또는 기졸업지',1)
        # Only the second poster receives an extra required degree.
        soup=BeautifulSoup(html,'html.parser');section=soup.select('section[data-ocr]')[-1]
        p=soup.new_tag('p');p.string='석사 필수';section.append(p)
        roles=egong_roles(CASES[2]['title'],str(soup),'')
        self.assertEqual([d[0] for _,d in roles],['AX','자격 제외'])

    def test_unknown_and_conflicting_dates_are_not_guessed(self):
        self.assertIsNone(poster_deadline('<p>~11/29</p>'))
        self.assertIsNone(poster_deadline('<p>2026.11.01~2026.11.29</p><p>2026.11.01~2026.12.01</p>'))

class RecoveryReplayTests(unittest.TestCase):
    def test_targets_deduplicate_ads_without_losing_roles_in_outputs(self):
        from recheck_exclusions import targets, unique_postings
        base=dict(id='12:1',company='회사',title='개발',url='https://jasoseol.com/recruit/12',result='수집 제외',evidence='구획 미확인')
        groups=targets([dict(site='자소설닷컴',audit=[base,{**base,'id':'12:2','title':'설계'}])])
        self.assertEqual(len(groups['jasoseol']),1)
        a=dict(source='자소설닷컴',source_id='12:1',title='개발',url=base['url'])
        self.assertEqual(len(unique_postings([a,a,{**a,'title':'설계'}])),2)

    def test_replay_does_not_query_listing_and_scopes_each_structured_role(self):
        from collectors import collect_site
        from contextlib import redirect_stdout
        import io
        details=dict(initialEmploymentCompany=dict(end_time='2026-12-01T12:00:00+09:00',employments=[dict(id=1,division=1,field='반도체 공정 개발'),dict(id=2,division=2,field='AI 개발 경력')],content='<table><tr><td>반도체 공정 개발</td><td>담당업무: 반도체 공정 개발 및 평가. 지원자격: 학사 신입</td></tr><tr><td>AI 개발 경력</td><td>석사 필수</td></tr></table>'))
        card=dict(id='12',company='회사',title='여러 직무 석사 포함 채용',url='https://jasoseol.com/recruit/12')
        with patch('collectors.next_props',return_value=details),patch('collectors.PublicReader') as reader,redirect_stdout(io.StringIO()):
            postings,report=collect_site('jasoseol',recheck_cards=[card])
        self.assertEqual(report['coverage'],'explicit-recheck')
        self.assertEqual(len(postings),1,report)
        self.assertEqual(postings[0]['title'],'반도체 공정 개발')
        self.assertEqual(reader.return_value.soup.call_count,1)

    def test_table_with_separated_role_rows_is_not_merged(self):
        html=fixture_html(CASES[0]);soup=BeautifulSoup(html,'html.parser');section=soup.select_one('section[data-ocr]')
        p=soup.new_tag('p');p.string='다른 Engineer';p['data-x']='0.05';p['data-y']='0.34';p['data-width']='0.12';p['data-height']='0.02';section.append(p)
        self.assertEqual(split_ocr_grid(str(soup)),[])

class RecoveryStorageTests(unittest.TestCase):
    def test_recovered_roles_repeat_as_updates_without_changing_notes(self):
        from notion_sync import make_posting
        from test_notion_sync import MemoryNotion
        postings=[]
        for case in CASES:
            for title,(field,evidence) in egong_roles(case['title'],fixture_html(case),case['url']):
                if field in {'반도체','AX','반도체×AX'}:
                    postings.append(make_posting(case['company'],title,case['url'],field,evidence,'이공계모야',case['id']))
        self.assertEqual(len(postings),3)
        client=MemoryNotion()
        for p in postings:self.assertEqual(client.upsert(p)[0],'신규')
        client.rows[0]['body']='사용자 메모'
        client.rows[0]['properties']['지원 상태']={'status':{'name':'지원 준비'}}
        for p in postings:self.assertEqual(client.upsert(p)[0],'갱신')
        self.assertEqual(len(client.rows),3)
        self.assertEqual(client.rows[0]['body'],'사용자 메모')
        self.assertEqual(client.rows[0]['properties']['지원 상태']['status']['name'],'지원 준비')

class RecoveryScopeTests(unittest.TestCase):
    def test_rechecking_rejected_roles_does_not_recreate_previously_selected_role(self):
        from recheck_exclusions import newly_eligible
        from notion_sync import make_posting
        old=dict(company='LS ITC',title='AI 서비스 시스템 운영 (채용형 인턴)',url='https://egongmoya.letuin.com/CommunityBoard/view/2026/11/36682',result='AX')
        posting=make_posting('엘에스아이티씨㈜',old['title'],'https://www.jobkorea.co.kr/Recruit/GI_Read/50376620','AX','생성형 AI 서비스 운영','잡코리아 신입','50376620')
        candidate=make_posting('새 회사','반도체 공정 개발','https://example.org/job/2','반도체','반도체 공정 개발','사이트','2')
        self.assertEqual(newly_eligible([posting,candidate],[dict(audit=[old])]),[candidate])

class RecoveryCLITests(unittest.TestCase):
    def test_cli_filters_expired_jobs_and_can_collect_legacy_without_notion_writes(self):
        import tempfile,io
        from contextlib import redirect_stdout
        from recheck_exclusions import main
        from notion_sync import make_posting
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report=root/'input.json';output=root/'output.json';audit=root/'audit.json'
            report.write_text(json.dumps([dict(site='이공계모야',audit=[dict(company='회사',title='공정',id='1',url='https://egongmoya.letuin.com/CommunityBoard/view/2026/11/1',result='수집 제외')])]))
            past=make_posting('회사','반도체 공정 개발','https://example.org/1','반도체','반도체 공정 개발','사이트','1','2020-01-01')
            future={**past,'source_id':'2','url':'https://example.org/2','deadline':'2099-01-01'}
            with patch('sys.argv',['recheck_exclusions.py','--report',str(report),'--output',str(output),'--audit',str(audit),'--include-legacy']),patch('recheck_exclusions.collect_site',return_value=([past,future],dict(site='이공계모야',status='success'))),patch('recheck_exclusions.show_rndjob',return_value=[]),patch('recheck_exclusions.show_loofit',return_value=[]),patch('recheck_exclusions.save_postings') as save,redirect_stdout(io.StringIO()):
                main()
            self.assertEqual(json.loads(output.read_text()),[future])
            self.assertEqual(json.loads(audit.read_text())[0]['expired'],1)
            save.assert_not_called()

class ActualCollectorReplayTests(unittest.TestCase):
    def test_replay_recovers_each_poster_date_and_never_uses_another_role_date(self):
        from collectors import collect_site
        from contextlib import redirect_stdout
        import io
        expected=['2026-11-29','2026-11-22','2026-11-25']
        for case,deadline in zip(CASES,expected):
            html=fixture_html(case)
            card=dict(id=case['id'],company=case['company'],title=case['title'],url=case['url'],career='',api='https://egongmoya.letuin.com/api/board'+case['url'].split('.com')[1])
            with patch('collectors.PublicReader') as reader,redirect_stdout(io.StringIO()):
                reader.return_value.json.return_value=dict(code=1000,data=dict(view=dict(content=html)))
                postings,report=collect_site('egong',recheck_cards=[card])
            self.assertEqual(report['status'],'success')
            self.assertEqual(len(postings),1,report)
            self.assertEqual(postings[0]['deadline'],deadline,case['company'])

class OCRRoleOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.html=Path(__file__).with_name('fixtures').joinpath('scoped-ocr-table.html').read_text()
        self.names=['Resource','Growth','Biz Ops','IT팀','인사팀']

    def test_entire_ocr_poster_is_never_a_dom_role_scope(self):
        from collectors import scoped_body
        self.assertEqual(scoped_body(self.html,'인사팀',self.names),'')

    def test_roster_names_and_preferences_do_not_inherit_other_roles_ai_duties(self):
        from ocr import scope_ocr_role
        from collectors import classify_body
        results=[classify_body(name,scope_ocr_role(self.html,name,self.names))[0] for name in self.names]
        self.assertEqual(results,['직무 제외','직무 제외','AX','AX','직무 제외'])
        hr=scope_ocr_role(self.html,'인사팀',self.names)
        self.assertNotIn('AI 코딩 에이전트',hr)

    def test_common_degree_applies_but_other_role_degree_does_not(self):
        from ocr import scope_ocr_role
        from collectors import classify_body
        changed=self.html.replace('·학력·전공·연령·성별·경력 제한 없음','석사 필수')
        self.assertEqual(classify_body('IT팀',scope_ocr_role(changed,'IT팀',self.names))[0],'자격 제외')
        changed=self.html.replace('디캠프의 인사 업무를 지원합니다.','디캠프의 인사 업무를 지원합니다. 석사 필수')
        self.assertEqual(classify_body('IT팀',scope_ocr_role(changed,'IT팀',self.names))[0],'AX')

class QualificationConflictTests(unittest.TestCase):
    def test_explicit_education_upper_bound_is_held_for_review(self):
        from collectors import classify_body
        html='<h2>주요업무</h2><p>반도체 공정 제품 조립과 계측기를 이용한 측정</p><h2>자격요건</h2><p>학력: 전문대졸 이하</p><p>경력: 신입</p>'
        result,evidence=classify_body('반도체 제조 신입',html)
        self.assertEqual(result,'수집 제외')
        self.assertIn('학력 상한',evidence)
