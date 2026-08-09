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


def _load_hwpx(path):
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist()
             if re.match(r"Contents/section\d+\.xml$", n)]
    names.sort(key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    paras = []
    for n in names:
        s = z.read(n).decode("utf-8", "replace")
        for pm in re.finditer(r"<hp:p\b[^>]*>(.*?)</hp:p>", s, re.S):
            body = pm.group(1)
            text, eqs = [], []
            for m in re.finditer(
                    r"<hp:t\b[^>]*/>|<hp:t\b[^>]*>(.*?)</hp:t>"
                    r"|<hp:script\b[^>]*>(.*?)</hp:script>"
                    r"|<hp:tab\b[^>]*/>", body, re.S):
                if m.group(2) is not None:
                    eqs.append(_unesc(m.group(2)))
                    text.append(EQ_MARK)
                elif m.group(1) is not None:
                    text.append(_unesc(m.group(1)))
                elif m.group(0).startswith("<hp:tab"):
                    text.append("\t")
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
NUM_HEAD = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*(?:\t|\s)")


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


def split_problems(paras):
    """문단을 문항 단위로 자른다. 번호와 마침표와 탭으로 시작하는 문단이 경계다."""
    groups, cur, no = [], [], None
    for p in paras:
        t = p.get("text", "")
        m = NUM_HEAD.match(t)
        if m:
            if cur:
                groups.append((no, cur))
            cur = [p]
            no = m.group(1)
        elif cur:
            cur.append(p)
        elif t.strip():
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


def load(path):
    """원고 파일 -> [{no, parts}, ...]"""
    return split_problems(load_paragraphs(path))


def parts_to_markup(parts):
    """GUI 편집기에 넣을 문자열로. 달러 기호 사이가 수식이다."""
    out = []
    for p in parts:
        if p.get("br"):
            out.append("\n")
        elif "eq" in p:
            out.append("$%s$" % p["eq"])
        else:
            out.append(p.get("t", ""))
    return "".join(out).strip()
