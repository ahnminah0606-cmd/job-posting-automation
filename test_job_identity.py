import copy
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from job_identity import company_key, match_kind
from notion_sync import NotionError, identity_record, make_posting, property_text, row_identity, save_postings
from test_notion_sync import MemoryNotion, posting

JK = 'https://www.jobkorea.co.kr/Recruit/GI_Read/50376620'
EG = 'https://egongmoya.letuin.com/CommunityBoard/view/2026/11/36682'
ROLE = 'AI 서비스 기획 및 개발 (채용형 인턴)'
OTHER = 'AI 서비스 시스템 운영 (채용형 인턴)'
SUMMARY = '2027 LS ITC 채용연계형 인턴 모집'


def ls(title=ROLE, source='이공계모야', url=EG, company='LS ITC', deadline=None):
    return make_posting(company,title,url,'AX','생성형 AI 서비스 구축 및 운영',source,'36682' if url==EG else '50376620',deadline)


class IdentityTests(unittest.TestCase):
    def test_company_legal_forms_and_verified_bilingual_aliases(self):
        for name in ['엘에스아이티씨㈜','(주)엘에스아이티씨','주식회사 엘에스아이티씨','LS ITC','LSITC','ＬＳ ＩＴＣ']:
            self.assertEqual(company_key(name), company_key('LS ITC'))
        self.assertEqual(company_key('(주)쎄노텍'),company_key('쎄노텍㈜'))
        self.assertNotEqual(company_key('LS ITC'),company_key('LS ELECTRIC'))

    def test_verified_cross_site_role_updates_without_losing_notes_or_status(self):
        c=MemoryNotion();c.upsert(ls())
        c.rows[0]['properties']['지원 상태']={'status':{'name':'지원 완료'}}
        c.rows[0]['body']='지원 문항과 작성 중인 메모'
        action,row=c.upsert(ls(title='AI 서비스 기획 및 개발 (인턴)',source='잡코리아 신입',url=JK,company='엘에스아이티씨㈜',deadline='2026-11-29'))
        self.assertEqual(action,'갱신');self.assertEqual(len(c.rows),1)
        self.assertEqual(row['properties']['지원 상태']['status']['name'],'지원 완료')
        self.assertEqual(row['body'],'지원 문항과 작성 중인 메모')
        self.assertEqual(row['properties']['공고 링크']['url'],EG)
        self.assertEqual(property_text(row['properties'],'회사'),'LS ITC')
        links={x['text'].get('link',{}).get('url') for x in row['properties']['출처']['rich_text']}
        self.assertTrue({JK,EG} <= links)
        self.assertNotIn('수집 키',row['properties']);self.assertNotIn('판단 근거',row['properties'])

    def test_different_roles_in_same_campaign_stay_separate(self):
        c=MemoryNotion();c.upsert(ls());c.upsert(ls(OTHER,source='잡코리아 신입',url=JK,company='엘에스아이티씨㈜'))
        self.assertEqual(len(c.rows),2)

    def test_different_year_and_same_year_different_ad_stay_separate(self):
        for deadline in ['2027-11-29','2026-12-29','2026-11-29']:
            c=MemoryNotion();c.upsert(ls())
            self.assertEqual(c.upsert(ls(source='잡코리아 신입',url='https://www.jobkorea.co.kr/Recruit/GI_Read/99999',deadline=deadline))[0],'신규')
            self.assertEqual(len(c.rows),2)

    def test_same_url_but_explicit_different_year_or_round_is_not_merged(self):
        for first,second in [('2027 AI 개발','2028 AI 개발'),('AI 개발 1차','AI 개발 2차'),('AI 개발 상반기','AI 개발 하반기')]:
            c=MemoryNotion();c.upsert(posting(title=first))
            self.assertEqual(c.upsert(posting(title=second))[0],'신규')

    def test_summary_is_suppressed_in_either_collection_order(self):
        for summary_first in [True,False]:
            c=MemoryNotion();summary=ls(SUMMARY,source='잡코리아 신입',url=JK,company='엘에스아이티씨㈜',deadline='2026-11-29')
            if summary_first:self.assertEqual(c.upsert(summary)[0],'요약 제외')
            c.upsert(ls());c.upsert(ls(OTHER))
            self.assertEqual(c.upsert(summary)[0],'요약 제외')
            self.assertEqual(len(c.rows),2)
            self.assertFalse(any(method=='PATCH' and path.endswith('/archive') for method,path,p in c.calls))

    def test_old_summary_is_not_overwritten_or_archived(self):
        c=MemoryNotion()
        from notion_sync import properties_for
        old={'id':'summary','body':'요약에 남긴 사용자 메모','properties':properties_for(ls(SUMMARY,source='잡코리아 신입',url=JK))}
        old['properties']['회사']={'rich_text':[{'text':{'content':'엘에스아이티씨㈜'}}]}
        c.rows.append(old)
        self.assertEqual(c.upsert(ls())[0],'신규')
        self.assertEqual(c.rows[0],old)
        self.assertEqual(match_kind(row_identity(old),identity_record(ls())),'summary-overlap')

    def test_tracking_and_rnd_listing_parameters_do_not_create_duplicates(self):
        c=MemoryNotion()
        a=posting(company='(주)쎄노텍',url='https://www.rndjob.or.kr/info/eview01_worknet.asp?gno=00172724&page=9&catecd=1',source='R&D잡')
        b=posting(company='쎄노텍㈜',url='https://www.rndjob.or.kr/info/eview01_worknet.asp?gno=00172724&page=1&catecd=2&utm_source=x',source='R&D잡')
        c.upsert(a);self.assertEqual(c.upsert(b)[0],'갱신');self.assertEqual(len(c.rows),1)
        c2=MemoryNotion();c2.upsert(posting(url=JK+'?sc=1'))
        self.assertEqual(c2.upsert(posting(url=JK+'?sc=2'))[0],'갱신')

    def test_read_your_writes_survives_query_index_lag(self):
        class LaggyNotion(MemoryNotion):
            def request(self,method,path,payload=None):
                if path.endswith('/query'):
                    self.calls.append((method,path,payload));return {'results':[],'has_more':False}
                return super().request(method,path,payload)
        c=LaggyNotion()
        with redirect_stdout(StringIO()):save_postings([ls(),ls(source='잡코리아 신입',url=JK),ls()],c)
        self.assertEqual(len(c.rows),1)
        self.assertIn('잡코리아 신입',property_text(c.rows[0]['properties'],'출처'))
        self.assertEqual(sum(path.endswith('/query') for method,path,p in c.calls),1)

    def test_unknown_companies_or_unverified_other_links_are_not_fuzzy_merged(self):
        c=MemoryNotion();c.upsert(posting(company='LS ITC',url='https://example.com/jobs/1'))
        self.assertEqual(c.upsert(posting(company='LS ELECTRIC',url='https://example.com/jobs/1'))[0],'신규')
        self.assertEqual(c.upsert(posting(company='LS ITC',url='https://example.com/jobs/2'))[0],'신규')
        self.assertEqual(len(c.rows),3)

    def test_same_native_ad_handles_bilingual_label_without_speculative_company_merge(self):
        c=MemoryNotion();c.upsert(posting(company='브랜드',url='https://www.jobkorea.co.kr/Recruit/GI_Read/42'))
        self.assertEqual(c.upsert(posting(company='Brand',url='https://www.jobkorea.co.kr/Recruit/GI_Read/42?sc=1'))[0],'갱신')

    def test_linkless_native_id_is_saved_in_existing_source_property(self):
        c=MemoryNotion();p=posting(url='',source_id='42');c.upsert(p)
        self.assertIn('공고 42',property_text(c.rows[0]['properties'],'출처'))
        other=MemoryNotion();other.rows=copy.deepcopy(c.rows)
        self.assertEqual(other.upsert(p)[0],'갱신')
        self.assertEqual(other.upsert(posting(url='',source_id='43'))[0],'신규')

    def test_linkless_legacy_record_without_identifier_is_held_for_review(self):
        c=MemoryNotion();c.upsert(posting(url=''))
        c.rows[0]['properties']['출처']={'rich_text':[{'text':{'content':'SKALA 루핏'}}]}
        other=MemoryNotion();other.rows=copy.deepcopy(c.rows)
        with self.assertRaises(NotionError):other.upsert(posting(url=''))
        self.assertEqual(len(other.rows),1)

