# -*- coding: utf-8 -*-
"""예제 교재 PDF를 그린다.

실물 교재는 디자인 저작권이 디자이너에게 있어 저장소에 올릴 수 없다. 그래서
학원 교재가 흔히 쓰는 짜임새만 흉내 내어 직접 그린다. 처음 받은 사람이
바로 눌러 볼 것이 있어야 한다.

  python make_sample.py
"""
import os

import fitz

W, H = 595.276, 841.89          # A4
NAVY = (0.09, 0.24, 0.51)
BLUE = (0.18, 0.44, 0.84)
PALE = (0.85, 0.90, 0.98)
GRAY = (0.62, 0.66, 0.74)

FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"


def font(path):
    return fitz.Font(fontfile=path if os.path.exists(path) else FONT)


def write(page, x, y, text, size, path=FONT, color=(0, 0, 0)):
    tw = fitz.TextWriter(page.rect)
    tw.append(fitz.Point(x, y), text, font=font(path), fontsize=size)
    tw.write_text(page, color=color)


def header(page, chapter, title):
    page.draw_rect(fitz.Rect(0, 0, W, 92), color=None, fill=PALE)
    page.draw_polyline([fitz.Point(0, 0), fitz.Point(300, 0),
                        fitz.Point(250, 92), fitz.Point(0, 92)],
                       color=None, fill=NAVY, closePath=True)
    write(page, 34, 56, chapter, 20, FONT_B, (1, 1, 1))
    write(page, 322, 58, title, 26, FONT_B, BLUE)
    for i in range(5):
        page.draw_circle(fitz.Point(420 + i * 15, 46), 4.0, color=None, fill=BLUE)
    box = fitz.Rect(500, 22, 566, 70)
    page.draw_rect(box, color=(1, 1, 1), fill=(1, 1, 1), radius=0.12)
    page.draw_line(fitz.Point(506, 46), fitz.Point(560, 46), color=BLUE, width=0.8)
    write(page, 512, 40, "분", 8, FONT, BLUE)
    write(page, 546, 40, "초", 8, FONT, BLUE)
    write(page, 512, 62, "/", 8, FONT, BLUE)
    write(page, 546, 62, "점", 8, FONT, BLUE)


def footer(page, pageno, chapter):
    page.draw_rect(fitz.Rect(0, H - 46, W, H - 40), color=None, fill=PALE)
    write(page, 34, H - 22, "%02d" % pageno, 9, FONT_B, NAVY)
    write(page, 58, H - 22, chapter, 9, FONT, GRAY)


def problem_cell(page, x, y, w, h, no, filler):
    """문제 한 칸. 번호를 크게 쓰고 아래를 비워 둔다.

    슬롯 검출이 번호 격자를 보고 칸을 잡는다. 그래서 번호 위치와 크기가
    실제 교재와 비슷해야 한다."""
    write(page, x, y, no, 25, FONT_B, BLUE)
    # 자리를 채워 둘 예시 문장. 도구가 이 글을 지우고 새 문제를 얹는다
    ty = y + 30
    for line in filler:
        write(page, x + 2, ty, line, 12, FONT_B, (0.12, 0.12, 0.14))
        ty += 19


def build(path):
    doc = fitz.open()

    # --- 1쪽: 문제 4칸
    p = doc.new_page(width=W, height=H)
    header(p, "Chapter. 01", "TEST")
    p.draw_line(fitz.Point(W / 2, 150), fitz.Point(W / 2, H - 60),
                color=(0.88, 0.91, 0.96), width=0.8)
    cells = [
        (45, 152, "01", ["등속 직선 운동을 하는 물체가 5초 동안",
                         "20m를 이동했다. 이 물체의 속력은?"]),
        (329, 152, "02", ["질량 3kg인 물체에 6N의 힘이 작용할 때",
                          "물체의 가속도를 구하시오."]),
        (45, 462, "03", ["마찰이 없는 수평면에서 물체가 등속으로",
                         "움직이고 있다. 알짜힘의 크기는?"]),
        (329, 462, "04", ["높이 5m에서 물체를 가만히 놓았다.",
                          "지면에 닿는 순간의 속력은?"]),
    ]
    for x, y, no, filler in cells:
        problem_cell(p, x, y, 222, 300, no, filler)
    footer(p, 2, "Chapter 01. 운동")

    # --- 2쪽: 자료가 붙는 문제 2칸. 칸이 크다
    p2 = doc.new_page(width=W, height=H)
    header(p2, "Chapter. 01", "자료 문제")
    p2.draw_line(fitz.Point(45, 470), fitz.Point(W - 45, 470),
                 color=(0.88, 0.91, 0.96), width=0.8)
    for i, (x, y, no) in enumerate(((45, 152, "05"), (45, 500, "06"))):
        write(p2, x, y, no, 25, FONT_B, BLUE)
        write(p2, x + 2, y + 30, "그래프를 보고 물음에 답하시오.", 12, FONT_B,
              (0.12, 0.12, 0.14))
    footer(p2, 3, "Chapter 01. 운동")

    # 서브셋을 안 걸면 맑은 고딕 한 벌이 통째로 들어가 14MB가 된다
    try:
        doc.subset_fonts()
    except Exception:
        pass
    doc.save(path, garbage=4, deflate=True, clean=True)
    doc.close()


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "samples", "예제_교재.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build(out)
    print("만듦:", out, "%.0f KB" % (os.path.getsize(out) / 1024))
