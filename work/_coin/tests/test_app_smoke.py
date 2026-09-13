"""앱 화면 스모크 테스트: 네트워크 없이 합성 캐시로 앱 전체를 실행해 오류 없이 그려지는지 본다.

- AppTest 는 app.py 를 새로 __main__ 으로 실행하므로 app 모듈을 패치해도 스크립트에는 닿지 않는다.
  네트워크는 requests.Session.get 을 막는다. 네트워크 예외(RequestException)를 던지면
  재시도 대기로 10초가량 걸리므로 다른 예외를 던져 곧바로 오프라인 모드로 들어가게 한다.
- 캐시 · 결과 경로는 상대 경로라, 임시 폴더로 이동한 뒤 합성 캐시를 쓴다
  (프로젝트의 upbit_cache/ · output/ 은 건드리지 않는다).
- Streamlit 은 import 될 때 MPLBACKEND=Agg 를 설정한다(streamlit/__init__.py).
  streamlit run 은 streamlit 을 먼저 import 하므로 앱의 matplotlib 이 Agg 가 되지만,
  이 테스트는 conftest 에서 app(→ matplotlib)을 먼저 import 해 그 설정이 늦는다.
  그러면 macOS 에서 차트가 'GUI FigureManager outside the main thread' 로 실패하므로 직접 지정한다.
- requests 를 전역으로 막으므로 run_all.py 의 파일별 프로세스 분리를 전제로 한다.
"""
# ruff: noqa: E402  (환경 변수 · bytecode 설정이 import 보다 먼저 와야 한다)
import os
import sys

sys.dont_write_bytecode = True
os.environ["MPLBACKEND"] = "Agg"

import tempfile

import requests
from streamlit.testing.v1 import AppTest

from conftest_paths import APP, app, check, finish, geometric, make_candles


def blocked(self, *args, **kwargs):
    raise RuntimeError("테스트: 네트워크 차단")


requests.Session.get = blocked

with tempfile.TemporaryDirectory(prefix="coin_apptest_") as tmp:
    os.chdir(tmp)

    # --- 합성 시장: 상승 2 · BTC · 하락 1 ------------------------------------
    names = {"KRW-BTC": "비트코인", "KRW-UP1": "상승1", "KRW-UP2": "상승2", "KRW-DOWN": "하락"}
    closes = {
        "KRW-BTC": geometric(200, 0.003),
        "KRW-UP1": geometric(200, 0.004),
        "KRW-UP2": geometric(200, 0.0045, start=1500),
        "KRW-DOWN": geometric(200, -0.004),
    }
    app.save_markets(list(names), names)
    app.save_tickers(
        [
            {"market": s, "trade_price": float(c[-1]), "acc_trade_price_24h": 5e11 if s == "KRW-BTC" else 5e9}
            for s, c in closes.items()
        ]
    )
    for symbol, series in closes.items():
        app.save_ohlcv(symbol, 240, make_candles(series, 240))
        app.save_ohlcv(symbol, 60, make_candles(geometric(200, 0.002, start=float(series[-1]) / 1.2), 60))

    # --- 1) 기본 설정으로 앱 전체 실행 ----------------------------------------
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()

    check("예외 없음", not at.exception, [e.value for e in at.exception])
    check("오류 메시지 없음", not at.error, [e.value for e in at.error])
    check("오프라인 모드 안내", any("오프라인" in w.value for w in at.warning), [w.value for w in at.warning])

    subheaders = [s.value for s in at.subheader]
    for title in ["상위", "핵심 해석", "MA / ATR 기반 매수·손절·익절 + Runner", "캔들 차트", "전체 분석 데이터"]:
        check(f"섹션 '{title}' 표시", any(title in s for s in subheaders), subheaders)

    cards = [e.label for e in at.expander if "FinalScore" in e.label]
    check("전략 카드 2개 이상", len(cards) >= 2, cards)
    check("하락 종목은 카드에 없음", not any("KRW-DOWN" in label for label in cards), cards)
    trail_lines = sum("현재 Trail:" in m.value for m in at.markdown)
    check("카드마다 '현재 Trail:' 설명", trail_lines == len(cards), (trail_lines, len(cards)))
    check(
        "전략 섹션 안내에 Trail 설명",
        any("현재 Trail은 계획 시점에는 본전" in c.value for c in at.caption),
        [c.value for c in at.caption][:5],
    )
    check("표 2개 이상 (후보 · 전체 데이터)", len(at.dataframe) >= 2, len(at.dataframe))
    # st.pyplot 은 AppTest 에서 'image' 요소로 보인다.
    charts = at.get("image")
    check("차트 그림 1개 이상", len(charts) >= 1, len(charts))
    check("기본 설정(계좌 1억)에서는 주문 경고 없음", not any("5,000원 미만" in w.value for w in at.warning))
    check("결과 CSV 는 임시 폴더에 저장", os.path.exists(os.path.join(tmp, "output", "upbit_screener_240m_60m.csv")))

    # --- 2) 작은 계좌로 다시 분석 → 최소 주문 금액 경고 ------------------------
    def widget(items, label):
        return next(item for item in items if label in item.label)

    widget(at.text_input, "계좌 자금(원)").set_value("100,000")
    widget(at.text_input, "비중(%)").set_value("1")
    widget(at.button, "다시 분석").click()
    at.run()

    check("작은 계좌 재분석: 예외 없음", not at.exception, [e.value for e in at.exception])
    check(
        "작은 계좌 재분석: 최소 주문 금액 경고 표시",
        any("5,000원 미만 주문" in w.value for w in at.warning),
        [w.value[:60] for w in at.warning],
    )

finish()
