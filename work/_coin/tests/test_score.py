"""FinalScore(100점 만점) 구성과 패널티.

'점수가 0~100 안' 은 마지막 clamp 때문에 항상 참이라 아무것도 지키지 못한다.
대신 (1) 모든 조건이 최고일 때 정확히 100점인지, (2) 총점이 구성요소의
합과 일치하는지, (3) 구간 경계값을 고정한다.
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import numpy as np

from conftest_paths import app, check, close, finish

SETTINGS = app.Settings()


def candidate(
    slopes=None,
    flags=(True, True, True, True),
    distance=1.5,
    change=5.0,
    trade_value=20_000_000_000,
) -> app.Candidate:
    above, ordered, ma5_up, close_up = flags
    return app.Candidate(
        symbol="KRW-TEST",
        korean_name="테스트",
        price=100.0,
        change_24h=change,
        trade_value_24h=trade_value,
        ma_slope_pct=dict(app.MA_SLOPE_THRESHOLDS) if slopes is None else slopes,
        entry=app.EntryTiming(
            distance_ma20_pct=distance,
            above_ma20=above,
            short_ordered=ordered,
            ma5_rising=ma5_up,
            close_rising=close_up,
        ),
    )


# --- 1) 최고 조건이면 정확히 100점 (30 + 40 + 20 + 6 + 4) ---------------
best = app.calculate_score(candidate(), SETTINGS)
check("최고 조건 총점 100", best.total == 100.0, best)
check("4시간 추세 30", best.trend_4h == 30.0, best.trend_4h)
check("1시간 진입 40", best.entry_1h == 40.0, best.entry_1h)
check("MA20 위치 20", best.ma20_position == 20.0, best.ma20_position)
check("시장 품질 10", best.market_quality == 10.0, best.market_quality)
check("패널티 없음", best.penalty == 0.0, best.penalty)

# 기준치를 크게 넘어도 추세 점수는 30점을 넘지 않는다.
steep = app.calculate_score(candidate(slopes={20: 50.0, 60: 50.0, 120: 50.0}), SETTINGS)
check("추세 상한 30", steep.trend_4h == 30.0, steep.trend_4h)

# --- 2) 추세 점수는 기준치 대비 비례, 음수 기울기는 0 ---------------------
half = {p: t / 2 for p, t in app.MA_SLOPE_THRESHOLDS.items()}
check("기울기 절반 → 15점", app.calculate_score(candidate(slopes=half), SETTINGS).trend_4h == 15.0)
down = {20: -3.0, 60: -3.0, 120: -3.0}
check("음수 기울기 → 0점", app.calculate_score(candidate(slopes=down), SETTINGS).trend_4h == 0.0)
check("기울기 누락 → 0점", app.calculate_score(candidate(slopes={}), SETTINGS).trend_4h == 0.0)

# --- 3) 진입 조건은 개당 10점 --------------------------------------------
for n in range(5):
    flags = tuple([True] * n + [False] * (4 - n))
    got = app.calculate_score(candidate(flags=flags), SETTINGS).entry_1h
    check(f"진입 조건 {n}개 → {n * 10}점", got == n * 10.0, got)

# --- 4) 패널티 ------------------------------------------------------------
over = app.calculate_score(candidate(distance=9.0), SETTINGS)
check("MA20 이격 8% 초과 → 과열 15", over.penalty_overheat == 15.0 and over.penalty == 15.0, over)
check("과열 구간 위치 점수 0", over.ma20_position == 0.0, over.ma20_position)

below = app.calculate_score(candidate(distance=-0.5), SETTINGS)
check("MA20 아래 → 10 감점", below.penalty_below_ma20 == 10.0, below)
check("MA20 바로 아래 위치 5점", below.ma20_position == 5.0, below.ma20_position)

surge = app.calculate_score(candidate(change=13.0), SETTINGS)
check("24h 12% 초과 급등 → 10 감점", surge.penalty_daily_surge == 10.0, surge)
check("급등 시 모멘텀 0", surge.market_quality == 4.0, surge.market_quality)

stacked = app.calculate_score(candidate(distance=9.0, change=13.0), SETTINGS)
check("과열+급등 패널티 누적 25", stacked.penalty == 25.0, stacked.penalty)

# 1시간봉 데이터가 없으면(EntryTiming 기본값) 위치·진입 점수 0, 패널티도 없음
missing = app.calculate_score(candidate(flags=(False,) * 4, distance=np.nan), SETTINGS)
check("진입 데이터 없음 → 위치 0", missing.ma20_position == 0.0, missing)
check("진입 데이터 없음 → 패널티 0", missing.penalty == 0.0, missing)

# --- 5) 구간 경계값 --------------------------------------------------------
position_cases = [
    (0.0, 20.0), (3.0, 20.0), (3.0001, 15.0), (5.0, 15.0), (5.01, 8.0),
    (8.0, 8.0), (8.01, 0.0), (-0.01, 5.0), (-1.0, 5.0), (-1.01, 0.0), (np.nan, 0.0),
]
for distance, expected in position_cases:
    got = app._ma20_position_score(distance)
    check(f"위치 점수 이격 {distance}", got == expected, f"{got} != {expected}")

momentum_cases = [
    (0.99, 0.0), (1.0, 4.0), (2.99, 4.0), (3.0, 6.0), (8.0, 6.0),
    (8.01, 3.0), (12.0, 3.0), (12.01, 0.0), (-5.0, 0.0),
]
for change, expected in momentum_cases:
    got = app._momentum_score(change)
    check(f"모멘텀 점수 {change}%", got == expected, f"{got} != {expected}")

minimum = SETTINGS.min_trade_value_24h
liquidity_cases = [
    (10_000_000_000, 4.0), (9_999_999_999, 3.0), (3_000_000_000, 3.0),
    (1_000_000_000, 2.0), (minimum, 1.0), (minimum - 1, 0.0),
]
for value, expected in liquidity_cases:
    got = app._liquidity_score(value, minimum)
    check(f"유동성 점수 {value:,}", got == expected, f"{got} != {expected}")

# --- 6) 무작위 입력: 총점 = clamp(구성요소 합 - 패널티) ---------------------
rng = np.random.default_rng(7)
allowed_penalties = {0.0, 10.0, 15.0, 20.0, 25.0}
for i in range(3000):
    c = candidate(
        slopes={p: rng.uniform(-5, 5) for p in app.MA_SLOPE_THRESHOLDS},
        flags=tuple(rng.random(4) < 0.5),
        distance=rng.choice([np.nan, rng.uniform(-5, 15)]),
        change=rng.uniform(-10, 40),
        trade_value=rng.uniform(0, 3e10),
    )
    s = app.calculate_score(c, SETTINGS)
    raw = s.trend_4h + s.entry_1h + s.ma20_position + s.market_quality - s.penalty
    ok = (
        close(s.total, round(app.clamp(raw, 0.0, 100.0), 1), tol=2e-3)
        and 0 <= s.trend_4h <= 30
        and 0 <= s.entry_1h <= 40
        and 0 <= s.ma20_position <= 20
        and 0 <= s.market_quality <= 10
        and s.penalty in allowed_penalties
        and s.penalty == s.penalty_overheat + s.penalty_below_ma20 + s.penalty_daily_surge
    )
    if not ok:
        check(f"무작위 점수 구성 #{i}", False, s)
        break
else:
    check("무작위 점수 구성 3000건", True)

finish()
