"""
app.py 의 한글 폰트 블록을 'Cloud 리눅스' 조건으로 검증한다.

주의: 이 맥에는 macOS 시스템 NanumGothic 이 있어서 그대로 두면
      번들 폰트가 일을 했는지 알 수 없다.
      따라서 Nanum 계열을 fontManager 에서 모두 제거한 뒤 실행한다.
"""
import logging
import platform
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH

PROJECT = PROJECT
BUNDLED = PROJECT / "fonts" / "NanumGothic.ttf"

# ① Cloud 와 같게: 시스템에 설치된 한글 폰트를 모두 없앤 상태로 만든다
removed = [f for f in fm.fontManager.ttflist if "Nanum" in f.name]
for f in removed:
    fm.fontManager.ttflist.remove(f)

print(f"① 시스템 Nanum 폰트 {len(removed)}개 제거 (Cloud 리눅스 재현)")
print("   제거 후 NanumGothic 존재 :",
      any(f.name == "NanumGothic" for f in fm.fontManager.ttflist))

# ② 운영체제를 리눅스로 강제
platform.system = lambda: "Linux"

# ③ app.py 의 폰트 블록만 실행
src = (PROJECT / "app.py").read_text()
block = src[
    src.index("# 저장소에 함께 넣어 둔 나눔고딕"):
    src.index('plt.rcParams["axes.unicode_minus"]')
]
ns = {"fm": fm, "plt": plt, "platform": platform,
      "BASE_DIR": PROJECT, "logger": logging.getLogger("app")}
exec(compile(block, "app.py", "exec"), ns)

font = ns["font"]
print("③ 선택된 폰트 :", font)

# ④ 실제로 쓰인 폰트 파일이 저장소의 번들 파일인지
resolved = Path(fm.findfont(fm.FontProperties(family=font)))
print("④ 실제 사용 파일 :", resolved)
is_bundled = resolved.resolve() == BUNDLED.resolve()
print("   저장소 번들 파일인가 :", is_bundled)

# ⑤ 한글 렌더링에 두부(□)가 없는지
plt.rcParams["font.family"] = font
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    fig, ax = plt.subplots(figsize=(8, 2.4))
    ax.set_title("삼성전자 | 균형형 | 위험도 낮음\n추세와 과열 정도의 균형이 좋은 종목",
                 fontsize=11)
    ax.plot([1, 2, 3], [1, 3, 2])
    ax.set_xlabel("거래일")
    ax.set_ylabel("종가(원)")
    ax.legend(["매수가 219,000원"], loc="upper left", fontsize=9)
    fig.tight_layout()
    out = SCRATCH / "font_check.png"
    fig.savefig(out, dpi=110)
    fig.canvas.draw()
    plt.close(fig)
    missing = [str(x.message) for x in w if "missing from font" in str(x.message)]

print("⑤ 글리프 누락 경고 :", missing if missing else "없음")
print("   이미지 :", out)

ok = font == "NanumGothic" and is_bundled and not missing
print("\n결과 :", "통과" if ok else "실패")
sys.exit(0 if ok else 1)
