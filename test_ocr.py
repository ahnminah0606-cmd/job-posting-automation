import unittest
from unittest.mock import patch

from collectors import classify_body
from ocr import OCRError, enrich_html, scope_ocr_role


class OCRTests(unittest.TestCase):
    def document(self, lines, confidence=.95):
        return dict(key='fixture', engine='fixture', confidence=confidence,
                    text='\n'.join(lines), lines=[dict(text=s, y=i / len(lines)) for i, s in enumerate(lines)])

    def classify_image(self, lines, confidence=.95):
        with patch('ocr.image_bytes', return_value=b'image'), patch('ocr.recognize', return_value=self.document(lines, confidence)):
            return classify_body('반도체 공정 개발 신입/경력', '<img src="poster.png">', base_url='https://example.org/job')

    def test_image_duties_are_classified_and_mixed_career_allowed(self):
        result, evidence = self.classify_image(['신입/경력 채용', '담당업무', '반도체 공정 개발 및 장비 기술 개선 업무 수행', '지원자격', '학사 졸업 예정자 지원 가능'])
        self.assertEqual(result, '반도체', evidence)

    def test_degree_and_required_experience_in_image_are_excluded(self):
        for rule in ('석사 우대', '해당 직무 경력 3년 필수'):
            result, evidence = self.classify_image(['신입/경력 채용', '담당업무', '반도체 공정 개발 및 장비 기술 개선 업무 수행', '지원자격', rule])
            self.assertEqual(result, '자격 제외', evidence)

    def test_low_confidence_or_unreadable_image_never_qualifies(self):
        result, evidence = self.classify_image(['담당업무', '반도체 공정 개발'], .4)
        self.assertEqual(result, '수집 제외')
        self.assertIn('신뢰도', evidence)
        result, evidence = self.classify_image([])
        self.assertEqual(result, '수집 제외')

    def test_failed_image_cannot_leave_only_easy_text_to_qualify(self):
        with patch('ocr.image_bytes', side_effect=OCRError('다운로드 실패')):
            result, evidence = classify_body('반도체 공정 개발', '<h2>담당업무</h2><p>반도체 공정 개발 및 장비 기술 개선 업무 수행</p><img src="qualifications.png">')
        self.assertEqual(result, '수집 제외')

    def test_multi_role_boundaries_preserve_role_qualification(self):
        doc = self.document(['공정개발', '담당업무', '반도체 공정 개발 및 장비 기술 개선 업무 수행', '지원자격', '학사 졸업', 'AI개발', '담당업무', 'LLM 서비스 개발 및 시스템 운영과 모델 배포 업무 수행', '지원자격', '석사 필수'])
        with patch('ocr.image_bytes', return_value=b'image'), patch('ocr.recognize', return_value=doc):
            html = enrich_html('<img src="poster.png">', 'https://example.org')
        body = scope_ocr_role(html, '공정개발', ['공정개발', 'AI개발'])
        self.assertNotIn('석사', body)
        self.assertEqual(classify_body('공정개발', body)[0], '반도체')
        body = scope_ocr_role(html, 'AI개발', ['공정개발', 'AI개발'])
        self.assertEqual(classify_body('AI개발', body)[0], '자격 제외')
        self.assertEqual(scope_ocr_role(html, '없는직무', ['없는직무', 'AI개발']), '')


if __name__ == '__main__':
    unittest.main()

class ScheduleTests(unittest.TestCase):
    def test_all_runs_eight_sources_including_catch(self):
        import io
        import tempfile
        from pathlib import Path
        from contextlib import redirect_stdout
        from fetch_page import main
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), \
             patch('sys.argv', ['fetch_page.py', '--all', '--report', str(Path(tmp) / 'report.json')]), \
             patch('ocr.check_engine', return_value='test'), \
             patch('fetch_page.show_rndjob', return_value=[]), \
             patch('fetch_page.show_loofit', return_value=[]), \
             patch('collectors.collect_site', return_value=([], {'status': 'success'})) as collect:
            main()
        self.assertEqual([call.args[0] for call in collect.call_args_list],
                         ['saramin-home', 'saramin-kangso', 'jobkorea', 'jasoseol', 'egong', 'catch'])

class EngineTests(unittest.TestCase):
    @unittest.skipUnless(__import__('os').environ.get('OCR_INTEGRATION') == '1', 'OCR engine integration opt-in')
    def test_installed_engine_reads_actual_image(self):
        import io
        from PIL import Image, ImageDraw, ImageFont
        from ocr import recognize
        image = Image.new('RGB', (1200, 300), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=40)
        for index, line in enumerate(['SEMICONDUCTOR PROCESS DEVELOPMENT', 'DUTIES AND RESPONSIBILITIES', 'ENTRY LEVEL RECRUITMENT']):
            draw.text((35, 35 + index * 75), line, font=font, fill='black')
        raw = io.BytesIO()
        image.save(raw, format='PNG')
        result = recognize(raw.getvalue())
        self.assertIn('SEMICONDUCTOR', result['text'].upper())
        self.assertIn('ENTRY', result['text'].upper())
        self.assertGreaterEqual(result['confidence'], .60)