class ReviewTests(unittest.TestCase):
    def test_existing_summary_and_applied_role_are_only_proposed_for_review(self):
        from review_duplicates import build_review
        from notion_sync import properties_for
        summary=dict(id='summary',url='https://notion.so/summary',properties=properties_for(ls(SUMMARY,source='잡코리아 신입',url=JK)))
        summary['properties']['회사']={'rich_text':[{'text':{'content':'엘에스아이티씨㈜'}}]}
        role=dict(id='role',url='https://notion.so/role',body='보존할 메모',properties=properties_for(ls()))
        role['properties']['지원 상태']={'status':{'name':'지원 완료'}}
        rows=[summary,role];before=copy.deepcopy(rows)
        report=build_review(rows)
        self.assertTrue(report['read_only']);self.assertEqual(report['candidate_count'],1)
        self.assertEqual(report['candidates'][0]['summary_ids'],['summary'])
        self.assertEqual(rows,before)

class RecruitmentYearTests(unittest.TestCase):
    def test_reused_link_with_a_different_deadline_year_stays_separate(self):
        c=MemoryNotion();c.upsert(ls(deadline='2026-11-29'))
        self.assertEqual(c.upsert(ls(deadline='2027-11-29'))[0],'신규')
        self.assertEqual(len(c.rows),2)

