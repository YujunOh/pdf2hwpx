# -*- coding: utf-8 -*-
"""인쇄용 PDF를 만든다. 원본 디자인을 뜯지 않는다.

원본 페이지를 통째로 벡터 상태로 깔고 그 위에 강사 글만 얹는다. 도형을
다시 그리지 않으므로 클리핑, 투명도, 그라데이션, 소프트 마스크, CMYK,
임베드 폰트가 전부 원본 그대로 남는다. 굽는 단계가 없어서 dpi를 고를
일도 없다.

채운 칸의 옛 글자만 redaction으로 뺀다. 이 원고의 PDF는 글자를 벡터
외곽선으로도 그려 두어서 텍스트 레이어만 지우면 외곽선이 남는다.
칸에 완전히 덮인 벡터까지 지운다.
"""
import os
import re

import fitz

import preview as pv

# 넘칠 때 줄여 볼 크기
STEPS = (10.5, 10.0, 9.5, 9.0, 8.5, 8.0)
FALLBACK = r"C:\Windows\Fonts\malgun.ttf"
MATH = r"C:\Windows\Fonts\times.ttf"
MATH_I = r"C:\Windows\Fonts\timesi.ttf"


def installed_fonts():
    """설치된 한글 폰트를 {보여줄 이름: 파일경로} 로. 레지스트리에서 읽는다.

    원본 PDF에서 폰트 이름을 읽을 수 없는 경우가 많다. PDFium을 거친 파일은
    글자가 이름 없는 Type3로 들어와서 무슨 폰트였는지 알 길이 없다. 그래서
    사람이 고르게 한다."""
    out = {}
    try:
        import winreg
    except ImportError:
        return {"맑은 고딕": FALLBACK}
    root = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    user = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE,
                       r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                      (winreg.HKEY_CURRENT_USER,
                       r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")):
        try:
            k = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            if not isinstance(val, str) or not val.lower().endswith((".ttf", ".otf")):
                continue
            path = val if os.path.isabs(val) else os.path.join(root, val)
            if not os.path.exists(path) and user:
                path = os.path.join(user, os.path.basename(val))
            if not os.path.exists(path):
                continue
            # "맑은 고딕 (TrueType)" 에서 괄호를 뗀다
            label = re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", name).strip()
            out.setdefault(label, path)
        winreg.CloseKey(k)
    if not out:
        out["맑은 고딕"] = FALLBACK
    return out


def korean_fonts():
    """한글 글자가 실제로 들어 있는 것만 남긴다. 목록이 400개면 못 고른다."""
    ok = {}
    for label, path in installed_fonts().items():
        try:
            f = fitz.Font(fontfile=path)
            if f.has_glyph(ord("한")) and f.has_glyph(ord("긿")):
                ok[label] = path
        except Exception:
            continue
    return ok


def font_file(name=""):
    """이름이나 경로로 폰트 파일을 찾는다. 못 찾으면 맑은 고딕."""
    if name and os.path.exists(name):
        return name
    if name:
        table = installed_fonts()
        if name in table:
            return table[name]
        low = name.lower()
        for label, path in table.items():
            if label.lower() == low:
                return path
        # Tk는 "Pretendard" 로 부르는데 레지스트리에는 "Pretendard Regular" 로
        # 들어 있다. 보통 굵기를 먼저 찾는다. 그냥 앞글자만 맞춰 고르면
        # Black이 먼저 걸려서 본문이 새까맣게 나온다
        for suffix in (" regular", " medium", " book", " light"):
            for label, path in table.items():
                if label.lower() == low + suffix:
                    return path
        for label, path in sorted(table.items()):
            if label.lower().startswith(low + " "):
                return path
    return FALLBACK if os.path.exists(FALLBACK) else None


def rgb(h):
    h = (h or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


_FONTS = {}


class PdfFont:
    """preview가 기대하는 폰트 흉내. 폭을 재고 실물 폰트를 들고 있다."""

    def __init__(self, path, px):
        self.path, self.px = path, px
        if path not in _FONTS:
            _FONTS[path] = fitz.Font(fontfile=path)
        self.face = _FONTS[path]

    def measure(self, s):
        return self.face.text_length(s, fontsize=self.px)


class PdfCanvas:
    """preview.render_parts가 쓰는 캔버스 흉내. PDF 페이지에 그린다.

    화면과 같은 조판 엔진을 거치므로 미리보기에서 본 대로 인쇄물이 나온다.

    글자는 TextWriter로 쓴다. insert_text는 페이지의 기존 폰트 자원을 훑다가
    원본에 있는 Type3 폰트에서 죽는다. TextWriter는 그 경로를 타지 않는다.
    insert_textbox도 쓰지 않는다. 사각형을 넘치는 글을 경고 없이 버려서
    문제 하나가 통째로 사라질 수 있다."""

    def __init__(self, page):
        self.page = page
        self._cache = {}
        self._tw = {}            # 색깔별로 따로 모은다

    def font_for(self, path, px):
        key = (path, round(px, 2))
        if key not in self._cache:
            self._cache[key] = PdfFont(path, px)
        return self._cache[key]

    def mkfont(self, px, italic=False, roman=False):
        return self.font_for(MATH_I if italic else MATH, px)

    def create_text(self, x, y, text="", anchor="sw", font=None, fill="#111111", tags=()):
        if not text or not text.strip():
            return
        tw = self._tw.get(fill)
        if tw is None:
            tw = self._tw[fill] = fitz.TextWriter(self.page.rect)
        tw.append(fitz.Point(x, y), text, font=font.face, fontsize=font.px)

    def create_line(self, x1, y1, x2, y2, fill="#111111", tags=(), width=0.7):
        self.page.draw_line(fitz.Point(x1, y1), fitz.Point(x2, y2),
                            color=rgb(fill), width=width)

    def flush(self):
        for color, tw in self._tw.items():
            tw.write_text(self.page, color=rgb(color))
        self._tw.clear()


def wipe(page, boxes):
    """칸 안의 옛 내용을 지운다. 지울 게 없으면 아무것도 안 한다."""
    if not boxes:
        return
    for r in boxes:
        page.add_redact_annot(r)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)


def build(src_path, pageno, slots, parts_of, out_path, fontpath="", pad=3.0,
          base_size=None, lh=1.55):
    """slots는 [(x, y, w, h)] pt 좌표, parts_of는 {슬롯번호: parts}.

    parts는 manuscript가 만드는 그 형식이다. {"t": 글}, {"eq": 수식}, {"br": True}.
    수식은 이미지가 아니라 벡터 글자와 선으로 그려진다.

    돌려주는 값은 (슬롯번호, 크기) 목록이다. 기본 크기로 다 들어갔으면 빈 리스트,
    크기가 0이면 제일 작게 해도 넘쳤다는 뜻이다."""
    src = fitz.open(src_path)
    page = src[pageno]

    boxes = {}
    for i, (x, y, w, h) in enumerate(slots):
        if parts_of.get(i):
            boxes[i] = fitz.Rect(x, y, x + w, y + h)
    wipe(page, list(boxes.values()))

    out = fitz.open()
    np_ = out.new_page(width=page.rect.width, height=page.rect.height)
    # 원본을 벡터 그대로 얹는다. 여기가 무손실인 지점이다
    np_.show_pdf_page(np_.rect, src, pageno)

    ff = font_file(fontpath)
    steps = STEPS
    if base_size:
        # 고른 크기에서 시작해 필요한 만큼만 줄인다
        steps = tuple(x for x in (base_size,) + STEPS if x <= base_size) or (base_size,)
    cv = PdfCanvas(np_)
    # 크기를 재 볼 곳. 같은 문서에 만들었다 지우면 페이지 참조가 무효가 된다
    scratch = fitz.open()
    probe = PdfCanvas(scratch.new_page(width=page.rect.width, height=page.rect.height))
    shrunk = []
    for i, rect in boxes.items():
        parts = parts_of[i]
        for size in steps:
            # 먼저 재 본다. 넘치면 그리지 않고 한 단계 줄인다
            end = pv.render_parts(probe, parts, rect.x0 + pad, rect.y0 + pad,
                                  rect.width - pad * 2, px=size,
                                  mkfont=probe.mkfont, lh=lh,
                                  bodyfont=probe.font_for(ff, size))
            if end <= rect.y1 - pad:
                break
        else:
            size = steps[-1]
        if size != steps[0]:
            shrunk.append((i, size if end <= rect.y1 - pad else 0))
        pv.render_parts(cv, parts, rect.x0 + pad, rect.y0 + pad,
                        rect.width - pad * 2, px=size,
                        mkfont=cv.mkfont, lh=lh, bodyfont=cv.font_for(ff, size))

    cv.flush()
    # 서브셋을 안 걸면 맑은 고딕 한 벌이 통째로 들어가 9MB가 붙는다
    try:
        out.subset_fonts()
    except Exception:
        pass
    out.save(out_path, garbage=4, deflate=True, clean=True)
    out.close()
    scratch.close()
    src.close()
    return shrunk


def report(path):
    """만든 PDF가 정말 무손실인지 센다."""
    d = fitz.open(path)
    p = d[0]
    info = {
        "size_mm": (round(p.rect.width * 25.4 / 72, 1), round(p.rect.height * 25.4 / 72, 1)),
        "images": len(p.get_images(full=True)),
        "chars": len(p.get_text().strip()),
        "bytes": os.path.getsize(path),
    }
    d.close()
    return info
