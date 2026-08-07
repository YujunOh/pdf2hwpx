# -*- coding: utf-8 -*-
"""생성한 HWPX를 한글로 열어 PDF로 내보내 렌더를 확인한다. 검증 전용."""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "out", "교재5p3_문제채움.hwpx")
PDF = os.path.join(HERE, "out", "교재5p3_문제채움_검증.pdf")

import pythoncom
import win32com.client.gencache as gencache

pythoncom.CoInitialize()
hwp = None
try:
    print("한글 기동")
    hwp = gencache.EnsureDispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception as e:
        print("  보안모듈 등록 실패(계속 진행):", e)

    print("파일 열기:", os.path.basename(SRC))
    ok = hwp.Open(os.path.abspath(SRC), "HWPX", "")
    print("  Open 반환:", ok)
    if not ok:
        print("  >> 한글이 파일을 열지 못했습니다.")
        sys.exit(2)

    # 실제로 내용이 들어왔는지 확인
    try:
        txt = hwp.GetTextFile("TEXT", "")
        print("  문서에서 추출한 텍스트 %d자" % len(txt))
        head = txt.replace("\r", " ").replace("\n", " ")[:200]
        print("  앞부분:", head)
    except Exception as e:
        print("  텍스트 추출 실패:", e)

    if os.path.exists(PDF):
        os.remove(PDF)
    print("PDF로 내보내기")
    r = hwp.SaveAs(os.path.abspath(PDF), "PDF", "")
    print("  SaveAs 반환:", r)
    for _ in range(60):
        if os.path.exists(PDF) and os.path.getsize(PDF) > 0:
            break
        time.sleep(0.5)
    if os.path.exists(PDF):
        print("  PDF 생성됨: %.1f KB" % (os.path.getsize(PDF) / 1024))
    else:
        print("  PDF 생성 실패")
finally:
    if hwp is not None:
        try:
            hwp.Clear(1)
        except Exception:
            pass
        try:
            hwp.Quit()
        except Exception:
            pass
    pythoncom.CoUninitialize()
    print("한글 종료")
