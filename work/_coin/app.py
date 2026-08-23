import streamlit as st
import pyupbit
import pandas as pd
import time
import os
import json
from datetime import datetime, timedelta
import requests
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import mplfinance as mpf
import numpy as np
import platform


# =============================================
# 0. Streamlit 페이지 설정
# =============================================
st.set_page_config(
    page_title="📊 업비트 코인 분석기",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 업비트 코인 분석기")
st.markdown("---")


# =============================================
# 1. 한글 폰트 설정
# =============================================
def setup_korean_font():
    """
    운영체제에 맞는 한글 폰트를 설정한다.

    Windows:
        Malgun Gothic

    macOS:
        AppleGothic

    Linux / Streamlit Cloud:
        NanumGothic

    Streamlit Cloud에서는 프로젝트 루트의
    packages.txt에 fonts-nanum을 추가해야 한다.
    """

    system = platform.system()

    # 현재 matplotlib에서 인식하고 있는 폰트 목록
    available_fonts = {font.name for font in fm.fontManager.ttflist}

    if system == "Windows":
        candidates = ["Malgun Gothic", "NanumGothic"]

    elif system == "Darwin":
        candidates = ["AppleGothic", "NanumGothic"]

    else:
        # Streamlit Cloud / Linux
        candidates = ["NanumGothic", "Nanum Gothic"]

    # 실제 설치된 폰트 확인
    font_name = None

    for candidate in candidates:
        if candidate in available_fonts:
            font_name = candidate
            break

    # 찾지 못했을 경우
    if font_name is None:
        # Linux에서 Nanum 폰트 파일을 직접 다시 등록
        if system == "Linux":
            possible_font_dirs = [
                "/usr/share/fonts",
                "/usr/local/share/fonts",
                os.path.expanduser("~/.fonts"),
                os.path.expanduser("~/.local/share/fonts"),
            ]

            for font_dir in possible_font_dirs:
                if not os.path.exists(font_dir):
                    continue

                for root, dirs, files in os.walk(font_dir):
                    for file in files:
                        if (
                            file.lower().endswith((".ttf", ".otf"))
                            and "nanum" in file.lower()
                        ):
                            try:
                                font_path = os.path.join(root, file)

                                fm.fontManager.addfont(font_path)

                            except Exception:
                                pass

            # 폰트 목록 다시 확인
            available_fonts = {font.name for font in fm.fontManager.ttflist}

            for candidate in ["NanumGothic", "Nanum Gothic"]:
                if candidate in available_fonts:
                    font_name = candidate
                    break

    # 그래도 찾지 못하면 기본 폰트
    if font_name is None:
        font_name = "DejaVu Sans"

    # matplotlib 전체 폰트 설정
    plt.rcParams["font.family"] = font_name

    # 마이너스(-) 기호 깨짐 방지
    plt.rcParams["axes.unicode_minus"] = False

    return font_name


# 한 번 설정한 폰트를 matplotlib / mplfinance에서 공통 사용
KOREAN_FONT = setup_korean_font()


# =============================================
# 2. 설정 (사이드바에서 조절 가능)
# =============================================
st.sidebar.header("⚙️ 분석 설정")


CACHE_DIR = "ohlcv_cache_upbit_krw"

CACHE_EXPIRE_MINUTES = st.sidebar.slider("캐시 만료 시간 (분)", 10, 120, 60)

os.makedirs(CACHE_DIR, exist_ok=True)


# ---------------------------------------------
# 분할 매수/매도 설정
# ---------------------------------------------
st.sidebar.subheader("💰 분할 매수/매도 전략")


INVEST_PER_STEP = st.sidebar.number_input(
    "단계별 투자금 (원)", value=10_000_000, step=1_000_000, format="%d"
)


BUY_LEVELS = [5, 10, 15]


SELL_LEVELS = [5, 10, 15]


# ---------------------------------------------
# 분석 조건 설정
# ---------------------------------------------
st.sidebar.subheader("🔍 필터링 조건")


MIN_CHANGE = st.sidebar.slider("최소 변동률 (%)", 0.0, 10.0, 1.0, 0.5)


MAX_CHANGE = st.sidebar.slider("최대 변동률 (%)", 10.0, 50.0, 30.0, 5.0)


MIN_VOLUME = st.sidebar.number_input(
    "최소 거래량 (원)", value=100_000_000, step=50_000_000, format="%d"
)


# ---------------------------------------------
# 상위 표시 개수
# ---------------------------------------------
TOP_N = st.sidebar.slider("표시할 상위 코인 수", 5, 30, 10)


# ---------------------------------------------
# 실행 버튼
# ---------------------------------------------
run_analysis = st.sidebar.button("🚀 분석 실행", type="primary")


# =============================================
# 3. 캐시 함수
# =============================================
def get_cache_path(symbol, timeframe):

    filename = f"{symbol.replace('-', '_')}_{timeframe}.json"

    return os.path.join(CACHE_DIR, filename)


def load_from_cache(symbol, timeframe):

    cache_path = get_cache_path(symbol, timeframe)

    # 캐시 파일 없음
    if not os.path.exists(cache_path):
        return None

    # 캐시 만료 검사
    file_time = datetime.fromtimestamp(os.path.getmtime(cache_path))

    if datetime.now() - file_time > timedelta(minutes=CACHE_EXPIRE_MINUTES):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            df = pd.DataFrame(json.load(f))

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            df.set_index("timestamp", inplace=True)

        return df

    except Exception:
        return None


def save_to_cache(symbol, timeframe, df):

    try:
        df_reset = df.reset_index()

        if "index" in df_reset.columns:
            df_reset["timestamp"] = df_reset["index"].astype(str)

            df_reset.drop("index", axis=1, inplace=True)

        elif df_reset.index.name == "timestamp" or "timestamp" in df_reset.columns:
            df_reset["timestamp"] = df_reset["timestamp"].astype(str)

        cache_path = get_cache_path(symbol, timeframe)

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(df_reset.to_dict("records"), f, ensure_ascii=False)

    except Exception as e:
        st.warning(f"{symbol} 캐시 저장 실패: {e}")


# =============================================
# 4. 분할 매수/매도 계산 함수
# =============================================
def calculate_split_strategy(current_price, buy_levels, sell_levels, invest_per_step):

    result = {
        "buy_levels": [],
        "sell_levels": [],
        "total_buy_invest": 0,
        "total_sell_revenue": 0,
        "buy_prices": [],
        "sell_prices": [],
    }

    # -----------------------------------------
    # 분할 매수
    # -----------------------------------------
    for level in buy_levels:
        buy_price = current_price * (1 - level / 100)

        quantity = invest_per_step / buy_price

        result["buy_levels"].append(
            {
                "level": f"-{level}%",
                "price": round(buy_price, 2),
                "invest": invest_per_step,
                "quantity": round(quantity, 4),
            }
        )

        result["buy_prices"].append(buy_price)

        result["total_buy_invest"] += invest_per_step

    # -----------------------------------------
    # 분할 매도
    # -----------------------------------------
    for level in sell_levels:
        sell_price = current_price * (1 + level / 100)

        quantity = invest_per_step / current_price

        result["sell_levels"].append(
            {
                "level": f"+{level}%",
                "price": round(sell_price, 2),
                "revenue": invest_per_step * (1 + level / 100),
                "quantity": round(quantity, 4),
            }
        )

        result["sell_prices"].append(sell_price)

        result["total_sell_revenue"] += invest_per_step * (1 + level / 100)

    return result


# =============================================
# 5. 캔들 차트 그리기 함수
# =============================================
def plot_candle_with_strategy(
    df, symbol, korean_name, strategy, current_price, change_24h, volume_krw
):
    """
    캔들 차트에
    분할 매수 / 매도 라인을 추가한다.
    """

    # 최근 50봉
    df_plot = df.tail(50).copy()

    buy_prices = strategy["buy_prices"]

    sell_prices = strategy["sell_prices"]

    # =========================================
    # 수평선
    # =========================================
    hlines = []

    hline_colors = []

    # 매수선
    for price in buy_prices:
        hlines.append(price)

        hline_colors.append("red")

    # 매도선
    for price in sell_prices:
        hlines.append(price)

        hline_colors.append("green")

    # 현재가
    hlines.append(current_price)

    hline_colors.append("blue")

    # =========================================
    # 이동평균선
    # =========================================
    add_plots = []

    ma_settings = [(5, "red"), (20, "orange"), (60, "green"), (120, "blue")]

    for period, color in ma_settings:
        column = f"MA{period}"

        if column in df_plot.columns:
            add_plots.append(mpf.make_addplot(df_plot[column], color=color, width=0.8))

    # =========================================
    # 캔들 색상
    # =========================================
    mc = mpf.make_marketcolors(
        up="red", down="blue", edge="inherit", wick="inherit", volume="inherit"
    )

    # =========================================
    # mplfinance 스타일
    #
    # 중요:
    # matplotlib에서 설정한 KOREAN_FONT와
    # 같은 폰트를 사용한다.
    # =========================================
    style = mpf.make_mpf_style(
        marketcolors=mc, rc={"font.family": KOREAN_FONT, "axes.unicode_minus": False}
    )

    # =========================================
    # 차트 제목
    # =========================================
    title = (
        f"{korean_name} ({symbol})\n"
        f"현재가: "
        f"{current_price:,.0f}원"
        f" | 변동률: "
        f"{change_24h:.2f}%"
        f" | 거래량: "
        f"{volume_krw / 100_000_000:.2f}억원"
    )

    # =========================================
    # 매수/매도 수평선
    # =========================================
    hline_params = dict(
        hlines=hlines, colors=hline_colors, linestyle="--", linewidths=1.0, alpha=0.8
    )

    # =========================================
    # 차트 생성
    # =========================================
    fig, axes = mpf.plot(
        df_plot,
        type="candle",
        style=style,
        title=title,
        ylabel="가격 (원)",
        ylabel_lower="거래량",
        addplot=(add_plots if add_plots else []),
        hlines=hline_params,
        volume=True,
        figsize=(12, 6),
        returnfig=True,
        warn_too_much_data=1000,
    )

    # =========================================
    # 범례
    # =========================================
    ax = axes[0]

    legend_elements = []

    # -----------------------------------------
    # 매수선
    # -----------------------------------------
    for i, price in enumerate(buy_prices):
        legend_elements.append(
            plt.Line2D(
                [0],
                [0],
                color="red",
                linestyle="--",
                label=(f"매수 {i + 1} (-{BUY_LEVELS[i]}%): {price:,.0f}원"),
            )
        )

    # -----------------------------------------
    # 매도선
    # -----------------------------------------
    for i, price in enumerate(sell_prices):
        legend_elements.append(
            plt.Line2D(
                [0],
                [0],
                color="green",
                linestyle="--",
                label=(f"매도 {i + 1} (+{SELL_LEVELS[i]}%): {price:,.0f}원"),
            )
        )

    # -----------------------------------------
    # 현재가
    # -----------------------------------------
    legend_elements.append(
        plt.Line2D(
            [0],
            [0],
            color="blue",
            linestyle="--",
            label=(f"현재가: {current_price:,.0f}원"),
        )
    )

    # -----------------------------------------
    # 이동평균선
    # -----------------------------------------
    ma_colors = {"MA5": "red", "MA20": "orange", "MA60": "green", "MA120": "blue"}

    for period in [5, 20, 60, 120]:
        column = f"MA{period}"

        if column in df_plot.columns:
            legend_elements.append(
                plt.Line2D(
                    [0], [0], color=ma_colors[column], label=column, linewidth=1.5
                )
            )

    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)

    try:
        plt.subplots_adjust(left=0.08, right=0.92, top=0.88, bottom=0.10)

    except Exception:
        pass

    return fig