class PosterRoleTests(unittest.TestCase):
    def poster(self, title, qualification):
        return '<section data-ocr="fixture">' + ''.join('<p>' + value + '</p>' for value in [title, '담당업무', '반도체 공정 개발 및 장비 기술 개선 업무 수행', '지원자격', qualification]) + '</section>'

    def test_independent_posters_do_not_share_degree_restriction(self):
        from ocr import split_ocr_roles
        html = self.poster('디지털 설계 엔지니어 (신입)', '석사 우대') + self.poster('반도체 검증 엔지니어 (신입)', '학사 졸업 예정자 지원 가능')
        roles = split_ocr_roles(html)
        self.assertEqual(len(roles), 2)
        self.assertEqual([classify_body(t,b)[0] for t,b in roles], ['자격 제외', '반도체'])
        # 별도의 공통 요강을 놓친 채 두 포스터만 분리해서 통과시키지 않는다.
        self.assertEqual(split_ocr_roles(html + '<section data-ocr="common"><p>공통 지원자격 석사 이상 ' + '필수 조건 확인 ' * 15 + '</p></section>'), [])

    def test_ocr_career_field_label_is_not_experience_requirement(self):
        result = OCRTests().classify_image(['경력', '신입', '담당업무', '반도체 공정 개발 및 장비 기술 개선 업무 수행', '지원자격', '학사 졸업 예정자 지원 가능'])
        self.assertEqual(result[0], '반도체', result)

class JobkoreaImageTests(unittest.TestCase):
    def test_public_detail_frame_reaches_image_ocr_without_browser_race(self):
        import io
        from contextlib import redirect_stdout
        from bs4 import BeautifulSoup
        from collectors import collect_site
        listing = BeautifulSoup('<li><a class="coLink">반도체회사</a><a title="반도체 공정 개발 신입" href="/Recruit/GI_Read/123">공고</a><div class="sDesc"><strong>신입</strong></div></li>', 'html.parser')
        detail = BeautifulSoup('<script type="application/ld+json">{"@type":"JobPosting","title":"반도체 공정 개발 신입","hiringOrganization":{"name":"반도체회사"},"experienceRequirements":"신입","educationRequirements":"학사"}</script>', 'html.parser')
        frame = BeautifulSoup('<table data-sentry-component="HtmlViewer"><tr><td><img src="https://example.org/poster.png"></td></tr></table>', 'html.parser')
        doc = OCRTests().document(['담당업무', '반도체 공정 개발 및 장비 기술 개선 업무 수행', '지원자격', '학사 졸업 예정자 지원 가능'])
        with redirect_stdout(io.StringIO()), patch('collectors.PublicReader') as reader, patch('ocr.image_bytes', return_value=b'image') as download, patch('ocr.recognize', return_value=doc):
            reader.return_value.soup.side_effect = [listing, detail, frame]
            postings, report = collect_site('jobkorea', 1)
        self.assertEqual(report['status'], 'success')
        self.assertEqual(len(postings), 1)
        self.assertEqual(postings[0]['field'], '반도체')
        download.assert_called_once()

class SharedPosterTests(unittest.TestCase):
    def html(self, shared='학사 졸업 예정자 지원 가능'):
        from ocr import enrich_html
        lines = ['모집 직무', 'AI 서비스 개발', '담당 업무', '생성형 AI 서비스 구축 및 운영 업무 수행', '필수 요건', '프로그래밍 기본 능력', '우대 사항', '프로젝트 경험', '네트워크 운영', '담당 업무', '네트워크 장비 구성 및 운영 업무 수행', '필수 요건', 'TCP/IP 기초', '우대 사항', '자격증 보유', '공통 사항', '공통 자격 요건', shared, '채용 프로세스', '서류 면접']
        with patch('ocr.image_bytes', return_value=b'image'), patch('ocr.recognize', return_value=OCRTests().document(lines)):
            return enrich_html('<img src="poster.png">', 'https://example.org')

    def test_shared_poster_keeps_only_ai_role_and_applies_common_qualification(self):
        from collectors import egong_roles
        roles = egong_roles('AI 및 네트워크 등 채용형 인턴 채용', self.html(), 'https://example.org')
        self.assertEqual([r for t,(r,e) in roles], ['AX', '직무 제외'])
        self.assertEqual(roles[0][0], 'AI 서비스 개발 (채용형 인턴)')
        roles = egong_roles('AI 및 네트워크 등 채용형 인턴 채용', self.html('석사 이상'), 'https://example.org')
        self.assertTrue(all(r not in {'AX','반도체'} for t,(r,e) in roles))

    def test_ambiguous_multi_role_image_is_reviewed_instead_of_merged(self):
        from collectors import egong_roles
        html = self.html().replace('공통 사항', '기타 사항').replace('공통 자격 요건', '별도 안내')
        roles = egong_roles('AI 및 네트워크 등 채용형 인턴 채용', html, 'https://example.org')
        self.assertEqual(roles[0][1][0], '수집 제외')

class ReadingOrderTests(unittest.TestCase):
    def test_same_row_label_precedes_value_despite_font_height(self):
        from ocr import reading_order
        lines = [dict(text='신입',x=.3,y=.195,height=.04),dict(text='지원자격',x=.05,y=.20,height=.03),dict(text='담당업무',x=.05,y=.25,height=.03)]
        self.assertEqual([line['text'] for line in reading_order(lines)], ['지원자격','신입','담당업무'])
