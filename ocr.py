"""채용 상세 이미지의 한국어/영어 OCR. 이미지나 토큰을 외부 AI 서비스에 보내지 않는다."""

import base64
import hashlib
from functools import lru_cache
import html as html_module
import io
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from PIL import Image, ImageOps

CACHE = Path(__file__).with_name(".cache") / "ocr"
VERSION = "v4"
EVENTS = []


def snapshot():
    return list(EVENTS)
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000


class OCRError(RuntimeError):
    pass


def engine():
    return "rapidocr-ppocrv5-korean"


@lru_cache(maxsize=1)
def prepare_engine():
    from rapidocr import RapidOCR, EngineType, ModelType, OCRVersion
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        return RapidOCR(params={
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.ocr_version": OCRVersion.PPOCRV4,
            "Det.model_type": ModelType.MOBILE,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": "korean",
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Global.model_root_dir": str((CACHE / "models").resolve()),
            "Global.log_level": "warning",
            "Global.use_cls": False,
            "Global.max_side_len": 3000,
            "EngineConfig.onnxruntime.intra_op_num_threads": 1,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })
    except Exception as error:
        raise OCRError("한국어 OCR 모델 준비 실패: " + type(error).__name__) from None


def check_engine():
    prepare_engine()
    return engine()


@lru_cache(maxsize=32)
def image_bytes(url, base_url):
    url = urljoin(base_url, url)
    if url.startswith("data:image/") and ";base64," in url:
        raw = base64.b64decode(url.split(",", 1)[1], validate=True)
    else:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise OCRError("유효한 공개 이미지 주소가 아님")
        if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
            raise OCRError("로컬 이미지 주소는 다운로드하지 않음")
        headers = {"User-Agent": "Mozilla/5.0", "Referer": base_url}
        with urlopen(Request(url, headers=headers), timeout=25) as response:
            raw = response.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise OCRError("이미지가 20MB 한도를 초과함")
    return raw


def recognize_lines(path, width, height):
    result = prepare_engine()(str(path))
    if result.txts is None or result.boxes is None:
        return []
    lines = []
    for box, value, confidence in zip(result.boxes, result.txts, result.scores):
        xs, ys = box[:, 0], box[:, 1]
        lines.append(dict(text=value, confidence=float(confidence),
                          x=float(min(xs)) / width, y=float(min(ys)) / height,
                          width=float(max(xs) - min(xs)) / width,
                          height=float(max(ys) - min(ys)) / height))
    return lines


def reading_order(lines):
    """같은 행의 왼쪽 항목명→오른쪽 값을 읽고 다음 행으로 이동한다."""
    rows = []
    for line in sorted(lines, key=lambda item: item["y"] + item["height"] / 2):
        center = line["y"] + line["height"] / 2
        if rows and abs(center - rows[-1][0]) <= min(line["height"], rows[-1][1]) * .55:
            rows[-1][2].append(line)
            rows[-1][1] = min(rows[-1][1], line["height"])
        else:
            rows.append([center, line["height"], [line]])
    return [line for _, _, row in rows for line in sorted(row, key=lambda item: item["x"])]


