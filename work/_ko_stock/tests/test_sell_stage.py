"""
app.py 의 '20. 매수가 / 손절가' ~ '22. 현재 매도 단계' 블록을
파일에서 그대로 떼어 내 실행한다.

목적: 매수가를 실제로 입력했을 때 매도 단계가 상수가 아니라
      조건별로 갈라지는지 확인한다. (기존에는 항상 '보유' 였음)
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH


src = APP.read_text()
start = src.index("# 20. 매수가 / 손절가")
end = src.index("# 23. 매수 / 매도 계획 표")
block = src[start:end]

# 블록 앞의 '# ====' 줄 잔재 제거
block = re.sub(r"^#.*\n#=*\n", "", block)
print("떼어 낸 코드 줄 수 :", len(block.splitlines()))

# 분석을 통과한 종목과 비슷한 형태의 표본
# (app.py 필터상 Close > MA20 > MA60 은 항상 성립)
selected = pd.DataFrame(
    {
        "Code": ["A", "B", "C", "D", "E", "F", "G"],
        "Close": [10000.0] * 7,
        "MA20": [9500.0] * 7,
        "MA60": [9000.0] * 7,
    }
)

STOP_RATE = 0.08

positions = {
    # 매수가 미입력 → 미보유
    "A": {"매수가": None, "손절가": None},
    # 이제 막 샀다 → 1R 전
    "B": {"매수가": 9800.0, "손절가": None},
    # 손절가 9000, R=1000 → 1R=11000, 2R=12000 : 현재가 10000 → 1R 전
    "C": {"매수가": 10000.0, "손절가": 9000.0},
    # 싸게 샀다. 손절 9000, R=500 → 1R=10000 : 현재가 10000 → 1R 이상
    "D": {"매수가": 9500.0, "손절가": 9000.0},
    # 아주 싸게 샀다. 손절 8000, R=500 → 2R=9500 : 현재가 10000 → 2R 이상
    "E": {"매수가": 8500.0, "손절가": 8000.0},
    # 고점에 물렸다. 손절가를 현재가 위로 직접 지정 → 손절 구간
    "F": {"매수가": 13000.0, "손절가": 12000.0},
    # MA60(9000)보다 싸게 산 경우.
    # 자동 손절가가 매수가를 넘으면 안 된다. R 이 음수가 되어
    # 1R / 2R 이 매수가 아래로 뒤집히기 때문이다.
    "G": {"매수가": 8800.0, "손절가": None},
}

ns = {"pd": pd, "np": np, "selected": selected, "positions": positions,
      "STOP_RATE": STOP_RATE}
exec(compile(block, str(APP), "exec"), ns)

out = ns["selected"][
    ["Code", "Close", "매수가", "손절가", "1R(30%매도)", "2R(30%매도)",
     "현재단계", "매도신호"]
]
print()
print(out.to_string(index=False))

expected = {
    # 손절가 8,096(=8,800×0.92) / 1R 9,504 / 2R 10,208
    # 현재가 10,000 은 1R 을 넘었지만 2R 에는 못 미친다
    "G": "1R 이상",
    "A": "미보유",
    "B": "1R 전",
    "C": "1R 전",
    "D": "1R 이상",
    "E": "2R 이상",
    "F": "손절 구간",
}

actual = dict(zip(out["Code"], out["현재단계"]))
print("\n기대 :", expected)
print("실제 :", actual)

ok = actual == expected
print("\n단계 분기 :", "통과" if ok else "실패")

# 미보유 종목은 가격 컬럼이 모두 비어 있어야 한다
a = out[out["Code"] == "A"].iloc[0]
blank = all(pd.isna(a[c]) for c in ["손절가", "1R(30%매도)", "2R(30%매도)"])
print("미보유 종목 가격 공란 :", "통과" if blank else "실패")

# 상수가 아니어야 한다 (원래 버그의 핵심)
varied = out["현재단계"].nunique() > 1
print("매도 단계가 상수 아님 :", "통과" if varied else "실패")

# 손절가는 언제나 매수가보다 낮아야 한다
held_rows = out[out["매수가"].notna()]
below = bool((held_rows["손절가"] < held_rows["매수가"]).all())
print("손절가 < 매수가      :", "통과" if below else "실패")

# 1R / 2R 은 매수가보다 위여야 한다
upward = bool(
    (held_rows["1R(30%매도)"] > held_rows["매수가"]).all()
    and (held_rows["2R(30%매도)"] > held_rows["1R(30%매도)"]).all()
)
print("1R < 2R, 둘 다 매수가 위 :", "통과" if upward else "실패")

ok = ok and below and upward

sys.exit(0 if (ok and blank and varied) else 1)
