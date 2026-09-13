"""run_analysis 전체 흐름을 네트워크 없이, 임시 폴더 캐시로 끝까지 돌린다.

- 업비트 호출은 전부 실패하게 막아 오프라인(캐시) 모드로 들어가게 한다.
- 캐시/결과 경로 상수는 import 시점에 CACHE_ROOT 에서 파생되므로
  CACHE_ROOT 하나만 바꾸면 안 된다. 여섯 개를 모두 임시 폴더로 돌린다.
  (프로젝트의 upbit_cache/, output/ 는 절대 건드리지 않는다)
- app 모듈 전역값과 UpbitClient.get 을 되돌리지 않는다. run_all.py 가
  파일마다 별도 프로세스로 실행하는 것을 전제로 한다(pytest 한 프로세스 실행 X).
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from conftest_paths import PROJECT, app, check, finish, geometric, make_candles

real_paths = {
    name: getattr(app, name)
    for name in ["CACHE_ROOT", "MARKET_CACHE_FILE", "TICKER_CACHE_FILE", "OHLCV_CACHE_DIR", "OUTPUT_DIR", "RESULT_CSV"]
}


def blocked(self, path, params=None):
    raise requests.ConnectionError(f"테스트에서 네트워크 차단: {path}")


with tempfile.TemporaryDirectory(prefix="coin_test_") as tmp:
    root = Path(tmp) / "upbit_cache"
    app.CACHE_ROOT = root
    app.MARKET_CACHE_FILE = root / "market" / "krw_markets.json"
    app.TICKER_CACHE_FILE = root / "ticker" / "krw_ticker.json"
    app.OHLCV_CACHE_DIR = root / "ohlcv"
    app.OUTPUT_DIR = Path(tmp) / "output"
    app.RESULT_CSV = app.OUTPUT_DIR / "result.csv"
    app.UpbitClient.get = blocked

    for name, path in real_paths.items():
        if name != "CACHE_ROOT":
            check(f"{name} 가 임시 폴더를 가리킴", str(getattr(app, name)).startswith(tmp))

    # --- 합성 시장 --------------------------------------------------------
    series_240 = {
        "KRW-BTC": geometric(200, 0.003),
        "KRW-UP": geometric(200, 0.004),
        "KRW-DOWN": geometric(200, -0.004),
        "KRW-THIN": geometric(200, 0.004),  # 추세는 좋지만 거래대금 미달
    }
    names = {"KRW-BTC": "비트코인", "KRW-UP": "상승코인", "KRW-DOWN": "하락코인", "KRW-THIN": "소형코인"}
    trade_values = {"KRW-BTC": 5e11, "KRW-UP": 5e9, "KRW-DOWN": 5e9, "KRW-THIN": 1e6}

    app.save_markets(list(names), names)
    app.save_tickers(
        [
            {"market": s, "trade_price": float(c[-1]), "acc_trade_price_24h": trade_values[s]}
            for s, c in series_240.items()
        ]
    )
    for symbol, closes in series_240.items():
        app.save_ohlcv(symbol, 240, make_candles(closes, 240))
        app.save_ohlcv(symbol, 60, make_candles(geometric(200, 0.002), 60))

    # --- 실행 --------------------------------------------------------------
    progress = []
    result = app.run_analysis(app.Settings(), lambda ratio, msg: progress.append(ratio))

    check("API 실패 → 오프라인 모드", result.offline)
    check("캐시에서 KRW 마켓 4개", sorted(result.krw_pairs) == sorted(names), result.krw_pairs)
    check("거래대금 미달 종목은 캔들 요청 전 제외", "KRW-THIN" not in result.target_pairs, result.target_pairs)
    check("티커 캐시 사용 가능", result.ticker is not None and result.ticker.usable and result.ticker.source == "cache", result.ticker)
    check("4시간봉은 캐시에서", result.source_240m.get("cache", 0) + result.source_240m.get("stale", 0) == 3, result.source_240m)
    check("수집 오류 없음", result.errors == [], result.errors)
    check("BTC 국면 계산됨", result.btc_regime.get("label") == "Q4 Very Strong", result.btc_regime)

    symbols = [c.symbol for c in result.candidates]
    check("상승 종목 선별", "KRW-UP" in symbols, symbols)
    check("하락 종목 제외", "KRW-DOWN" not in symbols, symbols)

    up = next((c for c in result.candidates if c.symbol == "KRW-UP"), None)
    if up is not None:
        check("한글명 매핑", up.korean_name == "상승코인", up.korean_name)
        check("1시간봉 진입 판단 채움", up.entry.status != "데이터 부족", up.entry.status)
        check("매매 계획 계산됨", up.plan.available, up.plan.reason)
        check("점수 채움", up.score.total > 0, up.score)
        btc_change = result.btc_regime["change_24h"]
        check("RS = 종목 24h - BTC 24h", np.isclose(up.rs_vs_btc_24h, up.change_24h - btc_change), up.rs_vs_btc_24h)
        check("조언 채움", bool(up.advice), up.advice)

    table = result.result_table
    check("결과표 행 수 = 후보 수", len(table) == len(result.candidates), (len(table), len(result.candidates)))
    check("결과표 점수 내림차순", table["final_score"].is_monotonic_decreasing, table["final_score"].tolist())
    check("후보 순서 = 결과표 순서", symbols == table["symbol"].tolist(), (symbols, table["symbol"].tolist()))

    check("CSV 는 임시 폴더에 저장", app.RESULT_CSV.exists())
    if app.RESULT_CSV.exists():
        saved = pd.read_csv(app.RESULT_CSV, encoding="utf-8-sig")
        check("CSV 행 수 = 결과표", len(saved) == len(table), len(saved))

    check("진행률 단조 증가", progress == sorted(progress), progress)
    check("진행률 1.0 으로 끝남", progress and progress[-1] == 1.0, progress[-1:])

    # --- 티커 캐시가 오래되면 매매 판단을 멈춘다 -----------------------------
    import json

    payload = json.loads(app.TICKER_CACHE_FILE.read_text(encoding="utf-8"))
    payload["saved_at"] = (pd.Timestamp.now() - pd.Timedelta(hours=3)).isoformat(timespec="seconds")
    app.TICKER_CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    try:
        app.run_analysis(app.Settings(ticker_max_age_min=60))
        check("오래된 티커 → 분석 중단", False, "예외가 나지 않음")
    except RuntimeError as exc:
        check("오래된 티커 → 분석 중단", "ticker" in str(exc), exc)

# 프로젝트 폴더 쪽 경로는 테스트 전후로 원래 값 그대로여야 한다(파생 규칙 확인).
check("원래 결과 경로는 프로젝트 output/", real_paths["RESULT_CSV"] == Path("output") / "upbit_screener_240m_60m.csv")
check("테스트 파일은 프로젝트 안에 있음", (PROJECT / "app.py").exists())

finish()
