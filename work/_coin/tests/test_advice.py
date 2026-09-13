"""사람이 읽는 판단(classify_candidate)과 규칙 기반 조언(make_advice)의 우선순위.

make_advice 는 위에서부터 먼저 걸리는 규칙이 이긴다.
  BTC Q1 약세 > LH/LL 하락 구조 > 과열 > MA20 하회 > 적극 관심 > 눌림 대기 > 관망
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import numpy as np

from conftest_paths import app, check, finish


def candidate(**overrides) -> app.Candidate:
    """모든 조건이 좋은 후보에서 필요한 값만 바꾼다."""
    entry = dict(status="진입 관심", distance_ma20_pct=1.5)
    entry.update(overrides.pop("entry", {}))
    base = dict(
        symbol="KRW-TEST",
        korean_name="테스트",
        price=100.0,
        change_24h=5.0,
        trade_value_24h=1e10,
        btc_regime="Q3 Strong",
        swing_structure="HH/HL",
        rs_vs_btc_24h=3.0,
        volume_ratio=1.6,
        rsi_240m=55.0,
        rsi_dyn_upper=70.0,
        rsi_dyn_lower=30.0,
    )
    base.update(overrides)
    return app.Candidate(entry=app.EntryTiming(**entry), **base)


def action(**overrides) -> str:
    return app.make_advice(candidate(**overrides))[0]


# --- 1) 적극 관심 구간 ------------------------------------------------------
check("모두 양호 → 분할매수 관심", action() == "분할매수 관심", action())
check("Q4 도 강한 시장", action(btc_regime="Q4 Very Strong") == "분할매수 관심")
check("RSI 상단 → 눌림 후 분할매수", action(rsi_240m=75.0) == "눌림 후 분할매수 관심")
check("RS 약한 양수 → 매수 관심", action(rs_vs_btc_24h=1.0) == "매수 관심")
check("거래량 부족 → 매수 관심", action(volume_ratio=0.8) == "매수 관심")
check("눌림 확인도 적극 관심 대상", action(entry={"status": "눌림 확인"}) == "분할매수 관심")

# --- 2) 우선순위: 위 규칙이 아래 규칙을 이긴다 -----------------------------
check("Q1 이면 다른 조건 무관 → 신규매수 보류", action(btc_regime="Q1 Weak") == "신규매수 보류")
_, text = app.make_advice(candidate(btc_regime="Q1 Weak", rs_vs_btc_24h=-1.0, swing_structure="LH/LL"))
check("Q1 조언에 약한 RS·하락 구조 이유 포함", "상대강도" in text and "LH/LL" in text, text)

check("LH/LL → 관망 / 반등 확인", action(swing_structure="LH/LL") == "관망 / 반등 확인")
check("LH/LL 가 과열보다 우선", action(swing_structure="LH/LL", entry={"status": "과열 주의", "distance_ma20_pct": 12.0}) == "관망 / 반등 확인")

check("과열 주의 → 추격매수 자제", action(entry={"status": "과열 주의", "distance_ma20_pct": 9.0}) == "추격매수 자제")
check("상태와 무관하게 이격 8% 초과 → 추격매수 자제", action(entry={"distance_ma20_pct": 8.5}) == "추격매수 자제")
check("과열이 MA20 하회보다 우선", action(entry={"status": "MA20 하회", "distance_ma20_pct": 9.0}) == "추격매수 자제")

check("MA20 하회 → 반등 확인 후 접근", action(entry={"status": "MA20 하회", "distance_ma20_pct": -2.0}) == "반등 확인 후 접근")

# --- 3) 약한 신호 -----------------------------------------------------------
check("Q2 + 상승 구조 + RS 양수 → 눌림 대기", action(btc_regime="Q2 Neutral") == "눌림 대기")
check("눌림 대기 상태 → 눌림 대기", action(entry={"status": "눌림 대기", "distance_ma20_pct": 4.0}) == "눌림 대기")

act, text = app.make_advice(candidate(swing_structure="HH/LL", rs_vs_btc_24h=-2.0))
check("혼재 구조 + RS 음수 → 관망", act == "관망", act)
check("관망 조언에 혼재 이유 포함", "혼재" in text, text)

# --- 4) 값이 없을 때 보수적으로 판단 ----------------------------------------
# BTC 데이터가 없어 RS 를 계산 못 하면 '상대강도 우위' 로 보면 안 된다.
check("RS NaN → 매수 계열 아님", action(rs_vs_btc_24h=np.nan) == "관망", action(rs_vs_btc_24h=np.nan))
# 모르는 값을 '약함' · '음수' 로 쓰면 안 된다. 판단은 RS 음수와 똑같이 보수적으로 둔다.
for label, overrides in [
    ("기본", {}),
    ("Q1 약세", {"btc_regime": "Q1 Weak"}),
    ("LH/LL", {"swing_structure": "LH/LL"}),
    ("혼재 구조", {"swing_structure": "HH/LL"}),
]:
    act_nan, text_nan = app.make_advice(candidate(rs_vs_btc_24h=np.nan, **overrides))
    act_neg, text_neg = app.make_advice(candidate(rs_vs_btc_24h=-1.0, **overrides))
    check(f"RS NaN({label}) → '확인 불가' 문구", "확인 불가" in text_nan, text_nan)
    check(f"RS NaN({label}) → '약함'·'음수' 문구 없음", "약함" not in text_nan and "음수" not in text_nan, text_nan)
    check(f"RS NaN({label}) 판단 = RS 음수 판단", act_nan == act_neg, (act_nan, act_neg))
    check(f"RS 음수({label}) → 약함/음수 문구 유지", "약함" in text_neg or "음수" in text_neg, text_neg)
# BTC 국면을 모르면 강한 시장으로 보지 않는다.
check("BTC 국면 확인 불가 → 분할매수 아님", action(btc_regime="확인 불가") == "눌림 대기", action(btc_regime="확인 불가"))
check("스윙 데이터 부족 → 관망", action(swing_structure="데이터 부족") == "관망")

# 조언 문장은 비어 있지 않고, 표·카드에서 한눈에 읽히도록 60자 이하로 짧다.
MAX_ADVICE_LEN = 60
longest = ""
for regime in ["Q1 Weak", "Q2 Neutral", "Q3 Strong", "Q4 Very Strong", "확인 불가"]:
    for swing in ["HH/HL", "LH/LL", "HH/LL", "데이터 부족"]:
        for status in ["진입 관심", "눌림 확인", "눌림 대기", "과열 주의", "MA20 하회", "데이터 부족"]:
            for extra in [{}, {"rsi_240m": 75.0, "volume_ratio": 0.8}, {"rs_vs_btc_24h": np.nan}]:
                act, text = app.make_advice(
                    candidate(btc_regime=regime, swing_structure=swing, entry={"status": status}, **extra)
                )
                if not (act and text.strip()):
                    check(f"조언 문장 {regime}/{swing}/{status}", False, (act, text))
                longest = max(longest, text, key=len)
check(f"가장 긴 조언도 {MAX_ADVICE_LEN}자 이하", len(longest) <= MAX_ADVICE_LEN, f"{len(longest)}자: {longest}")

# --- 5) 한 줄 판단 ----------------------------------------------------------
def judgement(status, change=5.0):
    return app.classify_candidate(candidate(change_24h=change, entry={"status": status}))


check("진입 관심 → 우선관찰", judgement("진입 관심") == "우선관찰")
check("진입 관심 + 24h 8% 이상 → 강한상승", judgement("진입 관심", 8.0) == "강한상승+진입 가능")
check("진입 관심 + 7.99% → 우선관찰", judgement("진입 관심", 7.99) == "우선관찰")
check("눌림 확인 → 눌림 기다리기", judgement("눌림 확인") == "눌림 기다리기")
check("과열 주의 → 과열 주의", judgement("과열 주의") == "과열 주의")
check("MA20 하회 → 반등 확인 필요", judgement("MA20 하회") == "반등 확인 필요")
check("데이터 부족 → 확인 필요", judgement("데이터 부족") == "확인 필요")

notes = {name for name, _ in app.JUDGEMENT_NOTES}
for status in ["진입 관심", "눌림 확인", "눌림 대기", "과열 주의", "MA20 하회", "데이터 부족"]:
    for change in (5.0, 10.0):
        check(f"판단 '{judgement(status, change)}' 은 범례에 있음", judgement(status, change) in notes)

finish()
