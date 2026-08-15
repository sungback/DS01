import logging
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import mplfinance as mpf
import streamlit as st

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


# ============================================================
# 1. 기본 설정
# ============================================================

st.set_page_config(page_title="KOSPI 추세 투자", page_icon="📈", layout="wide")
st.title("📈 KOSPI 추세 투자 분석")

BASE_DIR = Path(__file__).resolve().parent
CACHE = BASE_DIR / "stock_cache"

# 실제 매수 후 필요하면 직접 입력
BUY_PRICE = {
    # "021240": 98200,
}

BUY_STOP = {
    # "021240": 92100,
}

TYPE_ORDER = ["균형형", "강한추세", "급등주의", "과열주의", "저과열", "일반"]
TYPE_OPTIONS = ["전체"] + TYPE_ORDER


# ============================================================
# 2. 한글 폰트
# ============================================================

system = platform.system()

if system == "Windows":
    font = "Malgun Gothic"

elif system == "Darwin":
    font = "AppleGothic"

else:
    # Streamlit Cloud (Linux)
    font_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"

    if Path(font_path).exists():
        fm.fontManager.addfont(font_path)
        font = fm.FontProperties(fname=font_path).get_name()
    else:
        st.error("NanumGothic 폰트가 설치되지 않았습니다.")
        font = "DejaVu Sans"

plt.rcParams["font.family"] = font
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.titleweight"] = "normal"


# ============================================================
# 2. 한글 폰트
# ============================================================




# ============================================================
# 3. 사이드바
# ============================================================

with st.sidebar:
    st.header("분석 설정")

    opt = st.selectbox("종목 유형", TYPE_OPTIONS)
    TOP_N = st.slider("전체 매수 후보 수", 5, 100, 20, 5)
    CHART_N = st.slider("매매계획 / 차트 종목 수", 1, 30, 10)

    min_value_eok = st.number_input(
        "최소 평균 거래대금(억원)",
        min_value=1,
        value=10,
        step=1
    )

    stop_percent = st.slider("최대 손실률(%)", 1, 20, 8)

    MIN_VALUE = min_value_eok * 100_000_000
    STOP_RATE = stop_percent / 100

    if st.button("🔄 화면 새로고침", width="stretch"):
        st.rerun()


# ============================================================
# 4. 필수 파일 확인
# ============================================================

KOSPI_FILE = CACHE / "KS11.csv"
LIST_FILE = CACHE / "KOSPI_list.csv"

if not CACHE.exists():
    st.error(f"stock_cache 폴더를 찾을 수 없습니다.\n\n{CACHE}")
    st.stop()

if not KOSPI_FILE.exists():
    st.error("stock_cache/KS11.csv 파일이 없습니다.")
    st.stop()

if not LIST_FILE.exists():
    st.error("stock_cache/KOSPI_list.csv 파일이 없습니다.")
    st.stop()


# ============================================================
# 5. KOSPI 시장 상태
# ============================================================

kospi = pd.read_csv(KOSPI_FILE, index_col="Date", parse_dates=["Date"])
kospi_close = pd.to_numeric(kospi["Close"], errors="coerce").dropna()

if len(kospi_close) < 200:
    st.error("KOSPI 데이터가 200일 미만입니다.")
    st.stop()

kospi_now = kospi_close.iloc[-1]
ma200 = kospi_close.rolling(200).mean().iloc[-1]
market_up = kospi_now > ma200
market_date = kospi_close.index[-1].date()

st.subheader("시장 상태")

col1, col2, col3, col4 = st.columns(4)
col1.metric("데이터 기준일", str(market_date))
col2.metric("KOSPI", f"{kospi_now:,.2f}")
col3.metric("MA200", f"{ma200:,.2f}")
col4.metric("시장 상태", "상승장" if market_up else "하락장")

if not market_up:
    st.warning("현재 KOSPI가 MA200 아래입니다. 신규 매수는 보수적으로 접근하세요.")


# ============================================================
# 6. KOSPI 종목 목록
# ============================================================

stocks = pd.read_csv(LIST_FILE)

if "Code" in stocks.columns:
    code_col = "Code"
elif "Symbol" in stocks.columns:
    code_col = "Symbol"
else:
    st.error("KOSPI_list.csv에 Code 또는 Symbol 컬럼이 없습니다.")
    st.stop()

stocks[code_col] = (
    stocks[code_col]
    .astype(str)
    .str.replace(".0", "", regex=False)
    .str.zfill(6)
)

