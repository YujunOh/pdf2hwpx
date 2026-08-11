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


# 교재에 실제로 나오는 글자들. 이게 어긋나면 인쇄물이 틀린다.
# 괄호와 붙임표를 꼭 넣는다. OTF가 깨질 때 제일 먼저 사라지는 것들인데
# 문제마다 나온다
PROBE = "60% (2)-1 ± ≥ ① ② ㈜ ℃ ㎡"

# 한 글리프에 여러 코드포인트가 걸린 것들. 그대로 두면 화면은 멀쩡한데
# 복사하면 다른 글자가 나온다. ① 을 복사했더니 ➀ 이 나오는 식이다.
# 쓰기 전에 대표 코드포인트로 통일한다
NORMALIZE = {0x00A0: " ", 0x2206: "Δ", 0x2126: "Ω"}
for _i in range(10):                      # ➀~➉ -> ①~⑩
    NORMALIZE[0x2780 + _i] = chr(0x2460 + _i)
for _i in range(0x3163 - 0x3131 + 1):     # 반각 자모 -> 온각
    NORMALIZE[0xFFA1 + _i] = chr(0x3131 + _i)


def normalize(text):
    return text.translate(NORMALIZE)


# 글자 한 자를 찍었을 때 정상적인 잉크 비율. 맑은 고딕 0.050, Hancom 0.056,
# Pretendard TTF 0.058 이었다. 엉뚱한 글리프가 나오면 검은 배지가 그려져
# 0.19~0.21 로 뛴다. 아예 안 그려지면 0 이 된다
INK_MAX = 0.10
INK_MIN = 0.002
INK_CHARS = "%(-"        # 이 셋이면 갈린다. 여섯 자를 다 보면 두 배 느리다


def ink_ratio(path, ch):
    """이 글자를 찍었을 때 검은 픽셀이 차지하는 비율."""
    doc = fitz.open()
    page = doc.new_page(width=64, height=64)
    tw = fitz.TextWriter(page.rect)
    tw.append(fitz.Point(12, 48), ch, font=fitz.Font(fontfile=path), fontsize=36)
    tw.write_text(page)
    try:
        doc.subset_fonts()
    except Exception:
        pass
    data = doc.tobytes()
    doc.close()
    chk = fitz.open("pdf", data)
    pix = chk[0].get_pixmap(dpi=96, colorspace=fitz.csGRAY)
    chk.close()
    s = pix.samples
    return sum(1 for v in s if v < 128) / float(len(s))


def draws_ok(path):
    """글자가 제대로 그려지는지. 추출만 봐서는 못 잡는다.

    Pretendard OTF 로 여는 괄호를 찍으면 검은 배지가 그려지고 붙임표는
    아예 안 그려진다. 그런데 텍스트를 뽑아 보면 멀쩡하게 나온다. 화면과
    추출이 따로 노는 것이라 눈으로 보는 수밖에 없다."""
    try:
        for ch in INK_CHARS:
            r = ink_ratio(path, ch)
            if r > INK_MAX or r < INK_MIN:
                return False
        return True
    except Exception:
        return False


def glyphs_ok(path):
    """이 폰트로 쓴 글자가 제대로 나오는지 실제로 한 장 찍어 확인한다.

    OTF(CFF) 폰트에서 PyMuPDF의 글리프 매핑이 어긋나는 경우가 있다.
    Pretendard로 %를 쓰면 검은 Y 배지가 그려지고, 원문자 ①은 보기에는
    멀쩡한데 복사하면 ➀ 이 나온다. has_glyph만 봐서는 안 걸린다."""
    try:
        doc = fitz.open()
        page = doc.new_page()
        tw = fitz.TextWriter(page.rect)
        tw.append(fitz.Point(20, 50), PROBE, font=fitz.Font(fontfile=path), fontsize=14)
        tw.write_text(page)
        # build()가 서브셋을 걸므로 검사도 걸어야 한다. 안 걸면 검사는
        # 통과하는데 실제 출력물에서 괄호와 % 가 사라지는 폰트가 빠져나간다
        try:
            doc.subset_fonts()
        except Exception:
            pass
        got = doc.tobytes()
        doc.close()
        chk = fitz.open("pdf", got)
        back = normalize(chk[0].get_text().strip())
        chk.close()
        return back == PROBE
    except Exception:
        return False


