# -*- coding: utf-8 -*-
"""레이아웃 PDF + 문제 원고 -> 편집 가능한 HWPX

- PDF 벡터 도형을 HWPX 네이티브 도형으로 옮긴다 (래스터화 0회)
- 문제 텍스트는 진짜 텍스트, 수식은 <hp:script> 문자열
- 한글 프로그램을 띄우지 않는다

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
"""
import fitz, json, os, re, shutil, sys, zipfile

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
            # 'c'(베지어)는 이번 대상 페이지에 없다. 있으면 LINE 근사가 필요하다.

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
                            "s": s, "size": sp["size"], "color": "#%06X" % sp.get("color", 0)})
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


def write_hwpx(template, section_xml, out_path):
    """템플릿 hwpx의 나머지 엔트리는 그대로 두고 section0.xml만 갈아끼운다."""
    zin = zipfile.ZipFile(template, "r")
    if os.path.exists(out_path):
        os.remove(out_path)
    zout = zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "Contents/section0.xml":
            data = section_xml.encode("utf-8")
        if item.filename == "mimetype":
            zi = zipfile.ZipInfo("mimetype")
            zi.compress_type = zipfile.ZIP_STORED
            zout.writestr(zi, data)
        else:
            zout.writestr(item.filename, data)
    zout.close()
    zin.close()


# ---------------------------------------------------------------- 5. 실행
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    scratch = r"C:\Users\dbwns\AppData\Local\Temp\claude\C--Users-dbwns\3518c5f8-e4ac-4813-b221-b03d83aef551\scratchpad"
    SRC = r"C:\Users\dbwns\OneDrive\문서\카카오톡 받은 파일\박진성 선생님 교재 5 (2).pdf"
    TEMPLATE = os.path.join(scratch, "hwpx_base", "SimpleRectangle.hwpx")
    OUT = os.path.join(here, "out", "교재5p3_문제채움.hwpx")
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
