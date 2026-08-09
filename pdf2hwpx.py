# -*- coding: utf-8 -*-
"""레이아웃 PDF + 문제 원고 -> 편집 가능한 HWPX

- PDF 벡터 도형을 HWPX 네이티브 도형으로 옮긴다 (래스터화 0회)
- 문제 텍스트는 진짜 텍스트, 수식은 <hp:script> 문자열
- 한글 프로그램을 띄우지 않는다

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
"""
import fitz, json, os, re, shutil, sys, zipfile


# ---------------------------------------------------------------- 경로
def resource_path(*parts):
    """번들 안의 읽기 전용 자원. PyInstaller로 묶어도 찾을 수 있다."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def work_dir():
    """산출물을 쓸 곳. exe면 exe 옆, 스크립트면 소스 옆."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def template_path():
    return resource_path("resources", "base.hwpx")


# ---------------------------------------------------------------- 단위
PT = 100                      # 1pt = 100 HWPUNIT (정확)
MM = 283.465


def hu(pt_val):
    """pt -> HWPUNIT 정수"""
    return int(round(pt_val * PT))


def rgb(c):
    if c is None:
        return None
    return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in c[:3])


# ---------------------------------------------------------------- 1. 레이아웃 추출
def extract_layout(pdf_path, pageno, clip=None):
    """PDF 한 면에서 도형과 원본 텍스트를 뽑는다.
    clip=(x0,y0,x1,y1)이면 그 영역만. 판정은 도형 중심 기준이라 옆면 도형이 안 딸려온다."""
    doc = fitz.open(pdf_path)
    page = doc[pageno]
    ox, oy = (clip[0], clip[1]) if clip else (0, 0)

    def inside(x0, x1):
        cx = (x0 + x1) / 2.0
        return clip[0] - 1 <= cx <= clip[2] + 1

    out = []
    for g in page.get_drawings():
        fill = rgb(g.get("fill"))
        stroke = rgb(g.get("color"))
        lw = g.get("width") or 0
        # 곡선이 섞인 path는 통째로 curve로 옮긴다. 쪼개면 모양이 무너진다.
        if any(it[0] == "c" for it in g["items"]):
            r = g["rect"]
            if clip and not inside(r.x0, r.x1):
                continue
            pts = [(px - ox, py - oy) for px, py in flatten_path(g["items"])]
            if len(pts) >= 2:
                out.append({"k": "curve", "pts": pts, "fill": fill, "stroke": stroke,
                            "lw": lw, "close": bool(g.get("closePath"))})
            continue
        for it in g["items"]:
            if it[0] == "re":
                q = it[1]
                if clip and not inside(q.x0, q.x1):
                    continue
                out.append({"k": "rect", "x": q.x0 - ox, "y": q.y0 - oy,
                            "w": q.width, "h": q.height,
                            "fill": fill, "stroke": stroke, "lw": lw})
            elif it[0] == "l":
                p1, p2 = it[1], it[2]
                if clip and not inside(p1.x, p2.x):
                    continue
                out.append({"k": "line", "x1": p1.x - ox, "y1": p1.y - oy,
                            "x2": p2.x - ox, "y2": p2.y - oy,
                            "stroke": stroke or fill, "lw": lw})

    # 원본에 박혀 있던 텍스트(문제번호 등)도 그대로 옮긴다
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                s = sp["text"]
                if not s.strip():
                    continue
                bb = sp["bbox"]
                if clip and not inside(bb[0], bb[2]):
                    continue
                out.append({"k": "text", "x": bb[0] - ox, "y": bb[1] - oy,
                            "w": bb[2] - bb[0], "h": bb[3] - bb[1],
                            "s": s, "size": sp["size"],
                            "color": span_color(sp.get("color", 0)),
                            "font": sp.get("font", ""),
                            "italic": bool(sp.get("flags", 0) & 2)})
    doc.close()
    return out


# ---------------------------------------------------------------- 2. 도형 XML
_ID = [1100000000]


def _nid():
    _ID[0] += 7
    return _ID[0]