class UncertainCreateTests(unittest.TestCase):
    def test_lost_create_response_blocks_another_source_from_creating_again(self):
        class LostResponseNotion(MemoryNotion):
            def __init__(self):
                super().__init__();self.creates=0
            def request(self,method,path,payload=None):
                if path.endswith('/query'):return {'results':[],'has_more':False}
                result=super().request(method,path,payload)
                if method=='POST' and path=='pages':
                    self.creates+=1
                    if self.creates==1:raise NotionError('응답 확인 실패')
                return result
        c=LostResponseNotion()
        with self.assertRaises(NotionError):c.upsert(ls())
        with self.assertRaises(NotionError):c.upsert(ls(source='잡코리아 신입',url=JK))
        self.assertEqual(c.creates,1);self.assertEqual(len(c.rows),1)
        self.assertEqual(c.upsert(ls(OTHER))[0],'신규')
        self.assertEqual(len(c.rows),2)

class AppliedCompanyTests(unittest.TestCase):
    def test_applied_company_new_role_is_skipped_across_verified_alias(self):
        c=MemoryNotion();c.upsert(ls());row=c.rows[0]
        row['properties']['지원 상태']={'status':{'name':'지원 완료'}}
        row['body']='지원 완료 본문과 메모'
        before=copy.deepcopy(row)
        action,_=c.upsert(ls(OTHER,source='잡코리아 신입',url=JK,company='엘에스아이티씨㈜'))
        self.assertEqual(action,'지원 회사 제외')
        self.assertEqual(c.rows,[before])
        self.assertEqual(c.upsert(ls(source='잡코리아 신입',url=JK))[0],'갱신')
        self.assertEqual(c.rows[0]['body'],before['body'])
        self.assertEqual(c.rows[0]['properties']['지원 상태'],before['properties']['지원 상태'])

    def test_other_companies_and_not_yet_applied_roles_are_still_saved(self):
        c=MemoryNotion();c.upsert(ls())
        self.assertEqual(c.upsert(ls(OTHER))[0],'신규')
        c.rows[0]['properties']['지원 상태']={'status':{'name':'지원 완료'}}
        self.assertEqual(c.upsert(posting(company='다른 회사',url='https://example.org/another'))[0],'신규')
        # 지원 완료 상태가 없어지면 회사의 다른 공고도 다시 수집할 수 있다.
        c.rows[0]['properties']['지원 상태']={'status':{'name':'검토 전'}}
        self.assertEqual(c.upsert(ls('AI 개발 다른 차수',url='https://www.jobkorea.co.kr/Recruit/GI_Read/99999'))[0],'신규')

    def test_save_summary_reports_applied_company_skips(self):
        c=MemoryNotion();c.upsert(ls());c.rows[0]['properties']['지원 상태']={'status':{'name':'지원 완료'}}
        out=StringIO()
        with redirect_stdout(out):save_postings([ls(OTHER)],c)
        self.assertIn('지원 회사 제외 1건',out.getvalue())
        self.assertEqual(len(c.rows),1)
