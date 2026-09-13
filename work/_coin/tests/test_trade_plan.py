"""MA/ATR 매매 계획: 매수구간 · 손절 · 익절 · 포지션 크기.

손으로 계산한 기준 사례로 값을 고정하고, 무작위 입력으로 불변식을 확인한다.
  - 계획 진입가는 항상 매수구간 안
  - 손절폭은 1 ATR 이상(가격이 그보다 작으면 가격), 2 ATR + 호가 1틱 이하
  - 실제 손실 금액은 거래당 허용위험을, 투자 금액은 최대 비중을 넘지 않는다
  - 모든 가격은 업비트 원화 호가 단위 (사는 가격·손절·Trail 은 내림, 익절은 올림)
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import numpy as np

from conftest_paths import app, check, close, finish, on_tick

SETTINGS = app.Settings()  # 계좌 1억, 거래당 위험 0.5%, 최대 비중 20%


def plan(price, ma20, ma60, atr, settings=SETTINGS) -> app.TradePlan:
    c = app.Candidate(
        symbol="KRW-TEST",
        korean_name="테스트",
        price=price,
        change_24h=5.0,
        trade_value_24h=1e10,
        entry=app.EntryTiming(ma20=ma20, ma60=ma60, atr=atr),
    )
    return app.build_trade_plan(c, settings)


# --- 1) 기준 사례: 가격 100, MA20 100, MA60 97, ATR 2 ----------------------
p = plan(100, 100, 97, 2)
check("기준 사례 계획 가능", p.available, p.reason)
check("매수구간 99~101", (p.buy_zone_low, p.buy_zone_high) == (99.0, 101.0), p)
check("구간 안 → 진입가 = 현재가", p.buy_reference == 100.0, p.buy_reference)
# 손절 = min(max(MA60-0.5ATR=96, 진입가-2ATR=96), 구간하단-0.25ATR=98.5) = 96
check("손절 96", p.stop_price == 96.0, p.stop_price)
check("1개당 위험 4 (4%)", p.risk_per_unit == 4.0 and p.risk_pct == 4.0, p)
check("1차 익절 +1.5R = 106", p.take_profit_1 == 106.0, p.take_profit_1)
check("2차 익절 +2.5R = 110", p.take_profit_2 == 110.0, p.take_profit_2)
check("Runner 기준 +4R = 116", p.runner_trigger_4r == 116.0, p.runner_trigger_4r)
check("본전 손절 = 진입가", p.breakeven_stop == 100.0, p.breakeven_stop)
check("기본 Trail 모드", p.trailing_stop_current == p.trailing_stop_normal and "기본" in p.runner_mode, p.runner_mode)
# 위험예산 50만 ÷ 4 × 100 = 1,250만 (최대 비중 2,000만 이하)
check("위험예산 50만", p.risk_budget == 500_000, p.risk_budget)
check("투자금액 1,250만", close(p.position_amount, 12_500_000), p.position_amount)
check("수량 125,000", close(p.position_quantity, 125_000), p.position_quantity)
check("실제 위험 = 예산", close(p.actual_risk_amount, 500_000), p.actual_risk_amount)
check("비중 제한 안 걸림", not p.position_capped)

# --- 2) 진입가 결정 분기 ----------------------------------------------------
check("구간 위 → 구간 상단", plan(105, 100, 97, 2).buy_reference == 101.0)
# MA20 + 0.1ATR = 100.2 → 1원 단위 내림
check("구간 아래 → MA20 + 0.1ATR 을 호가 단위로 내림", plan(95, 100, 97, 2).buy_reference == 100.0, plan(95, 100, 97, 2).buy_reference)

# --- 3) 최소 손절폭 보장 ----------------------------------------------------
# MA60 이 MA20 에 붙어 있으면 구조적 손절이 98.5 가 되어 폭 1.5 < 1ATR(2)
narrow = plan(100, 100, 99.9, 2)
check("최소 손절폭 → 손절 98", close(narrow.stop_price, 98.0), narrow.stop_price)
check("최소 손절폭 → 위험 = 1ATR", close(narrow.risk_per_unit, 2.0), narrow.risk_per_unit)

# --- 4) 최대 비중 제한 ------------------------------------------------------
# 위험 0.2% 짜리 계획이면 위험 기준 금액(2.5억)이 최대 비중(2,000만)을 넘는다.
capped = plan(100, 100, 99.9, 0.2)
check("비중 제한 발동", capped.position_capped, capped)
check("투자금액 = 최대 비중 2,000만", close(capped.position_amount, 20_000_000), capped.position_amount)
check("제한 시 실제 위험 < 예산", capped.actual_risk_amount < capped.risk_budget, capped.actual_risk_amount)

# --- 5) Runner(4R 이후 강화 Trail) -----------------------------------------
runner = plan(200, 100, 97, 2)
check("4R 도달 → 강화 Trail", runner.trailing_stop_current == runner.trailing_stop_tight and "4R" in runner.runner_mode, runner.runner_mode)

# --- 6) 계산 불가 입력 ------------------------------------------------------
for label, args in [
    ("ATR NaN", (100, 100, 97, np.nan)),
    ("ATR 0", (100, 100, 97, 0)),
    ("MA20 0", (100, 0, 97, 2)),
    ("가격 0", (0, 100, 97, 2)),
    ("MA60 NaN", (100, 100, np.nan, 2)),
]:
    check(f"{label} → 계획 없음", not plan(*args).available)

# --- 7) 가격 단위와 무관 (1원 미만 코인) -----------------------------------
tiny = plan(0.1, 0.1, 0.097, 0.002)
check("가격 1/1000 → 손절도 1/1000", close(tiny.stop_price, 0.096), tiny.stop_price)
check("가격 1/1000 → 위험% 동일", close(tiny.risk_pct, p.risk_pct), tiny.risk_pct)
check("가격 1/1000 → 투자금액 동일", close(tiny.position_amount, p.position_amount), tiny.position_amount)

# --- 8) ATR 이 가격보다 큰 극단 사례: 손절 0원, 위험 100% -------------------
# 현재 동작을 고정한다. 손실 한도는 여전히 예산 안이다.
wild = plan(1.0, 1.0, 0.9, 1.0)
check("극단 변동성 → 손절 0", wild.stop_price == 0.0, wild.stop_price)
check("극단 변동성 → 위험 100%", close(wild.risk_pct, 100.0), wild.risk_pct)
check("극단 변동성 → 실제 위험 ≤ 예산", wild.actual_risk_amount <= wild.risk_budget + 1e-6, wild)

# --- 9) 호가 단위 (업비트 원화 마켓) ----------------------------------------
# 100~1,000원 구간은 1원 단위. 원값: 구간 149.55~151.25, 진입 151.25, 손절 148.3
t1 = plan(151.37, 150.4, 149.15, 1.7)
check("1원 구간: 매수구간 149~151 (내림)", (t1.buy_zone_low, t1.buy_zone_high) == (149.0, 151.0), (t1.buy_zone_low, t1.buy_zone_high))
check("1원 구간: 진입가 151 (151.25 내림)", t1.buy_reference == 151.0, t1.buy_reference)
check("1원 구간: 손절 148 (148.3 내림)", t1.stop_price == 148.0, t1.stop_price)
check("1원 구간: 위험은 반올림한 가격으로 3", t1.risk_per_unit == 3.0, t1.risk_per_unit)
check("1원 구간: 1차 익절 156 (155.5 올림)", t1.take_profit_1 == 156.0, t1.take_profit_1)
check("1원 구간: 2차 익절 159 (158.5 올림)", t1.take_profit_2 == 159.0, t1.take_profit_2)
check("1원 구간: Runner 163", t1.runner_trigger_4r == 163.0, t1.runner_trigger_4r)
check(
    "1원 구간: 수량·실제 위험도 반올림한 가격 기준",
    close(t1.position_quantity * 151.0, t1.position_amount) and close(t1.actual_risk_amount, t1.position_quantity * 3.0),
    t1,
)

# 0.1~1원 구간은 0.001원 단위 (예: KRW-VTHO 0.877원). 계산 오차로 한 틱 밀리면 안 된다.
t2 = plan(0.8773, 0.8761, 0.86, 0.0042)
check("0.001원 구간: 매수구간 0.874~0.878", close(t2.buy_zone_low, 0.874) and close(t2.buy_zone_high, 0.878), (t2.buy_zone_low, t2.buy_zone_high))
check("0.001원 구간: 진입가 0.877", close(t2.buy_reference, 0.877), t2.buy_reference)
check("0.001원 구간: 손절 0.868 (0.8686 내림)", close(t2.stop_price, 0.868), t2.stop_price)
check("0.001원 구간: 1차 익절 0.891 (0.8905 올림)", close(t2.take_profit_1, 0.891), t2.take_profit_1)
check("0.001원 구간: 2차 익절 0.9 (0.8995 올림)", close(t2.take_profit_2, 0.9), t2.take_profit_2)
check("0.001원 구간: Runner 0.913 (오차로 0.914 아님)", close(t2.runner_trigger_4r, 0.913), t2.runner_trigger_4r)

# 2,000,000원 이상은 1,000원 단위
t3 = plan(151_234_567, 150_900_000, 149_000_000, 1_200_000)
check("1,000원 구간: 진입가 151,234,000", t3.buy_reference == 151_234_000, t3.buy_reference)
check("1,000원 구간: 손절 148,834,000", t3.stop_price == 148_834_000, t3.stop_price)

# 익절 올림이 윗 구간(5원 단위)으로 넘어가면 그 구간 단위를 따른다: 5,005 · 5,014 → 5,015
t4 = plan(4_990.4, 4_990, 4_985, 3)
check("구간 넘김: 진입가 4,990 · 손절 4,984", (t4.buy_reference, t4.stop_price) == (4_990.0, 4_984.0), (t4.buy_reference, t4.stop_price))
check("구간 넘김: 1차 익절 4,999 (1원 단위)", t4.take_profit_1 == 4_999.0, t4.take_profit_1)
check("구간 넘김: 2차 익절 5,005 (5원 단위)", t4.take_profit_2 == 5_005.0, t4.take_profit_2)
check("구간 넘김: Runner 5,015 (5,014 올림)", t4.runner_trigger_4r == 5_015.0, t4.runner_trigger_4r)

# ATR 이 호가 1틱보다 작으면 Trail 계산값(MA20-2ATR=150.5)이 본전(150)보다 위에 올 수 있다.
# 이때 Trail 은 내림 → 150. 올림(151)이면 본전보다 위에서 끊게 된다.
t5 = plan(150.9, 150.9, 150.8, 0.2)
check("작은 ATR: 진입가 150 · 손절 149", (t5.buy_reference, t5.stop_price) == (150.0, 149.0), (t5.buy_reference, t5.stop_price))
check("작은 ATR: 기본 Trail 150 (150.5 내림, 151 아님)", t5.trailing_stop_normal == 150.0, t5.trailing_stop_normal)
check("작은 ATR: 강화 Trail 150 (150.6 내림)", t5.trailing_stop_tight == 150.0, t5.trailing_stop_tight)

for label, t in [("1원", t1), ("0.001원", t2), ("1,000원", t3), ("구간 넘김", t4), ("작은 ATR", t5)]:
    fields = [t.buy_zone_low, t.buy_zone_high, t.buy_reference, t.stop_price, t.take_profit_1,
              t.take_profit_2, t.runner_trigger_4r, t.trailing_stop_normal, t.trailing_stop_tight]
    check(f"{label} 사례: 모든 가격이 호가 단위", all(on_tick(v) for v in fields), fields)

# --- 10) 무작위 불변식 ------------------------------------------------------
rng = np.random.default_rng(11)
eps = 1e-6
checked = 0
for i in range(5000):
    ma20 = 10 ** rng.uniform(-3, 7)
    atr = ma20 * rng.uniform(0.001, 0.8)
    ma60 = ma20 * rng.uniform(0.7, 1.1)
    price = ma20 * rng.uniform(0.8, 1.6)
    settings = app.Settings(
        account_capital=rng.uniform(1e5, 1e9),
        risk_per_trade_pct=rng.uniform(0.05, 10),
        max_position_pct=rng.uniform(1, 100),
    )
    t = plan(price, ma20, ma60, atr, settings)
    if not t.available:
        check(f"무작위 계획 #{i} 계산 불가", False, t.reason)
        break

    ref, risk = t.buy_reference, t.risk_per_unit
    budget = settings.account_capital * settings.risk_per_trade_pct / 100
    max_amount = settings.account_capital * settings.max_position_pct / 100
    tick = app.krw_tick_size(ref)
    prices = [t.buy_zone_low, t.buy_zone_high, ref, t.stop_price, t.take_profit_1, t.take_profit_2,
              t.runner_trigger_4r, t.trailing_stop_normal, t.trailing_stop_tight]
    rules = {
        "진입가가 매수구간 안": t.buy_zone_low - eps * ref <= ref <= t.buy_zone_high + eps * ref,
        "손절 < 진입가, 0 이상": 0 <= t.stop_price < ref,
        "손절폭 ≥ min(1ATR, 진입가)": risk >= min(app.MIN_RISK_ATR * atr, ref) * (1 - 1e-9),
        "손절폭 ≤ 2ATR + 호가 1틱": risk <= (app.MAX_STOP_ATR * atr + tick) * (1 + 1e-9),
        "익절 순서": ref < t.take_profit_1 <= t.take_profit_2 <= t.runner_trigger_4r,
        "익절은 R 배수 이상(올림)": t.take_profit_1 >= (ref + app.TP1_R * risk) * (1 - 1e-9)
        and t.runner_trigger_4r >= (ref + app.RUNNER_TRIGGER_R * risk) * (1 - 1e-9),
        "매수구간 상단 ≤ MA20+0.5ATR(내림)": t.buy_zone_high <= (ma20 + app.BUY_ZONE_ATR * atr) * (1 + 1e-9),
        "모든 가격이 호가 단위": all(on_tick(v) for v in prices),
        "Trail ≥ 본전": t.trailing_stop_normal >= ref and t.trailing_stop_tight >= ref,
        "Trail 은 계산값 이하(내림)": t.trailing_stop_normal <= max(ref, ma20 - app.TRAIL_ATR_MULT * atr) * (1 + 1e-9)
        and t.trailing_stop_tight <= max(ref, ma20 - app.RUNNER_TRAIL_ATR_MULT * atr) * (1 + 1e-9),
        "투자금액 ≤ 최대 비중": t.position_amount <= max_amount * (1 + 1e-9),
        "투자금액 ≤ 계좌": t.position_amount <= settings.account_capital * (1 + 1e-9),
        "실제 위험 ≤ 예산": t.actual_risk_amount <= budget * (1 + 1e-9),
        "수량 × 진입가 = 금액": close(t.position_quantity * ref, t.position_amount, 1e-9),
        "제한 표시 일치": t.position_capped == (t.actual_risk_amount < budget * (1 - 1e-9)),
    }
    broken = [name for name, ok in rules.items() if not ok]
    if broken:
        check(f"무작위 계획 #{i}", False, f"{broken} price={price} ma20={ma20} ma60={ma60} atr={atr}")
        break
    checked += 1
check(f"무작위 계획 불변식 {checked}건", checked == 5000)

finish()
