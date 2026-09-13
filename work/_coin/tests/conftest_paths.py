"""테스트 공용 경로 · 합성 캔들 · 결과 집계.

각 테스트 파일은 맨 위에서 sys.dont_write_bytecode = True 로 둔 뒤
이 모듈을 import 한다. (_coin 에는 .gitignore 가 없어 __pycache__ 가 남는다)
"""
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
APP = PROJECT / "app.py"

sys.path.insert(0, str(PROJECT))
warnings.filterwarnings("ignore")
# 캐시 경고·Streamlit 런타임 경고가 테스트 출력을 덮지 않게 한다.
logging.disable(logging.WARNING)

import app  # noqa: E402


# ------------------------------------------------------------
# 합성 캔들
# ------------------------------------------------------------
def completed_end(unit: int) -> pd.Timestamp:
    """지금 기준 마지막 '완료' 봉의 시작 시각.

    screen_symbol / analyze_entry 는 내부에서 현재 시각으로 진행 중인 봉을
    잘라내므로, 시각을 고정하면 다음 날 테스트가 빈 데이터로 바뀐다.
    """
    return app.current_candle_start_kst(unit) - pd.Timedelta(minutes=unit)


def make_candles(closes, unit: int, end=None, spread: float = 0.003) -> pd.DataFrame:
    """종가 배열로 업비트 형식(timestamp 인덱스) OHLCV 를 만든다."""
    closes = np.asarray(closes, dtype=float)
    end = completed_end(unit) if end is None else pd.Timestamp(end)
    index = pd.date_range(end=end, periods=len(closes), freq=f"{unit}min")
    index.name = "timestamp"

    opens = np.r_[closes[0], closes[:-1]]
    df = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * (1 + spread),
            "low": np.minimum(opens, closes) * (1 - spread),
            "close": closes,
            "volume": 1_000.0,
        },
        index=index,
    )
    df["trade_value"] = df["close"] * df["volume"]
    return df


def geometric(n: int, step: float, start: float = 100.0) -> np.ndarray:
    """봉마다 step 비율로 변하는 매끄러운 종가."""
    return start * (1 + step) ** np.arange(n)


# ------------------------------------------------------------
# 결과 집계
# ------------------------------------------------------------
_failures: list[str] = []
_count = 0


def check(label: str, condition, detail="") -> None:
    """첫 실패에서 멈추지 않고 모두 모아 보고한다."""
    global _count
    _count += 1
    if bool(condition):
        return
    message = f"  실패: {label}" + (f"  ({detail})" if detail != "" else "")
    _failures.append(message)
    print(message)


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def finish() -> None:
    if _failures:
        print(f"{len(_failures)}/{_count} 실패")
        sys.exit(1)
    print(f"{_count}개 확인 통과")
    sys.exit(0)
