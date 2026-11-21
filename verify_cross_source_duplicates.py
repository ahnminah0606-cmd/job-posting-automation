"""실제 LS ITC 두 출처를 읽고 메모리 저장소에서 중복을 검증한다. 실제 Notion 쓰기 없음."""
from urllib.parse import unquote_plus
from collectors import PublicReader, egong_roles, job_schema
from notion_sync import make_posting, property_text
from test_notion_sync import MemoryNotion


def main():
    reader = PublicReader()
    jk='https://www.jobkorea.co.kr/Recruit/GI_Read/50376620'
    eg='https://egongmoya.letuin.com/CommunityBoard/view/2026/11/36682'
    schema=next(job_schema(reader.soup(jk)))
    frame_url='https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm?Gno=50376620&isHiringCenter=false&hideMapView=false'
    frame=reader.soup(frame_url,referer=jk).select_one('[data-sentry-component="HtmlViewer"]')
    data=reader.json('https://egongmoya.letuin.com/api/board/CommunityBoard/view/2026/11/36682')['data']['view']
    sources=[(schema['hiringOrganization']['name'],schema['title'],str(frame),frame_url,jk,'잡코리아 신입','50376620','2026-11-29'),
             ('LS ITC',data['title'],unquote_plus(data['content']),eg,eg,'이공계모야','36682',None)]
    by_source=[]
    for company,title,html,base,url,source,job_id,deadline in sources:
        selected=[]
        for role,(field,evidence) in egong_roles(title,html,base):
            if field in {'AX','반도체','반도체×AX'}:
                selected.append(make_posting(company,role,url,field,evidence,source,job_id,deadline))
        print(source,'관심 직무',[(p['company'],p['title']) for p in selected],flush=True)
        assert len(selected)==2,'LS ITC source must produce the two AI roles, not a summary'
        by_source.append(selected)
    assert {p['title'] for p in by_source[0]}=={p['title'] for p in by_source[1]}
    for source_order in (by_source,list(reversed(by_source))):
        client=MemoryNotion()
        for group in source_order:
            for posting in group:client.upsert(posting)
        assert len(client.rows)==2
        client.rows[0]['properties']['지원 상태']={'status':{'name':'지원 완료'}}
        client.rows[0]['body']='보존할 사용자 메모'
        for group in source_order:
            for posting in group:assert client.upsert(posting)[0]=='갱신'
        assert len(client.rows)==2
        assert client.rows[0]['properties']['지원 상태']['status']['name']=='지원 완료'
        assert client.rows[0]['body']=='보존할 사용자 메모'
        assert all('잡코리아 신입' in property_text(r['properties'],'출처') and '이공계모야' in property_text(r['properties'],'출처') for r in client.rows)
    print('실제 두 출처의 4개 후보 → 직무 2개, 순서 반대·재실행·지원 상태·메모 보존 통과. 실제 Notion 쓰기: 0',flush=True)


if __name__=='__main__':main()