def _common_head(w, h):
    return (
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="%d" height="%d"/>'
        '<hp:curSz width="%d" height="%d"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="%d" centerY="%d" rotateimage="1"/>'
        '<hp:renderingInfo>'
        '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '</hp:renderingInfo>' % (w, h, w, h, w // 2, h // 2))


def _line_shape(color, lw, style="SOLID"):
    if color is None:
        return ('<hp:lineShape color="#000000" width="0" style="NONE" endCap="FLAT"'
                ' headStyle="NORMAL" tailStyle="NORMAL" headfill="1" tailfill="1"'
                ' headSz="MEDIUM_MEDIUM" tailSz="MEDIUM_MEDIUM" outlineStyle="NORMAL" alpha="0"/>')
    return ('<hp:lineShape color="%s" width="%d" style="%s" endCap="FLAT"'
            ' headStyle="NORMAL" tailStyle="NORMAL" headfill="1" tailfill="1"'
            ' headSz="MEDIUM_MEDIUM" tailSz="MEDIUM_MEDIUM" outlineStyle="NORMAL" alpha="0"/>'
            % (color, max(hu(lw), 1), style))


def _fill(color):
    if color is None:
        return ''
    return ('<hc:fillBrush><hc:winBrush faceColor="%s" hatchColor="#D8D8D8" alpha="0"/>'
            '</hc:fillBrush>' % color)


def _pos(x, y):
    return ('<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="1"'
            ' holdAnchorAndSO="0" vertRelTo="PAPER" horzRelTo="PAPER"'
            ' vertAlign="TOP" horzAlign="LEFT" vertOffset="%d" horzOffset="%d"/>' % (hu(y), hu(x)))


def rect_xml(x, y, w, h, fill=None, stroke=None, lw=0, ratio=0, z=0, inner=None):
    W, H = max(hu(w), 1), max(hu(h), 1)
    drawtext = ''
    if inner is not None:
        drawtext = ('<hp:drawText lastWidth="%d" name="" editable="0">'
                    '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP"'
                    ' linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"'
                    ' hasTextRef="0" hasNumRef="0">%s</hp:subList>'
                    '<hp:textMargin left="0" right="0" top="0" bottom="0"/></hp:drawText>'
                    % (W, inner))
    return (
        '<hp:rect id="%d" zOrder="%d" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0"'
        ' instid="%d" ratio="%d">%s%s%s'
        '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>%s'
        '<hc:pt0 x="0" y="0"/><hc:pt1 x="%d" y="0"/><hc:pt2 x="%d" y="%d"/><hc:pt3 x="0" y="%d"/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '%s<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:shapeComment>사각형입니다.</hp:shapeComment></hp:rect>'
        % (_nid(), z, _nid(), ratio, _common_head(W, H),
           _line_shape(stroke, lw), _fill(fill), drawtext,
           W, W, H, H, W, H, _pos(x, y)))


def flatten_path(items, steps=12):
    """PDF path를 점 목록으로 편다. 3차 베지어는 직선으로 쪼갠다.
    HWPX의 <hp:seg>에는 제어점이 없어서 근사가 불가피하다."""
    pts = []

    def push(p):
        if not pts or abs(pts[-1][0] - p[0]) > 0.01 or abs(pts[-1][1] - p[1]) > 0.01:
            pts.append((p[0], p[1]))

    for it in items:
        if it[0] == "l":
            push((it[1].x, it[1].y)); push((it[2].x, it[2].y))
        elif it[0] == "c":
            p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
            push((p0.x, p0.y))
            for s in range(1, steps + 1):
                t = s / float(steps)
                u = 1.0 - t
                a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
                push((a * p0.x + b * p1.x + c * p2.x + d * p3.x,
                      a * p0.y + b * p1.y + c * p2.y + d * p3.y))
        elif it[0] == "re":
            r = it[1]
            for p in ((r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)):
                push(p)
        elif it[0] == "qu":
            q = it[1]
            for p in (q.ul, q.ur, q.lr, q.ll, q.ul):
                push((p.x, p.y))
    return pts


def curve_xml(pts, fill=None, stroke=None, lw=0, close=False, z=0):
    """점 목록을 <hp:curve>로. 세그먼트는 전부 LINE이다."""
    if len(pts) < 2:
        return ""
    p = list(pts)
    if close and (abs(p[0][0] - p[-1][0]) > 0.01 or abs(p[0][1] - p[-1][1]) > 0.01):
        p.append(p[0])
    xs = [q[0] for q in p]
    ys = [q[1] for q in p]
    x0, y0 = min(xs), min(ys)
    W, H = max(hu(max(xs) - x0), 1), max(hu(max(ys) - y0), 1)
    segs = []
    for i in range(len(p) - 1):
        segs.append('<hp:seg type="LINE" x1="%d" y1="%d" x2="%d" y2="%d"/>'
                    % (hu(p[i][0] - x0), hu(p[i][1] - y0),
                       hu(p[i + 1][0] - x0), hu(p[i + 1][1] - y0)))
    return (
        '<hp:curve id="%d" zOrder="%d" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0"'
        ' instid="%d">%s%s%s'
        '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>%s'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '%s<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:shapeComment>곡선입니다.</hp:shapeComment></hp:curve>'
        % (_nid(), z, _nid(), _common_head(W, H),
           _line_shape(stroke, lw), _fill(fill), "".join(segs), W, H, _pos(x0, y0)))


def line_xml(x1, y1, x2, y2, stroke="#000000", lw=0.5, z=0):
    x, y = min(x1, x2), min(y1, y2)
    W, H = max(hu(abs(x2 - x1)), 1), max(hu(abs(y2 - y1)), 1)
    sx, sy = hu(x1 - x), hu(y1 - y)
    ex, ey = hu(x2 - x), hu(y2 - y)
    return (
        '<hp:line id="%d" zOrder="%d" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0"'
        ' instid="%d" isReverseHV="0">%s%s'
        '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>'
        '<hc:startPt x="%d" y="%d"/><hc:endPt x="%d" y="%d"/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '%s<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:shapeComment>선입니다.</hp:shapeComment></hp:line>'
        % (_nid(), z, _nid(), _common_head(W, H), _line_shape(stroke, lw),
           sx, sy, ex, ey, W, H, _pos(x, y)))


# ---------------------------------------------------------------- 3. 텍스트와 수식
def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------- 글자모양
# 굵기가 이름에 흡수되는 폰트. Windows GDI 패밀리 이름이 따로 잡히는 것들이다.
# Regular와 Bold만 한 패밀리를 공유하고, Light/Medium 같은 중간 굵기는
# 각자 독립 패밀리라 face에 굵기를 넣고 bold 플래그는 켜지 않는다.
FONT_ALIAS = {
    "NanumMyeongjoExtraBold": ("나눔명조 ExtraBold", False),
    "NanumMyeongjoBold": ("나눔명조", True),
    "NanumMyeongjo": ("나눔명조", False),
    "NanumGothicBold": ("나눔고딕", True),
    "NanumGothic": ("나눔고딕", False),
    "NEXONLv1GothicOTFRegular": ("NEXON Lv1 Gothic OTF", False),
    "NEXONLv1GothicOTFBold": ("NEXON Lv1 Gothic OTF Bold", False),
    "MalgunGothic": ("맑은 고딕", False),
}

WEIGHTS = ("ExtraLight", "SemiBold", "ExtraBold", "UltraLight", "Regular",
           "Medium", "Light", "Bold", "Thin", "Black", "Heavy", "Normal")


def normalize_font(name):
    """PDF 폰트 이름 -> (한글에 넣을 face 이름, bold 플래그)."""
    if not name:
        return "함초롬바탕", False
    n = re.sub(r"^[A-Z]{6}\+", "", name)          # 서브셋 접두사 제거
    n = n.split(",")[0]
    if n in FONT_ALIAS:
        return FONT_ALIAS[n]
    base, weight = n, ""
    m = re.match(r"^(.*?)[-_ ]?(" + "|".join(WEIGHTS) + r")$", n)
    if m:
        base, weight = m.group(1), m.group(2)
    base = base.rstrip("-_ ")
    if base in FONT_ALIAS:
        fam, _ = FONT_ALIAS[base]
        base = fam
    if weight in ("", "Regular", "Normal"):
        return base, False
    if weight == "Bold":
        return base, True                          # RIBBI 짝이라 플래그로 표현
    return "%s %s" % (base, weight), False         # 나머지는 독립 패밀리


def span_color(c):
    return "#%06X" % (int(c) & 0xFFFFFF)


class StyleTable:
    """수집한 글자모양을 header.xml에 넣을 수 있게 모은다."""

    LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")

    def __init__(self, base_charpr_count):
        self.fonts = []                # face 이름 순서 목록
        self.styles = {}               # key -> charPr id
        self.rows = []                 # (id, fontidx, height, color, bold, italic)
        self.next_id = base_charpr_count

    def font_index(self, face):
        if face not in self.fonts:
            self.fonts.append(face)
        return self.fonts.index(face)

    def get(self, face, bold, size_pt, color="#000000", italic=False):
        height = int(round(float(size_pt) * 100))
        key = (face, bold, height, color, italic)
        if key in self.styles:
            return self.styles[key]
        cid = self.next_id
        self.next_id += 1
        self.styles[key] = cid
        self.rows.append((cid, self.font_index(face), height, color, bold, italic))
        return cid

    def from_span(self, font, size_pt, color=0, italic=False):
        face, bold = normalize_font(font)
        return self.get(face, bold, size_pt, span_color(color), italic)

    # ---- header.xml 갱신
    def font_xml(self, start_id):
        return "".join(
            '<hh:font id="%d" face="%s" type="TTF" isEmbedded="0"/>' % (start_id + i, esc(f))
            for i, f in enumerate(self.fonts))

    def charpr_xml(self, border_fill_ref, font_base):
        out = []
        for cid, fi, height, color, bold, italic in self.rows:
            fid = font_base + fi
            ref = " ".join('%s="%d"' % (l.lower(), fid) for l in
                           ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"))
            pct = lambda v: " ".join('%s="%d"' % (l.lower(), v) for l in
                                     ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"))
            out.append(
                '<hh:charPr id="%d" height="%d" textColor="%s" shadeColor="none"'
                ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="%s">'
                '<hh:fontRef %s/><hh:ratio %s/><hh:spacing %s/><hh:relSz %s/><hh:offset %s/>'
                '%s%s</hh:charPr>'
                % (cid, height, color, border_fill_ref, ref,
                   pct(100), pct(0), pct(100), pct(0),
                   "<hh:italic/>" if italic else "",
                   "<hh:bold/>" if bold else ""))
        return "".join(out)


def patch_header(header_xml, table):
    """템플릿 header.xml에 폰트와 글자모양을 덧붙인다."""
    if not table.rows:
        return header_xml
    s = header_xml

    # 언어군마다 폰트를 같은 목록으로 추가한다. 언어군별로 id 공간이 따로 논다.
    first_cnt = None
    def add_fonts(m):
        nonlocal first_cnt
        head, cnt, body = m.group(1), int(m.group(2)), m.group(3)
        if first_cnt is None:
            first_cnt = cnt
        return ('%s fontCnt="%d">%s%s</hh:fontface>'
                % (head, cnt + len(table.fonts), body, table.font_xml(cnt)))

    s = re.sub(r'(<hh:fontface\b[^>]*?)\s*fontCnt="(\d+)"\s*>(.*?)</hh:fontface>',
               add_fonts, s, flags=re.S)
    font_base = first_cnt if first_cnt is not None else 0

    # borderFill 참조는 기존 charPr에서 쓰는 값을 그대로 빌린다
    m = re.search(r'borderFillIDRef="(\d+)"', s)
    bf = m.group(1) if m else "1"

    def add_charprs(m2):
        cnt = int(m2.group(1))
        return ('<hh:charProperties itemCnt="%d">%s%s</hh:charProperties>'
                % (cnt + len(table.rows), m2.group(2), table.charpr_xml(bf, font_base)))

    s = re.sub(r'<hh:charProperties itemCnt="(\d+)">(.*?)</hh:charProperties>',
               add_charprs, s, flags=re.S)
    return s


def eq_size(script):
    """수식 상자 크기 추정. 분수·적분·합이 있으면 높이를 키운다."""
    tall = any(k in script for k in ("over", "int", "sum", "sqrt", "lim", "atop", "prod"))
    h = 3000 if tall else 1400
    w = max(int(len(script) * 78), 1200)
    return w, h


def eq_xml(script):
    w, h = eq_size(script)
    return (
        '<hp:equation id="%d" zOrder="0" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" version="Equation Version 60"'
        ' baseLine="85" textColor="#000000" baseUnit="1000" lineMode="CHAR" font="HYhwpEQ">'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0"'
        ' holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT"'
        ' vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="56" right="56" top="0" bottom="0"/>'
        '<hp:shapeComment>수식입니다.</hp:shapeComment>'
        '<hp:script>%s</hp:script></hp:equation>' % (_nid(), w, h, esc(script)))


def paras_from_parts(parts, char_pr=0, para_pr=3, width_hu=25000):
    """parts -> 문단 XML 목록. br로 문단을 끊는다."""
    paras, cur = [], []

    def flush():
        body = "".join(cur) if cur else "<hp:t/>"
        paras.append(
            '<hp:p id="0" paraPrIDRef="%d" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            '<hp:run charPrIDRef="%d">%s</hp:run>'
            '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000"'
            ' baseline="850" spacing="600" horzpos="0" horzsize="%d" flags="393216"/>'
            '</hp:linesegarray></hp:p>' % (para_pr, char_pr, body, width_hu))
        cur.clear()

    for p in parts:
        if p.get("br"):
            flush()
        elif "eq" in p:
            cur.append(eq_xml(p["eq"]))
        else:
            cur.append("<hp:t>%s</hp:t>" % esc(p["t"]))
    flush()
    return "".join(paras)


# ---------------------------------------------------------------- 4. HWPX 조립
NS = ('xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
      'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
      'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
      'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
      'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
      'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
      'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
      'xmlns:dc="http://purl.org/dc/elements/1.1/" '
      'xmlns:opf="http://www.idpf.org/2007/opf/" '
      'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
      'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
      'xmlns:epub="http://www.idpf.org/2007/ops" '
      'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"')


def build_section(shapes_xml, page_w_pt, page_h_pt):
    secpr = (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000"'
        ' tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0"'
        ' textVerticalWidthHead="0" masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0"'
        ' border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0"'
        ' showLineNumber="0"/>'
        '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
        '<hp:pagePr landscape="WIDELY" width="%d" height="%d" gutterType="LEFT_ONLY">'
        '<hp:margin header="0" footer="0" gutter="0" left="0" right="0" top="0" bottom="0"/>'
        '</hp:pagePr>'
        '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
        ' supscript="0"/><hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hp:noteSpacing betweenNotes="850" belowLine="567" aboveLine="850"/>'
        '<hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="EACH_COLUMN"'
        ' beneathText="0"/></hp:footNotePr>'
        '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
        ' supscript="0"/><hp:noteLine length="14692344" type="SOLID" width="0.12 mm"'
        ' color="#000000"/><hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
        '<hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="END_OF_DOCUMENT"'
        ' beneathText="0"/></hp:endNotePr>'
        '<hp:pageBorderFill type="BOTH"><hp:offset left="1417" right="1417" top="1417"'
        ' bottom="1417"/></hp:pageBorderFill>'
        '<hp:pageBorderFill type="EVEN"><hp:offset left="1417" right="1417" top="1417"'
        ' bottom="1417"/></hp:pageBorderFill>'
        '<hp:pageBorderFill type="ODD"><hp:offset left="1417" right="1417" top="1417"'
        ' bottom="1417"/></hp:pageBorderFill></hp:secPr>'
        % (hu(page_w_pt), hu(page_h_pt)))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            '<hs:sec %s>'
            '<hp:p id="1" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            '<hp:run charPrIDRef="0">%s%s<hp:t/></hp:run>'
            '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000"'
            ' baseline="850" spacing="600" horzpos="0" horzsize="%d" flags="393216"/>'
            '</hp:linesegarray></hp:p></hs:sec>'
            % (NS, secpr, shapes_xml, hu(page_w_pt)))


def base_charpr_count(template):
    """템플릿에 이미 정의된 글자모양 개수. 새 id는 그 다음부터 매긴다."""
    try:
        h = zipfile.ZipFile(template).read("Contents/header.xml").decode("utf-8")
        m = re.search(r'<hh:charProperties itemCnt="(\d+)"', h)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def write_hwpx(template, section_xml, out_path, style_table=None):
    """템플릿 hwpx에서 section0.xml을 갈아끼우고, 글자모양이 있으면 header.xml도 고친다."""
    zin = zipfile.ZipFile(template, "r")
    if os.path.exists(out_path):
        os.remove(out_path)
    zout = zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "Contents/section0.xml":
            data = section_xml.encode("utf-8")
        elif item.filename == "Contents/header.xml" and style_table is not None:
            data = patch_header(data.decode("utf-8"), style_table).encode("utf-8")
        if item.filename == "mimetype":
            zi = zipfile.ZipInfo("mimetype")
            zi.compress_type = zipfile.ZIP_STORED
            zout.writestr(zi, data)
        else:
            zout.writestr(item.filename, data)
    zout.close()
    zin.close()


# ---------------------------------------------------------------- 5. 실행
def main(src=None):
    here = work_dir()
    SRC = src or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not SRC:
        print("사용법: python pdf2hwpx.py <레이아웃PDF경로>")
        print("GUI로 쓰려면 python gui.py")
        return None
    TEMPLATE = template_path()
    OUT = os.path.join(here, "out", "문제채움.hwpx")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    # 교재5 3쪽 우면(문제 4개 그리드). A3 스프레드의 오른쪽 절반.
    HALF = 595.276
    PAGE_W, PAGE_H = 595.276, 841.89
    clip = (HALF, 0, HALF * 2, PAGE_H)

    print("[1] 레이아웃 추출")
    shapes = extract_layout(SRC, 2, clip)
    n_rect = sum(1 for s in shapes if s["k"] == "rect")
    n_line = sum(1 for s in shapes if s["k"] == "line")
    print("    사각형 %d개, 직선 %d개 (래스터화 0회)" % (n_rect, n_line))

    xml = []
    z = 0
    for s in shapes:
        if s["k"] == "rect":
            xml.append(rect_xml(s["x"], s["y"], s["w"], s["h"],
                                fill=s["fill"], stroke=s["stroke"], lw=s["lw"], z=z))
        elif s["k"] == "line":
            xml.append(line_xml(s["x1"], s["y1"], s["x2"], s["y2"],
                                stroke=s["stroke"] or "#000000", lw=s["lw"] or 0.5, z=z))
        else:  # 원본 텍스트(문제번호 등)를 투명 글상자로 그 자리에 재현
            inner = paras_from_parts([{"t": s["s"]}], width_hu=hu(s["w"] + 8))
            xml.append(rect_xml(s["x"] - 1, s["y"] - 2, s["w"] + 8, s["h"] + 6,
                                fill=None, stroke=None, lw=0, z=z, inner=inner))
        z += 1

    print("[2] 문제 슬롯 계산")
    # 헤더 바 4개(파란색, h≈25.1)를 찾아 그 아래를 본문 슬롯으로 잡는다
    bars = sorted([s for s in shapes
                   if s["k"] == "rect" and 240 < s["w"] < 270 and 20 < s["h"] < 30],
                  key=lambda s: (s["y"], s["x"]))
    print("    검출된 문제 헤더 바 %d개" % len(bars))
    slots = []
    for i, b in enumerate(bars):
        top = b["y"] + b["h"] + 8
        below = [c["y"] for c in bars if c["y"] > b["y"] + 5 and abs(c["x"] - b["x"]) < 20]
        bottom = (min(below) - 14) if below else (PAGE_H - 40)
        slots.append((b["x"] + 10, top, b["w"] - 20, bottom - top))
        print("    슬롯 %d: x=%.1f y=%.1f w=%.1f h=%.1f pt" % (i, slots[-1][0], slots[-1][1],
                                                              slots[-1][2], slots[-1][3]))

    print("[3] 문제 원고 주입")
    data = json.load(open(os.path.join(here, "problems.json"), encoding="utf-8"))
    n_eq = 0
    for prob in data["problems"]:
        si = prob["slot"]
        if si >= len(slots):
            print("    슬롯 %d 없음, 건너뜀" % si)
            continue
        x, y, w, h = slots[si]
        inner = paras_from_parts(prob["parts"], width_hu=hu(w))
        n_eq += sum(1 for p in prob["parts"] if "eq" in p)
        xml.append(rect_xml(x, y, w, h, fill=None, stroke=None, lw=0, z=z, inner=inner))
        z += 1
        print("    문제 %s -> 슬롯 %d" % (prob["no"], si))
    print("    수식 %d개 삽입" % n_eq)

    print("[4] HWPX 조립")
    section = build_section("".join(xml), PAGE_W, PAGE_H)
    write_hwpx(TEMPLATE, section, OUT)
    print("    저장: %s  (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))
    return OUT


if __name__ == "__main__":
    main()
