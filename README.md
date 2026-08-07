# pdf2hwpx

디자인만 끝난 교재 PDF에 문제 텍스트와 수식을 채워 넣어, 강사가 한글에서 열어 고칠 수 있는 HWPX로 내보낸다.

한글 프로그램을 띄우지 않고 zip과 xml만 만들어서 만든다. 페이지를 이미지로 굽는 단계가 어디에도 없다.

## 왜 만들었나

[indd2hwp](https://github.com/YujunOh/indd2hwp)를 먼저 만들었다. 디자이너가 InDesign으로 넘긴 산출물을 학원 한글 환경으로 옮기는 도구였는데, README에 한계를 이렇게 적어두고 끝났다.

> - PDF 변환 결과는 이미지 기반이라 한/글에서 본문 편집이 어렵습니다.
> - IDML은 텍스트 중심 추출이라 원본 레이아웃을 완전히 보존하지 않습니다.

레이아웃과 편집 가능성이 그때 배타적으로 갈렸다. PDF 경로는 레이아웃이 완벽한데 300dpi 이미지로 구워 넣어서 글자를 못 만지고, IDML 경로는 텍스트인데 `Spreads/*.xml` 의 좌표를 안 읽어서 레이아웃이 날아갔다.

이 저장소는 그 교집합을 만든다. PDF에서 벡터 도형과 좌표를 읽어 HWPX 네이티브 도형으로 옮기고, 그 위에 진짜 텍스트와 수식을 앉힌다.

## 어떻게 되나

```
레이아웃 PDF ──┐
               ├─ 도형과 슬롯 검출 ─┐
문제 원고    ──┘                    ├─ HWPX 조립 ─ 한글에서 편집
                                    │
                    수식 <hp:script> 문자열로 왕복
```

핵심은 셋이다.

**좌표.** HWPUNIT은 1pt가 정확히 100이다. PDF 좌표에 100을 곱하면 끝이라 반올림 손실이 없다. 도형은 `<hp:pos treatAsChar="0" horzRelTo="PAPER" vertRelTo="PAPER">` 로 용지 절대 좌표에 박는다.

**수식.** HWPX에서 수식은 `<hp:script>` 태그 안의 문자열 하나다. 개체를 통째로 옮길 필요가 없고 문자열만 넣으면 한글에서 더블클릭했을 때 수식 편집기가 열린다.

**화질.** 벡터를 벡터로 옮기므로 dpi를 고르는 단계가 없다. 원본에 이미지가 있으면 `extract_image()` 로 스트림을 재압축 없이 꺼내 쓴다.

## 실행

```bash
pip install PyMuPDF pillow pywin32
python gui.py
```

GUI가 세 단계로 되어 있다.

1. 레이아웃 PDF를 열면 도형을 뽑고 문제 슬롯을 검출해 페이지 위에 겹쳐 보여준다. 슬롯을 클릭해 고를 수 있다.
2. 고른 슬롯에 문제를 입력한다. 달러 기호 사이가 수식이다. 수식 팔레트로 분수, 근호, 적분 같은 걸 넣는다.
3. HWPX를 만들고, 한글로 열어 원본과 나란히 대조한다.

CLI만 쓰려면 이렇게 한다.

```bash
python pdf2hwpx.py      # problems.json을 읽어 out/에 hwpx 생성
python verify_hwp.py    # 한글로 열어 PDF로 내보내 검증
```

## 검증 결과

한글 2024가 생성한 파일을 열었다. `Open` 이 True를 반환했고 문서에서 텍스트 272자가 추출됐다. 내보낸 PDF는 210 x 297mm 정확히 A4이고 벡터 21개에 **이미지 0개**다. 폰트는 본문 HCRBatang, 수식 HyhwpEQ로 잡혔다.

| 요구 | 결과 |
|---|---|
| 글씨가 깨지지 않을 것 | 원문자 ①~④, 위첨자 ², ³ 전부 살아남 |
| 이미지로 박히지 않을 것 | 내보낸 PDF에 이미지 0개 |
| 나중에 선택하고 편집할 것 | 한글에서 텍스트 272자 추출됨 |
| 수식 | 더블클릭하면 수식 편집기가 열림 |
| 원본 화질 | 래스터화 0회 |

## 문제 원고 형식

`problems.json` 을 고치거나 GUI에서 입력한다. `t` 가 일반 텍스트, `eq` 가 한글 수식 스크립트, `br` 이 줄바꿈이다.

```json
{
  "no": "001",
  "slot": 0,
  "parts": [
    {"t": "다음 극한값을 구하시오."},
    {"br": true},
    {"eq": " lim _{h ``rarrow`` 0} {f left(2+h  right)-f left(2  right)} over {h}"}
  ]
}
```

수식은 한글 수식 편집기 문법을 그대로 쓴다. `over` 가 분수, `sqrt` 가 근호, `int _{a} ^{b}` 가 적분이고 백틱이 좁은 공백이다. 한 낱말이 아홉자를 넘으면 편집기가 두 항으로 쪼개므로 큰따옴표로 묶어야 한다.

## 아직 안 되는 것

- 베지어 곡선. `<hp:curve>` 에 제어점이 없어서 직선 세그먼트로 쪼개 근사해야 하는데 아직 구현하지 않았다. 대상 페이지에 곡선이 없어서 미뤘다.
- 폰트 지정. 지금은 한글 기본 폰트로 나온다. `header.xml` 에 폰트를 추가하고 `charPrIDRef` 를 연결해야 한다.
- 오버플로 대응. 문제가 슬롯보다 길면 그냥 넘친다. 행간과 크기를 줄이는 단계가 필요하다.
- 원고 자동 파싱. 선생님이 준 hwp에서 문제와 수식을 뽑아내는 부분이 없다. 지금은 손으로 넣는다.
- 이미지가 있는 페이지. 원본 스트림을 BinData로 옮기는 경로가 없다.
- 슬롯 검출 조건이 이 교재 디자인(헤더 바 폭 240~270pt)에 맞춰져 있다. 다른 디자인이면 조건을 고쳐야 한다.

## 참고한 것

HWPX 내부 마크업은 OWPML이고 KS X 6101:2011 한국산업표준이다.

- [hancom-io/hwpx-owpml-model](https://github.com/hancom-io/hwpx-owpml-model) 한컴 공식 OWPML 모델. 태그와 속성과 enum의 사실상 스펙
- [neolord0/hwpxlib](https://github.com/neolord0/hwpxlib) HWPX 객체 모델. 도형 XML 실물 샘플을 여기서 얻었다
- [airmang/python-hwpx](https://github.com/airmang/python-hwpx) 순수 파이썬 HWPX. LaTeX 양방향 변환기가 있다
- [한컴테크 HWPX 포맷 구조](https://tech.hancom.com/hwpxformat/)
- [한글 수식 명령어 공식 도움말](https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/equation/equation(script).htm)

## 관련 저장소

- [indd2hwp](https://github.com/YujunOh/indd2hwp) 이 도구의 전작. InDesign 산출물을 한글로 변환하는 Tkinter GUI

두 저장소 모두 [ditda](https://ditda.kr) 에서 나왔다. 학원 강사와 디자이너를 잇는 1:N 디자인 외주 매칭 플랫폼이고, 강사 인터뷰에서 한글 파일 호환이 가장 큰 마찰점으로 나왔다.

---

본 제품은 한글과컴퓨터의 한글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