def _cache_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fontcheck.json")


def korean_fonts(cache_dir=""):
    """쓸 수 있는 한글 폰트. {이름: (경로, 글자가 제대로 나오는가)}

    폰트마다 실제로 찍어 보므로 처음에는 30초쯤 걸린다. 판정을 파일에
    적어 두고 다음부터는 건너뛴다. 폰트가 바뀌면 크기와 시각이 달라져
    저절로 다시 잰다."""
    import json
    cpath = os.path.join(cache_dir, "fontcheck.json") if cache_dir else _cache_path()
    cache = {}
    try:
        cache = json.load(open(cpath, encoding="utf-8"))
    except Exception:
        pass

    ok, dirty = {}, False
    for label, path in installed_fonts().items():
        try:
            st = os.stat(path)
            key = "%s|%d|%d" % (path, st.st_size, int(st.st_mtime))
            if key in cache:
                if cache[key] is not None:
                    ok[label] = (path, cache[key])
                continue
            f = fitz.Font(fontfile=path)
            if not (f.has_glyph(ord("한")) and f.has_glyph(ord("긿"))):
                cache[key] = None          # 한글이 없는 폰트. 다시 재지 않는다
                dirty = True
                continue
            good = glyphs_ok(path) and draws_ok(path)
            cache[key] = good
            dirty = True
            ok[label] = (path, good)
        except Exception:
            continue
    if dirty:
        try:
            json.dump(cache, open(cpath, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception:
            pass
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
        tw.append(fitz.Point(x, y), normalize(text), font=font.face, fontsize=font.px)

    def create_line(self, x1, y1, x2, y2, fill="#111111", tags=(), width=0.7):
        self.page.draw_line(fitz.Point(x1, y1), fitz.Point(x2, y2),
                            color=rgb(fill), width=width)

    def drawimg(self, x, y, w, h, path, tags=()):
        """자료 그림. 원본 스트림을 그대로 넣는다. 다시 굽지 않는다."""
        try:
            self.page.insert_image(fitz.Rect(x, y, x + w, y + h), filename=path,
                                   keep_proportion=True)
        except Exception:
            pass

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


def slot_bg(page, rect):
    """칸 배경색. 그 안에서 가장 흔한 색을 고른다."""
    try:
        pix = page.get_pixmap(clip=rect, dpi=24, colorspace=fitz.csRGB, alpha=False)
        s, n = pix.samples, pix.n
        cnt = {}
        for i in range(0, len(s) - n + 1, n):
            k = (s[i], s[i + 1], s[i + 2])
            cnt[k] = cnt.get(k, 0) + 1
        best = max(cnt.items(), key=lambda kv: kv[1])[0]
        return tuple(v / 255.0 for v in best)
    except Exception:
        return (1.0, 1.0, 1.0)


def cover(page, rect, inset=1.2):
    """칸 안을 배경색으로 덮는다.

    redaction 은 칸에 완전히 덮인 벡터만 지운다. 칸을 살짝 넘나드는 그림은
    남아서 새 글과 겹친다. 그렇다고 닿기만 해도 지우게 하면 칸 사이 구분선
    까지 날아간다. 그래서 지우는 대신 칸 안쪽만 덮어 가린다. 테두리와
    구분선은 칸 밖이라 산다."""
    r = fitz.Rect(rect.x0 + inset, rect.y0 + inset,
                  rect.x1 - inset, rect.y1 - inset)
    if r.is_empty:
        return
    page.draw_rect(r, color=None, fill=slot_bg(page, rect), overlay=True)


# 그림을 줄이면 그 안의 축 이름과 눈금 숫자도 같이 줄어든다. 그래프의 눈금값은
# 장식이 아니라 문제를 푸는 데 읽어야 하는 정보다. Nature의 그림 지침은 그림
# 안 글자를 5pt 밑으로 내리지 말라고 못박는다. 원본 자료의 글자가 9pt라면
# 55%가 바닥이라는 뜻이다. 학원 교재는 중고등학생이 보므로 더 여유를 둔다.
IMG_MIN = 0.65
IMG_STEPS = (1.0, 0.92, 0.84, 0.76, 0.70, IMG_MIN)


def fit(probe, parts, rect, ff, steps, lh, pad, force_size=None):
    """칸에 들어가는 (글자 크기, 그림 배율, 그래도 넘치는가)를 찾는다.

    그림을 먼저 줄이고 글자는 마지막에 손댄다. force_size를 주면 글자 크기를
    그 값으로 고정하고 그림 배율만 맞춘다. 한 지면 안에서 문항마다 글자
    크기가 다르면 학생은 그 차이를 뜻으로 읽는다."""
    limit = rect.y1 - pad
    has_img = any("img" in p for p in parts)
    use = (force_size,) if force_size else steps

    def end_at(size, iscale):
        return pv.render_parts(probe, parts, rect.x0 + pad, rect.y0 + pad,
                               rect.width - pad * 2, px=size,
                               mkfont=probe.mkfont, lh=lh,
                               bodyfont=probe.font_for(ff, size),
                               iscale=iscale)

    if end_at(use[0], 1.0) <= limit:
        return use[0], 1.0, False
    if has_img:
        for iscale in IMG_STEPS[1:]:
            if end_at(use[0], iscale) <= limit:
                return use[0], iscale, False
    small = IMG_MIN if has_img else 1.0
    for size in use[1:]:
        if end_at(size, small) <= limit:
            return size, small, False
    # 여기까지 왔으면 더 줄이지 않는다. 뭉개는 대신 넘친다고 알린다
    return use[-1], small, True


def page_fit(probe, boxes, parts_of, ff, steps, lh, pad):
    """지면 전체에서 쓸 글자 크기 하나를 정한다.

    칸마다 따로 정하면 한 쪽 안에서 문항마다 크기가 달라진다. 가장 빡빡한
    칸이 요구하는 크기를 지면 전체에 똑같이 쓴다."""
    worst = steps[0]
    for i, rect in boxes.items():
        size, _, _ = fit(probe, parts_of[i], rect, ff, steps, lh, pad)
        worst = min(worst, size)
    return worst


def _boxes_of(slots, parts_of):
    boxes = {}
    for i, (x, y, w, h) in enumerate(slots):
        if parts_of.get(i):
            boxes[i] = fitz.Rect(x, y, x + w, y + h)
    return boxes


def _one_page(src, pageno, slots, parts_of, out, ff, steps, lh, pad, wiped=False):
    """원본 한 쪽을 새 문서에 얹고 그 위에 글을 그린다. 줄인 칸 목록을 돌려준다.

    wiped 면 지우기는 이미 끝난 상태다. 여러 쪽을 뽑을 때는 지우기를 다
    끝낸 뒤에 얹어야 한다. 지우기와 얹기를 번갈아 하면 MuPDF가 원본 객체
    번호를 잃고 source object number out of range 로 죽는다."""
    page = src[pageno]
    boxes = _boxes_of(slots, parts_of)
    if not wiped:
        wipe(page, list(boxes.values()))

    np_ = out.new_page(width=page.rect.width, height=page.rect.height)
    # 원본을 벡터 그대로 얹는다. 여기가 무손실인 지점이다
    np_.show_pdf_page(np_.rect, src, pageno)

    # redaction 이 못 지운 칸 안 그림을 가린다. 원본을 얹은 뒤에 해야
    # 새 문서 쪽에 덮인다
    for rect in boxes.values():
        cover(np_, rect)

    cv = PdfCanvas(np_)
    # 크기를 재 볼 곳. 같은 문서에 만들었다 지우면 페이지 참조가 무효가 된다
    scratch = fitz.open()
    probe = PdfCanvas(scratch.new_page(width=page.rect.width, height=page.rect.height))
    page_size = page_fit(probe, boxes, parts_of, ff, steps, lh, pad)
    shrunk = []
    for i, rect in boxes.items():
        parts = parts_of[i]
        size, iscale, over = fit(probe, parts, rect, ff, steps, lh, pad,
                                 force_size=page_size)
        if size != steps[0] or iscale < 1.0 or over:
            shrunk.append((i, size, iscale, over))
        pv.render_parts(cv, parts, rect.x0 + pad, rect.y0 + pad,
                        rect.width - pad * 2, px=size,
                        mkfont=cv.mkfont, lh=lh, bodyfont=cv.font_for(ff, size),
                        drawimg=cv.drawimg, iscale=iscale)
    cv.flush()
    scratch.close()
    return shrunk


def _steps_from(base_size):
    if not base_size:
        return STEPS
    return tuple(x for x in (base_size,) + STEPS if x <= base_size) or (base_size,)


def build(src_path, pageno, slots, parts_of, out_path, fontpath="", pad=4.5,
          base_size=None, lh=1.55):
    """slots는 [(x, y, w, h)] pt 좌표, parts_of는 {슬롯번호: parts}.

    parts는 manuscript가 만드는 그 형식이다. {"t": 글}, {"eq": 수식}, {"br": True}.
    수식은 이미지가 아니라 벡터 글자와 선으로 그려진다.

    돌려주는 값은 (슬롯번호, 크기, 그림배율, 넘침) 목록이다."""
    src = fitz.open(src_path)
    out = fitz.open()
    shrunk = _one_page(src, pageno, slots, parts_of, out,
                       font_file(fontpath), _steps_from(base_size), lh, pad)
    # 서브셋을 안 걸면 맑은 고딕 한 벌이 통째로 들어가 9MB가 붙는다
    try:
        out.subset_fonts()
    except Exception:
        pass
    out.save(out_path, garbage=4, deflate=True, clean=True)
    out.close()
    src.close()
    return shrunk


def build_book(src_path, jobs, out_path, fontpath="", pad=4.5,
               base_size=None, lh=1.55):
    """여러 쪽을 한 문서로 뽑는다. jobs는 [(쪽번호0based, slots, parts_of), ...].

    교재는 한 쪽짜리가 아니다. 원고를 쭉 흘려 넣고 한 번에 뽑아야 쓸모가 있다.
    문항 번호는 우리가 넣지 않는다. 디자인에 이미 박혀 있고, 원고를 순서대로
    칸에 넣으면 저절로 맞는다.

    돌려주는 값은 {쪽번호: 줄인 칸 목록} 이다."""
    src = fitz.open(src_path)
    out = fitz.open()
    ff, steps = font_file(fontpath), _steps_from(base_size)
    jobs = [j for j in jobs if 0 <= j[0] < src.page_count]

    # 지우기를 먼저 다 끝낸다. 지우기와 얹기를 번갈아 하면 MuPDF가 원본
    # 객체 번호를 잃는다
    for pageno, slots, parts_of in jobs:
        wipe(src[pageno], list(_boxes_of(slots, parts_of).values()))

    report_by_page = {}
    for pageno, slots, parts_of in jobs:
        sh = _one_page(src, pageno, slots, parts_of, out, ff, steps, lh, pad,
                       wiped=True)
        if sh:
            report_by_page[pageno] = sh
    try:
        out.subset_fonts()
    except Exception:
        pass
    out.save(out_path, garbage=4, deflate=True, clean=True)
    out.close()
    src.close()
    return report_by_page


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
