# -*- coding: utf-8 -*-
"""실제 강사 원고(hwpx)에서 문항을 뽑는다.

받아 본 물화브릿지 교재 30개를 열어 보니 번호로 자르는 방식이 통하지 않았다.
문제 본문에 "1." 같은 번호가 아예 없다. 대신 이런 구조였다.

  <hp:tbl colCnt="2">          문항 표. 행 하나가 문제 하나다
    <hp:tr>
      <hp:tc>  (빈 칸)         번호가 들어갈 자리. 비어 있다
      <hp:tc>  본문 + 그림      문제 내용
  <hp:tbl colCnt="3~5">        바로 뒤에 오는 선택지 표
    <hp:tr><hp:tc>①</hp:tc><hp:tc>...</hp:tc>

그래서 표 구조로 자른다. 그림은 BinData에 bmp로 들어 있고 pic 요소가
binaryItemIDRef 로 가리킨다. 꺼내서 png로 줄여 쓴다.
"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"

EQ_MARK = ""
IMG_MARK = ""

# 선택지 표를 알아보는 표시
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def _sections(z):
    names = [n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)]
    names.sort(key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    return names


def _para_bits(p, imgs):
    """문단 하나를 (글, 수식목록, 그림목록)으로. 직계 run 만 본다."""
    text, eqs, pics = [], [], []
    for run in p.findall(HP + "run"):
        for el in run:
            if el.tag == HP + "t":
                if el.text:
                    text.append(el.text)
                for sub in el:
                    if sub.tag == HP + "tab":
                        text.append("\t")
                    if sub.tail:
                        text.append(sub.tail)
            elif el.tag == HP + "tab":
                text.append("\t")
            elif el.tag == HP + "equation":
                sc = el.find(HP + "script")
                eqs.append(sc.text or "" if sc is not None else "")
                text.append(EQ_MARK)
            elif el.tag == HP + "pic":
                ref = None
                for q in el.iter():
                    if q.tag.endswith("}img"):
                        ref = q.get("binaryItemIDRef")
                        break
                if ref:
                    # 원고에 그림 크기가 이미 적혀 있다. 그걸 버리고 파일만
                    # 가져오면 크기를 다시 정해야 한다. HWPUNIT 은 1pt 가 100
                    sz = el.find(HP + "sz")
                    wpt = 0.0
                    if sz is not None:
                        try:
                            wpt = float(sz.get("width", 0)) / 100.0
                        except Exception:
                            wpt = 0.0
                    # 글자처럼 취급하지 않는 그림은 본문 옆에 붙는다.
                    # 원고가 정한 쪽을 그대로 따른다
                    side = ""
                    pos = el.find(HP + "pos")
                    if pos is not None and pos.get("treatAsChar") == "0":
                        al = (pos.get("horzAlign") or "").upper()
                        if al == "RIGHT":
                            side = "r"
                        elif al == "LEFT":
                            side = "l"
                    pics.append((ref, wpt, side))
                    text.append(IMG_MARK)
    return "".join(text), eqs, pics


def _cell_paras(tc):
    """셀 안의 문단들. 셀 안에 또 표가 있으면 그 표는 따로 다룬다."""
    out = []
    for sub in tc.findall(HP + "subList"):
        for p in sub.findall(HP + "p"):
            out.append(p)
    return out


def _tbl_of(p):
    for run in p.findall(HP + "run"):
        t = run.find(HP + "tbl")
        if t is not None:
            return t
    return None


def _is_problem_table(tbl):
    """문항 표인가. 두 칸짜리이고 첫 칸이 비어 있으면 그렇다.

    첫 칸은 번호 자리다. 디자인에서 번호를 넣기 때문에 원고에는 비어 있다."""
    rows = tbl.findall(HP + "tr")
    if not rows:
        return False
    if (tbl.get("colCnt") or "") not in ("2",):
        return False
    empty_first = 0
    for tr in rows:
        cells = tr.findall(HP + "tc")
        if len(cells) < 2:
            return False
        head = "".join(t.text or "" for t in cells[0].iter(HP + "t")).strip()
        if not head or head in CIRCLED:
            empty_first += 1
    return empty_first >= max(len(rows) - 1, 1)


def _flat_table(tbl, imgs):
    """선택지나 자료 표를 줄글로 편다. 우리 조판기에 표가 없어서다."""
    lines = []
    for tr in tbl.findall(HP + "tr"):
        bits = []
        for tc in tr.findall(HP + "tc"):
            chunks = []
            for p in _cell_paras(tc):
                s, eqs, pics = _para_bits(p, imgs)
                chunks.append(_restore(s, eqs, pics, imgs))
            cell = " ".join(c for c in chunks if c.strip())
            if cell.strip():
                bits.append(cell.strip())
        if bits:
            lines.append("   ".join(bits))
    return "\n".join(lines)


def _restore(text, eqs, pics, imgs):
    """자리표시자를 수식 문자열과 그림 마크업으로 되돌린다."""
    ei = pi = 0
    out = []
    for ch in text:
        if ch == EQ_MARK:
            out.append("$%s$" % (eqs[ei] if ei < len(eqs) else ""))
            ei += 1
        elif ch == IMG_MARK:
            item = pics[pi] if pi < len(pics) else None
            pi += 1
            if isinstance(item, tuple):
                ref, wpt, side = (tuple(item) + ("",))[:3]
            else:
                ref, wpt, side = item, 0.0, ""
            path = imgs.get(ref)
            if path:
                # 원고 판면을 A4에서 좌우 여백을 뺀 450pt로 보고 비율을 낸다.
                # 크기를 안 적어 주면 칸 폭에 맞춰 늘어나 원고보다 커진다
                pct = int(round(min(max(wpt / 450.0 * 100.0, 12), 99))) if wpt else 0
                tail = "|%d" % pct if pct else ""
                if side:
                    # 원고가 본문 옆에 붙여 둔 그림이다. 그 쪽을 그대로 따른다
                    tail = (tail or "|40") + "|" + side
                out.append("\n[[img:%s%s]]\n" % (path, tail))
        else:
            out.append(ch)
    return "".join(out)


def extract_images(path, outdir):
    """BinData의 그림을 꺼내 png로 저장한다. {참조이름: 경로}"""
    got = {}
    try:
        from PIL import Image
    except ImportError:
        Image = None
    z = zipfile.ZipFile(path)
    os.makedirs(outdir, exist_ok=True)
    for n in z.namelist():
        if not n.startswith("BinData/"):
            continue
        base = os.path.splitext(os.path.basename(n))[0]
        ext = os.path.splitext(n)[1].lower()
        dst = os.path.join(outdir, base + ".png")
        try:
            data = z.read(n)
            if Image is not None and ext in (".bmp", ".png", ".jpg", ".jpeg", ".gif"):
                import io
                # bmp 는 무압축이라 그대로 두면 파일이 크다. png 로 줄인다
                im = Image.open(io.BytesIO(data))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(dst, optimize=True)
            else:
                dst = os.path.join(outdir, os.path.basename(n))
                open(dst, "wb").write(data)
            got[base] = dst
        except Exception:
            continue
    z.close()
    return got


def body_font(path):
    """원고가 쓰는 본문 글꼴과 크기. 가장 많이 쓰인 글자 모양을 고른다.

    강사가 원고에서 쓴 글꼴이 있는데 우리가 임의로 정할 이유가 없다."""
    try:
        z = zipfile.ZipFile(path)
        head = ET.fromstring(z.read("Contents/header.xml"))
        faces = {}
        for fa in head.iter(HH + "fontface"):
            for fo in fa.iter(HH + "font"):
                faces[fo.get("id")] = fo.get("face")
        cps = {}
        for c in head.iter(HH + "charPr"):
            fr = c.find(HH + "fontRef")
            cps[c.get("id")] = (c.get("height"),
                                faces.get(fr.get("hangul")) if fr is not None else None)
        use = {}
        for name in _sections(z):
            root = ET.fromstring(z.read(name))
            for r in root.iter(HP + "run"):
                if r.find(HP + "t") is not None:
                    k = r.get("charPrIDRef")
                    use[k] = use.get(k, 0) + 1
        z.close()
        if not use:
            return None
        best = max(use.items(), key=lambda kv: kv[1])[0]
        hgt, face = cps.get(best, (None, None))
        return (face, float(hgt) / 100.0 if hgt else 0.0)
    except Exception:
        return None


def load(path, imgdir=""):
    """원고 -> [{no, parts}] . 표 구조로 문항을 나눈다.

    문항 표를 만나면 그 행 하나하나가 새 문제다. 그 뒤에 오는 선택지 표와
    문단은 직전 문제에 붙는다."""
    if not imgdir:
        imgdir = os.path.join(os.path.dirname(os.path.abspath(path)), "_원고그림")
    imgs = extract_images(path, imgdir)

    z = zipfile.ZipFile(path)
    chunks = []          # 문제마다 글 조각 목록

    def add(s):
        if s and s.strip() and chunks:
            chunks[-1].append(s.rstrip())

    for name in _sections(z):
        try:
            root = ET.fromstring(z.read(name))
        except Exception:
            continue
        for p in root:
            if p.tag != HP + "p":
                continue
            tbl = _tbl_of(p)
            if tbl is None:
                s, eqs, pics = _para_bits(p, imgs)
                add(_restore(s, eqs, pics, imgs))
                continue
            if _is_problem_table(tbl):
                for tr in tbl.findall(HP + "tr"):
                    cells = tr.findall(HP + "tc")
                    if len(cells) < 2:
                        continue
                    chunks.append([])
                    body = cells[1]
                    for q in _cell_paras(body):
                        inner = _tbl_of(q)
                        if inner is not None:
                            add(_flat_table(inner, imgs))
                            continue
                        s, eqs, pics = _para_bits(q, imgs)
                        add(_restore(s, eqs, pics, imgs))
            else:
                add(_flat_table(tbl, imgs))
    z.close()

    out = []
    for i, c in enumerate(chunks):
        body = "\n".join(x for x in c if x.strip())
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if body:
            out.append({"no": str(i + 1), "parts": [{"raw": body}]})
    return out


def looks_like_problem_tables(path):
    """이 파일이 표로 짜인 원고인지. 아니면 예전 방식으로 읽는다."""
    try:
        z = zipfile.ZipFile(path)
        for name in _sections(z):
            root = ET.fromstring(z.read(name))
            for p in root:
                if p.tag != HP + "p":
                    continue
                t = _tbl_of(p)
                if t is not None and _is_problem_table(t):
                    z.close()
                    return True
        z.close()
    except Exception:
        pass
    return False