def recognize(raw):
    name = engine()
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(VERSION.encode() + name.encode() + raw).hexdigest()
    cached = CACHE / (key + ".json")
    if cached.exists():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    try:
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > MAX_PIXELS:
            raise OCRError("이미지 해상도가 5천만 픽셀 한도를 초과함")
        if image.width < 180 or image.height < 70:
            return dict(text="", lines=[], confidence=0, engine=name, key=key, skipped="small-image")
        image = ImageOps.exif_transpose(image).convert("RGBA")
        white = Image.new("RGBA", image.size, "white")
        white.alpha_composite(image)
        image = white.convert("RGB")
        scale = max(1, min(2, 1400 / image.width))
        if scale > 1:
            image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise OCRError("이미지 파일을 열 수 없음") from error
    lines = []
    with tempfile.TemporaryDirectory(prefix="job-ocr-") as tmp:
        # 긴 공고를 겹치는 구간으로 나눠 OCR의 누락과 메모리 사용을 줄인다.
        for top in range(0, image.height, 2200):
            bottom = min(image.height, top + 2400)
            part = image.crop((0, top, image.width, bottom))
            path = Path(tmp) / f"{top}.png"
            part.save(path)
            chunk = recognize_lines(path, part.width, part.height)
            for line in chunk:
                line["y"] = (top + line["y"] * part.height) / image.height
                line["height"] = line["height"] * part.height / image.height
                if not any(line["text"] == old["text"] and abs(line["y"] - old["y"]) < max(line["height"], old["height"]) * .8 and abs(line["x"] - old["x"]) < .03 for old in lines):
                    lines.append(line)
            if bottom == image.height:
                break
    lines = reading_order(lines)
    value = "\n".join(line["text"] for line in lines)
    confidence = sum(line["confidence"] * len(line["text"]) for line in lines) / max(1, sum(len(line["text"]) for line in lines))
    document = dict(text=value, confidence=confidence, lines=lines, engine=name, key=key)
    cached.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return document


def enrich_html(html, base_url=""):
    """상세요강 내부 이미지에만 OCR을 적용하고 위치·신뢰도를 보고서용 HTML에 보존한다."""
    soup = BeautifulSoup(html, "html.parser")
    images = list(soup.select("img"))
    for image in images:
        src = image.get("data-src") or image.get("data-original") or image.get("src")
        if not src or src.lower().split("?")[0].endswith(".svg"):
            continue
        try:
            document = recognize(image_bytes(src, base_url))
        except Exception as error:
            EVENTS.append(dict(url=urljoin(base_url, src), error=type(error).__name__))
            raise OCRError("상세요강 이미지 OCR 실패: " + str(error).splitlines()[0][:160]) from None
        EVENTS.append(dict(url=urljoin(base_url, src), key=document["key"], engine=document["engine"], confidence=round(document["confidence"], 3), lines=len(document["lines"]), skipped=document.get("skipped")))
        if not document["text"].strip():
            if document.get("skipped"):
                image.decompose()
                continue
            raise OCRError("상세요강 이미지에서 문자를 읽지 못함: 검토 필요")
        if document["confidence"] < .60:
            raise OCRError(f"이미지 OCR 신뢰도 부족 ({document['confidence']:.0%})")
        block = soup.new_tag("section")
        block["data-ocr"] = document["key"]
        block["data-ocr-confidence"] = str(round(document["confidence"], 3))
        for line in document["lines"]:
            p = soup.new_tag("p")
            p["data-y"] = str(line["y"])
            p.string = line["text"]
            block.append(p)
        image.replace_with(block)
    return str(soup)


def scope_ocr_role(html, role, roles):
    """OCR에서 직무 이름을 찾고 다음 직무 이름 전까지 명확한 구획만 잘라낸다."""
    compact = lambda value: re.sub(r"[^가-힣a-zA-Z0-9]", "", value).lower()
    target = compact(role)
    soup = BeautifulSoup(html, "html.parser")
    lines = soup.select("section[data-ocr] p[data-y]")
    other = {compact(value) for value in roles if compact(value) != target}
    start = next((i for i, line in enumerate(lines) if target and target in compact(line.get_text())
                  and not any(value and value in compact(line.get_text()) for value in other)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines))
                if any(value and value in compact(lines[i].get_text()) for value in other)), len(lines))
    selected = lines[start:end]
    if len(selected) < 3:
        return ""
    content = "\n".join(line.get_text() for line in selected)
    # 공통 지원자격이 명시된 경우는 해당 직무에도 함께 적용한다.
    full_text = soup.get_text("\n", strip=True)
    common = re.search(r"(?:공통\s*지원\s*자격|공통\s*자격\s*요건)([\s\S]{0,1500})", full_text)
    if common:
        content += "\n지원자격\n" + common[1]
    if not re.search(r"담당\s*업무|주요\s*업무|수행\s*업무", content):
        # 표에서 역할별 행은 찾았지만 업무 컬럼을 식별하지 못하면 추정하지 않는다.
        return ""
    return "<section>" + "".join("<p>" + html_module.escape(line) + "</p>" for line in content.splitlines()) + "</section>"


