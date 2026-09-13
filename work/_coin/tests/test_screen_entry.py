"""4시간봉 스크리닝 · 1시간봉 진입 판단 · BTC 시장 국면.

세 함수는 내부에서 '지금' 기준으로 진행 중인 봉을 잘라내고 now 를 받지 않는다.
그래서 합성 캔들의 마지막 봉을 실행 시각의 마지막 완료봉에 맞춘다(make_candles).
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

from conftest_paths import app, check, close, finish, geometric, make_candles

SETTINGS = app.Settings()
UP_240 = make_candles(geometric(200, 0.004), 240)  # 24h 등락률 약 2.4%
TICKER = {"trade_price": float(UP_240["close"].iloc[-1]) * 1.001, "acc_trade_price_24h": 5e9}


def screen(df=UP_240, ticker=TICKER, settings=SETTINGS):
    return app.screen_symbol("KRW-TEST", "테스트", df, ticker, settings)


# --- 1) 스크리닝 통과 -------------------------------------------------------
c = screen()
check("상승 추세 종목 통과", c is not None)
if c is not None:
    check("현재가는 실시간 티커 우선", c.price == TICKER["trade_price"], c.price)
    check("거래대금은 티커 24h 값", c.trade_value_24h == 5e9, c.trade_value_24h)
    check("24h 등락률 약 2.43%", close(c.change_24h, (1.004**6 - 1) * 100, 1e-6), c.change_24h)
    check("MA 4종 모두 채움", set(c.ma_240m) == set(app.MA_PERIODS), c.ma_240m)
    check("마지막 완료봉 기록", c.last_completed_240m == UP_240.index[-1])

# 티커가 없으면 캔들로 대체
# 합성 캔들 거래대금은 약 130만 원이라 최소 거래대금을 낮춰서 본다.
fallback = screen(ticker=None, settings=app.Settings(min_trade_value_24h=1))
check(
    "티커 없음 → 캔들 종가·거래대금 사용",
    fallback is not None
    and fallback.price == UP_240["close"].iloc[-1]
    and close(fallback.trade_value_24h, UP_240["trade_value"].iloc[-6:].sum()),
)
check("티커 없음 + 캔들 거래대금 미달 → 탈락", screen(ticker=None) is None)
nan_ticker = screen(ticker={"trade_price": None, "acc_trade_price_24h": None}, settings=app.Settings(min_trade_value_24h=1))
check("티커 값 None → 캔들로 대체", nan_ticker is not None and close(nan_ticker.trade_value_24h, UP_240["trade_value"].iloc[-6:].sum()))

# 진행 중인 봉(아직 안 끝난 봉)의 급등은 반영하지 않는다.
live_bar = pd.DataFrame(
    {"open": 1.0, "high": 1e9, "low": 1.0, "close": 1e9, "volume": 1.0, "trade_value": 1e9},
    index=pd.DatetimeIndex([app.current_candle_start_kst(240)], name="timestamp"),
)
with_live = screen(df=pd.concat([UP_240, live_bar]))
check("진행 중인 봉은 무시", with_live is not None and close(with_live.change_24h, c.change_24h), None if with_live is None else with_live.change_24h)

# --- 2) 스크리닝 탈락 -------------------------------------------------------
check("하락 추세 탈락", screen(df=make_candles(geometric(200, -0.004), 240)) is None)
check("횡보 탈락", screen(df=make_candles(np.full(200, 100.0), 240)) is None)
check("봉 부족 탈락", screen(df=UP_240.iloc[-(app.MIN_SCREEN_BARS - 1):]) is None)
check("등락률 최대 초과 탈락", screen(settings=app.Settings(max_change_24h=2.0)) is None)
check("등락률 최소 미달 탈락", screen(settings=app.Settings(min_change_24h=3.0)) is None)
check("거래대금 미달 탈락", screen(ticker={**TICKER, "acc_trade_price_24h": 1e7}) is None)

# --- 3) 1시간봉 진입 판단 ---------------------------------------------------
UP_60 = make_candles(geometric(200, 0.002), 60)
base = app.analyze_entry(UP_60, np.nan)  # 가격 없으면 마지막 종가
ma20 = base.ma20
check("가격 NaN → 마지막 종가 사용", base.price == UP_60["close"].iloc[-1], base.price)
check("매끄러운 상승 → 단기 정배열·MA5 상승·종가 상승", base.short_ordered and base.ma5_rising and base.close_rising)


def entry_at(ratio, df=UP_60):
    return app.analyze_entry(df, ma20 * ratio)


cases = [
    (1.015, "진입 관심"),
    (1.00, "진입 관심"),   # MA20 정확히 위 → 눌림 구간 하단 포함
    (1.05, "눌림 대기"),
    (1.079, "눌림 대기"),  # 8% 직전까지는 과열 아님 (1.08 은 부동소수점으로 8.0000…07%)
    (1.09, "과열 주의"),
    (0.99, "MA20 하회"),
]
for ratio, status in cases:
    e = entry_at(ratio)
    check(f"MA20 × {ratio} → {status}", e.status == status, f"{e.status} (이격 {e.distance_ma20_pct:.2f}%)")

check("진입 관심 점수 = 4 + 눌림 2", entry_at(1.015).score == 6, entry_at(1.015).score)
check("MA20 하회 점수에 눌림 보너스 없음", entry_at(0.99).score == 3, entry_at(0.99).score)

# 마지막 봉이 내리면 눌림 구간이어도 '눌림 확인' 에 머문다.
dip = geometric(200, 0.002)
dip[-1] = dip[-2] * 0.999
dip_df = make_candles(dip, 60)
dip_entry = app.analyze_entry(dip_df, app.analyze_entry(dip_df, np.nan).ma20 * 1.01)
check("마지막 봉 하락 + 눌림 구간 → 눌림 확인", dip_entry.status == "눌림 확인", dip_entry.status)

check("1시간봉 부족 → 데이터 부족", app.analyze_entry(UP_60.iloc[-(app.MIN_ENTRY_BARS - 1):], 100).status == "데이터 부족")
check("1시간봉 없음 → 데이터 부족", app.analyze_entry(None, 100).status == "데이터 부족")
check("가격 0 → 종가로 대체", app.analyze_entry(UP_60, 0).price == UP_60["close"].iloc[-1])

# --- 4) BTC 시장 국면 -------------------------------------------------------
strong = app.calculate_btc_regime(make_candles(geometric(200, 0.004), 240))
check("계속 상승 → Q4 Very Strong", strong["label"] == "Q4 Very Strong" and strong["score"] == 4, strong)
weak = app.calculate_btc_regime(make_candles(geometric(200, -0.004), 240))
check("계속 하락 → Q1 Weak", weak["label"] == "Q1 Weak" and weak["score"] == 0, weak)
check("7일 수익률 = 42봉 전 대비", close(strong["return_7d"], (1.004**42 - 1) * 100, 1e-6), strong["return_7d"])

# 장기 상승 뒤 최근 급락: MA120 위지만 24h·7d·MA20 기울기는 음수 → 1점
recent_drop = np.r_[geometric(170, 0.01), geometric(30, -0.01, start=100 * 1.01**169)]
one = app.calculate_btc_regime(make_candles(recent_drop, 240))
check("MA120 위 + 최근 하락 → 점수 1 → Q1", one["score"] == 1 and one["label"] == "Q1 Weak", one)

check("BTC 데이터 없음 → 확인 불가", app.calculate_btc_regime(None)["label"] == "확인 불가")
check("BTC 봉 부족 → 확인 불가", app.calculate_btc_regime(make_candles(geometric(60, 0.004), 240))["label"] == "확인 불가")

finish()
