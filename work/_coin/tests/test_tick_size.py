"""업비트 원화(KRW) 마켓 호가 단위와 가격 반올림.

표 출처: docs.upbit.com/kr/docs/krw-market-info (2025-07-31 개편 기준).
2026-09-13 원화 마켓 288개 전 종목의 /v1/orderbook/instruments tick_size 와
표가 모두 일치함을 확인했다. 구간 경계는 '이상 ~ 미만' 이다.
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

from decimal import Decimal

import numpy as np

from conftest_paths import app, check, finish, on_tick


def same(a: float, b: str) -> bool:
    return Decimal(str(a)) == Decimal(b)


# --- 1) 구간 경계 (공식 표 17개 구간) ---------------------------------------
boundaries = [
    (150_000_000, "1000"), (2_000_000, "1000"), (1_999_999, "1000"), (1_000_000, "1000"),
    (999_999, "500"), (500_000, "500"), (499_999, "100"), (100_000, "100"),
    (99_999, "50"), (50_000, "50"), (49_999, "10"), (10_000, "10"),
    (9_999, "5"), (5_000, "5"), (4_999, "1"), (1_000, "1"), (999, "1"), (100, "1"),
    (99.99, "0.1"), (10, "0.1"), (9.999, "0.01"), (1, "0.01"),
    (0.9999, "0.001"), (0.1, "0.001"), (0.09999, "0.0001"), (0.01, "0.0001"),
    (0.009999, "0.00001"), (0.001, "0.00001"), (0.0009999, "0.000001"), (0.0001, "0.000001"),
    (0.00009999, "0.0000001"), (0.00001, "0.0000001"), (0.0000099, "0.00000001"),
]
for price, tick in boundaries:
    got = app.krw_tick_size(price)
    check(f"{price} 원 → 호가 단위 {tick}", same(got, tick), got)

# --- 2) 내림 · 올림 ----------------------------------------------------------
cases = [
    # (가격, 방향, 기대값, 설명)
    (151.37, "down", "151", "1원 단위 내림"),
    (151.37, "up", "152", "1원 단위 올림"),
    (5_003, "down", "5000", "5원 단위 내림"),
    (5_003, "up", "5005", "5원 단위 올림"),
    (4_999.7, "down", "4999", "1원 구간 내림"),
    (4_999.7, "up", "5000", "올림이 윗 구간 경계에 닿음"),
    (9_999.2, "up", "10000", "5원 구간에서 10원 구간 경계로 올림"),
    (0.12345, "down", "0.123", "0.001원 단위 내림"),
    (0.12345, "up", "0.124", "0.001원 단위 올림"),
    (0.0000123456, "down", "0.0000123", "0.0000001원 단위 내림"),
    (150_000_123, "down", "150000000", "1,000원 단위 내림"),
    (150_000_123, "up", "150001000", "1,000원 단위 올림"),
    (0.0, "down", "0", "0원"),
]
for price, direction, expected, label in cases:
    got = app.round_to_tick(price, direction)
    check(f"{label}: {price} {direction} → {expected}", same(got, expected), got)

# 이미 호가 단위에 맞는 가격은 어느 방향이든 그대로
for price in [150.0, 5_000.0, 0.877, 0.3, 151_234_000.0]:
    for direction in ("down", "up"):
        got = app.round_to_tick(price, direction)
        check(f"호가 단위 가격 {price} {direction} 유지", got == price, got)

# 계산 중 생긴 부동소수점 오차 때문에 한 틱 더 올라가거나 내려가면 안 된다.
check("0.1+0.2 올림 → 0.3 (0.301 아님)", same(app.round_to_tick(0.1 + 0.2, "up"), "0.3"), app.round_to_tick(0.1 + 0.2, "up"))
check("100×1.1 올림 → 110 (111 아님)", same(app.round_to_tick(100 * 1.1, "up"), "110"), app.round_to_tick(100 * 1.1, "up"))
check("0.7-0.1 내림 → 0.6 (0.599 아님)", same(app.round_to_tick(0.7 - 0.1, "down"), "0.6"), app.round_to_tick(0.7 - 0.1, "down"))

check("NaN → NaN", np.isnan(app.round_to_tick(np.nan, "down")))
try:
    app.round_to_tick(100.0, "nearest")
    check("잘못된 방향 → ValueError", False, "예외가 나지 않음")
except ValueError:
    check("잘못된 방향 → ValueError", True)

# --- 3) 무작위: 결과는 항상 호가 단위, 방향 지킴, 한 틱 이내 -----------------
rng = np.random.default_rng(5)
checked = 0
for i in range(20_000):
    price = float(10 ** rng.uniform(-6, 9))
    tick = app.krw_tick_size(price)
    down = app.round_to_tick(price, "down")
    up = app.round_to_tick(price, "up")
    rules = {
        "내림 ≤ 가격 ≤ 올림": down <= price * (1 + 1e-11) and up >= price * (1 - 1e-11),
        "내림·올림 모두 호가 단위": on_tick(down) and on_tick(up),
        "한 틱 이내": price - down < tick * (1 + 1e-9) and up - price < tick * (1 + 1e-9),
    }
    broken = [name for name, ok in rules.items() if not ok]
    if broken:
        check(f"무작위 반올림 #{i}", False, f"{broken} price={price!r} down={down!r} up={up!r} tick={tick}")
        break
    checked += 1
check(f"무작위 반올림 {checked}건", checked == 20_000)

finish()
