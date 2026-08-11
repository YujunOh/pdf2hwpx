# -*- coding: utf-8 -*-
"""선생님이 준 원고(hwp, hwpx, txt)에서 문항과 수식을 뽑는다.

수식은 한글 수식 스크립트 문자열 그대로 나온다. 변환하지 않는다.
그래야 출력 문서에 넣었을 때 원본 형태로 산다.

HWP 5.0 본문 파싱의 WCHAR 폭 규칙은 2025 수능 수학 문제지로 검증했다.
  문자 컨트롤 (0, 10, 13)                        1 WCHAR
  인라인 컨트롤 (4~9, 19, 20)                     8 WCHAR
  확장 컨트롤 (1,2,3,11,12,14~18,21~23)           8 WCHAR
이걸 틀리면 본문에 쓰레기 글자가 섞인다.
"""
import re, struct, zipfile

CHAR_ONLY = {0, 10, 13}
INLINE = {4, 5, 6, 7, 8, 9, 19, 20}
EXTENDED = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}

TAG_PARA_HEADER = 66
TAG_PARA_TEXT = 67
TAG_EQEDIT = 88

EQ_MARK = ""          # 본문에 수식 자리를 표시하는 임시 문자


# ---------------------------------------------------------------- HWP 5.0
def _records(data):
    pos = 0
    while pos < len(data) - 3:
        hdr = struct.unpack("<I", data[pos:pos + 4])[0]
        tag = hdr & 0x3FF
        level = (hdr >> 10) & 0x3FF
        size = (hdr >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            size = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
        yield tag, level, data[pos:pos + size]
        pos += size


def _para_text(body):
    w = [struct.unpack("<H", body[i:i + 2])[0] for i in range(0, len(body) - 1, 2)]
    out = []
    i = 0
    while i < len(w):
        c = w[i]
        if c in INLINE or c in EXTENDED:
            cid = body[i * 2 + 2:i * 2 + 6]
            try:
                name = cid.decode("ascii")[::-1].strip()
            except Exception:
                name = ""
            if c == 9:
                out.append("\t")
            elif name == "eqed":
                out.append(EQ_MARK)
            i += 8
        elif c == 13:
            out.append("\n")
            i += 1
        elif c in CHAR_ONLY:
            i += 1
        elif 0xD800 <= c <= 0xDBFF and i + 1 < len(w) and 0xDC00 <= w[i + 1] <= 0xDFFF:
            # UTF-16 대리 쌍. 유닛 하나씩 chr()로 바꾸면 고립 서로게이트가 되어
            # 나중에 UTF-8로 못 쓴다. 수학 원고의 𝑓 같은 글자가 여기 해당한다.
            out.append(chr(0x10000 + ((c - 0xD800) << 10) + (w[i + 1] - 0xDC00)))
            i += 2
        elif 0xD800 <= c <= 0xDFFF:
            i += 1                      # 짝 없는 서로게이트는 버린다
        elif c < 0x20 or c == 0x7F:
            out.append(" " if c in (0x1E, 0x1F) else "")   # XML이 못 받는 제어문자
            i += 1
        else:
            out.append(chr(c))
            i += 1
    return "".join(out)


def _load_hwp(path):
    import olefile
    import zlib
    f = olefile.OleFileIO(path)
    hdr = f.openstream("FileHeader").read()
    compressed = struct.unpack("<I", hdr[36:40])[0] & 1
    secs = sorted([s for s in f.listdir() if s[0] == "BodyText"], key=lambda s: s[1])
    paras = []
    for s in secs:
        raw = f.openstream("/".join(s)).read()
        data = zlib.decompress(raw, -15) if compressed else raw
        cur = None
        for tag, level, body in _records(data):
            if tag == TAG_PARA_HEADER:
                cur = {"text": "", "eq": []}
                paras.append(cur)
            elif tag == TAG_PARA_TEXT and cur is not None:
                cur["text"] += _para_text(body)
            elif tag == TAG_EQEDIT and cur is not None:
                n = struct.unpack("<H", body[4:6])[0]
                cur["eq"].append(body[6:6 + n * 2].decode("utf-16-le", "replace"))
    f.close()
    return paras


# ---------------------------------------------------------------- HWPX
def _unesc(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))


HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _load_hwpx(path):
    """정규식으로 문단을 자르면 표에서 무너진다. 표는 문단 안에 표가 있고
    그 안에 다시 문단이 있는 중첩이라, 비탐욕 매칭이 첫 셀에서 끊긴다.
    ElementTree로 읽고 각 문단의 직계 run만 본다."""
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)]
    names.sort(key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    paras = []
    for n in names:
        try:
            root = ET.fromstring(z.read(n))
        except Exception:
            continue
        for p in root.iter(HP + "p"):
            text, eqs = [], []
            for run in p.findall(HP + "run"):       # 직계만. 셀 문단은 따로 잡힌다
                for el in run:
                    if el.tag == HP + "t":
                        if el.text:
                            text.append(el.text)
                        for sub in el:              # t 안의 tab, markpenBegin 등
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
            paras.append({"text": "".join(text), "eq": eqs})
    z.close()
    return paras


def _load_txt(path):
    for enc in ("utf-8", "cp949"):
        try:
            s = open(path, encoding=enc).read()
            break
        except UnicodeDecodeError:
            continue
    else:
        s = open(path, encoding="utf-8", errors="replace").read()
    return [{"text": ln, "eq": []} for ln in s.split("\n")]


def load_paragraphs(path):
    p = path.lower()
    if p.endswith(".hwpx"):
        return _load_hwpx(path)
    if p.endswith(".hwp"):
        return _load_hwp(path)
    return _load_txt(path)


# ---------------------------------------------------------------- 문항 분리
# "1. 다음" 과 "1.다음" 을 모두 잡는다. 뒤에 공백을 요구하면 한국어 원고의
# 절반이 문항으로 안 잡힌다. 다만 "1.5" 같은 소수는 걸러야 하므로 마침표
# 바로 뒤에 숫자가 오면 제외한다.
NUM_HEAD = re.compile(r"^\s*(\d{1,3})\s*[.)](?!\d)\s*(?=\S)")


def to_parts(paras):
    """문단 목록을 parts 배열로. 수식은 자리표시자를 실제 스크립트로 되돌린다.

    수식 레코드가 자리표시자보다 늦게 나오는 문단이 있어서, 문단별로 짝짓지 않고
    묶음 전체를 한 줄로 세워 순서대로 소비한다."""
    allq = []
    for p in paras:
        allq.extend(p.get("eq", []))
    it = iter(allq)
    parts = []
    for i, p in enumerate(paras):
        if i:
            parts.append({"br": True})
        buf = ""
        for ch in p.get("text", ""):
            if ch == EQ_MARK:
                if buf:
                    parts.append({"t": buf}); buf = ""
                parts.append({"eq": next(it, "")})
            elif ch == "\n":
                if buf:
                    parts.append({"t": buf}); buf = ""
                parts.append({"br": True})
            else:
                buf += ch
        if buf:
            parts.append({"t": buf})
    # 앞뒤 빈 줄 정리
    while parts and parts[0].get("br"):
        parts.pop(0)
    while parts and parts[-1].get("br"):
        parts.pop()
    return parts


def split_problems(paras, drop_preamble=True):
    """문단을 문항 단위로 자른다. 번호와 마침표와 탭으로 시작하는 문단이 경계다.

    drop_preamble이면 첫 번호를 만나기 전 문단은 버린다. 표지나 머리말이
    1번 문항에 통째로 딸려 들어가는 것을 막는다."""
    groups, cur, no = [], [], None
    seen_number = False
    for p in paras:
        t = p.get("text", "")
        m = NUM_HEAD.match(t)
        if m:
            if cur:
                groups.append((no, cur))
            cur = [p]
            no = m.group(1)
            seen_number = True
        elif cur:
            cur.append(p)
        elif t.strip():
            if drop_preamble and not seen_number:
                continue          # 첫 번호 앞은 표지나 머리말이다
            cur = [p]
            no = None
    if cur:
        groups.append((no, cur))

    out = []
    for n, g in groups:
        # 번호 표시는 레이아웃이 이미 갖고 있으므로 본문에서 뗀다
        g = [dict(x) for x in g]
        if n is not None:
            g[0]["text"] = NUM_HEAD.sub("", g[0]["text"], count=1)
        parts = to_parts(g)
        if not parts:
            continue
        out.append({"no": n, "parts": parts})
    return out


def load(path, imgdir=""):
    """원고 파일 -> [{no, parts}, ...]

    실제 강사 원고는 문제 하나가 표 한 행이고 본문에 번호가 없다.
    그런 파일이면 표 구조로 자른다. 번호로 자르는 방식은 그 다음이다.

    번호를 하나도 못 찾으면 머리말 버리기가 원고를 통째로 날린다.
    그럴 때는 통으로 한 덩어리를 돌려주는 편이 낫다."""
    if path.lower().endswith(".hwpx"):
        try:
            import hwpx_reader
            if hwpx_reader.looks_like_problem_tables(path):
                got = hwpx_reader.load(path, imgdir)
                if got:
                    return got
        except Exception:
            pass
    paras = load_paragraphs(path)
    out = split_problems(paras)
    if not out and any(p.get("text", "").strip() for p in paras):
        out = split_problems(paras, drop_preamble=False)
    return out


def parts_to_markup(parts):
    """GUI 편집기에 넣을 문자열로. 달러 기호 사이가 수식이다."""
    out = []
    for p in parts:
        if "raw" in p:
            # 표로 짜인 원고는 hwpx_reader 가 이미 마크업까지 만들어 준다
            out.append(p["raw"])
        elif p.get("br"):
            out.append("\n")
        elif "eq" in p:
            out.append("$%s$" % p["eq"])
        else:
            out.append(p.get("t", ""))
    return "".join(out).strip()
