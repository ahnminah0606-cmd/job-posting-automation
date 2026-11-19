"""공개 채용 목록/상세 어댑터. 로그인·이미지 OCR·추천 문구는 판정에 사용하지 않는다."""

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, unquote_plus, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor

from bs4 import BeautifulSoup
from notion_sync import make_posting, deadline_from_text


NEW_SITES = {
    "saramin-home": ("사람인 홈", "https://www.saramin.co.kr/zf_user/"),
    "saramin-kangso": ("사람인 강소기업", "https://www.saramin.co.kr/zf_user/jobs/theme/kangso"),
    "jobkorea": ("잡코리아 신입", "https://www.jobkorea.co.kr/starter/"),
    "jasoseol": ("자소설닷컴", "https://jasoseol.com/search"),
    "egong": ("이공계모야", "https://egongmoya.letuin.com/CommunityBoard/list/11"),
    "catch": ("캐치", "https://www.catch.co.kr/NCS/RecruitSearch"),
}


class CollectionError(RuntimeError):
    pass


class PublicReader:
    def __init__(self, interval=0.5):
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.cache = {}
        self.interval = interval

    def read(self, url, data=None, referer=None):
        key = (url, data)
        if key in self.cache:
            return self.cache[key]
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}
        if referer:
            headers.update({"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
        for attempt in range(4):
            time.sleep(self.interval)
            try:
                with self.opener.open(Request(url, data=data, headers=headers), timeout=25) as response:
                    raw = response.read()
                    charset = response.headers.get_content_charset() or "utf-8"
                break
            except HTTPError as error:
                if error.code not in {429, 502, 503, 504} or attempt == 3:
                    raise
                retry = error.headers.get("Retry-After")
                try:
                    delay = float(retry) if retry else 5 * (2 ** attempt)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        delay = 5 * (2 ** attempt)
                if delay > 60:
                    raise CollectionError("서버 요청 대기시간이 60초를 초과해 이번 공고는 다음 실행으로 넘김") from None
                time.sleep(max(1, delay))
        text = raw.decode(charset, errors="replace")
        self.cache[key] = text
        return text

    def soup(self, url, **kwargs):
        return BeautifulSoup(self.read(url, **kwargs), "html.parser")

    def json(self, url):
        return json.loads(self.read(url))


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def iso_deadline(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(timezone(timedelta(hours=9)))
        return dt.date().isoformat()
    except (ValueError, TypeError):
        return None


def job_schema(soup):
    def walk(value):
        if isinstance(value, dict):
            types = value.get("@type", [])
            if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
                yield value
            for item in value.values():
                if isinstance(item, (dict, list)):
                    yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def next_props(soup):
    script = soup.select_one("#__NEXT_DATA__")
    if not script:
        raise CollectionError("Next.js 공개 공고 데이터를 찾을 수 없음")
    return json.loads(script.string)["props"]["pageProps"]


def qualification(title, career, education=""):
    from fetch_page import excluded_qualification
    for value in (title, career, education):
        if excluded_qualification(value):
            return "자격 제외", value
    if not re.search(r"신입|^무관$", career.strip()):
        return "자격 제외", "신입 지원 근거 부족 | " + (career or "표시 없음")
    return None


def classify_body(title, html, industry=""):
    from fetch_page import classify_loofit_jd
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script,style,nav,footer"):
        tag.decompose()
    # 고정 양식의 경력 항목명은 실제 입력값과 구분한다.
    for label in list(soup.select("dt,th,td")):
        if text(label).replace(" ", "") in {"경력", "신입/경력", "경력구분"}:
            value_node = label.find_next_sibling(["dd", "td"])
            if text(value_node) in {"신입", "무관"}:
                label.decompose()
    value = text(soup)
    if len(value) < 40 or not re.search(r"담당\s*업무|주요\s*업무|직무\s*(내용|소개)|지원\s*자격|자격\s*요건|수행\s*업무", value):
        return "수집 제외", "상세 요강 텍스트/직무 구획 미확인 (이미지·첨부파일 공고 포함)"
    return classify_loofit_jd(title, str(soup), industry)


def scoped_body(html, role):
    """다직무 공고를 한 행으로 섞지 않도록 직무가 명시된 최소 구획만 사용한다."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(string=lambda s: s and role.strip() == s.strip()):
        for parent in node.parents:
            if parent.name in {"tr", "section", "article", "li"} and len(text(parent)) > len(role) + 30:
                return str(parent)
    return ""


def labelled(soup, label):
    for dt in soup.select("dt"):
        if text(dt).replace(" ", "") == label:
            return text(dt.find_next_sibling("dd"))
    return ""


def listing_cards(key, soup):
    pattern = r"rec_idx=(\d+)" if key.startswith("saramin") else r"/Recruit/GI_Read/(\d+)"
    cards = []
    seen = set()
    for anchor in soup.select("a[href]"):
        match = re.search(pattern, anchor["href"], re.I)
        if not match or match[1] in seen:
            continue
        if key.startswith("saramin"):
            card = anchor.find_parent(class_="box_item") or anchor.find_parent("li") or anchor
            company = text(card.select_one(".c_name,.corp,.company_nm,.corp_name"))
            title = text(anchor.select_one(".title,.tit")) or anchor.get("title", "") or text(anchor)
            career = text(card.select_one(".career"))
            if not career and card.select_one("ul.desc"):
                career = " ".join(text(x) for x in card.select("ul.desc li")[1:2])
            url = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=" + match[1]
        else:
            card = anchor.find_parent("li") or anchor.parent
            company = text(card.select_one(".coLink"))
            title = anchor.get("title") or text(anchor)
            career = text(card.select_one(".sDesc strong"))
            url = "https://www.jobkorea.co.kr/Recruit/GI_Read/" + match[1]
        if not title:
            continue
        seen.add(match[1])
        cards.append(dict(id=match[1], company=company, title=title, career=career, url=url))
    return cards


def saramin_detail(reader, card):
    base = "https://www.saramin.co.kr"
    reader.read(card["url"])
    soup = reader.soup(base + "/zf_user/jobs/relay/view-ajax",
                       data=urlencode({"rec_idx": card["id"], "rec_seq": 0,
                                       "view_type": "mail_landing", "t_ref": "non-logged_relay_view",
                                       "t_ref_content": "category_new_rec"}).encode(), referer=card["url"])
    company = text(soup.select_one(".jv_header .company,.jv_header .corp_name")) or card["company"]
    title = text(soup.select_one("h1.tit_job")) or card["title"]
    career = labelled(soup, "경력")
    decision = qualification(title, career, labelled(soup, "학력"))
    if decision:
        return company, title, decision, None
    frame = soup.select_one('iframe[id^="iframe_content_"][src]')
    if not frame:
        raise CollectionError("사람인 상세요강 iframe 없음")
    html = reader.read(urljoin(base, frame["src"]), referer=card["url"])
    deadline = deadline_from_text("마감일 " + labelled(soup, "마감일"))
    return company, title, classify_body(title, html, labelled(soup, "업종")), deadline


class JobkoreaBrowser:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.page = self.browser.new_page()
        self.page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "font", "media"} else route.continue_())
        return self

    def body(self, url):
        self.page.goto(url, wait_until="commit", timeout=30000)
        self.page.locator("iframe").first.wait_for(state="attached", timeout=15000)
        chunks = []
        # Jobkorea는 상세요강을 about:blank iframe에 주입한다. 추천 공고 본문은 읽지 않는다.
        for frame in self.page.frames[1:]:
            if frame.url not in {"", "about:blank"}:
                continue
            try:
                frame.locator("body").wait_for(timeout=10000)
                html = frame.content()
                if text(BeautifulSoup(html, "html.parser")):
                    chunks.append(html)
            except Exception:
                continue
        return "\n".join(chunks)

    def __exit__(self, *args):
        self.browser.close()
        self.pw.stop()


def collect_site(key, limit=50):
    name, url = NEW_SITES[key]
    reader = PublicReader(interval=1.5 if key == "catch" else 0.5)
    counts, failures = Counter(), []
    postings, audit, seen = [], [], set()
    browser = None

    def record(card, decision, company=None, title=None, deadline=None, source_id=None):
        result, evidence = decision
        company, title = company or card.get("company", ""), title or card["title"]
        if result in {"반도체", "AX", "반도체×AX"} and not company:
            result, evidence = "수집 제외", "회사명 미확인"
        counts[result] += 1
        audit.append(dict(id=source_id or card["id"], company=company, title=title,
                          url=card["url"], result=result, evidence=evidence))
        if result in {"반도체", "AX", "반도체×AX"}:
            # 사람인 두 진입점은 같은 사이트 ID 공간을 사용한다.
            source = "사람인" if key.startswith("saramin") else name
            postings.append(make_posting(company, title, card["url"], result, evidence, source,
                                         source_id or card["id"], deadline))
            print(f"{name} | {company} | {result} | {title}\n근거: {evidence}\n{card['url']}", flush=True)

    def process(card):
        nonlocal browser
        pre = qualification(card["title"], card.get("career", ""))
        # 모집 구분이 목록에 없는 경우 상세에서 확인한다.
        if pre and (card.get("career") or pre[1] == card["title"]):
            record(card, pre)
            return
        try:
            if key.startswith("saramin"):
                company, title, decision, deadline = saramin_detail(reader, card)
            elif key == "jobkorea":
                soup = reader.soup(card["url"])
                schema = next(job_schema(soup), None)
                if not schema:
                    raise CollectionError("JobPosting 상세 메타데이터 없음")
                title = schema.get("title") or card["title"]
                company = schema.get("hiringOrganization", {}).get("name") or card["company"]
                decision = qualification(title, str(schema.get("experienceRequirements", "")), str(schema.get("educationRequirements", "")))
                deadline = iso_deadline(schema.get("validThrough"))
                if not decision:
                    if browser is None:
                        browser = JobkoreaBrowser().__enter__()
                    decision = classify_body(title, browser.body(card["url"]))
            elif key == "catch":
                soup = reader.soup(card["url"])
                schema = next(job_schema(soup), None)
                if not schema:
                    raise CollectionError("캐치 JobPosting 상세 메타데이터 없음")
                company, title = schema["hiringOrganization"]["name"], schema["title"]
                decision = qualification(title, " ".join(schema.get("experienceRequirements", [])), str(schema.get("educationRequirements", "")))
                deadline = iso_deadline(schema.get("validThrough"))
                if not decision:
                    frame = soup.select_one('iframe[src^="/controls/recruitDetail/"]')
                    if not frame:
                        raise CollectionError("캐치 상세요강 iframe 없음")
                    decision = classify_body(title, reader.read(urljoin(url, frame["src"])))
            elif key == "egong":
                data = reader.json(card["api"])
                if data.get("code") != 1000 or data.get("data", {}).get("is_paid"):
                    raise CollectionError("공개 상세 접근 불가")
                view = data["data"].get("view", {})
                if view.get("is_secret") == "y":
                    raise CollectionError("비공개 공고")
                company, title, deadline = card["company"], card["title"], None
                decision = classify_body(title, unquote_plus(view.get("content", "")))
            else:
                raise CollectionError("지원하지 않는 수집기")
            record(card, decision, company, title, deadline)
        except Exception as error:
            reason = f"상세 수집 실패 | {type(error).__name__}: {str(error).splitlines()[0][:200]}"
            failures.append(reason)
            record(card, ("수집 제외", reason))

    pages_read = 0
    try:
        if key in {"saramin-home", "saramin-kangso", "jobkorea"}:
            cards = listing_cards(key, reader.soup(url))
            if not cards:
                raise CollectionError("목록에서 개별 공고 링크를 읽지 못함")
            pages_read = 1
            for card in cards[:limit]:
                process(card)
        elif key == "jasoseol":
            for page in range(1, 6):
                props = next_props(reader.soup(url + "?page=" + str(page)))
                queries = props.get("dehydratedState", {}).get("queries", [])
                query = next((q for q in queries if q.get("queryKey", [None])[0] == "jobSearch"), None)
                if not query or int(query["queryKey"][1]["page"]) != page:
                    raise CollectionError("자소설 검색 페이지 데이터/페이지 번호 불일치")
                cards = query["state"]["data"]["data"]
                if not cards:
                    if not pages_read:
                        raise CollectionError("목록 공고 0건: 빈 검색 결과 확인 필요")
                    break
                pages_read += 1
                for item in cards:
                    if item["id"] in seen:
                        continue
                    if len(seen) >= limit:
                        break
                    seen.add(item["id"])
                    card = dict(id=str(item["id"]), title=item["title"], company=item["name"], url=f"https://jasoseol.com/recruit/{item['id']}")
                    try:
                        details = next_props(reader.soup(card["url"]))["initialEmploymentCompany"]
                        roles = details.get("employments") or []
                        if not roles:
                            raise CollectionError("모집 직무 데이터 없음")
                        html = details.get("content", "")
                        for role in roles:
                            # 상세 JSON의 division 1은 화면의 신입, 2는 경력에 대응한다.
                            division = role.get("division")
                            career = "신입" if division == 1 else ("경력" if division == 2 else "신입/경력" if division == 3 else "")
                            title = role.get("field") or card["title"]
                            decision = qualification(card["title"] + " " + title, career)
                            body = scoped_body(html, title) if len(roles) > 1 else html
                            decision = decision or classify_body(title, body)
                            record(card, decision, title=title, deadline=iso_deadline(details.get("end_time")), source_id=f"{item['id']}:{role['id']}")
                    except Exception as error:
                        failures.append(f"자소설 상세 {item['id']}: {type(error).__name__}")
                        record(card, ("수집 제외", failures[-1]))
                if len(seen) >= limit:
                    break
        elif key in {"catch", "egong"}:
            for page in range(1, 6):
                if key == "catch":
                    params = dict(Keyword="", JobCode="", Sido="", Career="", JCode="", Size="", EduLevel="", WorkPosition="", CompID="", GroupCode="", Sort=0, curpage=page, pageSize=30, onRecruitYN="Y", ExceptIDList="")
                    data = reader.json("https://www.catch.co.kr/api/v1.0/recruit/information/getRecruitList?" + urlencode(params))
                    items = data.get("recruitData")
                    if not isinstance(items, list):
                        raise CollectionError("캐치 공개 목록 형식 변경")
                    cards = [dict(id=str(i["RecruitID"]), title=i["RecruitTitle"], company=i["CompName"], career=i.get("CareerGubunCode", ""), url=f"https://www.catch.co.kr/NCS/RecruitInfoDetails/{i['RecruitID']}") for i in items if not i.get("IsProduct")]
                else:
                    data = reader.json(f"https://egongmoya.letuin.com/api/board/CommunityBoard/list/11?page={page}")
                    if data.get("code") != 1000:
                        raise CollectionError("이공계모야 공개 목록 접근 실패")
                    items = data.get("data", {}).get("list")
                    if not isinstance(items, list):
                        raise CollectionError("이공계모야 목록 형식 변경")
                    cards = []
                    for i in items:
                        if i.get("is_notice") == "y" or i.get("need_login") == "y":
                            continue
                        match = re.search(r"【(.+?)】", i["title"])
                        path = f"/CommunityBoard/view/{i['year']}/{i['board_no']}/{i['no']}"
                        cards.append(dict(id=i["no"], title=i["title"], company=match[1] if match else "", career="신입" if "신입" in i["title"] else "", url=urljoin(url, path), api="https://egongmoya.letuin.com/api/board" + path))
                if not items:
                    if not pages_read:
                        raise CollectionError("목록 공고 0건: 사이트 확인 필요")
                    break
                pages_read += 1
                for card in cards:
                    if card["id"] in seen:
                        continue
                    if len(seen) >= limit:
                        break
                    seen.add(card["id"])
                    process(card)
                if len(seen) >= limit:
                    break
    except Exception as error:
        failures.append(f"목록 수집 실패 | {type(error).__name__}: {str(error).splitlines()[0][:200]}")
    finally:
        if browser:
            browser.__exit__()
    report = dict(site=name, pages=pages_read, postings_seen=sum(counts.values()),
                  counts=dict(counts), failures=failures, audit=audit,
                  status="failed" if failures else "success")
    print(f"{name} | 목록 {pages_read}페이지 | 직무 {sum(counts.values())}건 | 관심 {len(postings)}건 | " + " | ".join(f"{k} {v}건" for k, v in counts.items()), flush=True)
    for failure in failures:
        print(f"{name} | 오류: {failure}", flush=True)
    return postings, report
