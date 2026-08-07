# -*- coding: utf-8 -*-
"""ditda 교재 자동조판 실습 GUI

과정을 눈으로 보면서 실습하고 결과를 대조한다.
  1단계  레이아웃 PDF를 열어 도형과 슬롯을 검출한다
  2단계  검출된 슬롯에 문제와 수식을 넣는다
  3단계  HWPX를 만들고 한글로 열어 원본과 나란히 대조한다

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
"""
import os, re, sys, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 고해상도 화면에서 흐릿하게 나오지 않도록. 캡처 좌표도 이걸 켜야 논리와 물리가 일치한다.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fitz
from PIL import Image, ImageTk
import pdf2hwpx as core

OUTDIR = os.path.join(HERE, "out")
os.makedirs(OUTDIR, exist_ok=True)

DEFAULT_PDF = r"C:\Users\dbwns\OneDrive\문서\카카오톡 받은 파일\박진성 선생님 교재 5 (2).pdf"

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
    ("분수", "{a} over {b}"),
    ("근호", " sqrt {a}"),
    ("적분", "int _{0} ^{1} f(x) dx"),
    ("극한", " lim _{x ``rarrow`` 0} f(x)"),
    ("합", " sum _{k=1} ^{n} a_{k}"),
    ("위첨자", "x ^{2}"),
    ("아래첨자", "a_{n}"),
    ("괄호", "LEFT ( x RIGHT )"),
    ("±", "+-"),
    ("≥", "GEQ"),
    ("→", "rarrow"),
    ("π", "pi"),
]


# ---------------------------------------------------------------- 원고 마크업 파서
def parse_markup(text):
    """`$...$` 안은 수식, 빈 줄과 줄바꿈은 br. -> parts 리스트"""
    parts = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
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


