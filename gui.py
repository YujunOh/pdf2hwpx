# -*- coding: utf-8 -*-
"""ditda 교재 자동조판 실습 GUI

왼쪽이 항상 미리보기다. 배경은 PDF를 그대로 구운 이미지다. 도형을 하나씩
다시 그리면 클리핑과 투명도와 글자 외곽선에서 계속 어긋나서, 원본을
그대로 보여주는 쪽으로 바꿨다. 그 위에 슬롯과 새 글만 얹는다.

'벡터 보기'를 켜면 예전처럼 도형을 그린다. HWPX에 무엇이 나갈지 확인용이다.

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
"""
import json, os, re, sys, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

# 고해상도 화면에서 흐릿하지 않도록. 캡처 좌표도 이걸 켜야 논리와 물리가 맞는다.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fitz
import pdf2hwpx as core
import preview as pv
import manuscript as ms
import printpdf as pp

OUTDIR = os.path.join(core.work_dir(), "out")
os.makedirs(OUTDIR, exist_ok=True)

def sample_pdf():
    """딸려 오는 예제 교재. exe 안에 넣어 두어서 받자마자 열 수 있다."""
    return core.resource_path("samples", "예제_교재.pdf")


DEFAULT_PDF = next((a for a in sys.argv[1:] if a.lower().endswith(".pdf")), "")
# 작업 파일을 인자로 받는다. 배치 파일이 한글 경로를 다루지 않아도 되게 하려는
# 것이다. cmd는 코드페이지에 따라 한글을 깨뜨리지만 dhp는 UTF-8 JSON이라 안전하다
DEFAULT_PROJ = next((a for a in sys.argv[1:] if a.lower().endswith(".dhp")), "")

MIN_W, MIN_H = 1180, 760

SAMPLES = [
    "다음 식을 간단히 하시오.\n\n$(x+2y) ^{3} -(x-2y) ^{3}$\n\n"
    "① 4y(3x²+4y²)    ② 4y(3x²+2y²)\n③ 2y(3x²+4y²)    ④ 2y(x²+4y²)",
    "다음 극한값을 구하시오.\n\n"
    "$ lim _{h ``rarrow`` 0} {f left(2+h  right)-f left(2  right)} over {h}$\n\n"
    "단, f(x)=x³-8x+7 이다.",
    "정적분의 값을 구하시오.\n\n"
    "$int _{0} ^{1} {x ^{2} -1} over { sqrt {x ^{2} +1}} dx$\n\n[3점]",
    "이차방정식 $x ^{2} -5x+k=0$ 의 두 근이\n모두 정수가 되도록 하는 자연수 k 의\n"
    "값을 모두 구하시오.\n\n(단, 두 근은 서로 다를 필요는 없다.)",
]

EQ_PALETTE = [
    ("분수", "{a} over {b}"), ("근호", "sqrt {a}"), ("적분", "int _{0} ^{1} f(x) dx"),
    ("극한", "lim _{x ``rarrow`` 0} f(x)"), ("합", "sum _{k=1} ^{n} a_{k}"),
    ("위첨자", "x ^{2}"), ("아래첨자", "a_{n}"), ("괄호", "left( x right)"),
    ("±", "+-"), ("≥", "GEQ"), ("→", "rarrow"), ("π", "pi"),
]


# 한글에서 손이 이미 익은 키를 그대로 쓴다. keys.json으로 바꿀 수 있다.
DEFAULT_KEYS = {
    "save": "<Control-s>",
    "open": "<Control-o>",
    "manuscript": "<Control-Shift-O>",
    "analyze": "<F5>",
    "build": "<Control-b>",
    "buildpdf": "<Control-p>",
    "verify": "<F12>",
    "next_slot": "<Control-Return>",
    "prev_slot": "<Control-Shift-Return>",
    "circled": "<Alt-i>",
    "equation": "<Control-m>",
    "zoom": "<F2>",
    "toggle_log": "<F9>",
    "help": "<F1>",
}

KEY_HELP = {
    "save": "작업 저장", "open": "작업 열기", "manuscript": "원고 불러오기",
    "analyze": "레이아웃 분석", "build": "HWPX 만들기", "verify": "한글로 확인",
    "buildpdf": "인쇄용 PDF",
    "next_slot": "다음 칸", "prev_slot": "이전 칸",
    "circled": "원문자 순환 (3 누르고 눌러 ③)", "equation": "수식 넣기",
    "zoom": "확대 토글", "toggle_log": "로그 접기", "help": "도움말",
}