# =============================================
# 6. 메인 분석 함수
# =============================================
def run_analysis_main():

    # =========================================
    # 업비트 마켓 정보
    # =========================================
    with st.spinner("📊 업비트 마켓 정보 로딩 중..."):
        krw_pairs = []

        symbol_korean_map = {}

        # -------------------------------------
        # 1차 : pyupbit
        # -------------------------------------
        try:
            krw_markets = pyupbit.get_tickers(fiat="KRW", verbose=True)

            krw_pairs = [market["market"] for market in krw_markets]

            symbol_korean_map = {
                market["market"]: market["korean_name"] for market in krw_markets
            }

        except Exception:
            # ---------------------------------
            # 2차 : 업비트 REST API
            # ---------------------------------
            try:
                response = requests.get(
                    "https://api.upbit.com/v1/market/all", timeout=10
                )

                if response.status_code == 200:
                    krw_markets = [
                        market
                        for market in response.json()
                        if market["market"].startswith("KRW-")
                    ]

                    krw_pairs = [market["market"] for market in krw_markets]

                    symbol_korean_map = {
                        market["market"]: market["korean_name"]
                        for market in krw_markets
                    }

            except Exception:
                # -----------------------------
                # 3차 : 티커 목록만
                # -----------------------------
                krw_pairs = pyupbit.get_tickers(fiat="KRW")

        # 마켓 정보 실패
        if not krw_pairs:
            st.error("❌ 마켓 정보를 가져올 수 없습니다.")

            return None, None

    # =========================================
    # 분석 진행 표시
    # =========================================
    progress_bar = st.progress(0)

    status_text = st.empty()

    # 이동평균
    ma_periods = [5, 20, 60, 120]

    timeframe = "minute60"

    limit = 200

    results = []

    error_symbols = []

    cache_hit = 0

    cache_miss = 0

    api_call_count = 0

    MAX_API_CALLS = 290

    total = len(krw_pairs)

    # =========================================
    # 전체 KRW 코인 분석
    # =========================================
    for idx, symbol in enumerate(krw_pairs):
        try:
            # ---------------------------------
            # 캐시 확인
            # ---------------------------------
            df = load_from_cache(symbol, timeframe)

            # ---------------------------------
            # 캐시 없음
            # ---------------------------------
            if df is None:
                cache_miss += 1

                if api_call_count >= MAX_API_CALLS:
                    time.sleep(60)

                    api_call_count = 0

                # OHLCV 다운로드
                df = pyupbit.get_ohlcv(symbol, interval=timeframe, count=limit)

                api_call_count += 1

                # 데이터 없음
                if df is None or df.empty:
                    progress_bar.progress((idx + 1) / total)

                    continue

                # 캐시 저장
                save_to_cache(symbol, timeframe, df)

                # API 과호출 방지
                time.sleep(0.2)

            else:
                cache_hit += 1

            # =================================
            # 이동평균 계산
            # =================================
            for period in ma_periods:
                df[f"MA{period}"] = df["close"].rolling(window=period).mean()

            latest = df.iloc[-1]

            ma5 = latest["MA5"]

            ma20 = latest["MA20"]

            ma60 = latest["MA60"]

            ma120 = latest["MA120"]

            # 이동평균 계산 불가
            if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60) or pd.isna(ma120):
                progress_bar.progress((idx + 1) / total)

                continue

            # =================================
            # 정배열 조건
            #
            # MA5 > MA20 > MA60 > MA120
            # =================================
            if ma5 > ma20 > ma60 > ma120 and len(df) >= 25:
                # =============================
                # 최근 24시간 변동률
                # =============================
                change_24h = (
                    (latest["close"] - df.iloc[-25]["close"])
                    / df.iloc[-25]["close"]
                    * 100
                )

                # =============================
                # 현재 시간봉 거래대금
                # =============================
                volume_krw = latest["close"] * latest["volume"]

                # =============================
                # 필터
                # =============================
                if MIN_CHANGE <= change_24h <= MAX_CHANGE and volume_krw >= MIN_VOLUME:
                    strategy = calculate_split_strategy(
                        latest["close"], BUY_LEVELS, SELL_LEVELS, INVEST_PER_STEP
                    )

                    # 결과 저장
                    results.append(
                        {
                            "symbol": symbol,
                            "korean_name": symbol_korean_map.get(symbol, ""),
                            "df": df,
                            "price": round(latest["close"], 2),
                            "change_24h": round(change_24h, 2),
                            "volume_krw": round(volume_krw, 0),
                            "MA5": round(ma5, 2),
                            "MA20": round(ma20, 2),
                            "MA60": round(ma60, 2),
                            "MA120": round(ma120, 2),
                            "strategy": strategy,
                        }
                    )

            # =================================
            # 진행상태 표시
            # =================================
            status_text.text(
                f"진행: "
                f"{idx + 1}/{total}"
                f" | 발견: "
                f"{len(results)}개"
                f" | 캐시: "
                f"{cache_hit}개"
            )

            progress_bar.progress((idx + 1) / total)

        except Exception:
            error_symbols.append(symbol)

            progress_bar.progress((idx + 1) / total)

            continue

    status_text.text(f"✅ 분석 완료! 발견된 코인: {len(results)}개")

    return (results, error_symbols)


