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
    def test_all_runs_seven_sources_without_catch(self):
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
                         ['saramin-home', 'saramin-kangso', 'jobkorea', 'jasoseol', 'egong'])
