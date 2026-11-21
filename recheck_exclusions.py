"""과거 보고서의 제외 공고를 원문에서 다시 읽는다. 기본은 읽기 전용이며 --notion일 때만 저장한다."""
import argparse
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from collectors import NEW_SITES, collect_site
from fetch_page import INTERESTS, open_postings, show_rndjob, show_loofit
from notion_sync import save_postings, identity_record
from job_identity import match_kind


def targets(report):
    groups={}
    names={name:key for key,(name,_) in NEW_SITES.items()}
    for site in report:
        key=names.get(site['site'])
        if not key:
            continue
        seen=set();cards=[]
        for item in site.get('audit',[]):
            if item['result'] in INTERESTS or item['url'] in seen:
                continue
            url=item['url'];host=urlsplit(url).hostname
            if host != urlsplit(NEW_SITES[key][1]).hostname:
                raise ValueError('보고서 공고의 사이트 불일치: '+url)
            seen.add(url)
            if key=='jasoseol':
                match=re.fullmatch(r'/recruit/(\d+)',urlsplit(url).path)
            elif key=='egong':
                match=re.fullmatch(r'/CommunityBoard/view/\d+/\d+/(\d+)',urlsplit(url).path)
            else:
                match=None
            card=dict(id=match[1] if match else str(item['id']).split(':')[0],
                      company=item['company'],title=item['title'],url=url,career='')
            if key=='egong':
                card['api']='https://egongmoya.letuin.com/api/board'+urlsplit(url).path
            cards.append(card)
        if cards:
            groups[key]=cards
    return groups


def unique_postings(postings):
    # 같은 광고의 다른 직무는 수집 키가 같을 수 있으므로 제목도 함께 비교한다.
    unique={}
    for p in postings:
        unique[(p['source'],p['source_id'],p['title'],p['url'])]=p
    return list(unique.values())


def newly_eligible(postings, report):
    # 한 광고의 일부 직무만 제외됐던 경우 이미 선택됐던 다른 직무는 복원하지 않는다.
    previous=[dict(company=item['company'],title=item['title'],urls=[item['url']],deadline=None)
              for site in report for item in site.get('audit',[]) if item['result'] in INTERESTS]
    return [p for p in postings if not any(match_kind(identity_record(p),old) in
            {'same-ad-role','verified-campaign-role'} for old in previous)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--output',type=Path,default=Path('recovery-postings.json'))
    parser.add_argument('--audit',type=Path,default=Path('recovery-report.json'))
    parser.add_argument('--include-legacy',action='store_true',help='개별 제외 기록이 없던 R&D잡·루핏은 현재 동일 범위를 재수집')
    parser.add_argument('--notion',action='store_true')
    args=parser.parse_args()
    original=json.loads(args.report.read_text())
    groups=targets(original)
    selected=[];reports=[]
    today=datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    def checkpoint():
        args.output.write_text(json.dumps(unique_postings(selected),ensure_ascii=False,indent=2)+'\n')
        args.audit.write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n')
    for key in sorted(groups,key=lambda k:(k!="egong",k!="jobkorea",k)):
        cards=groups[key]
        print(f'재검토 시작 | {NEW_SITES[key][0]} | 이전 제외 광고 {len(cards)}건',flush=True)
        postings,report=collect_site(key,recheck_cards=cards)
        active=open_postings(postings,today)
        expired=len(postings)-len(active)
        recovered=newly_eligible(active,original)
        report.update(target_ads=len(cards),expired=expired,previously_selected=len(active)-len(recovered),selected=len(recovered))
        active=recovered
        reports.append(report);selected.extend(active);checkpoint()
        print(f'재검토 완료 | {NEW_SITES[key][0]} | 활성 관심 직무 {len(active)}건',flush=True)
    if args.include_legacy:
        for name,collect in [('R&D잡',show_rndjob),('SKALA 루핏',show_loofit)]:
            print(f'재검토 시작 | {name} | 이전 개별 기록이 없어 현재 5페이지 재수집',flush=True)
            try:
                postings=collect(5);active=open_postings(postings,today);selected.extend(active)
                reports.append(dict(site=name,coverage='current-five-pages-not-historical-replay',selected=len(active),status='success'))
            except (Exception,SystemExit) as error:
                reports.append(dict(site=name,coverage='current-five-pages-not-historical-replay',status='failed',failures=[str(error)]))
            checkpoint()
    selected=unique_postings(selected);checkpoint()
    if args.notion:
        save_postings(selected)
    print(f'재검토 결과 | 이전 제외 광고 {sum(map(len,groups.values()))}건 | 활성 관심 후보 {len(selected)}건 | 실제 Notion 저장 요청 {args.notion}',flush=True)


if __name__=='__main__':main()