def load_keys():
    """exe 옆 keys.json을 읽는다. 없으면 기본값으로 하나 만들어 둔다."""
    path = os.path.join(core.work_dir(), "keys.json")
    keys = dict(DEFAULT_KEYS)
    try:
        if os.path.exists(path):
            keys.update(json.load(open(path, encoding="utf-8")))
        else:
            json.dump(DEFAULT_KEYS, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
    except Exception:
        pass
    return keys, path


def next_circled(ch):
    """3 을 ③ 으로, ③ 을 ⑶ 으로, ⑶ 을 다시 3 으로. 한글 상용구 순환과 같은 방식."""
    if len(ch) != 1:
        return ch
    if ch in "0123456789":            # ①도 isdigit이 참이라 아스키만 본다
        n = int(ch)
        return chr(0x2460 + n - 1) if 1 <= n <= 20 else ch
    o = ord(ch)
    if 0x2460 <= o <= 0x2473:          # ① ~ ⑳
        return chr(0x2474 + o - 0x2460)
    if 0x2474 <= o <= 0x2487:          # ⑴ ~ ⒇
        return str(o - 0x2474 + 1)
    return ch


EQ_GUIDE = [
    ("분수", "{a} over {b}", "가로선 없는 분수는 atop"),
    ("근호", "sqrt {a}", "세제곱근은 sqrt {3} of {a}"),
    ("위첨자", "x ^{2}", "여러 글자는 중괄호로 묶는다"),
    ("아래첨자", "a_{n}", ""),
    ("적분", "int _{0} ^{1} f(x) dx", "oint dint tint 도 있다"),
    ("극한", "lim _{x ``rarrow`` 0} f(x)", "lim은 소문자"),
    ("합과 곱", "sum _{k=1} ^{n} a_{k}", "prod union inter"),
    ("괄호", "left( x right)", "내용 높이에 맞춰 늘어난다"),
    ("행렬", "matrix{a & b # c & d}", "pmatrix bmatrix dmatrix"),
    ("연립", "cases{2x+y=4 # 3x-4y=-1}", "#이 줄바꿈, &가 칸 맞춤"),
    ("빈칸", "` 또는 ~", "백틱이 좁은 칸, 물결이 보통 칸"),
    ("로만체", "rm 2H_2 O", "영문은 기본이 이탤릭이다"),
    ("기호", "+- GEQ LEQ NEQ rarrow pi theta", "그리스는 이름 그대로"),
]

EQ_TRAPS = [
    "한 낱말이 아홉 자를 넘으면 수식 편집기가 두 항으로 쪼갠다. 앞뒤를 큰따옴표로 묶어야 한다.",
    "스페이스는 화면 공백이 아니라 항 구분이다. 실제 공백은 백틱이나 물결로 넣는다.",
    "sin cos log lim max min 은 자동으로 로만체가 된다. 나머지 영문은 이탤릭이다.",
    "left( 와 LEFT ( 는 같은 뜻이다. 원고마다 대소문자가 섞여 온다.",
]


IMG_RE = re.compile(r"\[\[img:([^\]|]+?)(?:\|(\d{1,3}))?(?:\|([lr]))?\]\]")

# 과학 문제는 대부분 보기 상자를 낀다. 수능 과학 80문항 중 61개가 그렇다.
# [[보기]] 와 [[/보기]] 사이가 상자 안이다. [[자료]] 는 라벨 없는 상자다
BOX_OPEN = re.compile(r"^\s*\[\[(보기|자료)\]\]\s*$")
BOX_CLOSE = re.compile(r"^\s*\[\[/(보기|자료)\]\]\s*$")
BOX_LABEL = {"보기": "<보 기>", "자료": ""}


def _line_parts(line, parts):
    """한 줄을 조각으로 나눠 담는다."""
    for tok in re.split(r"(\$[^$]*\$|\[\[img:[^\]]*\]\])", line):
        if not tok:
            continue
        m = IMG_RE.fullmatch(tok)
        if m:
            q = {"img": m.group(1).strip()}
            if m.group(2):
                q["pct"] = int(m.group(2))
            if m.group(3):
                q["wrap"] = m.group(3)
            parts.append(q)
        elif tok.startswith("$") and tok.endswith("$") and len(tok) > 1:
            parts.append({"eq": tok[1:-1]})
        else:
            parts.append({"t": tok})


def readable(markup):
    """목록에 보여줄 짧은 글. 마크업을 사람이 읽는 말로 바꾼다."""
    t = IMG_RE.sub("[그림]", markup)
    t = re.sub(r"\$[^$]*\$", "[수식]", t)
    t = re.sub(r"\[\[/?(보기|자료)\]\]", "[보기]", t)
    return " ".join(t.split())


def parse_markup(text):
    """달러 기호 사이는 수식, 줄바꿈은 br, [[img:경로]] 는 그림.

    그림 뒤에 |70 처럼 적으면 칸 폭의 70%로 넣는다. 안 적으면 99%다.
    그 뒤에 |r 이나 |l 을 붙이면 본문이 그림 옆으로 흐른다.

    [[보기]] 와 [[/보기]] 사이는 테두리 상자에 담긴다. 과학 문제는
    대부분 이 상자를 낀다."""
    lines = text.split("\n")
    parts, i, first = [], 0, True
    while i < len(lines):
        m = BOX_OPEN.match(lines[i])
        if m:
            kind = m.group(1)
            j, body = i + 1, []
            while j < len(lines) and not BOX_CLOSE.match(lines[j]):
                body.append(lines[j])
                j += 1
            parts.append({"box": {"label": BOX_LABEL[kind],
                                  "parts": parse_markup("\n".join(body))}})
            i, first = j + 1, False
            continue
        if not first:
            parts.append({"br": True})
        first = False
        _line_parts(lines[i], parts)
        i += 1
    return parts


def count_eq(parts):
    return sum(1 for p in parts if "eq" in p)


class App:
    # ---- 쪽별 상태 -------------------------------------------------------
    # slots 와 texts 를 지금 보고 있는 쪽의 것으로 바꿔치기한다. 이렇게 하면
    # 이미 쓰인 자리 백 곳을 고치지 않고도 쪽마다 따로 남길 수 있다.
    def page_key(self):
        return (self.pdf_path.get(), self.pageno.get(), self.side.get())

    def page_state(self, key=None):
        k = key or self.page_key()
        if k not in self.pages:
            self.pages[k] = {"slots": [], "texts": {}}
        return self.pages[k]

    @property
    def slots(self):
        return self.page_state()["slots"]

    @slots.setter
    def slots(self, v):
        self.page_state()["slots"] = list(v)

    @property
    def texts(self):
        return self.page_state()["texts"]

    @texts.setter
    def texts(self, v):
        self.page_state()["texts"] = dict(v)

    def filled_pages(self):
        """글이 하나라도 든 쪽 목록. (쪽번호, 채운 칸 수)"""
        out = []
        for (path, pno, side), st in sorted(self.pages.items(), key=lambda kv: kv[0][1]):
            if path != self.pdf_path.get() or side != self.side.get():
                continue
            n = sum(1 for v in st["texts"].values() if v.strip())
            if n:
                out.append((pno, n))
        return out

    def __init__(self, root):
        self.root = root
        root.title("ditda 교재 자동조판 실습")
        # 고정 크기로 열면 화면이 작을 때 오른쪽 칸이 잘려 안 보인다.
        # 화면에 맞춰 열고 가운데에 둔다
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = max(MIN_W, min(int(sw * 0.88), 1720))
        h = max(MIN_H, min(int(sh * 0.88), 1040))
        root.geometry("%dx%d+%d+%d" % (w, h, max((sw - w) // 2, 0),
                                       max((sh - h) // 2 - 16, 0)))
        # 버튼이 가려질 만큼 줄어들지 않게 막는다
        root.minsize(MIN_W, MIN_H)

        self.pdf_path = tk.StringVar(value=DEFAULT_PDF)
        self.pageno = tk.IntVar(value=1)
        self.side = tk.StringVar(value="전체")
        self.showgrid = tk.BooleanVar(value=True)
        self.zoomsel = tk.BooleanVar(value=False)
        self.striptext = tk.BooleanVar(value=True)
        self.showvec = tk.BooleanVar(value=False)
        self.fontname = tk.StringVar(value="맑은 고딕")
        self.bodysize = tk.DoubleVar(value=10.5)
        self.leading = 1.55        # 원본에서 재서 덮어쓴다
        self._bg_key = None          # 배경 이미지 캐시. 같은 화면이면 다시 안 굽는다
        self._bg_img = None
        self._bg_photo = None
        self._photos = {}    # 미리보기에 그린 자료 그림
        self.bad_fonts = set()
        self._psize = None       # 지면 글자 크기 캐시
        self._psize_key = None
        # 쪽마다 칸과 글을 따로 담는다. 예전에는 한 벌만 들고 있어서 1쪽을
        # 채우고 2쪽으로 넘어가면 1쪽에 친 글이 그대로 날아갔다. 교재는
        # 한 권이 작업 단위인데 도구가 한 쪽만 기억하고 있었다
        self.pages = {}
        self.shapes = []
        self.texts = {}
        self.sel = 0
        self.page_w, self.page_h = 595.276, 841.89
        self._job = None
        self._drag = None
        self._rubber = None
        self.problems = []
        self.ms_path = ""
        self.proj_path = ""
        self.log_shown = False
        self.keys, self.keys_path = load_keys()
        self.recent = []
        try:
            rp = os.path.join(core.work_dir(), "recent.json")
            if os.path.exists(rp):
                self.recent = [q for q in json.load(open(rp, encoding="utf-8")).get("recent", [])
                               if os.path.exists(q)]
        except Exception:
            pass
        self._help = None
        self._text_boxes = []
        self.result_imgs = []
        self._build()
        self._menubar()
        # 설치 폰트를 훑는 데 2초쯤 걸린다. 창을 띄운 뒤 뒤에서 채운다
        threading.Thread(target=self._load_fonts, daemon=True).start()

    # ------------------------------------------------------------ 화면
    def _menubar(self):
        """성격이 다른 명령이 상단에 같은 무게로 늘어서 있었다. 자주 쓰는
        셋만 도구 모음에 남기고 나머지는 메뉴로 접는다."""
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="교재 PDF 열기...", command=self.pick)
        f.add_command(label="예제로 해보기", command=self.open_sample)
        f.add_separator()
        f.add_command(label="작업 열기...", accelerator="Ctrl+O", command=self.open_project)
        f.add_command(label="작업 저장...", accelerator="Ctrl+S", command=self.save_project)
        f.add_separator()
        f.add_command(label="끝내기", command=self.root.destroy)
        m.add_cascade(label="파일", menu=f)

        v = tk.Menu(m, tearoff=0)
        v.add_checkbutton(label="칸 경계", variable=self.showgrid, command=self.redraw)
        v.add_checkbutton(label="고른 칸 확대", variable=self.zoomsel, command=self.redraw)
        v.add_checkbutton(label="칸 안 원본 글자 빼기", variable=self.striptext,
                          command=self.redraw)
        v.add_checkbutton(label="벡터로 보기", variable=self.showvec, command=self.redraw)
        v.add_separator()
        v.add_command(label="자세한 기록 보이기/숨기기", accelerator="F9",
                      command=self.key_toggle_log)
        m.add_cascade(label="보기", menu=v)

        p = tk.Menu(m, tearoff=0)
        p.add_command(label="이 쪽 다시 분석", accelerator="F5", command=self.analyze)
        p.add_separator()
        p.add_command(label="기준 배치 저장...", command=self.save_layout)
        p.add_command(label="기준 배치 불러오기...", command=self.load_layout)
        m.add_cascade(label="쪽", menu=p)

        g = tk.Menu(m, tearoff=0)
        g.add_command(label="원고 불러오기...", accelerator="Ctrl+Shift+O",
                      command=self.load_manuscript)
        g.add_command(label="고른 칸부터 순서대로 채우기", command=self.autofill)
        m.add_cascade(label="원고", menu=g)

        e = tk.Menu(m, tearoff=0)
        e.add_command(label="배분 미리 보기", command=self.dry_run)
        e.add_separator()
        e.add_command(label="이 쪽만 PDF로", accelerator="Ctrl+P", command=self.build_pdf)
        e.add_command(label="채운 쪽 전부 PDF로", command=self.build_filled)
        e.add_command(label="원고를 여러 쪽에 부어 만들기", command=self.layout_all_pages)
        e.add_separator()
        e.add_command(label="한글 파일(HWPX)로", accelerator="Ctrl+B", command=self.build)
        e.add_command(label="한글로 열어 확인", accelerator="F12", command=self.verify)
        m.add_cascade(label="내보내기", menu=e)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="도움말", accelerator="F1", command=self.show_help)
        h.add_command(label="만든 파일이 있는 폴더", command=self.open_dir)
        m.add_cascade(label="도움말", menu=h)
        self.root.config(menu=m)

    def _build(self):
        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x")
        # 자주 쓰는 것만 남긴다. 나머지는 메뉴로 접었다. 성격이 다른 명령이
        # 같은 무게로 늘어서 있으면 무엇이 중요한지 알 수 없다
        ttk.Button(top, text="원고 불러오기",
                   command=self.load_manuscript).pack(side="left")
        ttk.Button(top, text="배분 미리 보기",
                   command=self.dry_run).pack(side="left", padx=6)
        ttk.Button(top, text="내보내기 ▾",
                   command=self.export_menu).pack(side="left")

        ttk.Label(top, text="  쪽").pack(side="left", padx=(14, 0))
        ttk.Button(top, text="◀", width=3, command=lambda: self.step_page(-1)).pack(side="left")
        ttk.Spinbox(top, from_=1, to=999, width=4, textvariable=self.pageno,
                    command=self.page_changed).pack(side="left")
        ttk.Button(top, text="▶", width=3, command=lambda: self.step_page(1)).pack(side="left")
        self.pagenote = ttk.Label(top, text="", foreground="#6b7689")
        self.pagenote.pack(side="left", padx=8)

        self.title = ttk.Label(top, text="", foreground="#55617a")
        self.title.pack(side="right")

        # 산출물이 어디 생겼는지 알리는 자리. 로그를 안 보는 사람이 대부분이다
        self.resultbar = ttk.Frame(self.root, padding=(8, 4))
        self.rlabel = ttk.Label(self.resultbar, text="", foreground="#1a6b3a")
        self.rlabel.pack(side="left")
        ttk.Button(self.resultbar, text="폴더에서 보기", width=12,
                   command=self.show_result).pack(side="right")
        ttk.Button(self.resultbar, text="파일 열기", width=10,
                   command=lambda: self.last_out and os.startfile(self.last_out)
                   ).pack(side="right", padx=6)
        self.last_out = ""

        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)
        self.pane = pane

        # --- 왼쪽: 항상 보이는 미리보기
        lf = ttk.LabelFrame(pane, text="미리보기 (원본 디자인 위에 새로 넣은 글)", padding=4)
        pane.add(lf, weight=3)
        self.canvas = tk.Canvas(lf, bg="#e9e9ee", highlightthickness=0, width=560)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_rclick)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.root.after(120, self.redraw)      # 첫 화면 안내
        bar = ttk.Frame(lf)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(bar, text="칸 경계", variable=self.showgrid,
                        command=self.redraw).pack(side="left")
        ttk.Checkbutton(bar, text="확대", variable=self.zoomsel,
                        command=self.redraw).pack(side="left", padx=6)
        ttk.Checkbutton(bar, text="원본 글자 빼기", variable=self.striptext,
                        command=self.redraw).pack(side="left")
        ttk.Checkbutton(bar, text="벡터", variable=self.showvec,
                        command=self.redraw).pack(side="left", padx=6)
        self.status = ttk.Label(bar, text="", foreground="#555555")
        self.status.pack(side="right")

        bar2 = ttk.Frame(lf)
        bar2.pack(fill="x", pady=(2, 0))
        ttk.Label(bar2, text="본문").pack(side="left")
        self.fontbox = ttk.Combobox(bar2, textvariable=self.fontname, width=17,
                                    state="readonly", values=["맑은 고딕"])
        self.fontbox.pack(side="left", padx=(4, 4))
        self.fontbox.bind("<<ComboboxSelected>>", lambda e: self.redraw())
        ttk.Spinbox(bar2, from_=6.0, to=20.0, increment=0.5, width=5,
                    textvariable=self.bodysize,
                    command=self.redraw).pack(side="left")
        ttk.Label(bar2, text="pt").pack(side="left", padx=(2, 10))
        ttk.Button(bar2, text="그림 넣기", command=self.insert_image).pack(side="left")

        # --- 오른쪽: 편집
        rf = ttk.Frame(pane)
        pane.add(rf, weight=2)

        box = ttk.LabelFrame(rf, text="검출 결과", padding=6)
        box.pack(fill="x")
        self.info = ttk.Label(box, text="PDF를 고르고 레이아웃 분석을 누르세요.",
                              justify="left", foreground="#333333")
        self.info.pack(anchor="w")

        mf = ttk.LabelFrame(rf, text="선생님 원고", padding=6)
        mf.pack(fill="x", pady=(6, 0))
        mrow = ttk.Frame(mf)
        mrow.pack(fill="x")
        ttk.Button(mrow, text="원고 불러오기", command=self.load_manuscript).pack(side="left")
        ttk.Button(mrow, text="순서대로 채우기", command=self.autofill).pack(side="left", padx=6)
        self.mlabel = ttk.Label(mrow, text="hwp, hwpx, txt", foreground="#777777")
        self.mlabel.pack(side="left")
        plw = ttk.Frame(mf)
        plw.pack(fill="x", pady=(6, 0))
        self.problist = tk.Listbox(plw, height=5, font=("맑은 고딕", 9),
                                   activestyle="none")
        psb = ttk.Scrollbar(plw, orient="vertical", command=self.problist.yview)
        self.problist.configure(yscrollcommand=psb.set)
        self.problist.pack(side="left", fill="x", expand=True)
        psb.pack(side="right", fill="y")
        self.problist.bind("<Double-Button-1>", self.put_problem)

        sf = ttk.LabelFrame(rf, text="문제 입력", padding=6)
        sf.pack(fill="both", expand=True, pady=6)
        row = ttk.Frame(sf)
        row.pack(fill="x")
        self.sellabel = ttk.Label(row, text="칸을 누르세요", foreground="#2f6fd0")
        self.sellabel.pack(side="left")
        ttk.Button(row, text="예시", width=6,
                   command=self.fill_sample).pack(side="left", padx=(10, 2))
        ttk.Button(row, text="전체 예시", width=9, command=self.fill_all).pack(side="left")
        ttk.Button(row, text="비우기", width=7, command=self.clear_slot).pack(side="left", padx=2)

        pal = ttk.Frame(sf)
        pal.pack(fill="x", pady=(6, 2))
        for i, (label, code) in enumerate(EQ_PALETTE):
            ttk.Button(pal, text=label, width=8,
                       command=lambda c=code: self.insert_eq(c)).grid(
                           row=i // 6, column=i % 6, padx=1, pady=1, sticky="ew")
        for c in range(6):
            pal.columnconfigure(c, weight=1)
        ttk.Label(sf, text="달러 기호 사이가 수식입니다.  예: $1 over 2$",
                  foreground="#777777").pack(anchor="w", pady=(2, 4))

        self.editor = tk.Text(sf, wrap="word", font=("맑은 고딕", 11), undo=True, height=10)
        self.editor.pack(fill="both", expand=True)
        self.editor.bind("<KeyRelease>", self.on_type)

        act = ttk.Frame(rf)
        act.pack(fill="x")
        ttk.Button(act, text="인쇄용 PDF 만들기",
                   command=self.build_pdf).pack(side="left")
        ttk.Button(act, text="한글로 열어 확인", command=self.verify).pack(side="left", padx=6)
        ttk.Button(act, text="결과 폴더", command=self.open_dir).pack(side="left")
        ttk.Button(act, text="도움말 F1", command=self.show_help).pack(side="right")

        self.log = tk.Text(self.root, height=4, font=("Consolas", 9),
                           bg="#1e1e1e", fg="#d4d4d4")
        # 처음에는 접어 둔다. 개발용 기록이 화면 반을 먹고 있었다
        self.bind_keys()
        self.say("준비됨.  F5 분석 · Ctrl+B 만들기 · Ctrl+S 저장 · Alt+I 원문자 순환 · F9 로그 접기")
        self.say("단축키는 %s 를 고치면 바뀝니다." % self.keys_path)
        # 미리보기가 절반 넘게 차지하도록 초기 분할 위치를 잡는다
        self.root.after(120, self._place_sash)

    def _load_fonts(self):
        """쓸 수 있는 한글 폰트를 목록에 채운다.

        글자가 제대로 안 나오는 폰트는 이름 뒤에 표를 달아 둔다. OTF 폰트
        가운데 %가 엉뚱한 모양으로 그려지거나 원문자를 복사하면 다른 글자가
        나오는 것들이 있다."""
        try:
            table = pp.korean_fonts(cache_dir=core.work_dir())
        except Exception:
            return
        good = sorted(n for n, v in table.items() if v[1])
        bad = sorted(n for n, v in table.items() if not v[1])
        self.bad_fonts = set(bad)
        names = good + [n + " △" for n in bad]

        def apply():
            self.fontbox["values"] = names
            if self.fontname.get() not in names and names:
                for want in ("맑은 고딕", "Malgun Gothic"):
                    if want in names:
                        self.fontname.set(want); break
            self.say("한글 폰트 %d종. 그 중 %d종은 글자가 어긋나 △ 를 달았습니다."
                     % (len(names), len(bad)))
            if bad:
                self.say("  △ 폰트는 괄호나 %% 가 검은 상자로 나오거나 아예 안 찍힙니다.")
                if any("Pretendard" in n for n in bad):
                    self.say("  Pretendard 는 OTF 라 걸립니다. TTF 판을 받아 설치하면 쓸 수 있습니다.")
                    self.say("  github.com/orioncactus/pretendard/releases")
        try:
            self.root.after(0, apply)
        except Exception:
            pass          # 창이 이미 닫혔다

    def picked_font(self):
        """콤보에서 고른 이름에서 표를 뗀다."""
        return self.fontname.get().replace(" △", "")

    def layout_menu(self):
        """칸 배치를 저장하거나 얹는다."""
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="칸 배치 저장 (.dlay)", command=self.save_layout)
        m.add_command(label="칸 배치 불러오기", command=self.load_layout)
        m.add_separator()
        m.add_command(label="채운 쪽 전부 내보내기", command=self.build_filled)
        m.add_separator()
        m.add_command(label="배분 미리 보기", command=self.dry_run)
        m.add_command(label="이 배치를 모든 쪽에 쓰기", command=self.layout_all_pages)
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            m.grab_release()

    def build_filled(self):
        """손으로 채워 둔 쪽을 전부 한 문서로 뽑는다.

        원고를 흘려 넣는 일괄 만들기와 달리, 쪽마다 직접 손본 것을 그대로
        낸다. 쪽별 상태가 남게 된 뒤에야 가능해진 경로다."""
        done = self.filled_pages()
        if not done:
            messagebox.showinfo("", "글을 채운 쪽이 없습니다.\n"
                                    "칸을 누르고 문제를 넣은 뒤에 눌러 주세요.")
            return
        jobs = []
        for pno, _ in done:
            st = self.page_state((self.pdf_path.get(), pno, self.side.get()))
            if not st["slots"]:
                continue
            parts_of = {i: parse_markup(v) for i, v in st["texts"].items() if v.strip()}
            if parts_of:
                jobs.append((pno - 1, st["slots"], parts_of))
        if not jobs:
            messagebox.showinfo("", "내보낼 것이 없습니다.")
            return
        out = os.path.join(OUTDIR, "교재.pdf")
        try:
            rep = pp.build_book(self.pdf_path.get(), jobs, out,
                                fontpath=self.picked_font(),
                                base_size=self.bodysize.get(), lh=self.leading)
        except Exception:
            self.say(traceback.format_exc()); return
        info = pp.report(out)
        self.say("채워 둔 %d쪽을 뽑았습니다: %s (%.0f KB)"
                 % (len(jobs), out, info["bytes"] / 1024))
        for pno in sorted(rep):
            for row in rep[pno]:
                if row[3]:
                    self.say("  %d쪽 칸%d 는 약 %d자 넘칩니다."
                             % (pno + 1, row[0] + 1, row[4] if len(row) > 4 else 0))
        self.announce(out, "%d쪽 · %.0f KB" % (len(jobs), info["bytes"] / 1024))

    def dry_run(self):
        """만들기 전에 어느 문항이 어느 칸에 가고 어디가 넘치는지 보여준다.

        인쇄물을 뽑고 나서 넘친 것을 발견하면 늦다. 원고를 고칠 사람에게는
        몇 줄이 아니라 몇 자를 줄여야 하는지가 쓸모 있다."""
        if not self.slots or not self.problems:
            messagebox.showwarning("", "칸을 잡고 원고를 불러온 뒤에 눌러 주세요.")
            return
        w = tk.Toplevel(self.root)
        w.title("배분 미리 보기")
        w.geometry("860x560")
        w.transient(self.root)
        head = ttk.Label(w, text="세는 중입니다...", padding=(10, 8))
        head.pack(anchor="w")
        cols = ("쪽", "칸", "문항", "글자", "상태")
        tv = ttk.Treeview(w, columns=cols, show="headings", height=20)
        for c, width in zip(cols, (50, 50, 420, 70, 200)):
            tv.heading(c, text=c)
            tv.column(c, width=width, anchor="w" if c == "문항" else "center")
        tv.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        tv.tag_configure("over", foreground="#c0392b")
        tv.tag_configure("small", foreground="#b9770e")
        ttk.Button(w, text="닫기", command=w.destroy).pack(pady=(0, 10))
        w.update()

        try:
            doc = fitz.open(self.pdf_path.get())
            total = doc.page_count
            doc.close()
        except Exception:
            self.say(traceback.format_exc()); return

        start = self.pageno.get()
        taken, pno, nover = 0, start - 1, 0
        while taken < len(self.problems) and pno < total:
            slots = self.slots if pno == start - 1 else self.slots_of_page(pno)
            if not slots:
                pno += 1
                continue
            psize = None
            rows = []
            for i, (x, y, sw, sh) in enumerate(slots):
                if taken >= len(self.problems):
                    break
                prob = self.problems[taken]
                parts = parse_markup(ms.parts_to_markup(prob["parts"]))
                size, iscale, over = self.fit_size(parts, sw, sh)
                psize = size if psize is None else min(psize, size)
                rows.append((i, prob, parts, sw, sh))
                taken += 1
            for i, prob, parts, sw, sh in rows:
                size, iscale, over = self.fit_size(parts, sw, sh, force_size=psize)
                body = readable(ms.parts_to_markup(prob["parts"]))
                tag, note = "", ""
                if over:
                    per_line = max(sw / max(size, 1.0), 1.0)
                    n = int(round(over / max(size * self.leading, 1.0) * per_line))
                    note = "약 %d자 넘침" % n
                    tag = "over"
                    nover += 1
                elif iscale < 1.0 and size < self.bodysize.get():
                    note = "그림 %d%%, 글자 %.1fpt" % (round(iscale * 100), size)
                    tag = "small"
                elif iscale < 1.0:
                    note = "그림 %d%%" % round(iscale * 100)
                    tag = "small"
                elif size < self.bodysize.get():
                    note = "글자 %.1fpt" % size
                    tag = "small"
                else:
                    note = "그대로 들어감"
                tv.insert("", "end", tags=(tag,),
                          values=(pno + 1, i, body[:70], len(body), note))
            pno += 1
        left = len(self.problems) - taken
        msg = "문항 %d개 중 %d개 배분. 넘치는 칸 %d개." % (len(self.problems), taken, nover)
        if left:
            msg += "  쪽이 모자라 %d개는 못 넣었습니다." % left
        head.config(text=msg)

    def layout_all_pages(self):
        """지금 칸 배치로 원고를 여러 쪽에 흘려 넣고 한 번에 뽑는다.

        교재는 한 쪽짜리가 아니다. 원고를 쭉 부어 넣고 한 번에 뽑아야
        쓸모가 있다. 문항 번호는 우리가 넣지 않는다. 디자인에 이미
        박혀 있고 순서대로 넣으면 저절로 맞는다."""
        if not self.slots:
            messagebox.showwarning("", "먼저 칸을 잡으세요.")
            return
        if not self.problems:
            messagebox.showwarning("", "먼저 원고를 불러오세요.\n"
                                       "Ctrl+Shift+O 로 hwp, hwpx, txt 를 엽니다.")
            return
        try:
            doc = fitz.open(self.pdf_path.get())
            total = doc.page_count
            doc.close()
        except Exception:
            self.say(traceback.format_exc()); return

        per = len(self.slots)
        start = self.pageno.get()                      # 1부터
        need = (len(self.problems) + per - 1) // per
        # 교재에는 표지와 목차와 Note 가 섞여 있다. 칸이 안 잡히는 쪽은
        # 아래에서 저절로 걸러지지만, 목차는 칸 크기가 문제 칸과 같아서
        # 가려낼 방법이 마땅치 않다. 끝 쪽은 사람이 정하는 편이 낫다
        from tkinter import simpledialog
        last = simpledialog.askinteger(
            "어디까지 넣을까요",
            "문항 %d개를 %d쪽부터 넣습니다.\n"
            "지금 쪽 기준 한 쪽에 %d개씩이니 %d쪽쯤 필요합니다.\n\n"
            "마지막 쪽 번호를 적으세요. (이 PDF는 %d쪽까지 있습니다)\n"
            "표지나 목차가 섞여 있으면 문제 지면 끝 쪽을 적으면 됩니다."
            % (len(self.problems), start, per, need, total),
            initialvalue=min(start + need - 1, total),
            minvalue=start, maxvalue=total, parent=self.root)
        if not last:
            return
        total = last          # 아래 루프가 여기까지만 돈다

        # 쪽마다 칸 모양이 다른 교재가 흔하다. 기본은 쪽마다 다시 찾는 것으로
        # 두고, 같은 판형이 반복되는 교재면 지금 배치를 그대로 쓰게 한다
        redetect = messagebox.askyesno(
            "칸 찾기",
            "쪽마다 칸을 다시 찾을까요?\n\n"
            "예 - 쪽마다 그 쪽의 칸을 찾습니다. 쪽 구성이 다른 교재에 맞습니다.\n"
            "아니오 - 지금 칸 배치를 모든 쪽에 그대로 씁니다.")

        jobs, taken, skipped = [], 0, []
        pno = start - 1
        while taken < len(self.problems) and pno < total:
            slots = self.slots
            if redetect and pno != start - 1:
                slots = self.slots_of_page(pno)
            if not slots:
                # 표지, 목차, Note 처럼 문제 칸이 없는 쪽이다. 여기에 지금
                # 쪽의 칸을 얹으면 원래 있던 글 위에 문제가 겹쳐 찍힌다
                skipped.append(pno + 1)
                pno += 1
                continue
            chunk = self.problems[taken:taken + len(slots)]
            taken += len(chunk)
            parts_of = {}
            for i, prob in enumerate(chunk):
                parts_of[i] = parse_markup(ms.parts_to_markup(prob["parts"]))
            jobs.append((pno, slots, parts_of))
            pno += 1
        if not jobs:
            messagebox.showwarning("", "문제 칸이 있는 쪽을 찾지 못했습니다.")
            return
        if skipped:
            self.say("문제 칸이 없어 건너뛴 쪽: %s"
                     % ", ".join(str(q) for q in skipped[:12]))
        out = os.path.join(OUTDIR, "교재.pdf")
        try:
            rep = pp.build_book(self.pdf_path.get(), jobs, out,
                                fontpath=self.picked_font(),
                                base_size=self.bodysize.get(), lh=self.leading)
        except Exception:
            self.say(traceback.format_exc()); return
        info = pp.report(out)
        self.say("교재 %d쪽을 만들었습니다: %s (%.0f KB)"
                 % (len(jobs), out, info["bytes"] / 1024))
        self.say("  문항 %d개를 넣었습니다." % taken)
        if taken < len(self.problems):
            self.say("  쪽이 모자라 문항 %d개가 남았습니다. 끝 쪽을 늘리거나"
                     " 문제 지면이 더 있는 교재를 쓰세요." % (len(self.problems) - taken))
        nover = 0
        for pno in sorted(rep):
            for row in rep[pno]:
                if row[3]:
                    nover += 1
                    self.say("  %d쪽 %d번째 칸은 약 %d자 넘칩니다."
                             % (pno + 1, row[0] + 1, row[4] if len(row) > 4 else 0))
        if nover:
            self.say("  넘치는 칸이 %d개입니다. 칸 배치 메뉴의 배분 미리 보기에서"
                     " 어디를 줄여야 하는지 볼 수 있습니다." % nover)
        self.announce(out, "%d쪽 · %.0f KB" % (len(jobs), info["bytes"] / 1024))

    def _place_sash(self):
        try:
            self.root.update_idletasks()
            w = self.root.winfo_width()
            self.pane.sashpos(0, int(w * 0.53))
        except Exception:
            pass

    # ------------------------------------------------------------ 유틸
    def say(self, m):
        self.log.insert("end", m + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def pick(self):
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            self.pdf_path.set(p)
            self.analyze()

    def step_page(self, d):
        """쪽을 앞뒤로 넘긴다. 쪽마다 칸과 글이 따로 남으니 잃는 것이 없다."""
        n = max(self.pageno.get() + d, 1)
        self.pageno.set(n)
        self.page_changed()

    def export_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="이 쪽만 PDF로", command=self.build_pdf)
        m.add_command(label="채운 쪽 전부 PDF로", command=self.build_filled)
        m.add_command(label="원고를 여러 쪽에 부어 만들기", command=self.layout_all_pages)
        m.add_separator()
        m.add_command(label="한글 파일(HWPX)로", command=self.build)
        m.add_command(label="한글로 열어 확인", command=self.verify)
        m.add_separator()
        m.add_command(label="기준 배치 저장...", command=self.save_layout)
        m.add_command(label="기준 배치 불러오기...", command=self.load_layout)
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            m.grab_release()

    def show_title(self):
        """지금 무엇을 열어 두었는지 위쪽에 적는다."""
        p = self.pdf_path.get()
        if not p:
            self.title.config(text="")
            return
        done = self.filled_pages()
        bits = [os.path.basename(p)]
        if done:
            bits.append("글이 든 쪽 %s" % ", ".join(str(q) for q, _ in done))
        self.title.config(text="   ".join(bits))

    def page_changed(self):
        """쪽을 넘기면 저절로 분석한다. 쪽마다 칸과 글이 따로 남으므로
        오가도 잃는 것이 없다."""
        if self.pdf_path.get() and os.path.exists(self.pdf_path.get()):
            self.analyze()

    def open_dir(self):
        os.startfile(OUTDIR)

    def show_result(self):
        """탐색기를 열되 그 파일이 골라진 채로 연다. 폴더만 열면 파일이
        여럿일 때 방금 만든 것을 다시 찾아야 한다."""
        if not self.last_out or not os.path.exists(self.last_out):
            os.startfile(OUTDIR)
            return
        import subprocess
        # explorer는 성공해도 종료 코드 1을 낸다. check를 걸면 안 된다
        subprocess.run(["explorer", "/select,%s" % os.path.normpath(self.last_out)],
                       check=False)

    def announce(self, path, note=""):
        """방금 만든 파일을 창 아래에 띄운다."""
        self.last_out = path
        self.rlabel.config(text="%s 저장됨   %s   %s"
                                % (os.path.basename(path), os.path.dirname(path), note))
        self.resultbar.pack(fill="x", side="bottom", before=self.pane)

    def clip_of(self, page):
        w = page.rect.width
        if self.side.get() == "좌면":
            return (0, 0, w / 2, page.rect.height)
        if self.side.get() == "우면":
            return (w / 2, 0, w, page.rect.height)
        return None

    # ------------------------------------------------------------ 분석
    def analyze(self):
        try:
            path = self.pdf_path.get()
            if not path or not os.path.exists(path):
                messagebox.showwarning("", "PDF 경로를 확인하세요.")
                return
            pno = self.pageno.get() - 1
            doc = fitz.open(path)
            if pno >= doc.page_count:
                messagebox.showwarning("", "페이지 번호가 문서 범위를 넘습니다.")
                doc.close(); return
            page = doc[pno]
            clip = self.clip_of(page)
            self.page_w = (clip[2] - clip[0]) if clip else page.rect.width
            self.page_h = page.rect.height
            doc.close()

            self.remember(path)
            self.shapes = core.extract_layout(path, pno, clip)
            n_r = sum(1 for s in self.shapes if s["k"] == "rect")
            n_l = sum(1 for s in self.shapes if s["k"] == "line")
            n_t = sum(1 for s in self.shapes if s["k"] == "text")

            self._target = (path, pno, self.side.get())
            self._text_boxes = [(t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"])
                                for t in self.shapes if t["k"] == "text"]
            # 이 쪽에 이미 잡아 둔 칸이 있으면 그대로 쓴다. 손으로 고쳐 둔
            # 것을 다시 분석했다고 날리면 안 된다
            keep = bool(self.slots)
            if not keep:
                self.slots = self.detect_slots()
            dropped = self.sync_slots()
            if dropped:
                self.say("  칸이 줄어 넘치는 글 %d개를 버렸습니다." % dropped)
            if keep:
                self.say("  이 쪽에 잡아 둔 칸 %d개를 그대로 씁니다." % len(self.slots))

            self.info.config(text=(
                "%.0f x %.0f mm   사각형 %d · 직선 %d · 원본텍스트 %d\n"
                "이미지 0개 (래스터화 없음)   찾은 문제 칸 %d개"
                % (self.page_w * 25.4 / 72, self.page_h * 25.4 / 72, n_r, n_l, n_t, len(self.slots))))
            m = self.measure_body()
            if m:
                self.bodysize.set(m[0]); self.leading = m[1]
                self.say("원본 본문은 %.1fpt, 행간 %.2f 입니다. 그 값으로 맞췄습니다."
                         % (m[0], m[1]))
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", self.texts.get(self.sel, ""))
            self.say("분석 완료. 사각형 %d, 직선 %d, 원본텍스트 %d, 문제 칸 %d개"
                     % (n_r, n_l, n_t, len(self.slots)))
            if not self.slots:
                self.say("  문제 칸을 못 찾았습니다. 빈 곳을 끌어서 직접 그려도 됩니다.")
            n = sum(1 for v in self.texts.values() if v.strip())
            self.pagenote.config(text="칸 %d개%s"
                                      % (len(self.slots), " · 채움 %d" % n if n else ""))
            self.show_title()
            self.redraw()
        except Exception:
            self.say(traceback.format_exc())

    def measure_body(self):
        """칸 안에 있던 원본 글자에서 크기와 행간을 잰다.

        디자이너가 정한 값을 그대로 따르는 것이 손으로 맞추는 것보다 낫다.
        이 교재는 12pt에 행간 1.58이었는데 기본값 10.5pt로 넣으면 원본보다
        작아서 한눈에 다르게 보인다."""
        import statistics as st
        sizes, gaps = [], []
        for sx, sy, sw, sh in self.slots:
            rows = [t for t in self.shapes if t["k"] == "text"
                    and sx - 2 <= t["x"] <= sx + sw + 2
                    and sy - 2 <= t["y"] <= sy + sh + 2]
            rows.sort(key=lambda t: t["y"])
            sizes += [t["size"] for t in rows]
            for a, b in zip(rows, rows[1:]):
                d = b["y"] - a["y"]
                if 2 < d < 40:
                    gaps.append(d)
        if not sizes:
            return None
        size = round(st.median(sizes) * 2) / 2.0      # 0.5pt 단위로
        lead = round(st.median(gaps) / st.median(sizes), 2) if gaps else 1.55
        return size, max(min(lead, 2.4), 1.1)

    # ------------------------------------------------------------ 슬롯 검출
    def slots_of_page(self, pageno):
        """다른 쪽의 칸을 찾아 온다. 화면 상태는 건드리지 않는다.

        여러 쪽을 한 번에 뽑을 때 쪽마다 칸 모양이 다를 수 있다."""
        keep = (self.shapes, self._text_boxes, self.page_w, self.page_h)
        try:
            doc = fitz.open(self.pdf_path.get())
            if pageno >= doc.page_count:
                doc.close(); return []
            page = doc[pageno]
            clip = self.clip_of(page)
            self.page_w = (clip[2] - clip[0]) if clip else page.rect.width
            self.page_h = page.rect.height
            doc.close()
            self.shapes = core.extract_layout(self.pdf_path.get(), pageno, clip)
            self._text_boxes = [(t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"])
                                for t in self.shapes if t["k"] == "text"]
            return self.detect_slots()
        except Exception:
            self.say(traceback.format_exc())
            return []
        finally:
            self.shapes, self._text_boxes, self.page_w, self.page_h = keep

    def detect_slots(self):
        """두 가지 패턴을 다 시도해서 많이 잡히는 쪽을 쓴다.
        (a) 문제마다 색 띠 헤더가 있고 그 아래가 본문인 배치
        (b) 테두리만 있는 큰 빈 상자가 문제 칸인 배치"""
        W, H = self.page_w, self.page_h

        def bbox(s):
            if s["k"] == "rect":
                return s["x"], s["y"], s["w"], s["h"]
            if s["k"] == "curve":
                xs = [p[0] for p in s["pts"]]
                ys = [p[1] for p in s["pts"]]
                return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
            return None

        # (a) 색으로 채운 가로 띠. 폭이 페이지의 3할 넘고 높이가 낮은 것.
        # 알약 모양 헤더는 곡선으로 들어오므로 curve도 본다.
        bars = []
        for s in self.shapes:
            if not s.get("fill") or s["k"] not in ("rect", "curve"):
                continue
            bb = bbox(s)
            if bb and bb[2] > W * 0.3 and 14 < bb[3] < 40:
                bars.append({"x": bb[0], "y": bb[1], "w": bb[2], "h": bb[3]})
        bars.sort(key=lambda s: (round(s["y"], 1), s["x"]))
        a = []
        for b in bars:
            top = b["y"] + b["h"] + 8
            below = [c["y"] for c in bars
                     if c["y"] > b["y"] + 5 and abs(c["x"] - b["x"]) < 20]
            bottom = (min(below) - 14) if below else (H - 40)
            if bottom - top > 60:
                a.append((b["x"] + 10, top, b["w"] - 20, bottom - top))

        # (b) 테두리만 있고 속이 빈 큰 상자. 둥근 상자는 curve로 들어온다
        boxes = []
        for s in self.shapes:
            if s.get("fill") or not s.get("stroke"):
                continue
            if s["k"] == "rect":
                x, y, w, h = s["x"], s["y"], s["w"], s["h"]
            elif s["k"] == "curve":
                xs = [p[0] for p in s["pts"]]
                ys = [p[1] for p in s["pts"]]
                x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
            else:
                continue
            if w > W * 0.35 and h > 80:
                boxes.append((x + 10, y + 34, w - 20, h - 44))
        b_ = sorted(boxes, key=lambda t: (round(t[1], 1), t[0]))

        # (c) 큰 숫자만 덩그러니 있는 배치. 테두리도 색 띠도 없이 01 02 03 04로
        # 자리를 나누는 디자인이 실제로 많다. 번호 아래를 칸으로 본다.
        nums = []
        for s in self.shapes:
            if s["k"] != "text":
                continue
            t = s["s"].strip()
            if s["size"] >= 14 and re.fullmatch(r"\d{1,3}", t):
                nums.append({"x": s["x"], "y": s["y"], "h": s["h"], "n": int(t)})
        c_ = []
        if len(nums) >= 2:
            nums.sort(key=lambda s: (round(s["y"], 1), s["x"]))
            # 가까운 x끼리 한 열로 묶는다. 번호 폭 차이로 몇 pt씩 어긋난다
            cols = []
            for x in sorted(s["x"] for s in nums):
                if not cols or x - cols[-1] > 24:
                    cols.append(x)
            if len(cols) > 1:
                gaps = sorted(b - a2 for a2, b in zip(cols, cols[1:]))
                colw = gaps[len(gaps) // 2] - 14      # 중앙값. 최소값을 쓰면 너무 좁다
            else:
                colw = W - 2 * cols[0]
            for i, s in enumerate(nums):
                below = [t["y"] for t in nums
                         if t["y"] > s["y"] + 5 and abs(t["x"] - s["x"]) < 14]
                bottom = (min(below) - 16) if below else (H - 46)
                top = s["y"] + s["h"] + 6
                if bottom - top <= 60:
                    continue
                # 같은 줄 오른쪽 이웃을 넘지 않게 폭을 자른다
                right = [t["x"] for t in nums
                         if abs(t["y"] - s["y"]) < 12 and t["x"] > s["x"] + 20]
                wid = min(colw, (min(right) - s["x"] - 14) if right else colw)
                c_.append((s["x"], top, max(wid, 80), bottom - top))
            # 같은 자리가 두 번 잡히는 일이 있다
            seen, uniq = set(), []
            for t in c_:
                k = (round(t[0]), round(t[1]))
                if k not in seen:
                    seen.add(k); uniq.append(t)
            c_ = uniq

        cands = [("헤더 띠", a), ("빈 상자", b_), ("번호 격자", c_)]
        name, picked = max(cands, key=lambda t: len(t[1]))
        self._slot_mode = name
        return picked

    def shape_box(self, s):
        if s["k"] == "curve":
            xs = [q[0] for q in s["pts"]]; ys = [q[1] for q in s["pts"]]
            return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        if s["k"] == "rect":
            return s["x"], s["y"], s["w"], s["h"]
        if s["k"] == "line":
            return (min(s["x1"], s["x2"]), min(s["y1"], s["y2"]),
                    abs(s["x2"] - s["x1"]), abs(s["y2"] - s["y1"]))
        return s["x"], s["y"], s.get("w", 0), s.get("h", 0)

    def is_glyph_outline(self, s):
        """Type3 폰트로 만든 PDF는 글자가 벡터 외곽선으로도 그려져 있다.
        같은 글자가 텍스트로도 잡히므로 그대로 두면 이중으로 겹쳐 찍힌다."""
        if s["k"] not in ("curve", "line"):
            return False
        x, y, w, h = self.shape_box(s)
        if w > 260 or h > 70:
            return False                 # 이만큼 크면 글자가 아니라 디자인이다
        # 크기로 자르면 제목처럼 큰 글자를 놓친다. 글자 상자 안에 들어가는지로 본다
        for t in self._text_boxes:
            if (x >= t[0] - 2 and y >= t[1] - 2
                    and x + w <= t[2] + 2 and y + h <= t[3] + 2):
                return True
        return False

    def covered_by_filled_slot(self, s):
        """원본 텍스트가 이미 채운 칸 안에 있으면 그건 갈아 끼울 옛 내용이다.
        디자인 시안에는 '내용을 입력하세요' 대신 실제 예시 문장이 들어 있어서,
        그대로 두면 새 문제와 겹쳐 찍힌다."""
        if not self.striptext.get():
            return False
        bx, by, bw, bh = self.shape_box(s)
        cx, cy = bx + bw / 2.0, by + bh / 2.0
        for i, (x, y, w, h) in enumerate(self.slots):
            if x - 2 <= cx <= x + w + 2 and y - 2 <= cy <= y + h + 2:
                # 아직 안 채운 칸이면 원본을 남긴다. 지워 버리면 무엇이
                # 있던 자리인지 알 수 없다
                return bool(self.texts.get(i, "").strip())
        return False

    # ------------------------------------------------------------ 미리보기
    def page_image(self, view, px_w):
        """PDF 페이지를 그대로 구워 배경으로 쓴다.

        도형을 하나씩 다시 그리는 것보다 이쪽이 정확하다. 클리핑, 투명도,
        그라데이션, 글자 외곽선이 전부 원본대로 나온다.

        채운 칸의 원본 글자는 지워야 새 글과 겹치지 않는다. 캔버스에서 흰
        사각형으로 덮으면 무늬가 있는 칸에서 티가 나므로, 굽기 전에
        redaction으로 글자만 뺀다. 배경 무늬는 살아남는다.

        같은 화면이면 다시 굽지 않는다. 타이핑하는 동안은 캐시가 맞는다."""
        if Image is None or px_w < 8:
            return None
        path = self.pdf_path.get()
        if not path or not os.path.exists(path):
            return None
        vx0, vy0, vx1, vy1 = view
        # 어느 칸을 지울지가 바뀌면 다시 구워야 한다
        wipe = tuple(sorted(
            tuple(round(v, 1) for v in self.slots[i])
            for i in range(len(self.slots)) if self.texts.get(i, "").strip()
        )) if self.striptext.get() else ()
        key = (path, self.pageno.get(), self.side.get(), px_w,
               tuple(round(v, 1) for v in view), wipe)
        if key == self._bg_key and self._bg_img is not None:
            return self._bg_img

        doc = None
        try:
            doc = fitz.open(path)
            pno = self.pageno.get() - 1
            if pno >= doc.page_count:
                return None
            page = doc[pno]
            clip = self.clip_of(page)
            ox = clip[0] if clip else 0.0        # 슬롯 좌표는 반쪽 원점 기준이다
            oy = clip[1] if clip else 0.0
            if wipe:
                for x, y, w, h in wipe:
                    page.add_redact_annot(fitz.Rect(x + ox, y + oy,
                                                    x + w + ox, y + h + oy))
                # 이 PDF는 글자를 벡터 외곽선으로도 그린다. 텍스트 레이어만
                # 지우면 외곽선이 남아 옛 글자가 그대로 보인다. 칸 안에
                # 완전히 들어간 벡터까지 지운다
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                      graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)
            z = px_w / max(vx1 - vx0, 1e-6)
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z),
                                  clip=fitz.Rect(vx0 + ox, vy0 + oy,
                                                 vx1 + ox, vy1 + oy),
                                  alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            self.say(traceback.format_exc())
            return None
        finally:
            if doc is not None:
                doc.close()
        self._bg_key, self._bg_img = key, img
        return img

    def welcome(self):
        """PDF를 아직 안 골랐을 때 무엇을 해야 하는지 화면에 적는다.

        처음 여는 사람은 빈 회색 화면을 보고 무엇부터 할지 모른다. 실제로
        '테스트 어떻게 하냐, PDF가 없다'는 말을 들었다."""
        cv = self.canvas
        cv.delete("all")
        cw = max(cv.winfo_width(), 300)
        ch = max(cv.winfo_height(), 200)
        cx = cw / 2
        y = max(ch / 2 - 170, 24)
        cv.create_text(cx, y, text="디자인이 끝난 교재 PDF를 여세요",
                       font=("맑은 고딕", -22, "bold"), fill="#2b3a55")
        y += 46

        # 눌러야 할 것을 먼저 놓는다. 설명은 그 아래에 접어 둔다
        cv.create_rectangle(cx - 96, y, cx + 96, y + 42,
                            fill="#2f6fd0", outline="", tags="pickbtn")
        cv.create_text(cx, y + 21, text="교재 PDF 고르기", fill="#ffffff",
                       font=("맑은 고딕", -14, "bold"), tags="pickbtn")
        cv.tag_bind("pickbtn", "<Button-1>", lambda e: self.pick())
        y += 54

        if os.path.exists(sample_pdf()):
            cv.create_rectangle(cx - 96, y, cx + 96, y + 36,
                                fill="", outline="#8fb0e0", tags="demobtn")
            cv.create_text(cx, y + 18, text="예제로 해보기", fill="#2f6fd0",
                           font=("맑은 고딕", -13), tags="demobtn")
            cv.tag_bind("demobtn", "<Button-1>", lambda e: self.open_sample())
            y += 48

        if self.recent:
            y += 8
            cv.create_text(cx, y, text="최근에 연 파일", font=("맑은 고딕", -11),
                           fill="#8892a6")
            for i, q in enumerate(self.recent[:3]):
                y += 26
                cv.create_text(cx, y, text=os.path.basename(q),
                               font=("맑은 고딕", -12, "underline"), fill="#2f6fd0",
                               tags="recent%d" % i)
                cv.create_text(cx, y + 13, text=os.path.dirname(q)[-52:],
                               font=("맑은 고딕", -9), fill="#a3abbb")
                cv.tag_bind("recent%d" % i, "<Button-1>",
                            lambda e, w=q: (self.pdf_path.set(w), self.analyze()))
                y += 14

        y += 34
        cv.create_text(cx, y, text="쓰는 순서", font=("맑은 고딕", -11), fill="#8892a6")
        y += 22
        for line in (
            "1.  PDF를 열면 문제 칸을 스스로 찾습니다. 잘못 잡히면 손으로 그리면 됩니다.",
            "2.  칸을 누르고 오른쪽에 문제를 칩니다. 원고 파일을 불러올 수도 있습니다.",
            "3.  그래프나 그림은 그림 넣기 로 넣습니다. 아래 글이 알아서 밀립니다.",
            "4.  Ctrl+P 를 누르면 인쇄용 PDF가 나오고 바로 열립니다.",
        ):
            cv.create_text(cx - 240, y, text=line, anchor="w",
                           font=("맑은 고딕", -12), fill="#6b7689")
            y += 24
        self.status.config(text="PDF를 고르면 시작합니다")

    def open_sample(self):
        """딸려 온 예제 교재를 연다. 처음 받은 사람이 바로 눌러 볼 것."""
        p = sample_pdf()
        if not os.path.exists(p):
            messagebox.showwarning("", "예제 파일을 찾지 못했습니다.")
            return
        self.pdf_path.set(p)
        self.pageno.set(1)
        self.side.set("전체")
        self.analyze()
        self.say("예제 교재를 열었습니다. 전체 예시 를 누른 뒤 Ctrl+P 를 눌러 보세요.")

    def remember(self, path):
        """방금 연 PDF를 기억한다. 다음에 열면 첫 화면에서 바로 고를 수 있다."""
        if not path:
            return
        self.recent = [path] + [p for p in self.recent if p != path]
        self.recent = self.recent[:5]
        try:
            json.dump({"recent": self.recent},
                      open(os.path.join(core.work_dir(), "recent.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass

    def redraw(self):
        p = self.pdf_path.get()
        if not p or not os.path.exists(p) or not self.slots and not self.shapes:
            if not p or not os.path.exists(p):
                self.welcome()
                return
        cv = self.canvas
        cv.delete("all")
        cw = max(cv.winfo_width(), 200)
        ch = max(cv.winfo_height(), 200)
        m = 12

        zoom = self.zoomsel.get() and self.slots and self.sel < len(self.slots)
        if zoom:
            # 편집 중인 슬롯만 크게. 헤더 바까지 보이게 위아래로 조금 넓힌다
            sx, sy, sw, sh = self.slots[self.sel]
            vx0, vy0 = max(sx - 14, 0), max(sy - 34, 0)
            vx1, vy1 = min(sx + sw + 14, self.page_w), min(sy + sh + 14, self.page_h)
            vw, vh = vx1 - vx0, vy1 - vy0
            sc = min((cw - m * 2) / vw, (ch - m * 2) / vh)
            ox = (cw - vw * sc) / 2 - vx0 * sc
            oy = m - vy0 * sc
        else:
            vx0, vy0, vx1, vy1 = 0.0, 0.0, self.page_w, self.page_h
            sc = min((cw - m * 2) / self.page_w, (ch - m * 2) / self.page_h)
            ox = (cw - self.page_w * sc) / 2
            oy = m
        if sc <= 0:
            return
        self.scale = sc
        self.origin = (ox, oy)

        def X(v): return ox + v * sc
        def Y(v): return oy + v * sc

        # 배경은 PDF를 그대로 구운 이미지다. 벡터 보기를 켰을 때만 직접 그린다
        img = None
        if not self.showvec.get():
            img = self.page_image((vx0, vy0, vx1, vy1),
                                  int(round((vx1 - vx0) * sc)))
        if img is not None:
            self._bg_photo = ImageTk.PhotoImage(img)
            cv.create_image(X(vx0), Y(vy0), image=self._bg_photo, anchor="nw")
        else:
            cv.create_rectangle(X(0), Y(0), X(self.page_w), Y(self.page_h),
                                fill="white", outline="#b9b9c4")

        # HWPX에 들어갈 도형. 배경을 구웠으면 그릴 필요가 없다
        for s in (self.shapes if img is None else []):
            if self.striptext.get() and self.is_glyph_outline(s):
                continue
            if s["k"] == "rect":
                cv.create_rectangle(X(s["x"]), Y(s["y"]), X(s["x"] + s["w"]), Y(s["y"] + s["h"]),
                                    fill=s["fill"] or "", outline=s["stroke"] or "",
                                    width=max(s["lw"] * sc, 1) if s["stroke"] else 0)
            elif s["k"] == "line":
                col = s["stroke"] or "#000000"
                cv.create_line(X(s["x1"]), Y(s["y1"]), X(s["x2"]), Y(s["y2"]),
                               fill=col, width=max((s["lw"] or 0.5) * sc, 1))
            elif s["k"] == "curve":
                flat = []
                for px, py in s["pts"]:
                    flat += [X(px), Y(py)]
                if len(flat) >= 4:
                    if s["fill"]:
                        cv.create_polygon(flat, fill=s["fill"],
                                          outline=s["stroke"] or "",
                                          width=max((s["lw"] or 0) * sc, 1) if s["stroke"] else 0)
                    else:
                        cv.create_line(flat, fill=s["stroke"] or "#000000",
                                       width=max((s["lw"] or 0.5) * sc, 1))
            else:
                if self.covered_by_filled_slot(s):
                    continue
                # 맑은고딕은 실제 높이가 요청 크기의 1.36배라 원본 크기 그대로
                # 그리면 줄 간격을 넘어 윗줄과 겹친다
                fpx = s["size"] * sc * 0.78
                if fpx < 5.0:
                    # 이 배율에서 읽을 수 없는 크기다. 억지로 키우면 줄끼리 겹친다
                    cv.create_rectangle(X(s["x"]), Y(s["y"]) + 1,
                                        X(s["x"] + s["w"]), Y(s["y"] + s["h"]) - 1,
                                        fill="#c9ccd4", outline="")
                else:
                    cv.create_text(X(s["x"]), Y(s["y"] + s["h"]), text=s["s"], anchor="sw",
                                   font=("맑은 고딕", -int(round(fpx))),
                                   fill=s.get("color") or "#000000")

        # 슬롯 경계와 입력 내용
        for i, (x, y, w, h) in enumerate(self.slots):
            if self.showgrid.get():
                on = (i == self.sel)
                cv.create_rectangle(X(x), Y(y), X(x + w), Y(y + h),
                                    outline="#d43f3a" if on else "#9db8dd",
                                    width=2 if on else 1, dash=() if on else (4, 3))
                # 번호는 고른 칸에만. 전부 붙이면 원본 헤더 배지와 겹쳐 지저분하다
                if on:
                    # 본문은 위에서 아래로 차니 배지는 아래쪽 구석에 둔다
                    fs = max(int(7 * sc * 1.4), 9)
                    bw, bh = fs * 2.4, fs * 1.5
                    lx, ly = X(x + w) - bw - 3, Y(y + h) - bh - 3
                    cv.create_rectangle(lx, ly, lx + bw, ly + bh,
                                        fill="#d43f3a", outline="")
                    cv.create_text(lx + bw / 2, ly + bh / 2, text="%d" % i,
                                   fill="#ffffff", font=("맑은 고딕", -fs, "bold"))
            txt = self.texts.get(i, "").strip()
            if txt:
                parts = parse_markup(txt)
                psz = self.page_size()
                px = max(int(psz * sc), 6)
                _, iscale, _ = self.fit_size(parts, w, h, force_size=psz)
                end = pv.render_parts(cv, parts, X(x) + 4,
                                      Y(y) + 2 + (px * 0.2 if self.showgrid.get() else 0),
                                      w * sc - 8, px=px, tags=("body", "s%d" % i),
                                      lh=self.leading, iscale=iscale,
                                      drawimg=self.draw_image,
                                      bodyfont=pv.body_font(px, self.picked_font()))
                if end > Y(y + h):
                    cv.create_rectangle(X(x), Y(y), X(x + w), Y(y + h),
                                        outline="#e05a4f", width=2, dash=(2, 2))
                    cv.create_text(X(x + w) - 4, Y(y + h) - 4, anchor="se",
                                   text="넘침", fill="#e05a4f",
                                   font=("맑은 고딕", -max(int(9 * sc * 1.6), 9), "bold"))

        # 페이지 밖으로 나간 도형을 가린다. PDF는 페이지에서 잘리는데
        # 캔버스는 안 잘라서 배경이 삐져나와 지저분해 보인다
        big = 10000
        for a, b, c2, d2 in ((X(0) - big, Y(0) - big, X(0), Y(self.page_h) + big),
                             (X(self.page_w), Y(0) - big, X(self.page_w) + big, Y(self.page_h) + big),
                             (X(0) - big, Y(0) - big, X(self.page_w) + big, Y(0)),
                             (X(0) - big, Y(self.page_h), X(self.page_w) + big, Y(self.page_h) + big)):
            cv.create_rectangle(a, b, c2, d2, fill="#e9e9ee", outline="")
        cv.create_rectangle(X(0), Y(0), X(self.page_w), Y(self.page_h),
                            outline="#b9b9c4")

        if self._rubber:
            rx, ry, rw, rh = self._rubber
            cv.create_rectangle(X(rx), Y(ry), X(rx + rw), Y(ry + rh),
                                outline="#d43f3a", width=2, dash=(3, 2))

        filled = sum(1 for k, v in self.texts.items()
                     if k < len(self.slots) and v.strip())
        self.status.config(text="%s %.0f%%   채운 칸 %d / %d"
                                % ("%d번째 칸 확대" % (self.sel + 1) if zoom else "전체",
                                   sc * 100, filled, len(self.slots)))

    # ------------------------------------------------------------ 슬롯 손질
    def to_pt(self, ex, ey, frozen=None):
        """확대 모드에서는 뷰 원점이 고른 칸을 따라간다. 드래그 중에는
        시작 시점 좌표계로 계산해야 커서보다 멀리 날아가지 않는다."""
        ox, oy, sc = frozen if frozen else (self.origin[0], self.origin[1], self.scale)
        return (ex - ox) / sc, (ey - oy) / sc

    def hit(self, px, py):
        """점이 어느 슬롯 위인지. 우하단 모서리면 크기 조절로 본다."""
        for i in reversed(range(len(self.slots))):
            x, y, w, h = self.slots[i]
            if x <= px <= x + w and y <= py <= y + h:
                grip = 14 / max(self.scale, 0.01)
                if px > x + w - grip and py > y + h - grip:
                    return i, "resize"
                return i, "move"
        return None, None

    def select(self, i):
        self.sel = i
        if 0 <= i < len(self.slots):
            self._show_sel()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts.get(i, ""))

    def on_press(self, ev):
        if not hasattr(self, "origin"):
            return
        px, py = self.to_pt(ev.x, ev.y)
        i, mode = self.hit(px, py)
        if i is None:
            self._drag = {"mode": "new", "sx": px, "sy": py,
                          "fz": (self.origin[0], self.origin[1], self.scale)}
        else:
            self.select(i)
            self._drag = {"mode": mode, "sx": px, "sy": py, "orig": self.slots[i],
                          "fz": (self.origin[0], self.origin[1], self.scale)}
        self.redraw()

    def on_drag(self, ev):
        d = getattr(self, "_drag", None)
        if not d:
            return
        px, py = self.to_pt(ev.x, ev.y, d.get("fz"))
        if d["mode"] == "new":
            self._rubber = (min(d["sx"], px), min(d["sy"], py),
                            abs(px - d["sx"]), abs(py - d["sy"]))
        elif d["mode"] == "move":
            x, y, w, h = d["orig"]
            self.slots[self.sel] = (x + px - d["sx"], y + py - d["sy"], w, h)
        elif d["mode"] == "resize":
            x, y, w, h = d["orig"]
            self.slots[self.sel] = (x, y, max(w + px - d["sx"], 30), max(h + py - d["sy"], 24))
        self.redraw()

    def on_release(self, ev):
        d = getattr(self, "_drag", None)
        self._drag = None
        rub = getattr(self, "_rubber", None)
        self._rubber = None
        if d and d["mode"] == "new" and rub and rub[2] > 25 and rub[3] > 20:
            self.slots.append(rub)
            self.texts.pop(len(self.slots) - 1, None)   # 옛 글을 물려받지 않게
            self.reindex()
            self.select(len(self.slots) - 1)
            self.say("%d번째 칸을 새로 그렸습니다 (%.0f x %.0f pt)"
                 % (self.sel + 1, rub[2], rub[3]))
        self.redraw()

    def on_rclick(self, ev):
        if not hasattr(self, "origin"):
            return
        px, py = self.to_pt(ev.x, ev.y)
        i, _ = self.hit(px, py)
        if i is None:
            return
        if not messagebox.askyesno("", "%d번째 칸을 지울까요?" % (i + 1)):
            return
        self.slots.pop(i)
        self.texts.pop(i, None)
        for k in sorted([k for k in self.texts if k > i]):
            self.texts[k - 1] = self.texts.pop(k)
        self.sync_slots()
        self.select(self.sel)
        self.say("%d번째 칸을 지웠습니다." % (i + 1))
        self.redraw()

    def reindex(self):
        self._show_sel()

    def sync_slots(self, clear=False):
        """슬롯 개수가 바뀌면 남는 글과 선택 위치를 정리한다.
        texts 키가 위치 인덱스라 정리하지 않으면 글이 엉뚱한 칸으로 밀린다."""
        n = len(self.slots)
        if clear:
            dropped = len(self.texts)
            self.texts.clear()
        else:
            over = [k for k in self.texts if k >= n]
            for k in over:
                self.texts.pop(k)
            dropped = len(over)
        self.sel = min(self.sel, n - 1) if n else 0
        self.reindex()
        if self.slots:
            self._show_sel()
        else:
            self._show_sel()
        return dropped

    # ------------------------------------------------------------ 도움말
    def key_help(self, ev=None):
        self.show_help(); return "break"

    def show_help(self):
        if getattr(self, "_help", None) and self._help.winfo_exists():
            self._help.lift(); self._help.focus_force(); return
        w = tk.Toplevel(self.root)
        self._help = w
        w.title("도움말")
        w.geometry("760x640")
        w.minsize(620, 480)
        w.transient(self.root)
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        def sheet(parent):
            fr = ttk.Frame(parent)
            cv = tk.Canvas(fr, highlightthickness=0, bg="#ffffff")
            sb = ttk.Scrollbar(fr, orient="vertical", command=cv.yview)
            inner = ttk.Frame(cv)
            win = cv.create_window((0, 0), window=inner, anchor="nw")
            inner.bind("<Configure>",
                       lambda e: cv.configure(scrollregion=cv.bbox("all")))
            # 내용이 창 폭을 다 쓰도록 맞춘다. 안 하면 오른쪽이 비어 보인다
            cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
            cv.configure(yscrollcommand=sb.set)
            cv.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            # bind_all로 걸면 도움말을 닫은 뒤에도 메인 창이 이 휠을 먹는다
            cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
            inner.bind("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
            return fr, inner

        # --- 단축키
        f1, k = sheet(nb)
        nb.add(f1, text="단축키")
        ttk.Label(k, text="한글에서 쓰던 키를 그대로 가져왔습니다.",
                  font=("맑은 고딕", 10, "bold")).grid(row=0, column=0, columnspan=2,
                                                     sticky="w", padx=12, pady=(10, 8))
        r = 1
        for name, seq in self.keys.items():
            pretty = (seq.strip("<>").replace("Control-", "Ctrl+").replace("Alt-", "Alt+")
                      .replace("Shift-", "Shift+").replace("Return", "Enter"))
            if len(pretty) == 1:
                pretty = pretty.upper()
            ttk.Label(k, text=pretty, font=("Consolas", 10),
                      foreground="#1a4f8a").grid(row=r, column=0, sticky="w", padx=(18, 16), pady=3)
            ttk.Label(k, text=KEY_HELP.get(name, name)).grid(row=r, column=1, sticky="w", pady=3)
            r += 1
        ttk.Label(k, text="이 파일을 고치면 키가 바뀝니다.",
                  foreground="#666666").grid(row=r, column=0, columnspan=2,
                                             sticky="w", padx=12, pady=(14, 2))
        e = ttk.Entry(k, width=74)
        e.insert(0, self.keys_path)
        e.configure(state="readonly")
        e.grid(row=r + 1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 14))

        # --- 쓰는 순서
        f2, u = sheet(nb)
        nb.add(f2, text="쓰는 순서")
        steps = [
            ("1. 레이아웃 PDF 열기",
             "디자이너가 만든 빈 교재 PDF를 고릅니다. 도형과 글자를 읽어 문제 칸을 찾아\n"
             "왼쪽 미리보기에 겹쳐 보여줍니다. 쪽과 면(좌면 우면)을 지정할 수 있습니다."),
            ("2. 칸이 틀렸으면 손으로 고치기",
             "빈 곳을 끌면 새 칸이 그려집니다. 칸 안쪽을 끌면 옮겨지고, 오른쪽 아래\n"
             "모서리를 끌면 크기가 바뀝니다. 오른쪽 버튼으로 지웁니다."),
            ("3. 선생님 원고 불러오기",
             "hwp, hwpx, txt를 읽어 문항과 수식을 뽑습니다. 목록에서 두 번 누르면\n"
             "고른 칸에 들어가고, 순서대로 채우기를 누르면 한 번에 배분됩니다."),
            ("4. 자료 그림 넣기",
             "그래프나 실험 그림을 넣습니다. 미리보기 아래 '그림 넣기' 를 누르면\n"
             "커서 자리에 들어가고 아래 글이 자동으로 밀립니다. 칸을 넘치면\n"
             "그림을 먼저 줄이고, 그래도 안 되면 글자를 줄입니다. 글자 크기는\n"
             "한 쪽 안에서 같아야 하므로 마지막에 손댑니다.\n"
             "[[img:경로|70]] 처럼 뒤에 숫자를 적으면 칸 폭의 70%로 넣습니다.\n"
             "[[img:경로|38|r]] 처럼 r 을 붙이면 그림이 오른쪽에 붙고 글이\n"
             "그 옆으로 흐릅니다. l 이면 왼쪽입니다. 수능 과학 문제지에서\n"
             "그림 절반가량이 이렇게 들어갑니다."),
            ("5. 보기 상자",
             "과학 문제는 대부분 보기 상자를 낍니다. 이렇게 적습니다.\n\n"
             "    [[보기]]\n"
             "    ㄱ. 파장은 2 cm이다.\n"
             "    ㄴ. P는 보강 간섭점이다.\n"
             "    [[/보기]]\n\n"
             "테두리와 <보 기> 라벨이 자동으로 붙습니다. 수능 문제지에서 잰\n"
             "규격 그대로입니다. [[자료]] 로 열면 라벨 없는 상자가 됩니다."),
            ("6. 칸 배치 재사용",
             "위쪽 '칸 배치' 에서 지금 칸을 파일로 저장해 두었다가 다른 쪽이나\n"
             "다른 PDF에 그대로 얹을 수 있습니다. 교재는 매주 새 문항이\n"
             "들어가므로, 디자이너가 잡아 준 칸을 자산으로 두고 내용만\n"
             "갈아 끼우는 쪽이 빠릅니다. 폰트와 크기와 행간도 같이 갑니다."),
            ("9. 손질하기",
             "달러 기호 사이가 수식입니다. 타이핑하는 동안 왼쪽이 바로 갱신됩니다.\n"
             "칸보다 글이 길면 글자를 줄여 맞추고, 그래도 넘치면 알려 줍니다."),
            ("6. 인쇄용 PDF (Ctrl+P)",
             "인쇄소에 그대로 내는 파일입니다. 원본 디자인을 뜯지 않고 통째로 깐 뒤\n"
             "글만 얹으므로 화질 손실이 0입니다. 굽는 단계가 없어 dpi를 고를 일도\n"
             "없고, 원본의 색과 폰트와 투명도가 그대로 남습니다."),
            ("7. HWPX 만들기 (Ctrl+B)",
             "강사가 한글에서 열어 고칠 파일입니다. 원고를 손볼 사람에게 넘길 때\n"
             "씁니다. 한글로 열어 확인을 누르면 실제로 열어 PDF로 뽑아 보여줍니다."),
        ]
        for i, (t, d) in enumerate(steps):
            ttk.Label(u, text=t, font=("맑은 고딕", 10, "bold")).grid(
                row=i * 2, column=0, sticky="w", padx=14, pady=(12, 2))
            ttk.Label(u, text=d, justify="left", foreground="#444444").grid(
                row=i * 2 + 1, column=0, sticky="w", padx=26)
        ttk.Label(u, text="작업은 저장됩니다. Ctrl+S 로 dhp 파일에 담고 Ctrl+O 로 엽니다.",
                  foreground="#1a4f8a").grid(row=99, column=0, sticky="w", padx=14, pady=16)

        # --- 수식
        f3, q = sheet(nb)
        nb.add(f3, text="수식 쓰는 법")
        ttk.Label(q, text="한글 수식 편집기 문법을 그대로 씁니다. 달러 기호 사이에 적으세요.",
                  font=("맑은 고딕", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                     sticky="w", padx=12, pady=(10, 8))
        for i, (name, code, note) in enumerate(EQ_GUIDE):
            ttk.Label(q, text=name).grid(row=i + 1, column=0, sticky="w", padx=(18, 12), pady=3)
            ttk.Label(q, text=code, font=("Consolas", 10),
                      foreground="#1a4f8a").grid(row=i + 1, column=1, sticky="w", pady=3)
            ttk.Label(q, text=note, foreground="#777777").grid(row=i + 1, column=2,
                                                              sticky="w", padx=(14, 12), pady=3)
        base = len(EQ_GUIDE) + 2
        ttk.Label(q, text="자주 걸리는 함정", font=("맑은 고딕", 10, "bold")).grid(
            row=base, column=0, columnspan=3, sticky="w", padx=12, pady=(16, 6))
        for i, t in enumerate(EQ_TRAPS):
            ttk.Label(q, text="· " + t, justify="left", foreground="#444444",
                      wraplength=660).grid(row=base + 1 + i, column=0, columnspan=3,
                                           sticky="w", padx=20, pady=2)

        ttk.Button(w, text="닫기", command=w.destroy).pack(pady=(0, 10))
        w.bind("<Escape>", lambda e: w.destroy())

    # ------------------------------------------------------------ 저장과 단축키
    def bind_keys(self):
        for name, seq in self.keys.items():
            fn = getattr(self, "key_" + name, None)
            if not fn or not seq:
                continue
            try:
                self.root.bind_all(seq, fn)
            except Exception:
                self.say("단축키를 걸지 못했습니다: %s = %s" % (name, seq))

    def key_save(self, ev=None):
        self.save_project(); return "break"

    def key_open(self, ev=None):
        self.open_project(); return "break"

    def key_manuscript(self, ev=None):
        self.load_manuscript(); return "break"

    def key_analyze(self, ev=None):
        self.analyze(); return "break"

    def key_buildpdf(self, ev=None):
        self.build_pdf()
        return "break"

    def key_build(self, ev=None):
        self.build(); return "break"

    def key_verify(self, ev=None):
        self.verify(); return "break"

    def key_zoom(self, ev=None):
        self.zoomsel.set(not self.zoomsel.get()); self.redraw(); return "break"

    def key_toggle_log(self, ev=None):
        self.log_shown = not getattr(self, "log_shown", True)
        if self.log_shown:
            self.log.pack(fill="x", padx=8, pady=(0, 8))
        else:
            self.log.pack_forget()
        return "break"

    def key_next_slot(self, ev=None):
        if self.slots:
            self.select((self.sel + 1) % len(self.slots)); self.redraw()
        return "break"

    def key_prev_slot(self, ev=None):
        if self.slots:
            self.select((self.sel - 1) % len(self.slots)); self.redraw()
        return "break"

    def key_equation(self, ev=None):
        self.editor.insert("insert", "$$")
        self.editor.mark_set("insert", "insert-1c")
        self.on_type()
        return "break"

    def key_circled(self, ev=None):
        """커서 앞 한 글자를 다음 형태로 바꾼다. 한글 상용구 순환과 같다."""
        try:
            ch = self.editor.get("insert-1c", "insert")
        except Exception:
            return "break"
        if not ch:
            return "break"
        nx = next_circled(ch)
        if nx != ch:
            self.editor.delete("insert-1c", "insert")
            self.editor.insert("insert", nx)
            self.on_type()
        return "break"

    def project_data(self):
        """작업 전체를 담는다. 예전에는 지금 쪽 하나만 담아서, 여러 쪽을
        채워 놓고 저장해도 한 쪽만 남았다."""
        pages = {}
        for (path, pno, side), st in self.pages.items():
            if path != self.pdf_path.get() or side != self.side.get():
                continue
            if not st["slots"] and not any(v.strip() for v in st["texts"].values()):
                continue
            pages[str(pno)] = {"slots": [list(s) for s in st["slots"]],
                               "texts": {str(k): v for k, v in st["texts"].items()}}
        return {
            "pdf": self.pdf_path.get(), "page": self.pageno.get(), "side": self.side.get(),
            "pages": pages,
            # 옛 판으로 열어도 지금 쪽은 살도록 남겨 둔다
            "slots": [list(s) for s in self.slots],
            "texts": {str(k): v for k, v in self.texts.items()},
            "manuscript": getattr(self, "ms_path", ""),
            "font": self.fontname.get(), "size": self.bodysize.get(),
            "leading": self.leading,
        }

    # ------------------------------------------------------------ 칸 배치 자산
    def save_layout(self):
        """칸 배치만 따로 저장한다.

        학원 교재는 한 번 만들고 끝이 아니라 매주 새 문항이 들어간다.
        디자이너가 잡아 준 칸 배치를 자산으로 두고 내용만 갈아 끼우는 것이
        이 도구의 쓸모다. 그래서 원고와 칸을 분리해 둔다."""
        if not self.slots:
            messagebox.showwarning("", "먼저 레이아웃을 분석하거나 칸을 그리세요.")
            return
        p = filedialog.asksaveasfilename(
            title="칸 배치 저장", defaultextension=".dlay", initialdir=OUTDIR,
            filetypes=[("칸 배치", "*.dlay")])
        if not p:
            return
        json.dump({"slots": [list(s) for s in self.slots],
                   "page_w": self.page_w, "page_h": self.page_h,
                   "font": self.picked_font(), "size": self.bodysize.get(),
                   "leading": self.leading},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        self.say("칸 배치를 저장했습니다: %s (칸 %d개)" % (p, len(self.slots)))
        self.announce(p, "칸 %d개" % len(self.slots))

    def load_layout(self):
        """저장해 둔 칸 배치를 지금 쪽에 얹는다. 내용은 건드리지 않는다."""
        p = filedialog.askopenfilename(title="칸 배치 불러오기", initialdir=OUTDIR,
                                       filetypes=[("칸 배치", "*.dlay")])
        if not p:
            return
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            self.say(traceback.format_exc()); return
        pw, ph = d.get("page_w", 0), d.get("page_h", 0)
        if pw and ph and (abs(pw - self.page_w) > 2 or abs(ph - self.page_h) > 2):
            if not messagebox.askyesno(
                    "쪽 크기가 다릅니다",
                    "저장할 때는 %.0f x %.0f mm 였고 지금은 %.0f x %.0f mm 입니다.\n"
                    "칸 위치가 안 맞을 수 있습니다. 그래도 얹을까요?"
                    % (pw * 25.4 / 72, ph * 25.4 / 72,
                       self.page_w * 25.4 / 72, self.page_h * 25.4 / 72)):
                return
        self.slots = [tuple(s) for s in d.get("slots", [])]
        if d.get("font"):
            self.fontname.set(d["font"])
        if d.get("size"):
            self.bodysize.set(d["size"])
        if d.get("leading"):
            self.leading = d["leading"]
        self.sync_slots()
        self.reindex()
        self._psize_key = None
        self.redraw()
        self.say("칸 배치를 얹었습니다: 칸 %d개, %s %.1fpt"
                 % (len(self.slots), self.picked_font(), self.bodysize.get()))

    def save_project(self):
        p = filedialog.asksaveasfilename(
            title="작업 저장", defaultextension=".dhp",
            initialdir=OUTDIR, filetypes=[("조판 작업", "*.dhp")])
        if not p:
            return
        json.dump(self.project_data(), open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        self.proj_path = p
        self.say("작업 저장: %s" % p)

    def open_project(self, path=""):
        p = path or filedialog.askopenfilename(title="작업 열기", initialdir=OUTDIR,
                                               filetypes=[("조판 작업", "*.dhp")])
        if not p:
            return
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            self.say(traceback.format_exc()); return
        self.pdf_path.set(d.get("pdf", ""))
        self.pageno.set(d.get("page", 1))
        self.side.set(d.get("side", "전체"))
        saved_font = d.get("font", "")
        saved_size = d.get("size", 0)
        saved_lead = d.get("leading", 0)
        # 분석에 실패하면 직전 페이지의 도형이 남아 화면과 결과가 어긋난다
        self.shapes = []
        self._target = None
        if os.path.exists(self.pdf_path.get()):
            self.analyze()
        else:
            self.say("PDF를 찾지 못했습니다: %s" % self.pdf_path.get())
            messagebox.showwarning("", "레이아웃 PDF를 찾지 못했습니다.\n경로를 다시 지정하고 분석하세요.")
        # 저장해 둔 조판 값이 있으면 분석이 잰 값보다 그쪽을 따른다
        if saved_font:
            self.fontname.set(saved_font)
            if saved_font not in (self.fontbox["values"] or ()):
                self.fontbox["values"] = list(self.fontbox["values"] or ()) + [saved_font]
        if saved_size:
            self.bodysize.set(saved_size)
        if saved_lead:
            self.leading = saved_lead
        if not self.shapes:
            self.say("  도형이 없습니다. 이대로 만들면 글만 들어갑니다.")
        side = self.side.get()
        got = d.get("pages") or {}
        if got:
            for k, st in got.items():
                key = (self.pdf_path.get(), int(k), side)
                self.pages[key] = {
                    "slots": [tuple(s) for s in st.get("slots", [])],
                    "texts": {int(i): v for i, v in st.get("texts", {}).items()},
                }
        else:
            # 옛 판 작업 파일. 한 쪽만 들어 있다
            self.slots = [tuple(s) for s in d.get("slots", [])]
            self.texts = {int(k): v for k, v in d.get("texts", {}).items()}
        self.sync_slots()
        mp = d.get("manuscript", "")
        if mp and os.path.exists(mp):
            self._read_manuscript(mp)
        self.select(0)
        self._psize_key = None
        self.redraw()
        self.proj_path = p
        done = self.filled_pages()
        self.say("작업 열기: %s (칸 %d, 채운 칸 %d)"
                 % (p, len(self.slots), sum(1 for v in self.texts.values() if v.strip())))
        if len(done) > 1:
            self.say("  글이 든 쪽: %s"
                     % ", ".join("%d쪽 %d칸" % (pno, n) for pno, n in done))

    # ------------------------------------------------------------ 원고
    def load_manuscript(self):
        p = filedialog.askopenfilename(
            title="선생님 원고를 고르세요",
            filetypes=[("원고", "*.hwp *.hwpx *.txt"), ("모든 파일", "*.*")])
        if not p:
            return
        self._read_manuscript(p)

    def _read_manuscript(self, p):
        try:
            # 원고에 든 그림은 작업 폴더 옆에 풀어 둔다. 원고마다 따로 담아야
            # 다른 원고를 열었을 때 그림이 섞이지 않는다
            imgdir = os.path.join(OUTDIR, "원고그림",
                                  re.sub(r"[^\w가-힣.-]+", "_", os.path.basename(p))[:60])
            self.problems = ms.load(p, imgdir)
        except Exception:
            self.say(traceback.format_exc())
            messagebox.showerror("", "원고를 읽지 못했습니다. 로그를 보세요.")
            return
        self.ms_path = p
        self.problist.delete(0, "end")
        n_eq = n_img = 0
        for i, pr in enumerate(self.problems):
            t = ms.parts_to_markup(pr["parts"])
            n_eq += t.count("$") // 2 + sum(1 for q in pr["parts"] if "eq" in q)
            n_img += t.count("[[img:")
            self.problist.insert("end", "%s. %s" % (pr["no"] or (i + 1), readable(t)[:70]))
        self.mlabel.config(text="%s  문항 %d개, 수식 %d개, 그림 %d개"
                                % (os.path.basename(p), len(self.problems), n_eq, n_img))
        if not self.problems:
            self.say("문항을 찾지 못했습니다. 개념 정리 파일이거나 번호가 없는 원고일 수 있습니다.")
            messagebox.showinfo("", "문항을 찾지 못했습니다.\n"
                                    "문제 파일이 맞는지 확인해 보세요.\n"
                                    "개념 정리 파일에는 문항이 없습니다.")
            return
        self.say("원고 읽음: %s (문항 %d, 수식 %d, 그림 %d). 목록을 두 번 누르면 고른 칸에 들어갑니다."
                 % (os.path.basename(p), len(self.problems), n_eq, n_img))

    def put_problem(self, ev=None):
        s = self.problist.curselection()
        if not s or not self.slots:
            return
        pr = self.problems[s[0]]
        self.texts[self.sel] = ms.parts_to_markup(pr["parts"])
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts[self.sel])
        self.redraw()
        self.say("문항 %s 를 %d번째 칸에 넣었습니다." % (pr["no"] or s[0] + 1, self.sel + 1))

    def autofill(self):
        if not getattr(self, "problems", None):
            messagebox.showwarning("", "먼저 원고를 불러오세요.")
            return
        if not self.slots:
            messagebox.showwarning("", "먼저 레이아웃을 분석하세요.")
            return
        n = min(len(self.problems), len(self.slots))
        for i in range(n):
            self.texts[i] = ms.parts_to_markup(self.problems[i]["parts"])
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts.get(self.sel, ""))
        self.redraw()
        self.say("문항 %d개를 칸에 채웠습니다. 남은 문항 %d개."
                 % (n, len(self.problems) - n))

    # ------------------------------------------------------------ 편집
    def on_type(self, ev=None):
        self.texts[self.sel] = self.editor.get("1.0", "end-1c")
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(220, self.redraw)

    def _show_sel(self):
        """지금 고른 칸을 글로 알린다. 사람은 1번부터 센다."""
        if not self.slots:
            self.sellabel.config(text="칸이 없습니다")
        elif 0 <= self.sel < len(self.slots):
            self.sellabel.config(text="%d번째 칸  (%d개 중)"
                                       % (self.sel + 1, len(self.slots)))
        else:
            self.sellabel.config(text="칸을 누르세요")

    def switch_slot(self, ev=None):
        pass
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts.get(self.sel, ""))
        self.redraw()

    def insert_eq(self, code):
        self.editor.insert("insert", "$%s$" % code)
        self.on_type()

    def fill_sample(self):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", SAMPLES[self.sel % len(SAMPLES)])
        self.on_type()

    def fill_all(self):
        for i in range(len(self.slots)):
            self.texts[i] = SAMPLES[i % len(SAMPLES)]
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts.get(self.sel, ""))
        self.redraw()
        self.say("칸 %d개에 예시를 넣었습니다." % len(self.slots))

    def insert_image(self):
        """자료 그림을 커서 자리에 넣는다. 그래프나 실험 그림처럼 과학 문제에
        꼭 붙는 것들이다. 넣으면 아래 글이 자동으로 밀린다."""
        p = filedialog.askopenfilename(
            title="자료 그림 고르기",
            filetypes=[("그림", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")])
        if not p:
            return
        at = self.editor.index("insert")
        # 그림은 한 줄을 통째로 쓴다. 쓰던 줄 중간이면 줄을 먼저 바꿔 준다
        head = self.editor.get("insert linestart", "insert")
        pre = "\n" if head.strip() else ""
        self.editor.insert(at, pre + "[[img:%s]]\n" % p)
        self.on_type()

    def draw_image(self, x, y, w, h, path, tags=()):
        """미리보기에 그림을 그린다. 화면 배율에 맞춰 그때그때 줄인다."""
        if Image is None:
            return
        key = (path, int(w), int(h))
        photo = self._photos.get(key)
        if photo is None:
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im = im.resize((max(int(w), 1), max(int(h), 1)), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(im)
            except Exception:
                return
            if len(self._photos) > 60:
                self._photos.clear()
            self._photos[key] = photo
        self.canvas.create_image(x, y, image=photo, anchor="nw", tags=tags)

    def clear_slot(self):
        self.texts[self.sel] = ""
        self.editor.delete("1.0", "end")
        self.redraw()

    # ------------------------------------------------------------ 생성
    def size_steps(self):
        base = self.bodysize.get()
        return tuple(x for x in (base,) + pp.STEPS if x <= base) or (base,)

    def fit_size(self, parts, w_pt, h_pt, force_size=None):
        """칸에 들어가는 (글자 크기, 그림 배율, 그래도 넘치는가).

        그림을 먼저 줄이고 글자는 마지막에 손댄다. 다만 그림을 줄이면 그 안의
        축 이름과 눈금 숫자도 같이 줄어든다. 그래서 그림 하한을 65%로 둔다.
        더 줄이면 그래프 눈금을 못 읽는다."""
        steps = (force_size,) if force_size else self.size_steps()
        has_img = any("img" in p for p in parts)
        cv = tk.Canvas(self.root)          # 화면에 붙이지 않는 측정용
        try:
            def end_at(size, iscale):
                cv.delete("all")
                return pv.render_parts(cv, parts, 0, 0, w_pt - 8, px=size,
                                       lh=self.leading, iscale=iscale,
                                       bodyfont=pv.body_font(size, self.picked_font()))
            limit = h_pt - 6
            if end_at(steps[0], 1.0) <= limit:
                return steps[0], 1.0, False
            if has_img:
                for iscale in pp.IMG_STEPS[1:]:
                    if end_at(steps[0], iscale) <= limit:
                        return steps[0], iscale, False
            small = pp.IMG_MIN if has_img else 1.0
            for size in steps[1:]:
                if end_at(size, small) <= limit:
                    return size, small, False
            return steps[-1], small, True
        finally:
            cv.destroy()

    def page_size(self):
        """지면 전체에서 쓸 글자 크기. 가장 빡빡한 칸에 맞춘다.

        칸마다 따로 정하면 한 쪽 안에서 문항마다 크기가 달라진다. 학생은 그
        차이를 뜻으로 읽는다. 매번 다시 재면 느리므로 글을 고칠 때만 다시 잰다."""
        key = (self.bodysize.get(), round(self.leading, 3), self.picked_font(),
               tuple(sorted((i, v) for i, v in self.texts.items() if v.strip())),
               tuple(tuple(round(v, 1) for v in s) for s in self.slots))
        if key != self._psize_key:
            worst = self.size_steps()[0]
            for i, (x, y, w, h) in enumerate(self.slots):
                t = self.texts.get(i, "").strip()
                if t:
                    worst = min(worst, self.fit_size(parse_markup(t), w, h)[0])
            self._psize, self._psize_key = worst, key
        return self._psize

    def build(self):
        try:
            if not self.slots:
                messagebox.showwarning("", "먼저 레이아웃을 분석하세요.")
                return
            tpl = core.template_path()
            table = core.StyleTable(core.base_charpr_count(tpl))
            xml, z = [], 0
            for s in self.shapes:
                if self.striptext.get() and self.is_glyph_outline(s):
                    continue
                if s["k"] == "rect":
                    xml.append(core.rect_xml(s["x"], s["y"], s["w"], s["h"],
                                             fill=s["fill"], stroke=s["stroke"], lw=s["lw"], z=z))
                elif s["k"] == "line":
                    xml.append(core.line_xml(s["x1"], s["y1"], s["x2"], s["y2"],
                                             stroke=s["stroke"] or "#000000",
                                             lw=s["lw"] or 0.5, z=z))
                elif s["k"] == "curve":
                    xml.append(core.curve_xml(s["pts"], fill=s["fill"], stroke=s["stroke"],
                                              lw=s["lw"], close=s.get("close", False), z=z))
                else:
                    if self.covered_by_filled_slot(s):
                        z += 1
                        continue
                    # 원본 글자의 폰트, 크기, 색을 그대로 재현한다
                    cp = table.from_span(s.get("font", ""), s["size"],
                                         int(s.get("color", "#000000")[1:], 16),
                                         s.get("italic", False))
                    inner = core.paras_from_parts([{"t": s["s"]}], char_pr=cp,
                                                  width_hu=core.hu(s["w"] + 8))
                    xml.append(core.rect_xml(s["x"] - 1, s["y"] - 2, s["w"] + 8, s["h"] + 6,
                                             fill=None, stroke=None, lw=0, z=z, inner=inner))
                z += 1
            n_eq = 0
            for i, (x, y, w, h) in enumerate(self.slots):
                txt = self.texts.get(i, "").strip()
                if not txt:
                    continue
                parts = parse_markup(txt)
                n_eq += count_eq(parts)
                size, iscale, over = self.fit_size(parts, w, h,
                                                   force_size=self.page_size())
                if over:
                    self.say("  %d번째 칸은 약 %d자 넘칩니다. 그만큼 줄이거나 칸을 키우세요."
                             % (i + 1, nch))
                if iscale < 1.0:
                    self.say("  %d번째 칸 그림을 %d%%로 줄였습니다." % (i + 1, iscale * 100))
                if size < self.bodysize.get():
                    self.say("  %d번째 칸 글자를 %.1fpt로 줄였습니다." % (i + 1, size))
                cp = table.get(self.picked_font(), False, size, "#1A1A1A")
                inner = core.paras_from_parts(parts, char_pr=cp, width_hu=core.hu(w))
                xml.append(core.rect_xml(x, y, w, h, fill=None, stroke=None, lw=0, z=z, inner=inner))
                z += 1
            section = core.build_section("".join(xml), self.page_w, self.page_h)
            out = os.path.join(OUTDIR, "실습결과.hwpx")
            core.write_hwpx(tpl, section, out, style_table=table)
            self.say("HWPX 저장: %s (%.1f KB, 도형 %d, 수식 %d)"
                     % (out, os.path.getsize(out) / 1024, z, n_eq))
            self.announce(out, "%.0f KB · 수식 %d" % (os.path.getsize(out) / 1024, n_eq))
            self.say("  글자모양 %d개, 폰트 %d종" % (len(table.rows), len(table.fonts)))
            import tkinter.font as tkf
            installed = set(tkf.families())
            missing = [f for f in table.fonts if f not in installed]
            for f in table.fonts:
                self.say("    %s %s" % ("O" if f not in missing else "X", f))
            if missing:
                self.say("  없는 폰트는 한글이 임의로 대체합니다. 원본대로 나오려면 설치하세요.")
                self.say("  Pretendard: github.com/orioncactus/pretendard/releases")
                self.say("  나눔글꼴: hangeul.naver.com/font    NEXON Lv1 Gothic: brand.nexon.com")
        except Exception:
            self.say(traceback.format_exc())

    def build_pdf(self):
        """인쇄용 PDF. 원본 디자인을 뜯지 않고 통째로 깐 뒤 글만 얹는다.

        굽는 단계가 없어서 dpi를 고를 일이 없다. 클리핑과 투명도와 그라데이션과
        CMYK와 임베드 폰트가 전부 원본 그대로 남는다. 인쇄소에 그대로 낸다."""
        try:
            if not self.slots:
                messagebox.showwarning("", "먼저 레이아웃을 분석하세요.")
                return
            filled = {i: parse_markup(self.texts.get(i, ""))
                      for i in range(len(self.slots)) if self.texts.get(i, "").strip()}
            if not filled:
                messagebox.showinfo("", "채운 칸이 없습니다.")
                return
            out = os.path.join(OUTDIR, "인쇄용.pdf")
            shrunk = pp.build(self.pdf_path.get(), self.pageno.get() - 1,
                              self.slots, filled, out,
                              fontpath=self.picked_font(),
                              base_size=self.bodysize.get(), lh=self.leading)
            info = pp.report(out)
            self.say("인쇄용 PDF를 만들었습니다.")
            self.say("  %s  (%.0f KB)" % (out, info["bytes"] / 1024))
            self.announce(out, "%.0f KB · 이미지 %d개" % (info["bytes"] / 1024, info["images"]))
            self.say("  %.1f x %.1f mm, 이미지 %d개, 글자 %d자"
                     % (info["size_mm"][0], info["size_mm"][1], info["images"], info["chars"]))
            if info["images"] == 0:
                self.say("  이미지 0개. 원본 디자인이 벡터 그대로 들어갔습니다.")
            for row in shrunk:
                i, size, iscale, over = row[0], row[1], row[2], row[3]
                nch = row[4] if len(row) > 4 else 0
                bits = []
                if iscale < 1.0:
                    bits.append("그림 %d%%" % round(iscale * 100))
                if size < self.bodysize.get():
                    bits.append("글자 %.1fpt" % size)
                if bits:
                    self.say("  %d번째 칸을 %s 로 맞췄습니다." % (i + 1, ", ".join(bits)))
                if over:
                    self.say("  %d번째 칸은 약 %d자 넘칩니다." % (i + 1, nch))
        except Exception:
            self.say(traceback.format_exc())

    def verify(self):
        threading.Thread(target=self._verify, daemon=True).start()

    def _verify(self):
        try:
            src = os.path.join(OUTDIR, "실습결과.hwpx")
            if not os.path.exists(src):
                self.say("먼저 HWPX를 만드세요.")
                return
            pdf = os.path.join(OUTDIR, "실습결과_검증.pdf")
            self.say("한글 기동")
            import pythoncom
            import win32com.client.gencache as gencache
            pythoncom.CoInitialize()
            hwp = gencache.EnsureDispatch("HWPFrame.HwpObject")
            try:
                hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            except Exception:
                pass
            ok = hwp.Open(os.path.abspath(src), "HWPX", "")
            txt = ""
            try:
                txt = hwp.GetTextFile("TEXT", "")
            except Exception:
                pass
            if os.path.exists(pdf):
                os.remove(pdf)
            hwp.SaveAs(os.path.abspath(pdf), "PDF", "")
            hwp.Clear(1); hwp.Quit()
            pythoncom.CoUninitialize()
            d = fitz.open(pdf)
            p = d[0]
            self.say("열림 %s · 추출 텍스트 %d자 · 벡터 %d · 이미지 %d"
                     % (ok, len(txt), len(p.get_drawings()), len(p.get_images())))
            d.close()
            os.startfile(pdf)
        except Exception:
            self.say(traceback.format_exc())


def selftest():
    from preview import parse_script
    for i, s in enumerate(SAMPLES):
        p = parse_markup(s)
        print("샘플%d parts=%d 수식=%d" % (i, len(p), count_eq(p)))
        for q in p:
            if "eq" in q:
                node = parse_script(q["eq"])
                print("   파싱된 수식 노드 수:", len(node[1]))
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        root = tk.Tk()
        app = App(root)
        if DEFAULT_PROJ and os.path.exists(DEFAULT_PROJ):
            root.after(300, lambda: app.open_project(DEFAULT_PROJ))
        elif DEFAULT_PDF:
            root.after(300, app.analyze)
        if "--demo" in sys.argv:
            def run():
                app.analyze()
                app.fill_all()
                root.update()
                try:            # 스크린샷은 문서용이라 없어도 그만이다
                    from PIL import ImageGrab
                    import time
                    root.attributes("-topmost", True); root.lift(); root.focus_force()
                    root.update(); time.sleep(0.7); root.update()
                    x, y = root.winfo_rootx(), root.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()),
                                   all_screens=True).save(os.path.join(OUTDIR, "gui_미리보기.png"))
                except Exception as e:
                    app.say("스크린샷 건너뜀: %s" % e)
                app.build()
                with open(os.path.join(OUTDIR, "gui_demo_log.txt"), "w", encoding="utf-8") as f:
                    f.write(app.log.get("1.0", "end"))
                root.after(600, root.destroy)
            root.after(700, run)
        root.mainloop()