def split_ocr_table(html):
    """반복된 직무명→담당업무→개별자격과 마지막 공통자격이 명시된 포스터만 분리한다."""
    soup = BeautifulSoup(html, 'html.parser')
    lines = [p.get_text(' ', strip=True) for p in soup.select('section[data-ocr] p[data-y]')]
    full = '\n'.join(lines)
    if not re.search(r'모집\s*(?:직무|부문|분야)', full):
        return []
    headings = []
    for index, line in enumerate(lines):
        match = re.search(r'담당\s*업무', line)
        if not match:
            continue
        prefix = line[:match.start()].strip(' •·*-[]')
        title = prefix or (lines[index - 1] if index else '')
        if not 2 <= len(title) <= 60 or re.search(r'요건|자격|우대|필수|[。:：]|^[-•0-9]', title):
            return []
        headings.append((index if prefix else index - 1, title))
    common = next((i for i, line in enumerate(lines) if re.search(r'공통\s*(?:사항|자격)', line)), None)
    if len(headings) < 2 or len({title for _, title in headings}) != len(headings) or common is None or common <= headings[-1][0]:
        return []
    stop = next((i for i in range(common + 1, len(lines)) if re.search(r'채용\s*프로세스|전형\s*절차|지원\s*방법|모집\s*기간', lines[i])), len(lines))
    shared = lines[common:stop]
    if not re.search(r'자격|요건', '\n'.join(shared)):
        return []
    roles = []
    for i, (start, title) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else common
        content = lines[start:end]
        value = '\n'.join(content)
        if not re.search(r'필수\s*요건|지원\s*자격|자격\s*요건', value) or not re.search(r'우대\s*사항', value):
            return []
        content += ['지원자격', *shared]
        body = '<section>' + ''.join('<p>' + html_module.escape(value) + '</p>' for value in content) + '</section>'
        roles.append((title, body))
    return roles


def split_ocr_roles(html):
    """각각 제목·업무·자격을 갖춘 별도 직무 포스터만 분리한다. 표의 행은 추정하지 않는다."""
    table_roles = split_ocr_table(html)
    if table_roles:
        return table_roles
    soup = BeautifulSoup(html, 'html.parser')
    sections = soup.select('section[data-ocr]')
    roles, unassigned = [], []
    for section in sections:
        lines = [p.get_text(' ', strip=True) for p in section.select('p')]
        value = '\n'.join(lines)
        title = lines[0] if lines else ''
        # 신입 표기가 있는 구체적인 직무 헤더와 자격요건이 한 이미지에 모두 있어야 한다.
        named = re.search(r'신입|경력|인턴', title) and re.search(r'엔지니어|Engineer|개발|설계|검증|공정|연구|기술|분석|데이터|품질|AI|SW', title, re.I)
        if named and re.search(r'담당\s*업무|주요\s*업무|수행\s*업무', value) and re.search(r'지원\s*자격|자격\s*요건', value):
            roles.append((title, str(section)))
        else:
            unassigned.append(value)
    # 로고 외 별도 자격 이미지 또는 공통 요강이 있으면 통째로 재검토한다.
    if len(roles) < 2 or any(len(value) > 80 for value in unassigned):
        return []
    for section in sections:
        section.decompose()
    if len(soup.get_text(' ', strip=True)) > 200 or re.search(r'공통|지원\s*자격|자격\s*요건', soup.get_text()):
        return []
    return roles
