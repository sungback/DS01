"""MA/ATR 매매 계획: 매수구간 · 손절 · 익절 · 포지션 크기.

손으로 계산한 기준 사례로 값을 고정하고, 무작위 입력으로 불변식을 확인한다.
  - 계획 진입가는 항상 매수구간 안
  - 손절폭은 1 ATR 이상(가격이 그보다 작으면 가격), 2 ATR 이하
  - 실제 손실 금액은 거래당 허용위험을, 투자 금액은 최대 비중을 넘지 않는다
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import numpy as np

from conftest_paths import app, check, close, finish

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
check("구간 아래 → MA20 + 0.1ATR", close(plan(95, 100, 97, 2).buy_reference, 100.2))

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

# --- 9) 무작위 불변식 -------------------------------------------------------
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
    rules = {
        "진입가가 매수구간 안": t.buy_zone_low - eps * ref <= ref <= t.buy_zone_high + eps * ref,
        "손절 < 진입가, 0 이상": 0 <= t.stop_price < ref,
        "손절폭 ≥ min(1ATR, 진입가)": risk >= min(app.MIN_RISK_ATR * atr, ref) * (1 - 1e-9),
        "손절폭 ≤ 2ATR": risk <= app.MAX_STOP_ATR * atr * (1 + 1e-9),
        "익절 순서": ref < t.take_profit_1 < t.take_profit_2 < t.runner_trigger_4r,
        "Trail ≥ 본전": t.trailing_stop_normal >= ref and t.trailing_stop_tight >= ref,
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