# 우선주 제외
stocks = stocks[
    ~stocks["Name"].str.contains(r"\d*우[A-Z]?$", regex=True, na=False)
].copy()


# ============================================================
# 7. 전체 종목 분석
# ============================================================

rows = []
errors = []

with st.spinner("KOSPI 종목 분석 중..."):

    for _, stock in stocks.iterrows():

        code = stock[code_col]
        name = stock["Name"]
        stock_file = CACHE / f"{code}.csv"

        if not stock_file.exists():
            continue

        try:
            df = pd.read_csv(stock_file, index_col="Date", parse_dates=["Date"])

            if not {"Close", "Volume"}.issubset(df.columns):
                continue

            data = df[["Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()

            if len(data) < 130:
                continue

            close = data["Close"]
            volume = data["Volume"]

            # 이동평균선
            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(60).mean()
            ma120 = close.rolling(120).mean()

            # 정배열: 현재가 > MA20 > MA60 > MA120
            trend = close.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1] > ma120.iloc[-1]

            # 이동평균선 모두 상승
            rising = (
                ma20.iloc[-1] > ma20.iloc[-6]
                and ma60.iloc[-1] > ma60.iloc[-6]
                and ma120.iloc[-1] > ma120.iloc[-6]
            )

            if not (trend and rising):
                continue

            # 투자 지표
            ret = close.pct_change()

            return20 = close.iloc[-1] / close.iloc[-21] - 1
            momentum = close.iloc[-22] / close.iloc[-126] - 1
            distance = close.iloc[-1] / ma20.iloc[-1] - 1
            value = (close * volume).tail(20).mean()
            volatility = ret.tail(20).std()
            max_up = ret.tail(5).max()

            # 기본 필터
            condition = (
                value >= MIN_VALUE
                and momentum > 0
                and return20 <= 0.30
                and distance <= 0.15
                and max_up <= 0.20
            )

            if not condition:
                continue

            rows.append([
                code, name, close.iloc[-1],
                ma20.iloc[-1], ma60.iloc[-1], ma120.iloc[-1],
                return20, momentum, distance, value, volatility
            ])

        except Exception as e:
            errors.append(f"{code} {name}: {e}")


# ============================================================
# 8. 분석 결과 DataFrame
# ============================================================

columns = [
    "Code", "Name", "Close",
    "MA20", "MA60", "MA120",
    "Return20", "Momentum", "Distance",
    "Value", "Volatility"
]

result = pd.DataFrame(rows, columns=columns)

if result.empty:
    st.warning("조건을 만족하는 종목이 없습니다.")
    st.stop()


# ============================================================
# 9. 매수 점수
# ============================================================

# 모멘텀 40점
result["모멘텀점수"] = result["Momentum"].rank(pct=True) * 40

# MA20 이격도 30점: 약 +5% 위치에 높은 점수
result["이격점수"] = (
    30 * (1 - abs(result["Distance"] - 0.05) / 0.10)
).clip(0, 30)

# 유동성 15점
result["유동성점수"] = result["Value"].rank(pct=True) * 15

# 안정성 15점: 변동성이 낮을수록 높은 점수
result["안정성점수"] = (
    1 - result["Volatility"].rank(pct=True)
) * 15

result["BuyScore"] = (
    result["모멘텀점수"]
    + result["이격점수"]
    + result["유동성점수"]
    + result["안정성점수"]
)

result = result.sort_values("BuyScore", ascending=False).reset_index(drop=True)


# ============================================================
# 10. 종목 유형 분류
# ============================================================

m = result["Momentum"] * 100
r20 = result["Return20"] * 100
dist = result["Distance"] * 100

conditions = [
    m >= 80,
    r20 >= 20,
    dist >= 10,
    (m >= 15) & (m <= 50) & (r20 <= 5) & (dist <= 6),
    dist <= 3
]

result["유형"] = np.select(
    conditions,
    ["강한추세", "급등주의", "과열주의", "균형형", "저과열"],
    default="일반"
)

result["위험도"] = result["유형"].map({
    "강한추세": "높음",
    "급등주의": "높음",
    "과열주의": "높음",
    "균형형": "낮음",
    "저과열": "낮음",
    "일반": "보통"
})

result["해석"] = result["유형"].map({
    "강한추세": "추세는 매우 강하지만 이미 많이 오른 종목",
    "급등주의": "최근 급등하여 추격매수 주의",
    "과열주의": "상승 추세지만 MA20에서 다소 멀어진 상태",
    "균형형": "추세와 과열 정도의 균형이 좋은 종목",
    "저과열": "과열은 적지만 상승 힘을 더 확인할 종목",
    "일반": "무난한 상승 추세 종목"
})


# ============================================================
# 11. 화면 표시용 데이터
# ============================================================

result["20일(%)"] = result["Return20"] * 100
result["6-1M(%)"] = result["Momentum"] * 100
result["MA20이격(%)"] = result["Distance"] * 100
result["거래대금(억)"] = result["Value"] / 100_000_000

SHOW_COLS = [
    "Code", "Name", "Close", "BuyScore",
    "20일(%)", "6-1M(%)", "MA20이격(%)", "거래대금(억)",
    "유형", "위험도", "해석"
]


# ============================================================
# 12. 전체 매수 후보
# ============================================================

st.divider()

title = "매수 후보" if market_up else "관심 종목"
st.subheader(f"{title} TOP {TOP_N}")

st.dataframe(
    result[SHOW_COLS].head(TOP_N).round(2),
    hide_index=True,
    width="stretch"
)


# ============================================================
# 13. 유형별 종목 수
# ============================================================

st.subheader("유형별 종목 수")

type_count = result["유형"].value_counts().reindex(TYPE_ORDER, fill_value=0)
cols = st.columns(len(TYPE_ORDER))

for col, stock_type in zip(cols, TYPE_ORDER):
    col.metric(stock_type, f"{int(type_count[stock_type])}개")


# ============================================================
# 14. 선택한 유형
# ============================================================

st.divider()

if opt == "전체":
    selected = result.copy()
else:
    selected = result[result["유형"] == opt].copy()

st.subheader(f"{opt} 종목 : {len(selected)}개")

if selected.empty:
    st.info(f"{opt} 유형에 해당하는 종목이 없습니다.")
    st.stop()


# 전체는 유형별로 묶어서 표시
if opt == "전체":
    type_map = {name: i for i, name in enumerate(TYPE_ORDER)}
    selected["유형순서"] = selected["유형"].map(type_map)

    selected_view = selected.sort_values(
        ["유형순서", "BuyScore"],
        ascending=[True, False]
    )
else:
    selected_view = selected.sort_values("BuyScore", ascending=False)

st.dataframe(
    selected_view[SHOW_COLS].round(2),
    hide_index=True,
    width="stretch"
)


# ============================================================
# 15. 매매계획 / 차트 대상
# ============================================================

# 특정 유형은 BuyScore TOP N
if opt != "전체":

    chart_selected = (
        selected
        .sort_values("BuyScore", ascending=False)
        .head(CHART_N)
        .copy()
    )

# 전체는 각 유형을 최소 1개씩 포함
else:

    first_stocks = []

    for stock_type in TYPE_ORDER:

        temp = (
            selected[selected["유형"] == stock_type]
            .sort_values("BuyScore", ascending=False)
            .head(1)
        )

        if not temp.empty:
            first_stocks.append(temp)

    first_stocks = pd.concat(first_stocks, ignore_index=True)

    # 유형 수보다 CHART_N이 작으면 자동 증가
    target_count = max(CHART_N, len(first_stocks))

    # 이미 선택된 대표 종목 제외
    remaining = (
        selected[~selected["Code"].isin(first_stocks["Code"])]
        .sort_values("BuyScore", ascending=False)
    )

    chart_selected = pd.concat(
        [
            first_stocks,
            remaining.head(target_count - len(first_stocks))
        ],
        ignore_index=True
    )

    chart_selected = (
        chart_selected
        .sort_values("BuyScore", ascending=False)
        .reset_index(drop=True)
    )


# ============================================================
# 16. 차트 대상 표시
# ============================================================

st.subheader(f"매매계획 / 차트 대상 : {len(chart_selected)}개")

CHART_COLS = [
    "Code", "Name", "BuyScore",
    "20일(%)", "6-1M(%)", "MA20이격(%)",
    "유형", "위험도"
]

st.dataframe(
    chart_selected[CHART_COLS].round(2),
    hide_index=True,
    width="stretch"
)


# 전체 선택 시 각 유형 포함 수
if opt == "전체":

    included = (
        chart_selected["유형"]
        .value_counts()
        .reindex(TYPE_ORDER, fill_value=0)
    )

    cols = st.columns(len(TYPE_ORDER))

    for col, stock_type in zip(cols, TYPE_ORDER):
        col.metric(stock_type, f"{int(included[stock_type])}개")


# ============================================================
# 17. 매수가 / 손절가 / 목표가
# ============================================================

# 입력한 매수가가 없으면 현재가 사용
chart_selected["매수가"] = (
    chart_selected["Code"]
    .map(BUY_PRICE)
    .fillna(chart_selected["Close"])
)

# MA60 또는 최대손실률 기준 중 높은 가격을 손절가로 사용
auto_stop = pd.concat(
    [
        chart_selected["MA60"],
        chart_selected["매수가"] * (1 - STOP_RATE)
    ],
    axis=1
).max(axis=1)

# 직접 입력한 손절가가 있으면 우선 적용
chart_selected["손절가"] = (
    chart_selected["Code"]
    .map(BUY_STOP)
    .fillna(auto_stop)
)

# R = 매수가 - 손절가
chart_selected["R"] = chart_selected["매수가"] - chart_selected["손절가"]

chart_selected["1R(30%매도)"] = chart_selected["매수가"] + chart_selected["R"]
chart_selected["2R(30%매도)"] = chart_selected["매수가"] + chart_selected["R"] * 2


# ============================================================
# 18. 매도 신호
# ============================================================

price = chart_selected["Close"]

sell_conditions = [
    price <= chart_selected["손절가"],
    price < chart_selected["MA60"],
    price < chart_selected["MA20"],
    price >= chart_selected["2R(30%매도)"],
    price >= chart_selected["1R(30%매도)"]
]

chart_selected["현재단계"] = np.select(
    sell_conditions,
    ["손절 구간", "추세 이탈", "MA20 이탈", "2R 이상", "1R 이상"],
    default="1R 전"
)

chart_selected["매도신호"] = np.select(
    sell_conditions,
    [
        "전량 손절",
        "매도",
        "주의",
        "30% 매도 → 남은 40% MA20 추적",
        "30% 매도"
    ],
    default="보유"
)


# ============================================================
# 19. 매매 계획
# ============================================================

st.subheader(f"{opt} 매매 계획")

PLAN_COLS = [
    "Code", "Name", "유형",
    "Close", "MA20", "MA60",
    "매수가", "손절가",
    "1R(30%매도)", "2R(30%매도)",
    "현재단계", "매도신호"
]

st.dataframe(
    chart_selected[PLAN_COLS].round(0),
    hide_index=True,
    width="stretch"
)


# ============================================================
# 20. 캔들 차트 스타일
# ============================================================

market_colors = mpf.make_marketcolors(
    up="red",
    down="blue",
    inherit=True
)

chart_style = mpf.make_mpf_style(
    base_mpf_style="yahoo",
    marketcolors=market_colors,
    rc={
        "font.family": font,
        "figure.titleweight": "normal"
    }
)


# ============================================================
# 21. 캔들 차트
# ============================================================

st.divider()
st.subheader("캔들 차트")

for _, row in chart_selected.iterrows():

    code = row["Code"]
    name = row["Name"]
    stock_file = CACHE / f"{code}.csv"

    if not stock_file.exists():
        continue

    try:
        df = pd.read_csv(stock_file, index_col="Date", parse_dates=["Date"])

        required = {"Open", "High", "Low", "Close"}

        if not required.issubset(df.columns):
            st.warning(f"{code} {name}: OHLC 데이터가 없습니다.")
            continue

        # 숫자로 변환
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        # 종목 정보
        st.markdown(f"### {name} ({code})")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("현재가", f"{row['Close']:,.0f}원")
        c2.metric("BuyScore", f"{row['BuyScore']:.1f}")
        c3.metric("유형", row["유형"])
        c4.metric("위험도", row["위험도"])

        st.caption(row["해석"])

        title = f"{name} | {row['유형']} | 위험도 {row['위험도']}"

        fig, _ = mpf.plot(
            df.tail(180),
            type="candle",
            mav=(20, 60, 120),
            volume="Volume" in df.columns,
            style=chart_style,
            figsize=(13, 7),
            title=title,
            returnfig=True
        )

        st.pyplot(fig, width="stretch")
        plt.close(fig)

    except Exception as e:
        st.error(f"{code} {name} 차트 오류: {e}")


# ============================================================
# 22. 오류 정보
# ============================================================

if errors:
    with st.expander(f"종목 분석 오류 {len(errors)}건"):
        for error in errors:
            st.text(error)


# ============================================================
# 23. 하단 정보
# ============================================================

st.divider()

st.caption(
    f"데이터 기준일: {market_date} | "
    f"분석 후보: {len(result)}개 | "
    f"선택 유형: {opt}"
)