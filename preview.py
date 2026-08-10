# -*- coding: utf-8 -*-
"""한글 수식 스크립트를 Tkinter Canvas에 직접 그리는 간이 렌더러.

한글을 띄우지 않고도 편집하면서 바로 결과를 보기 위한 것이다.
정확한 조판은 한글이 하고, 이건 위치와 모양을 가늠하는 용도다.
"""
import re
import tkinter.font as tkfont

# 이름 -> 기호
SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "sigma": "σ",
    "phi": "φ", "omega": "ω", "tau": "τ", "rho": "ρ", "eta": "η",
    "GAMMA": "Γ", "DELTA": "Δ", "THETA": "Θ", "LAMBDA": "Λ",
    "SIGMA": "Σ", "PI": "Π", "OMEGA": "Ω", "PHI": "Φ",
    "rarrow": "→", "larrow": "←", "leftarrow": "←", "rightarrow": "→",
    "times": "×", "div": "÷", "cdot": "·", "cdots": "⋯", "ldots": "…",
    "+-": "±", "-+": "∓", "pm": "±",
    "leq": "≤", "geq": "≥", "LEQ": "≤", "GEQ": "≥",
    "neq": "≠", "NEQ": "≠", "approx": "≈", "equiv": "≡",
    "in": "∈", "notin": "∉", "subset": "⊂", "supset": "⊃",
    "cup": "∪", "cap": "∩", "emptyset": "∅",
    "infty": "∞", "inf": "∞", "partial": "∂", "nabla": "∇",
    "angle": "∠", "perp": "⊥", "parallel": "∥",
    "therefore": "∴", "THEREFORE": "∴", "because": "∵",
    "prime": "′", "degree": "°", "circ": "∘",
    "forall": "∀", "exists": "∃", "neg": "¬",
    "oplus": "⊕", "otimes": "⊗", "propto": "∝", "sim": "∼",
}

BIGOPS = {"int": "∫", "iint": "∬", "oint": "∮", "sum": "∑", "prod": "∏",
          "union": "∪", "inter": "∩", "lim": "lim", "Lim": "lim"}

# 로만체로 그리는 예약어
ROMAN = {"sin", "cos", "tan", "sec", "csc", "cot", "log", "ln", "exp",
         "lim", "max", "min", "det", "dim", "gcd", "if", "for", "and", "or"}


# ---------------------------------------------------------------- 파서
def tokenize(s):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in "{}^_&#":
            out.append(c); i += 1
        elif c == "`":
            j = i
            while j < n and s[j] == "`":
                j += 1
            out.append(("sp", j - i)); i = j
        elif c == "~":
            out.append(("sp", 4)); i += 1
        elif c.isspace():
            i += 1
        elif c == '"':
            j = s.find('"', i + 1)
            if j < 0:
                j = n
            out.append(("txt", s[i + 1:j])); i = j + 1
        elif c.isalpha():
            j = i
            while j < n and (s[j].isalpha()):
                j += 1
            out.append(("word", s[i:j])); i = j
        else:
            j = i
            while j < n and not s[j].isalnum() and s[j] not in "{}^_&#`~\" " and not s[j].isspace():
                j += 1
            if j == i:
                j = i + 1
            out.append(("txt", s[i:j])); i = j
    return out


