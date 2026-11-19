"""두 실제 공개 이미지 공고의 직무 분리 검증. Notion에는 쓰지 않는다."""
import json
from pathlib import Path
from urllib.parse import unquote_plus
from collectors import PublicReader, egong_roles
from notion_sync import make_posting


def main():
    reader = PublicReader()
    cases = [('36695', '퀄리타스반도체', 'Digital Logic Design Engineer 등 신입 채용'),
             ('36682', 'LS ITC', '시스템 개발 및 운영, 네트워크 운영 및 구축 등 채용형 인턴 채용')]
    postings, audit = [], []
    for job_id, company, title in cases:
        url = f'https://egongmoya.letuin.com/CommunityBoard/view/2026/11/{job_id}'
        response = reader.json('https://egongmoya.letuin.com/api/board/CommunityBoard/view/2026/11/' + job_id)
        assert response.get('code') == 1000, 'Public poster unavailable'
        view = response['data']['view']
        decisions = egong_roles(title, unquote_plus(view['content']), url)
        for role, (field, evidence) in decisions:
            print(company, role, field, evidence, sep=' | ', flush=True)
            audit.append(dict(company=company, title=role, result=field, evidence=evidence, url=url))
            if field in {'반도체', 'AX', '반도체×AX'}:
                postings.append(make_posting(company, role, url, field, evidence, '이공계모야', job_id))
    Path('image-postings.json').write_text(json.dumps(postings, ensure_ascii=False, indent=2) + '\n')
    Path('image-verification-report.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    assert sum(p['company'] == 'LS ITC' and p['field'] == 'AX' for p in postings) == 2, 'LS ITC roles not separated'
    assert sum(p['company'] == '퀄리타스반도체' and p['field'] == '반도체' for p in postings) == 1, 'Semiconductor role not separated'
    print('Actual image verification passed: 3 roles / Notion writes: 0', flush=True)


if __name__ == '__main__':
    main()
