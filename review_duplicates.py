"""읽기 전용 중복 검토 보고서. Notion 행의 수정·삭제·보관 처리를 하지 않는다."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from job_identity import campaign_for, is_summary, match_kind
from notion_sync import NotionClient, property_text, row_identity


def describe(row):
    props=row['properties']
    return dict(id=row['id'],url=row.get('url',''),company=property_text(props,'회사'),
                title=property_text(props,'직무명'),posting_url=props.get('공고 링크',{}).get('url'),
                status=(props.get('지원 상태',{}).get('status') or {}).get('name'),
                source=property_text(props,'출처'))


def build_review(rows):
    candidates=[]
    for index,left in enumerate(rows):
        a=row_identity(left)
        for right in rows[index+1:]:
            b=row_identity(right);kind=match_kind(a,b)
            if not kind:continue
            campaign=campaign_for(a) or campaign_for(b)
            candidates.append(dict(kind=kind,rows=[describe(left),describe(right)],
                summary_ids=[r['id'] for r in (left,right) if is_summary(row_identity(r))],
                campaign_id=campaign['id'] if campaign else None,
                evidence=campaign['urls']+campaign.get('references',[]) if campaign else sorted(set(a['urls']+b['urls'])),
                proposed_action='직무별 행·상태·메모를 보존하고 요약 행 정리 여부를 먼저 확인' if kind=='summary-overlap' else '상태·메모를 비교해 유지할 행을 먼저 확인. 승인 전 자동 정리 없음'))
    return dict(created_at=datetime.now(timezone.utc).isoformat(),read_only=True,
                row_count=len(rows),candidate_count=len(candidates),candidates=candidates)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('duplicate-review.json'))
    args=parser.parse_args()
    report=build_review(NotionClient().read_rows())
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('읽기 전용 보고서 저장:',args.output,'| Notion 수정·삭제 0건')


if __name__=='__main__':main()