def parse(tokens, pos=0, stop=None):
    """토큰 -> 노드 리스트. 노드는 ('kind', ...) 형태."""
    items = []
    while pos < len(tokens):
        t = tokens[pos]
        if t == "}":
            if stop == "}":
                return items, pos + 1
            pos += 1
            continue
        if t == "{":
            sub, pos = parse(tokens, pos + 1, "}")
            items.append(("row", sub))
            continue
        if t == "^" or t == "_":
            kind = "sup" if t == "^" else "sub"
            arg, pos = parse_atom(tokens, pos + 1)
            base = items.pop() if items else ("row", [])
            # 같은 base에 sup과 sub이 이어 붙는 경우 합친다
            if base[0] in ("sup", "sub") and base[0] != kind:
                items.append(("supsub", base[1],
                              base[2] if base[0] == "sup" else arg,
                              arg if base[0] == "sup" else base[2]))
            else:
                items.append((kind, base, arg))
            continue
        if t == "&" or t == "#":
            items.append(("sp", 6)); pos += 1
            continue
        if isinstance(t, tuple):
            if t[0] == "sp":
                items.append(("sp", t[1] * 2)); pos += 1
                continue
            if t[0] == "txt":
                items.append(("txt", t[1])); pos += 1
                continue
            if t[0] == "word":
                w = t[1]
                low = w.lower()
                if low == "over" or low == "atop":
                    # 한글 수식에서 over는 바로 앞 항 하나만 분자로 삼는다.
                    # 앞의 전부를 가져가면 int _0 ^1 {..} over {..} 에서
                    # 적분 기호까지 분자로 올라가 조판이 무너진다.
                    num = items.pop() if items else ("row", [])
                    den, pos = parse_atom(tokens, pos + 1)
                    items.append(("frac", num, den, low == "over"))
                    continue
                if low == "sqrt":
                    arg, pos = parse_atom(tokens, pos + 1)
                    items.append(("sqrt", arg))
                    continue
                if w in BIGOPS:
                    items.append(("big", BIGOPS[w], w in ("lim", "Lim")))
                    pos += 1
                    continue
                if low in ("left", "right"):
                    pos += 1
                    if pos < len(tokens) and isinstance(tokens[pos], tuple):
                        items.append(("txt", tokens[pos][1]))
                        pos += 1
                    continue
                if w in SYMBOLS:
                    items.append(("txt", SYMBOLS[w])); pos += 1
                    continue
                if low in ("rm", "it", "bold"):
                    pos += 1
                    continue
                if low in ROMAN:
                    items.append(("rm", w)); pos += 1
                    continue
                items.append(("var", w)); pos += 1
                continue
        pos += 1
    return items, pos


def parse_atom(tokens, pos):
    """다음 한 덩어리만 읽는다."""
    if pos >= len(tokens):
        return ("row", []), pos
    t = tokens[pos]
    if t == "{":
        sub, pos = parse(tokens, pos + 1, "}")
        return ("row", sub), pos
    if isinstance(t, tuple):
        if t[0] == "word":
            w = t[1]
            if w in SYMBOLS:
                return ("txt", SYMBOLS[w]), pos + 1
            return ("var", w), pos + 1
        if t[0] == "txt":
            return ("txt", t[1]), pos + 1
        if t[0] == "sp":
            return ("row", []), pos + 1
    return ("row", []), pos + 1


def parse_script(s):
    if s is None:
        return ("row", [])
    for a, b in (("LEFT", "left"), ("RIGHT", "right")):
        s = s.replace(a, b)
    items, _ = parse(tokenize(s))
    return ("row", items)


