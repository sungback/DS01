"""공용 계산: 캔들 시간 경계 · RSI · ATR · 24h 등락률/거래대금 · 이동평균 추세 · Swing.

시간은 now_kst 를 넘겨 고정하므로 언제 돌려도 결과가 같다.
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

from conftest_paths import app, check, close, finish, geometric, make_candles

T = pd.Timestamp

# --- 1) 캔들 경계 (업비트 분봉은 UTC 기준 정렬) ------------------------------
check("240분봉 22:55 → 21:00 시작", app.current_candle_start_kst(240, T("2026-09-13 22:55")) == T("2026-09-13 21:00"))
check("240분봉 00:30 → 전날 21:00", app.current_candle_start_kst(240, T("2026-09-14 00:30")) == T("2026-09-13 21:00"))
check("240분봉 01:00 정각 → 01:00", app.current_candle_start_kst(240, T("2026-09-14 01:00")) == T("2026-09-14 01:00"))
check("60분봉 22:55 → 22:00", app.current_candle_start_kst(60, T("2026-09-13 22:55")) == T("2026-09-13 22:00"))
check(
    "tz 있는 입력(UTC 13:55) → KST 22:00",
    app.current_candle_start_kst(60, T("2026-09-13 13:55", tz="UTC")) == T("2026-09-13 22:00"),
)

df = make_candles([1, 2, 3], 240, end="2026-09-13 21:00")  # 13:00, 17:00, 21:00 시작
kept = app.keep_completed_candles(df, 240, T("2026-09-13 22:55"))
check("진행 중 21:00 봉 제외", list(kept.index) == [T("2026-09-13 13:00"), T("2026-09-13 17:00")], list(kept.index))
kept = app.keep_completed_candles(df, 240, T("2026-09-14 01:00"))
check("봉 종료 시각 정각이면 완료로 포함", len(kept) == 3, len(kept))
check("빈 입력 → 빈 표", app.keep_completed_candles(pd.DataFrame(), 240).empty)

# --- 2) RSI (Wilder) --------------------------------------------------------
def wilder_reference(close_prices, period=14):
    """반복문으로 쓴 교과서식 Wilder RSI (첫 평균도 지수평활로 시작)."""
    delta = np.diff(close_prices)
    out = np.full(len(close_prices), np.nan)
    avg_gain = avg_loss = None
    for i, d in enumerate(delta, start=1):
        gain, loss = max(d, 0.0), max(-d, 0.0)
        if avg_gain is None:
            avg_gain, avg_loss = gain, loss
        else:
            avg_gain += (gain - avg_gain) / period
            avg_loss += (loss - avg_loss) / period
        if i >= period:
            out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


rng = np.random.default_rng(3)
prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))
rsi = app._wilder_rsi(pd.Series(prices)).to_numpy()
ref = wilder_reference(prices)
check("RSI 앞 14개는 NaN", np.isnan(rsi[:14]).all(), rsi[:15])
check("RSI 가 반복문 구현과 일치", np.allclose(rsi[14:], ref[14:], atol=1e-8), np.nanmax(np.abs(rsi - ref)))
check("RSI 0~100", ((rsi[14:] >= 0) & (rsi[14:] <= 100)).all())
check("계속 상승 → RSI 100", app._wilder_rsi(pd.Series(geometric(40, 0.01))).iloc[-1] == 100.0)
check("가격 변화 없음 → RSI 50", app._wilder_rsi(pd.Series(np.full(40, 5.0))).iloc[-1] == 50.0)

# --- 3) ATR · 거래량 배율 ---------------------------------------------------
flat = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0}, index=range(60))
ind = app.add_indicators(flat)
check("고저폭 2, 갭 없음 → ATR 2", close(ind[app.ATR_COL].iloc[-1], 2.0), ind[app.ATR_COL].iloc[-1])
check("ATR% = 2%", close(ind["ATR_Pct"].iloc[-1], 2.0), ind["ATR_Pct"].iloc[-1])
check("일정 거래량 → 배율 1", close(ind["VolumeRatio"].iloc[-1], 1.0), ind["VolumeRatio"].iloc[-1])
check("add_indicators 가 선언된 지표 컬럼을 모두 만든다", app.INDICATOR_COLUMNS.issubset(ind.columns))
check("원본을 바꾸지 않음", "MA5" not in flat.columns)

# --- 4) 24h 등락률 · 거래대금 -----------------------------------------------
closes = geometric(20, 0.01)
bars = make_candles(closes, 240, end="2026-09-13 17:00")
expected = (closes[-1] / closes[-7] - 1) * 100  # 4시간봉 6개 = 24시간
check("24h 등락률 = 6봉 전 대비", close(app.rolling_change_24h(bars), expected), app.rolling_change_24h(bars))

gappy = bars.drop(bars.index[-7])  # 정확히 24시간 전 봉이 빠진 경우 → 그 이전 봉
expected_gap = (closes[-1] / closes[-8] - 1) * 100
check("24h 전 봉 누락 → 직전 봉 사용", close(app.rolling_change_24h(gappy), expected_gap), app.rolling_change_24h(gappy))
check("24h 이전 데이터 없음 → NaN", np.isnan(app.rolling_change_24h(bars.iloc[-3:])))

value = app.trade_value_24h(bars)
check("24h 거래대금 = 최근 6봉 합", close(value, bars["trade_value"].iloc[-6:].sum()), value)
no_value = bars.drop(columns="trade_value")
check("trade_value 없으면 종가×거래량", close(app.trade_value_24h(no_value), value))

# --- 5) 이동평균 추세 -------------------------------------------------------
up = app.add_indicators(make_candles(geometric(200, 0.004), 240))
ordered, rising, slopes = app.ma_trend(up)
check("상승 추세 → 정배열·상승", ordered and rising, (ordered, rising))
check("MA20 기울기 = 3봉 전 대비", close(slopes[20], (up["MA20"].iloc[-1] / up["MA20"].iloc[-4] - 1) * 100))

down = app.add_indicators(make_candles(geometric(200, -0.004), 240))
ordered, rising, _ = app.ma_trend(down)
check("하락 추세 → 정배열 아님·상승 아님", not ordered and not rising, (ordered, rising))

# --- 6) Swing 구조 ----------------------------------------------------------
def zigzag(n, trend):
    i = np.arange(n)
    triangle = 2 * np.abs((i % 10) / 10 - 0.5) * 2 - 1  # -1..1, 주기 10
    return 100 * (1 + trend * i) * (1 + 0.05 * triangle)


rising_zz = make_candles(zigzag(80, 0.01), 240, spread=0.0)
points = app.detect_swing_points(rising_zz)
check("지그재그 상승 → HH/HL", app.classify_swing_structure(points) == "HH/HL", app.classify_swing_structure(points))
check("Swing 고점/저점 모두 검출", {"high", "low"} <= set(points["kind"]), points["kind"].unique())
confirmable = rising_zz.index[: -app.SWING_RIGHT_BARS]
check("오른쪽 확인 봉이 없는 최근 3봉은 Swing 아님", points["timestamp"].isin(confirmable).all())

falling_zz = make_candles(zigzag(80, -0.008), 240, spread=0.0)
structure = app.classify_swing_structure(app.detect_swing_points(falling_zz))
check("지그재그 하락 → LH/LL", structure == "LH/LL", structure)

check("봉이 너무 적음 → 데이터 부족", app.classify_swing_structure(app.detect_swing_points(rising_zz.iloc[:8])) == "데이터 부족")
check("매끄러운 상승(Swing 없음) → 데이터 부족", app.classify_swing_structure(app.detect_swing_points(make_candles(geometric(80, 0.01), 240))) == "데이터 부족")

# --- 7) safe_float ----------------------------------------------------------
check("None → 기본값", np.isnan(app.safe_float(None)))
check("문자열 숫자 → float", app.safe_float("3.5") == 3.5)
check("문자 → 기본값", app.safe_float("abc", 0.0) == 0.0)
check("NaN → 기본값", app.safe_float(np.nan, -1.0) == -1.0)

finish()
