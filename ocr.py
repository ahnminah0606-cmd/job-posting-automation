"""채용 상세 이미지의 한국어/영어 OCR. 이미지나 토큰을 외부 AI 서비스에 보내지 않는다."""

import base64
import csv
import hashlib
from functools import lru_cache
import html as html_module
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from PIL import Image, ImageOps

CACHE = Path(__file__).with_name(".cache") / "ocr"
VERSION = "v2"
EVENTS = []


def snapshot():
    return list(EVENTS)
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000


class OCRError(RuntimeError):
    pass


def engine():
    if shutil.which("tesseract"):
        return "tesseract"
    if platform.system() == "Darwin" and shutil.which("clang"):
        return "vision"
    raise OCRError("OCR 엔진 없음: Tesseract와 한국어·영어 언어 데이터를 설치하세요.")


def check_engine():
    name = engine()
    if name == "tesseract":
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=15)
        if result.returncode or not {"kor", "eng"} <= set(result.stdout.split()):
            raise OCRError("Tesseract의 kor·eng 언어 데이터가 필요합니다.")
    if name == "vision":
        prepare_vision()
    return name


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


def tesseract_lines(path, width, height):
    result = subprocess.run(["tesseract", str(path), "stdout", "-l", "kor+eng", "--psm", "3", "tsv"],
                            capture_output=True, text=True, timeout=90,
                            env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    if result.returncode:
        raise OCRError("Tesseract 이미지 판독 실패")
    groups = {}
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
        value = (row.get("text") or "").strip()
        if row.get("level") != "5" or not value or float(row["conf"]) < 0:
            continue
        key = (row["block_num"], row["par_num"], row["line_num"])
        groups.setdefault(key, []).append(row)
    lines = []
    for words in groups.values():
        x, y = min(int(w["left"]) for w in words), min(int(w["top"]) for w in words)
        right = max(int(w["left"]) + int(w["width"]) for w in words)
        bottom = max(int(w["top"]) + int(w["height"]) for w in words)
        lines.append(dict(text=" ".join(w["text"] for w in words),
                          confidence=sum(float(w["conf"]) for w in words) / (100 * len(words)),
                          x=x / width, y=y / height, width=(right - x) / width, height=(bottom - y) / height))
    return lines


def prepare_vision():
    CACHE.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("macos_ocr.m")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    binary = CACHE / ("vision-" + digest)
    if not binary.exists():
        pending = binary.with_suffix("." + str(os.getpid()) + ".tmp")
        result = subprocess.run(["clang", "-fobjc-arc", "-fno-modules", "-framework", "Foundation",
                                 "-framework", "Vision", "-framework", "CoreGraphics", str(source),
                                 "-o", str(pending)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise OCRError("macOS OCR 엔진 준비 실패")
        pending.replace(binary)
    return binary


def vision_lines(path):
    binary = prepare_vision()
    result = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise OCRError("macOS 이미지 판독 실패")
    return json.loads(result.stdout)


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
            chunk = tesseract_lines(path, part.width, part.height) if name == "tesseract" else vision_lines(path)
            for line in chunk:
                line["y"] = (top + line["y"] * part.height) / image.height
                line["height"] = line["height"] * part.height / image.height
                if not any(line["text"] == old["text"] and abs(line["y"] - old["y"]) < .015 for old in lines):
                    lines.append(line)
            if bottom == image.height:
                break
    lines.sort(key=lambda line: (round(line["y"], 2), line["x"]))
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


def split_ocr_roles(html):
    """각각 제목·업무·자격을 갖춘 별도 직무 포스터만 분리한다. 표의 행은 추정하지 않는다."""
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