# ---------------------------------------------------------------- 레이아웃
class EqLayout:
    """노드의 크기를 재고 캔버스에 그린다. 단위는 픽셀."""

    def __init__(self, base_px=14, mkfont=None):
        self.base = base_px
        self._fonts = {}
        self._mk = mkfont          # PDF로 그릴 때는 폰트를 바깥에서 준다

    def font(self, px, italic=False, roman=False):
        """Cambria Math는 쓰지 않는다. 큰 괄호와 적분 기호를 담느라 폰트 메트릭의
        ascent와 descent가 극단적으로 커서, 22픽셀을 요청하면 123픽셀짜리 상자가
        나온다. 글자가 상자 안에서 위로 밀려 배치가 통째로 어긋난다."""
        if self._mk is not None:
            return self._mk(px, italic, roman)
        size = -max(int(round(px)), 6)          # tk는 정수만 받는다
        key = (size, italic, roman)
        if key not in self._fonts:
            f = tkfont.Font(family="Times New Roman", size=size,
                            slant="italic" if italic else "roman")
            self._fonts[key] = f
        return self._fonts[key]

    def measure(self, node, px):
        """(width, above, below) 반환. above/below는 baseline 기준."""
        k = node[0]
        if k == "row":
            w, a, b = 0, px * 0.72, px * 0.22
            for ch in node[1]:
                cw, ca, cb = self.measure(ch, px)
                w += cw; a = max(a, ca); b = max(b, cb)
            return w, a, b
        if k in ("txt", "var", "rm"):
            f = self.font(px, italic=(k == "var"), roman=(k == "rm"))
            return f.measure(node[1]), px * 0.75, px * 0.25
        if k == "sp":
            return node[1] * px / 14.0, px * 0.7, px * 0.2
        if k == "frac":
            nw, na, nb = self.measure(node[1], px * 0.92)
            dw, da, db = self.measure(node[2], px * 0.92)
            w = max(nw, dw) + px * 0.35
            return w, (na + nb) + px * 0.28, (da + db) + px * 0.18
        if k == "sqrt":
            iw, ia, ib = self.measure(node[1], px)
            return iw + px * 0.72, ia + px * 0.22, ib
        if k in ("sup", "sub"):
            bw, ba, bb = self.measure(node[1], px)
            sw, sa, sb = self.measure(node[2], px * 0.68)
            if k == "sup":
                return bw + sw + 1, max(ba, ba * 0.55 + sa + sb), bb
            return bw + sw + 1, ba, max(bb, bb * 0.5 + sa + sb)
        if k == "supsub":
            bw, ba, bb = self.measure(node[1], px)
            uw, ua, ub = self.measure(node[2], px * 0.68)
            lw, la, lb = self.measure(node[3], px * 0.68)
            sw = max(uw, lw)
            return bw + sw + 1, max(ba, ba * 0.55 + ua + ub), max(bb, bb * 0.5 + la + lb)
        if k == "big":
            f = self.font(int(px * (1.0 if node[2] else 1.7)), roman=True)
            return f.measure(node[1]) + px * 0.1, px * (0.8 if node[2] else 1.1), px * (0.25 if node[2] else 0.7)
        return 0, px * 0.7, px * 0.2

    def draw(self, cv, node, x, y, px, fill="#111111", tags=("eq",)):
        """y는 baseline. 그린 폭을 반환."""
        k = node[0]
        if k == "row":
            cx = x
            for ch in node[1]:
                cx += self.draw(cv, ch, cx, y, px, fill, tags)
            return cx - x
        if k in ("txt", "var", "rm"):
            f = self.font(px, italic=(k == "var"), roman=(k == "rm"))
            cv.create_text(x, y, text=node[1], anchor="sw", font=f, fill=fill, tags=tags)
            return f.measure(node[1])
        if k == "sp":
            return node[1] * px / 14.0
        if k == "frac":
            sp = px * 0.92
            nw, na, nb = self.measure(node[1], sp)
            dw, da, db = self.measure(node[2], sp)
            w = max(nw, dw) + sp * 0.35
            # 분수선을 글자 중심 높이에 두면 앞뒤 기호(lim, 등호)와 눈높이가 맞는다
            bar = y - px * 0.32
            self.draw(cv, node[1], x + (w - nw) / 2, bar - nb - px * 0.1, sp, fill, tags)
            self.draw(cv, node[2], x + (w - dw) / 2, bar + da + px * 0.12, sp, fill, tags)
            if node[3]:
                cv.create_line(x + 1, bar, x + w - 1, bar, fill=fill, tags=tags)
            return w
        if k == "sqrt":
            iw, ia, ib = self.measure(node[1], px)
            f = self.font(int(px * 1.15), roman=True)
            cv.create_text(x, y, text="√", anchor="sw", font=f, fill=fill, tags=tags)
            sw = f.measure("√")
            top = y - ia - px * 0.12
            cv.create_line(x + sw - 1, top, x + sw + iw + 2, top, fill=fill, tags=tags)
            self.draw(cv, node[1], x + sw + 1, y, px, fill, tags)
            return sw + iw + px * 0.2
        if k == "sup":
            bw = self.draw(cv, node[1], x, y, px, fill, tags)
            self.draw(cv, node[2], x + bw + 1, y - px * 0.45, px * 0.68, fill, tags)
            sw, _, _ = self.measure(node[2], px * 0.68)
            return bw + sw + 1
        if k == "sub":
            bw = self.draw(cv, node[1], x, y, px, fill, tags)
            self.draw(cv, node[2], x + bw + 1, y + px * 0.22, px * 0.68, fill, tags)
            sw, _, _ = self.measure(node[2], px * 0.68)
            return bw + sw + 1
        if k == "supsub":
            bw = self.draw(cv, node[1], x, y, px, fill, tags)
            uw, _, _ = self.measure(node[2], px * 0.68)
            lw, _, _ = self.measure(node[3], px * 0.68)
            self.draw(cv, node[2], x + bw + 1, y - px * 0.45, px * 0.68, fill, tags)
            self.draw(cv, node[3], x + bw + 1, y + px * 0.22, px * 0.68, fill, tags)
            return bw + max(uw, lw) + 1
        if k == "big":
            islim = node[2]
            f = self.font(int(px * (1.0 if islim else 1.7)), roman=True)
            cv.create_text(x, y + (0 if islim else px * 0.25), text=node[1],
                           anchor="sw", font=f, fill=fill, tags=tags)
            return f.measure(node[1]) + px * 0.1
        return 0


