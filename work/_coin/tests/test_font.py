"""차트 한글 글꼴: 굵은 글씨(Swing 라벨 HH/HL 등)가 굵은 서체로 그려지고 경고가 없어야 한다.

AppleGothic 처럼 굵기가 400 하나뿐인 글꼴을 쓰면 matplotlib 이
'findfont: Failed to find font weight bold, now using 400.' 경고를 남기고
굵은 글씨를 보통체로 그린다.
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import logging

from conftest_paths import app, check, finish

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.ft2font import FT2Font

# conftest 가 WARNING 을 꺼 두므로 다시 켜고, 글꼴 조회 로그를 모은다.
logging.disable(logging.NOTSET)
records: list[str] = []


class Grab(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        records.append(record.getMessage())


logging.getLogger("matplotlib.font_manager").addHandler(Grab())

check("차트 글꼴은 나눔고딕", app.KOREAN_FONT == "NanumGothic", app.KOREAN_FONT)

regular = fm.findfont(fm.FontProperties(family=app.KOREAN_FONT), fallback_to_default=False)
bold = fm.findfont(
    fm.FontProperties(family=app.KOREAN_FONT, weight="bold"), fallback_to_default=False
)



def weight(entry) -> int:
    value = entry.weight
    return value if isinstance(value, int) else fm.weight_dict.get(value, 400)


# 파일 이름으로는 판단할 수 없다(macOS 시스템 NanumGothic.ttc 는 한 파일에 여러 굵기).
# 찾은 파일 안에 이 글꼴의 700 이상 굵기 서체가 있는지로 본다.
bold_faces = [
    f for f in fm.fontManager.ttflist
    if f.fname == bold and f.name == app.KOREAN_FONT and weight(f) >= 700
]
check("굵은 글씨는 굵기 700 이상 서체로 찾음", bool(bold_faces), bold)
for label, path in [("보통체", regular), ("굵은체", bold)]:
    check(f"{label}에 한글 글자 있음", FT2Font(path).get_char_index(ord("한")) != 0, path)

# app.py 의 Swing 라벨과 같은 방식으로 굵은 한글·영문을 실제로 그린다.
fig, ax = plt.subplots()
ax.text(0.5, 0.5, "HH 한글", fontsize=7.5, fontweight="bold")
ax.set_title("테스트 차트")
fig.canvas.draw()
plt.close(fig)

warnings = [message for message in records if "findfont" in message]
check("글꼴 조회 경고 없음", not warnings, warnings)

finish()
