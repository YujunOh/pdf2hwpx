# -*- coding: utf-8 -*-
"""ditda 교재 자동조판 실습 GUI

왼쪽이 항상 미리보기다. HWPX에 들어갈 내용을 그대로 그리므로
타이핑하는 동안 결과가 바로 보인다. 수식도 한글 없이 그린다.

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
"""
import json, os, re, sys, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

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

OUTDIR = os.path.join(core.work_dir(), "out")
os.makedirs(OUTDIR, exist_ok=True)

DEFAULT_PDF = next((a for a in sys.argv[1:] if a.lower().endswith(".pdf")), "")

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
    "next_slot": "다음 슬롯", "prev_slot": "이전 슬롯",
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


def parse_markup(text):
    """달러 기호 사이는 수식, 줄바꿈은 br."""
    parts = []
    for i, line in enumerate(text.split("\n")):
        if i:
            parts.append({"br": True})
        for tok in re.split(r"(\$[^$]*\$)", line):
            if not tok:
                continue
            if tok.startswith("$") and tok.endswith("$") and len(tok) > 1:
                parts.append({"eq": tok[1:-1]})
            else:
                parts.append({"t": tok})
    return parts


def count_eq(parts):
    return sum(1 for p in parts if "eq" in p)


class App:
    def __init__(self, root):
        self.root = root
        root.title("ditda 교재 자동조판 실습")
        root.geometry("%dx%d" % (MIN_W + 220, MIN_H + 120))
        # 버튼이 가려질 만큼 줄어들지 않게 막는다
        root.minsize(MIN_W, MIN_H)

        self.pdf_path = tk.StringVar(value=DEFAULT_PDF)
        self.pageno = tk.IntVar(value=3)
        self.side = tk.StringVar(value="우면")
        self.showgrid = tk.BooleanVar(value=True)
        self.zoomsel = tk.BooleanVar(value=False)
        self.shapes, self.slots, self.texts = [], [], {}
        self.sel = 0
        self.page_w, self.page_h = 595.276, 841.89
        self._job = None
        self._drag = None
        self._rubber = None
        self.problems = []
        self.ms_path = ""
        self.proj_path = ""
        self.log_shown = True
        self.keys, self.keys_path = load_keys()
        self._help = None
        self.result_imgs = []
        self._build()

    # ------------------------------------------------------------ 화면
    def _build(self):
        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text="레이아웃 PDF").pack(side="left")
        ttk.Entry(top, textvariable=self.pdf_path).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(top, text="찾아보기", command=self.pick).pack(side="left")
        ttk.Label(top, text=" 쪽").pack(side="left")
        ttk.Spinbox(top, from_=1, to=999, width=4, textvariable=self.pageno).pack(side="left")
        ttk.Combobox(top, textvariable=self.side, values=["전체", "좌면", "우면"],
                     width=5, state="readonly").pack(side="left", padx=4)
        ttk.Button(top, text="레이아웃 분석", command=self.analyze).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="열기", width=5, command=self.open_project).pack(side="left", padx=(10, 2))
        ttk.Button(top, text="저장", width=5, command=self.save_project).pack(side="left")

        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)
        self.pane = pane

        # --- 왼쪽: 항상 보이는 미리보기
        lf = ttk.LabelFrame(pane, text="미리보기 (HWPX에 들어갈 내용 그대로)", padding=4)
        pane.add(lf, weight=3)
        self.canvas = tk.Canvas(lf, bg="#e9e9ee", highlightthickness=0, width=560)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_rclick)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        bar = ttk.Frame(lf)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(bar, text="슬롯 경계", variable=self.showgrid,
                        command=self.redraw).pack(side="left")
        ttk.Checkbutton(bar, text="선택 슬롯 확대", variable=self.zoomsel,
                        command=self.redraw).pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="", foreground="#555555")
        self.status.pack(side="right")

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
        ttk.Label(row, text="슬롯").pack(side="left")
        self.slotsel = ttk.Combobox(row, width=8, state="readonly")
        self.slotsel.pack(side="left", padx=4)
        self.slotsel.bind("<<ComboboxSelected>>", self.switch_slot)
        ttk.Button(row, text="예시", width=6, command=self.fill_sample).pack(side="left", padx=2)
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
        ttk.Button(act, text="HWPX 만들기", command=self.build).pack(side="left")
        ttk.Button(act, text="한글로 열어 확인", command=self.verify).pack(side="left", padx=6)
        ttk.Button(act, text="결과 폴더", command=self.open_dir).pack(side="left")
        ttk.Button(act, text="도움말 F1", command=self.show_help).pack(side="right")

        self.log = tk.Text(self.root, height=4, font=("Consolas", 9),
                           bg="#1e1e1e", fg="#d4d4d4")
        self.log.pack(fill="x", padx=8, pady=(0, 8))
        self.bind_keys()
        self.say("준비됨.  F5 분석 · Ctrl+B 만들기 · Ctrl+S 저장 · Alt+I 원문자 순환 · F9 로그 접기")
        self.say("단축키는 %s 를 고치면 바뀝니다." % self.keys_path)
        # 미리보기가 절반 넘게 차지하도록 초기 분할 위치를 잡는다
        self.root.after(120, self._place_sash)

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

    def open_dir(self):
        os.startfile(OUTDIR)

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

            self.shapes = core.extract_layout(path, pno, clip)
            n_r = sum(1 for s in self.shapes if s["k"] == "rect")
            n_l = sum(1 for s in self.shapes if s["k"] == "line")
            n_t = sum(1 for s in self.shapes if s["k"] == "text")

            key = (path, pno, self.side.get())
            changed = getattr(self, "_target", None) not in (None, key)
            self._target = key
            self.slots = self.detect_slots()
            dropped = self.sync_slots(clear=changed)
            if dropped:
                self.say("  다른 쪽이라 입력해둔 글 %d개를 비웠습니다." % dropped
                         if changed else
                         "  칸이 줄어 넘치는 글 %d개를 버렸습니다." % dropped)

            self.info.config(text=(
                "%.0f x %.0f mm   사각형 %d · 직선 %d · 원본텍스트 %d\n"
                "이미지 0개 (래스터화 없음)   검출된 문제 슬롯 %d개"
                % (self.page_w * 25.4 / 72, self.page_h * 25.4 / 72, n_r, n_l, n_t, len(self.slots))))
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", self.texts.get(self.sel, ""))
            self.say("분석 완료. 사각형 %d, 직선 %d, 원본텍스트 %d, 슬롯 %d개"
                     % (n_r, n_l, n_t, len(self.slots)))
            if not self.slots:
                self.say("  슬롯이 안 잡혔습니다. 이 디자인은 헤더 바 조건이 다릅니다.")
            self.redraw()
        except Exception:
            self.say(traceback.format_exc())

    # ------------------------------------------------------------ 슬롯 검출
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

        picked = a if len(a) >= len(b_) else b_
        self._slot_mode = "헤더 띠" if picked is a else "빈 상자"
        return picked

    # ------------------------------------------------------------ 미리보기
    def redraw(self):
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
            sc = min((cw - m * 2) / self.page_w, (ch - m * 2) / self.page_h)
            ox = (cw - self.page_w * sc) / 2
            oy = m
        if sc <= 0:
            return
        self.scale = sc
        self.origin = (ox, oy)

        def X(v): return ox + v * sc
        def Y(v): return oy + v * sc

        cv.create_rectangle(X(0), Y(0), X(self.page_w), Y(self.page_h),
                            fill="white", outline="#b9b9c4")

        # 원본 도형을 그대로 그린다. 이게 HWPX에 들어갈 것이다.
        for s in self.shapes:
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
                px = max(int(s["size"] * sc), 5)
                cv.create_text(X(s["x"]), Y(s["y"] + s["h"]), text=s["s"], anchor="sw",
                               font=("맑은 고딕", -px), fill=s.get("color") or "#000000")

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
                px = max(int(10.5 * sc), 6)
                end = pv.render_parts(cv, parse_markup(txt), X(x) + 4, Y(y) + 2 + (px * 0.2 if self.showgrid.get() else 0),
                                      w * sc - 8, px=px, tags=("body", "s%d" % i))
                if end > Y(y + h):
                    cv.create_rectangle(X(x), Y(y), X(x + w), Y(y + h),
                                        outline="#e05a4f", width=2, dash=(2, 2))
                    cv.create_text(X(x + w) - 4, Y(y + h) - 4, anchor="se",
                                   text="넘침", fill="#e05a4f",
                                   font=("맑은 고딕", -max(int(9 * sc * 1.6), 9), "bold"))

        if self._rubber:
            rx, ry, rw, rh = self._rubber
            cv.create_rectangle(X(rx), Y(ry), X(rx + rw), Y(ry + rh),
                                outline="#d43f3a", width=2, dash=(3, 2))

        filled = sum(1 for k, v in self.texts.items()
                     if k < len(self.slots) and v.strip())
        self.status.config(text="%s %.0f%%   채운 슬롯 %d / %d"
                                % ("슬롯%d 확대" % self.sel if zoom else "전체",
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
            self.slotsel.current(i)
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
            self.say("슬롯%d 추가 (%.0f x %.0f pt)" % (self.sel, rub[2], rub[3]))
        self.redraw()

    def on_rclick(self, ev):
        if not hasattr(self, "origin"):
            return
        px, py = self.to_pt(ev.x, ev.y)
        i, _ = self.hit(px, py)
        if i is None:
            return
        if not messagebox.askyesno("", "슬롯%d 를 지울까요?" % i):
            return
        self.slots.pop(i)
        self.texts.pop(i, None)
        for k in sorted([k for k in self.texts if k > i]):
            self.texts[k - 1] = self.texts.pop(k)
        self.sync_slots()
        self.select(self.sel)
        self.say("슬롯%d 삭제" % i)
        self.redraw()

    def reindex(self):
        self.slotsel["values"] = ["슬롯%d" % i for i in range(len(self.slots))]

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
            self.slotsel.current(self.sel)
        else:
            self.slotsel.set("")
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
            ("4. 손질하기",
             "달러 기호 사이가 수식입니다. 타이핑하는 동안 왼쪽이 바로 갱신됩니다.\n"
             "칸보다 글이 길면 글자를 줄여 맞추고, 그래도 넘치면 알려 줍니다."),
            ("5. HWPX 만들기",
             "한글에서 열어 고칠 수 있는 파일이 나옵니다. 한글로 열어 확인을 누르면\n"
             "실제로 열어 PDF로 뽑아 보여줍니다."),
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
        return {
            "pdf": self.pdf_path.get(), "page": self.pageno.get(), "side": self.side.get(),
            "slots": [list(s) for s in self.slots],
            "texts": {str(k): v for k, v in self.texts.items()},
            "manuscript": getattr(self, "ms_path", ""),
        }

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

    def open_project(self):
        p = filedialog.askopenfilename(title="작업 열기", initialdir=OUTDIR,
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
        # 분석에 실패하면 직전 페이지의 도형이 남아 화면과 결과가 어긋난다
        self.shapes = []
        self._target = None
        if os.path.exists(self.pdf_path.get()):
            self.analyze()
        else:
            self.say("PDF를 찾지 못했습니다: %s" % self.pdf_path.get())
            messagebox.showwarning("", "레이아웃 PDF를 찾지 못했습니다.\n경로를 다시 지정하고 분석하세요.")
        if not self.shapes:
            self.say("  도형이 없습니다. 이대로 만들면 글만 들어갑니다.")
        self.slots = [tuple(s) for s in d.get("slots", [])]
        self.texts = {int(k): v for k, v in d.get("texts", {}).items()}
        self.sync_slots()
        mp = d.get("manuscript", "")
        if mp and os.path.exists(mp):
            self._read_manuscript(mp)
        self.select(0)
        self.redraw()
        self.proj_path = p
        self.say("작업 열기: %s (슬롯 %d, 채운 칸 %d)"
                 % (p, len(self.slots), sum(1 for v in self.texts.values() if v.strip())))

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
            self.problems = ms.load(p)
        except Exception:
            self.say(traceback.format_exc())
            messagebox.showerror("", "원고를 읽지 못했습니다. 로그를 보세요.")
            return
        self.ms_path = p
        self.problist.delete(0, "end")
        n_eq = 0
        for i, pr in enumerate(self.problems):
            t = ms.parts_to_markup(pr["parts"]).replace("\n", " ")
            n_eq += sum(1 for q in pr["parts"] if "eq" in q)
            self.problist.insert("end", "%s. %s" % (pr["no"] or (i + 1), t[:70]))
        self.mlabel.config(text="%s  문항 %d개, 수식 %d개"
                                % (os.path.basename(p), len(self.problems), n_eq))
        self.say("원고 읽음: %s (문항 %d, 수식 %d). 목록을 두 번 누르면 선택한 슬롯에 들어갑니다."
                 % (os.path.basename(p), len(self.problems), n_eq))

    def put_problem(self, ev=None):
        s = self.problist.curselection()
        if not s or not self.slots:
            return
        pr = self.problems[s[0]]
        self.texts[self.sel] = ms.parts_to_markup(pr["parts"])
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts[self.sel])
        self.redraw()
        self.say("문항 %s 를 슬롯%d 에 넣었습니다." % (pr["no"] or s[0] + 1, self.sel))

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
        self.say("문항 %d개를 슬롯에 채웠습니다. 남은 문항 %d개."
                 % (n, len(self.problems) - n))

    # ------------------------------------------------------------ 편집
    def on_type(self, ev=None):
        self.texts[self.sel] = self.editor.get("1.0", "end-1c")
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(220, self.redraw)

    def switch_slot(self, ev=None):
        self.sel = self.slotsel.current()
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
        self.say("슬롯 %d개에 예시를 넣었습니다." % len(self.slots))

    def clear_slot(self):
        self.texts[self.sel] = ""
        self.editor.delete("1.0", "end")
        self.redraw()

    # ------------------------------------------------------------ 생성
    def fit_size(self, parts, w_pt, h_pt):
        """칸에 들어가는 가장 큰 글자 크기를 찾는다. 임의로 잘라내지는 않는다."""
        cv = tk.Canvas(self.root)          # 화면에 붙이지 않는 측정용
        try:
            for size in (10.5, 10.0, 9.5, 9.0):
                cv.delete("all")
                end = pv.render_parts(cv, parts, 0, 0, w_pt - 8, px=size)
                if end <= h_pt - 6:
                    return size, False
            return 9.0, True
        finally:
            cv.destroy()

    def build(self):
        try:
            if not self.slots:
                messagebox.showwarning("", "먼저 레이아웃을 분석하세요.")
                return
            tpl = core.template_path()
            table = core.StyleTable(core.base_charpr_count(tpl))
            xml, z = [], 0
            for s in self.shapes:
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
                size, over = self.fit_size(parts, w, h)
                if size < 10.5:
                    self.say("  슬롯%d 글자를 %.1fpt로 줄여 맞췄습니다." % (i, size))
                if over:
                    self.say("  슬롯%d 는 9pt로도 넘칩니다. 문제를 줄이거나 칸을 키우세요." % i)
                cp = table.get("맑은 고딕", False, size, "#1A1A1A")
                inner = core.paras_from_parts(parts, char_pr=cp, width_hu=core.hu(w))
                xml.append(core.rect_xml(x, y, w, h, fill=None, stroke=None, lw=0, z=z, inner=inner))
                z += 1
            section = core.build_section("".join(xml), self.page_w, self.page_h)
            out = os.path.join(OUTDIR, "실습결과.hwpx")
            core.write_hwpx(tpl, section, out, style_table=table)
            self.say("HWPX 저장: %s (%.1f KB, 도형 %d, 수식 %d)"
                     % (out, os.path.getsize(out) / 1024, z, n_eq))
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
        if DEFAULT_PDF:
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