# ---------------------------------------------------------------- GUI
class App:
    def __init__(self, root):
        self.root = root
        root.title("ditda 교재 자동조판 실습")
        root.geometry("1500x950")

        self.pdf_path = tk.StringVar(value=DEFAULT_PDF)
        self.pageno = tk.IntVar(value=3)
        self.side = tk.StringVar(value="우면")
        self.shapes = []
        self.slots = []
        self.sel = tk.IntVar(value=0)
        self.texts = {}
        self.page_img = None
        self.scale = 1.0
        self.origin = (0, 0)
        self.result_imgs = []

        self._build()

    # ------------------------------------------------------------ 레이아웃
    def _build(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="레이아웃 PDF", width=12).pack(side="left")
        ttk.Entry(top, textvariable=self.pdf_path, width=70).pack(side="left", padx=4)
        ttk.Button(top, text="찾아보기", command=self.pick).pack(side="left")
        ttk.Label(top, text="  페이지").pack(side="left")
        ttk.Spinbox(top, from_=1, to=999, width=5, textvariable=self.pageno).pack(side="left")
        ttk.Label(top, text="  면").pack(side="left")
        ttk.Combobox(top, textvariable=self.side, values=["전체", "좌면", "우면"],
                     width=6, state="readonly").pack(side="left", padx=4)
        ttk.Button(top, text="1. 레이아웃 분석", command=self.analyze).pack(side="left", padx=10)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)

        # --- 탭1 분석
        t1 = ttk.Frame(self.nb)
        self.nb.add(t1, text="1. 레이아웃 분석")
        left = ttk.Frame(t1)
        left.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(left, bg="#f4f4f4", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.click_canvas)
        right = ttk.Frame(t1, width=380)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        ttk.Label(right, text="검출 결과", font=("맑은 고딕", 11, "bold")).pack(anchor="w", pady=(6, 2))
        self.info = tk.Text(right, height=14, wrap="word", font=("맑은 고딕", 9))
        self.info.pack(fill="x", padx=4)
        ttk.Label(right, text="슬롯 (클릭하면 미리보기에서 선택)",
                  font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.slotbox = tk.Listbox(right, height=10, font=("Consolas", 9))
        self.slotbox.pack(fill="x", padx=4)
        self.slotbox.bind("<<ListboxSelect>>", self.pick_slot)

        # --- 탭2 문제 입력
        t2 = ttk.Frame(self.nb)
        self.nb.add(t2, text="2. 문제 입력")
        bar = ttk.Frame(t2, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="슬롯").pack(side="left")
        self.slotsel = ttk.Combobox(bar, width=8, state="readonly")
        self.slotsel.pack(side="left", padx=4)
        self.slotsel.bind("<<ComboboxSelected>>", self.switch_slot)
        ttk.Button(bar, text="예시 넣기", command=self.fill_sample).pack(side="left", padx=6)
        ttk.Button(bar, text="전체 슬롯에 예시", command=self.fill_all).pack(side="left")
        ttk.Label(bar, text="   달러 기호 사이가 수식입니다.  예:  $1 over 2$",
                  foreground="#666666").pack(side="left", padx=10)

        pal = ttk.LabelFrame(t2, text="수식 팔레트 (누르면 커서 위치에 삽입)", padding=6)
        pal.pack(fill="x", padx=6)
        for i, (label, code) in enumerate(EQ_PALETTE):
            ttk.Button(pal, text=label, width=7,
                       command=lambda c=code: self.insert_eq(c)).grid(row=i // 6, column=i % 6, padx=2, pady=2)

        self.editor = tk.Text(t2, wrap="word", font=("맑은 고딕", 11), undo=True)
        self.editor.pack(fill="both", expand=True, padx=6, pady=6)
        self.editor.bind("<KeyRelease>", self.save_text)

        # --- 탭3 결과
        t3 = ttk.Frame(self.nb)
        self.nb.add(t3, text="3. 변환과 확인")
        act = ttk.Frame(t3, padding=8)
        act.pack(fill="x")
        ttk.Button(act, text="2. HWPX 만들기", command=self.build).pack(side="left")
        ttk.Button(act, text="3. 한글로 열어 확인 (창이 잠깐 뜹니다)",
                   command=self.verify).pack(side="left", padx=8)
        ttk.Button(act, text="결과 폴더 열기", command=self.open_dir).pack(side="left")
        self.result_canvas = tk.Canvas(t3, bg="#f4f4f4", highlightthickness=0)
        self.result_canvas.pack(fill="both", expand=True, padx=6, pady=6)

        # --- 로그
        self.log = tk.Text(self.root, height=8, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        self.log.pack(fill="x", padx=8, pady=(0, 8))
        self.say("준비됨. 위에서 PDF를 고르고 '1. 레이아웃 분석'을 누르세요.")

    # ------------------------------------------------------------ 유틸
    def say(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def pick(self):
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            self.pdf_path.set(p)

    def open_dir(self):
        os.startfile(OUTDIR)

    def clip_of(self, page):
        w = page.rect.width
        if self.side.get() == "좌면":
            return (0, 0, w / 2, page.rect.height)
        if self.side.get() == "우면":
            return (w / 2, 0, w, page.rect.height)
        return None

    # ------------------------------------------------------------ 1단계
    def analyze(self):
        try:
            path = self.pdf_path.get()
            pno = self.pageno.get() - 1
            doc = fitz.open(path)
            page = doc[pno]
            clip = self.clip_of(page)
            self.page_w = (clip[2] - clip[0]) if clip else page.rect.width
            self.page_h = page.rect.height

            # 미리보기 렌더 (화면 표시용. 산출물에는 래스터가 안 들어간다)
            mb = page.mediabox
            if clip:
                r = fitz.Rect(max(mb.x0, clip[0]), mb.y0, min(mb.x1, clip[2]), mb.y1)
                page.set_cropbox(r)
            pix = page.get_pixmap(dpi=96)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()

            self.shapes = core.extract_layout(path, pno, clip)
            n_r = sum(1 for s in self.shapes if s["k"] == "rect")
            n_l = sum(1 for s in self.shapes if s["k"] == "line")
            n_t = sum(1 for s in self.shapes if s["k"] == "text")

            bars = sorted([s for s in self.shapes
                           if s["k"] == "rect" and 240 < s["w"] < 270 and 20 < s["h"] < 30],
                          key=lambda s: (s["y"], s["x"]))
            self.slots = []
            for b in bars:
                top = b["y"] + b["h"] + 8
                below = [c["y"] for c in bars if c["y"] > b["y"] + 5 and abs(c["x"] - b["x"]) < 20]
                bottom = (min(below) - 14) if below else (self.page_h - 40)
                self.slots.append((b["x"] + 10, top, b["w"] - 20, bottom - top))

            self.show_page(img)
            self.info.delete("1.0", "end")
            self.info.insert("end",
                             "페이지 크기  %.1f x %.1f pt  (%.0f x %.0f mm)\n"
                             % (self.page_w, self.page_h,
                                self.page_w * 25.4 / 72, self.page_h * 25.4 / 72))
            self.info.insert("end", "사각형 %d개\n직선 %d개\n원본 텍스트 %d개\n" % (n_r, n_l, n_t))
            self.info.insert("end", "이미지 0개 (래스터화 없음)\n\n")
            self.info.insert("end", "검출된 문제 슬롯 %d개\n" % len(self.slots))
            self.info.insert("end", "\n도형은 전부 HWPX 네이티브 도형으로\n옮겨집니다. dpi를 고르는 단계가\n없습니다.")

            self.slotbox.delete(0, "end")
            for i, (x, y, w, h) in enumerate(self.slots):
                self.slotbox.insert("end", "슬롯%d  x=%6.1f y=%6.1f  %5.1f x %5.1f" % (i, x, y, w, h))
            self.slotsel["values"] = ["슬롯%d" % i for i in range(len(self.slots))]
            if self.slots:
                self.slotsel.current(0)
                self.sel.set(0)
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", self.texts.get(0, ""))

            self.say("분석 완료. 사각형 %d, 직선 %d, 원본텍스트 %d, 슬롯 %d개"
                     % (n_r, n_l, n_t, len(self.slots)))
            if not self.slots:
                self.say("  슬롯이 안 잡혔습니다. 이 디자인은 헤더 바 크기 조건이 다릅니다.")
        except Exception:
            self.say(traceback.format_exc())

    def show_page(self, img):
        cw = max(self.canvas.winfo_width(), 700)
        ch = max(self.canvas.winfo_height(), 800)
        sc = min(cw / img.width, ch / img.height, 1.0)
        disp = img.resize((int(img.width * sc), int(img.height * sc)), Image.LANCZOS)
        self.page_img = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        ox = (cw - disp.width) // 2
        self.canvas.create_image(ox, 10, anchor="nw", image=self.page_img)
        self.scale = disp.width / self.page_w
        self.origin = (ox, 10)
        self.draw_slots()

    def draw_slots(self):
        self.canvas.delete("slot")
        ox, oy = self.origin
        for i, (x, y, w, h) in enumerate(self.slots):
            X, Y = ox + x * self.scale, oy + y * self.scale
            W, H = w * self.scale, h * self.scale
            on = (i == self.sel.get())
            self.canvas.create_rectangle(X, Y, X + W, Y + H,
                                         outline="#d43f3a" if on else "#3a7bd4",
                                         width=3 if on else 2,
                                         dash=() if on else (5, 3), tags="slot")
            filled = "●" if self.texts.get(i, "").strip() else "○"
            self.canvas.create_text(X + 8, Y + 12, anchor="w",
                                    text="%s 슬롯%d" % (filled, i),
                                    fill="#d43f3a" if on else "#3a7bd4",
                                    font=("맑은 고딕", 10, "bold"), tags="slot")

    def click_canvas(self, ev):
        ox, oy = self.origin
        for i, (x, y, w, h) in enumerate(self.slots):
            X, Y = ox + x * self.scale, oy + y * self.scale
            if X <= ev.x <= X + w * self.scale and Y <= ev.y <= Y + h * self.scale:
                self.sel.set(i)
                self.slotsel.current(i)
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", self.texts.get(i, ""))
                self.draw_slots()
                self.say("슬롯%d 선택" % i)
                return

    def pick_slot(self, ev):
        s = self.slotbox.curselection()
        if s:
            self.sel.set(s[0])
            self.slotsel.current(s[0])
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", self.texts.get(s[0], ""))
            self.draw_slots()

    # ------------------------------------------------------------ 2단계
    def switch_slot(self, ev=None):
        i = self.slotsel.current()
        self.sel.set(i)
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts.get(i, ""))
        self.draw_slots()

    def save_text(self, ev=None):
        self.texts[self.sel.get()] = self.editor.get("1.0", "end-1c")
        self.draw_slots()

    def insert_eq(self, code):
        self.editor.insert("insert", "$%s$" % code)
        self.save_text()

    def fill_sample(self):
        i = self.sel.get()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", SAMPLES[i % len(SAMPLES)])
        self.save_text()

    def fill_all(self):
        for i in range(len(self.slots)):
            self.texts[i] = SAMPLES[i % len(SAMPLES)]
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.texts.get(self.sel.get(), ""))
        self.draw_slots()
        self.say("슬롯 %d개에 예시 문제를 넣었습니다." % len(self.slots))

    # ------------------------------------------------------------ 3단계
    def build(self):
        try:
            if not self.slots:
                messagebox.showwarning("", "먼저 레이아웃을 분석하세요.")
                return
            self.say("HWPX 조립 시작")
            xml, z = [], 0
            for s in self.shapes:
                if s["k"] == "rect":
                    xml.append(core.rect_xml(s["x"], s["y"], s["w"], s["h"],
                                             fill=s["fill"], stroke=s["stroke"], lw=s["lw"], z=z))
                elif s["k"] == "line":
                    xml.append(core.line_xml(s["x1"], s["y1"], s["x2"], s["y2"],
                                             stroke=s["stroke"] or "#000000",
                                             lw=s["lw"] or 0.5, z=z))
                else:
                    inner = core.paras_from_parts([{"t": s["s"]}], width_hu=core.hu(s["w"] + 8))
                    xml.append(core.rect_xml(s["x"] - 1, s["y"] - 2, s["w"] + 8, s["h"] + 6,
                                             fill=None, stroke=None, lw=0, z=z, inner=inner))
                z += 1
            self.say("  도형 %d개 변환" % z)

            n_eq = 0
            for i, (x, y, w, h) in enumerate(self.slots):
                txt = self.texts.get(i, "").strip()
                if not txt:
                    continue
                parts = parse_markup(txt)
                n_eq += count_eq(parts)
                inner = core.paras_from_parts(parts, width_hu=core.hu(w))
                xml.append(core.rect_xml(x, y, w, h, fill=None, stroke=None, lw=0, z=z, inner=inner))
                z += 1
                self.say("  슬롯%d 주입 (%d자, 수식 %d개)" % (i, len(txt), count_eq(parts)))
            self.say("  수식 합계 %d개" % n_eq)

            section = core.build_section("".join(xml), self.page_w, self.page_h)
            template = os.path.join(
                r"C:\Users\dbwns\AppData\Local\Temp\claude\C--Users-dbwns"
                r"\3518c5f8-e4ac-4813-b221-b03d83aef551\scratchpad\hwpx_base",
                "SimpleRectangle.hwpx")
            self.out_hwpx = os.path.join(OUTDIR, "실습결과.hwpx")
            core.write_hwpx(template, section, self.out_hwpx)
            self.say("완료: %s (%.1f KB)" % (self.out_hwpx, os.path.getsize(self.out_hwpx) / 1024))
            self.nb.select(2)
        except Exception:
            self.say(traceback.format_exc())

    def verify(self):
        threading.Thread(target=self._verify_worker, daemon=True).start()

    def _verify_worker(self):
        try:
            src = os.path.join(OUTDIR, "실습결과.hwpx")
            if not os.path.exists(src):
                self.say("먼저 HWPX를 만드세요.")
                return
            pdf = os.path.join(OUTDIR, "실습결과_검증.pdf")
            self.say("한글 기동 중")
            import pythoncom
            import win32com.client.gencache as gencache
            pythoncom.CoInitialize()
            hwp = gencache.EnsureDispatch("HWPFrame.HwpObject")
            try:
                hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            except Exception:
                pass
            ok = hwp.Open(os.path.abspath(src), "HWPX", "")
            self.say("  한글이 파일을 열었나: %s" % ok)
            txt = ""
            try:
                txt = hwp.GetTextFile("TEXT", "")
            except Exception:
                pass
            self.say("  문서에서 추출한 텍스트 %d자 (이미지가 아니라는 증거)" % len(txt))
            if os.path.exists(pdf):
                os.remove(pdf)
            hwp.SaveAs(os.path.abspath(pdf), "PDF", "")
            hwp.Clear(1)
            hwp.Quit()
            pythoncom.CoUninitialize()

            d = fitz.open(pdf)
            p = d[0]
            n_img = len(p.get_images())
            n_vec = len(p.get_drawings())
            n_txt = len(p.get_text("text").strip())
            self.say("  내보낸 PDF: %.0f x %.0f mm, 벡터 %d, 이미지 %d, 텍스트 %d자"
                     % (p.rect.width * 25.4 / 72, p.rect.height * 25.4 / 72, n_vec, n_img, n_txt))
            pix = p.get_pixmap(dpi=96)
            gen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            d.close()

            doc = fitz.open(self.pdf_path.get())
            pg = doc[self.pageno.get() - 1]
            clip = self.clip_of(pg)
            mb = pg.mediabox
            if clip:
                pg.set_cropbox(fitz.Rect(max(mb.x0, clip[0]), mb.y0, min(mb.x1, clip[2]), mb.y1))
            px = pg.get_pixmap(dpi=96)
            org = Image.frombytes("RGB", (px.width, px.height), px.samples)
            doc.close()

            self.root.after(0, lambda: self.show_result(org, gen, n_img, n_txt))
            self.say("확인 끝. 이미지 %d개, 텍스트 %d자." % (n_img, n_txt))
        except Exception:
            self.say(traceback.format_exc())

    def show_result(self, org, gen, n_img, n_txt):
        c = self.result_canvas
        c.delete("all")
        cw = max(c.winfo_width(), 900)
        ch = max(c.winfo_height(), 600)
        sc = min((cw - 60) / (org.width + gen.width), (ch - 60) / max(org.height, gen.height))
        a = org.resize((int(org.width * sc), int(org.height * sc)), Image.LANCZOS)
        b = gen.resize((int(gen.width * sc), int(gen.height * sc)), Image.LANCZOS)
        self.result_imgs = [ImageTk.PhotoImage(a), ImageTk.PhotoImage(b)]
        c.create_text(20, 12, anchor="w", text="원본 (디자이너 PDF)",
                      font=("맑은 고딕", 11, "bold"), fill="#333333")
        c.create_image(20, 34, anchor="nw", image=self.result_imgs[0])
        x2 = 40 + a.width
        c.create_text(x2, 12, anchor="w", text="생성 (HWPX를 한글로 열어 내보낸 것)",
                      font=("맑은 고딕", 11, "bold"), fill="#333333")
        c.create_image(x2, 34, anchor="nw", image=self.result_imgs[1])
        c.create_text(x2, 40 + b.height, anchor="nw",
                      text="이미지 %d개 · 추출 텍스트 %d자" % (n_img, n_txt),
                      font=("맑은 고딕", 10), fill="#0a7d32" if n_img == 0 else "#b33")


def selftest():
    """GUI 없이 파서만 검사한다."""
    for i, s in enumerate(SAMPLES):
        p = parse_markup(s)
        print("샘플%d parts=%d 수식=%d" % (i, len(p), count_eq(p)))
        for q in p:
            if "eq" in q:
                print("   eq:", q["eq"])
    print("selftest OK")


def shot(root, app, path):
    """창을 맨 앞으로 올린 뒤 캡처한다. 문서용."""
    from PIL import ImageGrab
    import time
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    root.update()
    time.sleep(0.6)
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(path)
    app.say("스크린샷 저장: %s" % os.path.basename(path))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        root = tk.Tk()
        app = App(root)
        if "--demo" in sys.argv:
            # 자동으로 1단계와 2단계를 밟고 화면을 캡처한 뒤 닫는다
            def run():
                app.analyze()
                shot(root, app, os.path.join(OUTDIR, "gui_1_분석.png"))
                app.fill_all()
                app.nb.select(1)
                root.update()
                shot(root, app, os.path.join(OUTDIR, "gui_2_문제입력.png"))
                app.build()
                root.update()
                shot(root, app, os.path.join(OUTDIR, "gui_3_변환.png"))
                with open(os.path.join(OUTDIR, "gui_demo_log.txt"), "w", encoding="utf-8") as f:
                    f.write(app.log.get("1.0", "end"))
                root.after(800, root.destroy)
            root.after(600, run)
        root.mainloop()
