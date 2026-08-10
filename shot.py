# -*- coding: utf-8 -*-
"""GUI를 띄워 화면을 그대로 캡처한다. 미리보기가 실제로 어떻게 보이는지
사람 눈으로 확인하려고 쓴다.

  python shot.py <PDF> <쪽> <나갈파일.png> [전체|좌면|우면]
"""
import os, sys, time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gui as G


def main():
    pdf = sys.argv[1]
    page = int(sys.argv[2])
    out = sys.argv[3]
    side = sys.argv[4] if len(sys.argv) > 4 else "전체"
    demo = "--demo" in sys.argv

    root = tk.Tk()
    app = G.App(root)
    app.pdf_path.set(pdf)
    app.pageno.set(page)
    app.side.set(side)
    root.update()

    t = time.time()
    app.analyze()
    root.update()
    print("분석 %.0f ms  슬롯 %d" % ((time.time() - t) * 1000, len(app.slots)))

    if demo and app.slots:
        app.texts[0] = ("다음 극한값을 구하시오.\n"
                        "$lim _{x rarrow 0} {sin 2x} over {3x}$")
        t = time.time()
        app.redraw()
        root.update()
        print("첫 입력 후 다시 그리기 %.0f ms" % ((time.time() - t) * 1000))

    t = time.time()
    for _ in range(10):
        app.redraw()
    print("캐시 상태 다시 그리기 %.1f ms/회" % ((time.time() - t) * 100))

    root.update()
    time.sleep(0.5)
    from PIL import ImageGrab
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(out)
    print("저장", out)
    root.destroy()


if __name__ == "__main__":
    main()
