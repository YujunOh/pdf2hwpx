# -*- coding: utf-8 -*-
"""ditda 교재 자동조판 실습 GUI

왼쪽이 항상 미리보기다. HWPX에 들어갈 내용을 그대로 그리므로
타이핑하는 동안 결과가 바로 보인다. 수식도 한글 없이 그린다.

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
"""
import os, re, sys, threading, traceback
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

        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)
        self.pane = pane

        # --- 왼쪽: 항상 보이는 미리보기
        lf = ttk.LabelFrame(pane, text="미리보기 (HWPX에 들어갈 내용 그대로)", padding=4)
        pane.add(lf, weight=3)
        self.canvas = tk.Canvas(lf, bg="#e9e9ee", highlightthickness=0, width=560)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.click_canvas)
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

        self.log = tk.Text(self.root, height=6, font=("Consolas", 9),
                           bg="#1e1e1e", fg="#d4d4d4")
        self.log.pack(fill="x", padx=8, pady=(0, 8))
        self.say("준비됨.")
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

            self.slots = self.detect_slots()

            self.info.config(text=(
                "%.0f x %.0f mm   사각형 %d · 직선 %d · 원본텍스트 %d\n"
                "이미지 0개 (래스터화 없음)   검출된 문제 슬롯 %d개"
                % (self.page_w * 25.4 / 72, self.page_h * 25.4 / 72, n_r, n_l, n_t, len(self.slots))))
            self.slotsel["values"] = ["슬롯%d" % i for i in range(len(self.slots))]
            if self.slots:
                self.slotsel.current(0)
                self.sel = 0
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", self.texts.get(0, ""))
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
                # 라벨은 슬롯 밖 왼쪽 위에. 본문과 겹치면 읽기 어렵다
                cv.create_text(X(x), Y(y) - 3, anchor="sw", text="슬롯%d" % i,
                               fill="#d43f3a" if on else "#9db8dd",
                               font=("맑은 고딕", -max(int(7 * sc * 1.5), 9), "bold"))
            txt = self.texts.get(i, "").strip()
            if txt:
                px = max(int(10.5 * sc), 6)
                end = pv.render_parts(cv, parse_markup(txt), X(x) + 4, Y(y) + 2,
                                      w * sc - 8, px=px, tags=("body", "s%d" % i))
                if end > Y(y + h):
                    cv.create_rectangle(X(x), Y(y), X(x + w), Y(y + h),
                                        outline="#e05a4f", width=2, dash=(2, 2))
                    cv.create_text(X(x + w) - 4, Y(y + h) - 4, anchor="se",
                                   text="넘침", fill="#e05a4f",
                                   font=("맑은 고딕", -max(int(9 * sc * 1.6), 9), "bold"))

        filled = sum(1 for v in self.texts.values() if v.strip())
        self.status.config(text="%s %.0f%%   채운 슬롯 %d / %d"
                                % ("슬롯%d 확대" % self.sel if zoom else "전체",
                                   sc * 100, filled, len(self.slots)))

    def click_canvas(self, ev):
        if not self.slots:
            return
        ox, oy = self.origin
        for i, (x, y, w, h) in enumerate(self.slots):
            if (ox + x * self.scale <= ev.x <= ox + (x + w) * self.scale and
                    oy + y * self.scale <= ev.y <= oy + (y + h) * self.scale):
                self.sel = i
                self.slotsel.current(i)
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", self.texts.get(i, ""))
                self.redraw()
                return

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
                from PIL import ImageGrab
                import time
                root.attributes("-topmost", True); root.lift(); root.focus_force()
                root.update(); time.sleep(0.7); root.update()
                x, y = root.winfo_rootx(), root.winfo_rooty()
                ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()),
                               all_screens=True).save(os.path.join(OUTDIR, "gui_미리보기.png"))
                app.build()
                with open(os.path.join(OUTDIR, "gui_demo_log.txt"), "w", encoding="utf-8") as f:
                    f.write(app.log.get("1.0", "end"))
                root.after(600, root.destroy)
            root.after(700, run)
        root.mainloop()