# ---------------------------------------------------------------- 본문 렌더
_body_fonts = {}


BODY_FAMILY = "맑은 고딕"


def body_font(px, family=""):
    size = -max(int(round(px)), 6)
    key = (size, family or BODY_FAMILY)
    if key not in _body_fonts:
        _body_fonts[key] = tkfont.Font(family=key[1], size=size)
    return _body_fonts[key]


def render_parts(cv, parts, x, y, w, px=13, fill="#111111", tags=("body",), lh=1.55,
                 mkfont=None, bodyfont=None):
    """텍스트와 수식이 섞인 parts를 캔버스에 흘려 그린다. 마지막 아래끝을 반환.

    줄을 먼저 짠 다음 그린다. 그리면서 baseline을 조정하면 키 큰 수식이
    윗줄로 튀어나간다.

    mkfont와 bodyfont를 주면 화면이 아니라 PDF에 그린다. 미리보기와 인쇄물이
    같은 조판을 거치므로 보이는 대로 나온다."""
    eq = EqLayout(px, mkfont=mkfont)
    f = bodyfont if bodyfont is not None else body_font(px)
    epx = px * 1.05

    # 1) 줄 짜기. 각 조각은 (종류, 값, 폭, 위, 아래)
    lines, cur, cw = [], [], 0.0

    def wrap():
        nonlocal cur, cw
        lines.append(cur)
        cur, cw = [], 0.0

    for p in parts:
        if p.get("br"):
            wrap()
            continue
        if "eq" in p:
            node = parse_script(p["eq"])
            ew, ea, eb = eq.measure(node, epx)
            if cw + ew > w and cur:
                wrap()
            cur.append(("eq", node, ew, ea, eb))
            cw += ew + 2
            continue
        for word in re.findall(r"\S+\s*|\s+", p.get("t", "")):
            ww = f.measure(word)
            if cw + ww > w and cur:
                wrap()
            cur.append(("t", word, ww, px * 0.78, px * 0.24))
            cw += ww
    wrap()

    # 2) 줄마다 높이를 재서 그린다
    cy = y
    for ln in lines:
        above = max([c[3] for c in ln], default=px * 0.78)
        below = max([c[4] for c in ln], default=px * 0.24)
        base = cy + above
        cx = x
        # 낱말을 하나씩 따로 그리면 낱말마다 반올림 오차가 붙어 자간이 벌어진다.
        # 이어진 낱말은 한 문자열로 합쳐 한 번에 그린다. 그래야 폰트가 가진
        # 커닝도 산다.
        i = 0
        while i < len(ln):
            if ln[i][0] == "eq":
                eq.draw(cv, ln[i][1], cx, base, epx, fill, tags)
                cx += ln[i][2] + 2
                i += 1
                continue
            j = i
            buf = ""
            while j < len(ln) and ln[j][0] == "t":
                buf += ln[j][1]
                j += 1
            cv.create_text(cx, base, text=buf, anchor="sw", font=f, fill=fill, tags=tags)
            cx += f.measure(buf)
            i = j
        # 빈 줄도 한 줄 높이는 차지한다
        cy = base + max(below, px * (lh - 0.78))
    return cy