# =============================================
# 7. 메인 실행
# =============================================
if run_analysis:
    results, error_symbols = run_analysis_main()

    # =========================================
    # 분석 결과 있음
    # =========================================
    if results:
        df_result = pd.DataFrame(results).sort_values(
            by=["change_24h", "volume_krw"], ascending=[False, False]
        )

        # =====================================
        # 7-1. 요약 정보
        # =====================================
        st.markdown("---")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("발견된 코인", len(df_result))

        col2.metric("평균 변동률", (f"{df_result['change_24h'].mean():.2f}%"))

        col3.metric("최고 변동률", (f"{df_result['change_24h'].max():.2f}%"))

        col4.metric(
            "총 거래량", (f"{df_result['volume_krw'].sum() / 100_000_000:.2f}억원")
        )

        # =====================================
        # 7-2. 데이터 테이블
        # =====================================
        st.subheader("📈 상위 코인 목록")

        display_cols = [
            "symbol",
            "korean_name",
            "price",
            "change_24h",
            "volume_krw",
            "MA5",
            "MA20",
            "MA60",
            "MA120",
        ]

        st.dataframe(
            df_result.head(TOP_N)[display_cols].style.format(
                {
                    "price": "{:,.0f}",
                    "change_24h": "{:.2f}%",
                    "volume_krw": "{:,.0f}",
                    "MA5": "{:.2f}",
                    "MA20": "{:.2f}",
                    "MA60": "{:.2f}",
                    "MA120": "{:.2f}",
                }
            ),
            use_container_width=True,
        )

        # =====================================
        # 7-3. 분할 매수/매도 전략
        # =====================================
        with st.expander("💰 분할 매수/매도 전략 상세보기"):
            for idx, row in df_result.head(5).iterrows():
                strategy = row["strategy"]

                st.markdown(
                    f"**📌 "
                    f"{row['korean_name']} "
                    f"({row['symbol']})** "
                    f"- 현재가: "
                    f"{row['price']:,.0f}원"
                )

                col1, col2 = st.columns(2)

                # -----------------------------
                # 매수
                # -----------------------------
                with col1:
                    st.markdown("**📈 분할 매수**")

                    for buy in strategy["buy_levels"]:
                        st.write(
                            f"- "
                            f"{buy['level']} "
                            f"하락 시: "
                            f"{buy['price']:,.0f}원 "
                            f"(매수금: "
                            f"{buy['invest']:,}원)"
                        )

                # -----------------------------
                # 매도
                # -----------------------------
                with col2:
                    st.markdown("**📉 분할 매도**")

                    for sell in strategy["sell_levels"]:
                        st.write(
                            f"- "
                            f"{sell['level']} "
                            f"상승 시: "
                            f"{sell['price']:,.0f}원 "
                            f"(매도금: "
                            f"{sell['revenue']:,.0f}원)"
                        )

                st.write(
                    f"총 매수금: "
                    f"{strategy['total_buy_invest']:,}원"
                    f" | "
                    f"총 매도금: "
                    f"{strategy['total_sell_revenue']:,.0f}원"
                )

                st.markdown("---")

        # =====================================
        # 7-4. 캔들 차트
        # =====================================
        st.subheader("📊 캔들 차트 (분할 매수/매도 포함)")

        top_n_chart = min(TOP_N, 5)

        for idx, row in df_result.head(top_n_chart).iterrows():
            with st.expander(f"📌 {row['korean_name']} ({row['symbol']}) - 캔들 차트"):
                fig = plot_candle_with_strategy(
                    row["df"],
                    row["symbol"],
                    row["korean_name"],
                    row["strategy"],
                    row["price"],
                    row["change_24h"],
                    row["volume_krw"],
                )

                st.pyplot(fig)

                # 메모리 해제
                plt.close(fig)

        # =====================================
        # 7-5. CSV 다운로드
        # =====================================

        # df와 strategy 같은
        # 복잡한 컬럼은 다운로드에서 제외
        csv_columns = [
            "symbol",
            "korean_name",
            "price",
            "change_24h",
            "volume_krw",
            "MA5",
            "MA20",
            "MA60",
            "MA120",
        ]

        csv = df_result[csv_columns].to_csv(index=False, encoding="utf-8-sig")

        st.download_button(
            label="💾 CSV 다운로드",
            data=csv,
            file_name=(
                f"golden_cross_coins_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            ),
            mime="text/csv",
        )

        # =====================================
        # 오류 종목 표시
        # =====================================
        if error_symbols:
            with st.expander("⚠️ 분석 중 오류가 발생한 종목"):
                st.write(error_symbols)

    # =========================================
    # 조건 만족 코인 없음
    # =========================================
    else:
        st.warning("❌ 조건을 만족하는 코인이 없습니다. 필터링 조건을 완화해보세요.")


# =============================================
# 분석 전 안내
# =============================================
else:
    st.info("👈 좌측 사이드바에서 설정을 조정하고 '분석 실행' 버튼을 클릭하세요.")


# =============================================
# 8. 실행
# =============================================
# 터미널에서 실행:
#
# streamlit run app.py
