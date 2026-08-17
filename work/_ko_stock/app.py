# ==================================================
# KOSPI 추세 투자 분석 - Streamlit
# ==================================================

import logging

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

import platform
from pathlib import Path
from threading import RLock

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
import mplfinance as mpf
import streamlit as st


# ==================================================
# 1. 화면 설정
# ==================================================

st.set_page_config(page_title="KOSPI 추세 투자 분석", page_icon="📈", layout="wide")

st.title("KOSPI 추세 투자 분석")
st.caption("MA20 / MA60 / MA120 / MA200 + 모멘텀 + 매수·매도 계획")


# ==================================================
# 2. 작은 정보 카드 스타일
# ==================================================

st.markdown(
    """
    <style>
    .info-card {
        padding: 6px 8px;
        border: 1px solid #dddddd;
        border-radius: 8px;
        text-align: center;
        margin-bottom: 6px;
        min-height: 58px;
    }

    .info-title {
        font-size: 12px;
        color: #777777;
        margin-bottom: 1px;
    }

    .info-value {
        font-size: 16px;
        font-weight: 600;
        line-height: 1.25;
        word-break: keep-all;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==================================================
# 3. 기본 설정
# ==================================================

# 주가 데이터 폴더
# DATA_FOLDER = Path("stock_data") # <== 로컬에서는 OK(steamlit run app.py), app.py 배포시는 에러 발생.
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "stock_data" # <== app.py 배포시 사용할 코드

# 실제 매수가가 있으면 입력
# 예: {"021240": 98200}
BUY_PRICE = {}

# 직접 정한 손절가가 있으면 입력
# 예: {"021240": 92100}
BUY_STOP = {}

# matplotlib 동시 실행 충돌 방지
PLOT_LOCK = RLock()


# ==================================================
# 4. 한글 폰트
# ==================================================

# 운영체제에 따라 한글 폰트 선택
font = {"Windows": "Malgun Gothic", "Darwin": "AppleGothic"}.get(
    platform.system(), "NanumGothic"
)

# 설치된 폰트 확인
available_fonts = {f.name for f in fm.fontManager.ttflist}

# 해당 폰트가 없으면 기본 폰트 사용
if font not in available_fonts:
    font = "DejaVu Sans"

plt.rcParams["font.family"] = font
plt.rcParams["axes.unicode_minus"] = False


# ==================================================
# 5. 사이드바
# ==================================================

st.sidebar.header("분석 설정")

# 종목 유형은 항상 고정해서 표시
TYPE_OPTIONS = ["전체", "균형형", "강한추세", "급등주의", "과열주의", "저과열", "일반"]

opt = st.sidebar.selectbox("종목 유형", TYPE_OPTIONS, index=0)

TOP_N = st.sidebar.slider("추천 종목 수", min_value=5, max_value=50, value=20, step=5)

CHART_N = st.sidebar.slider("차트 개수", min_value=1, max_value=20, value=10)

min_value_uk = st.sidebar.number_input(
    "최소 평균 거래대금(억원)", min_value=1.0, max_value=1000.0, value=10.0, step=1.0
)

# 억원 → 원
MIN_VALUE = min_value_uk * 100_000_000

stop_rate_pct = st.sidebar.slider("최대 손실률(%)", min_value=3, max_value=20, value=8)

STOP_RATE = stop_rate_pct / 100


# 분석 데이터를 새로 받은 경우 캐시 삭제
if st.sidebar.button("분석 캐시 새로고침"):
    st.cache_data.clear()
    st.rerun()


# ==================================================
# 6. 작은 카드 출력 함수
# ==================================================


def show_card(column, title, value):
    """작은 정보 카드 표시"""

    with column:
        st.markdown(
            f"""
            <div class="info-card">
                <div class="info-title">{title}</div>
                <div class="info-value">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ==================================================
# 7. 데이터 읽기 함수
# ==================================================


@st.cache_data(show_spinner=False)
def load_market():
    """KOSPI 지수 읽기"""

    df = pd.read_csv(DATA_FOLDER / "KS11.csv", index_col="Date", parse_dates=["Date"])

    return df.sort_index()


@st.cache_data(show_spinner=False)
def load_stocks():
    """KOSPI 종목 목록 읽기"""

    df = pd.read_csv(DATA_FOLDER / "KOSPI_list.csv", dtype={"Code": str})

    # 종목코드를 6자리 문자열로 변경
    # 예: 5930 → 005930
    df["Code"] = df["Code"].astype(str).str.replace(".0", "", regex=False).str.zfill(6)

    return df


# ==================================================
# 8. 전체 종목 분석 함수
# ==================================================


@st.cache_data(show_spinner=False)
def analyze_stocks(min_value):
    stocks = load_stocks()
    rows = []

    for _, stock in stocks.iterrows():
        code = stock["Code"]
        name = stock["Name"]

        stock_file = DATA_FOLDER / f"{code}.csv"

        # 주가 파일이 없으면 제외
        if not stock_file.exists():
            continue

        try:
            # 주가 데이터 읽기
            df = pd.read_csv(
                stock_file, index_col="Date", parse_dates=["Date"]
            ).sort_index()

            # MA120과 모멘텀 계산에 필요한 데이터
            if len(df) < 130:
                continue

            close = df["Close"]
            now = close.iloc[-1]

            # ------------------------------------------
            # 이동평균선
            # ------------------------------------------

            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(60).mean()
            ma120 = close.rolling(120).mean()

            # ------------------------------------------
            # 상승 정배열
            # 현재가 > MA20 > MA60 > MA120
            # ------------------------------------------

            trend = now > ma20.iloc[-1] > ma60.iloc[-1] > ma120.iloc[-1]

            # ------------------------------------------
            # 이동평균선 상승 여부
            # ------------------------------------------

            rising = (
                ma20.iloc[-1] > ma20.iloc[-6]
                and ma60.iloc[-1] > ma60.iloc[-6]
                and ma120.iloc[-1] > ma120.iloc[-6]
            )

            if not (trend and rising):
                continue

            # ------------------------------------------
            # 투자 지표
            # ------------------------------------------

            daily_return = close.pct_change()

            # 최근 20일 수익률
            return20 = now / close.iloc[-21] - 1

            # 6개월 - 최근 1개월 모멘텀
            momentum = close.iloc[-22] / close.iloc[-126] - 1

            # MA20 이격도
            distance = now / ma20.iloc[-1] - 1

            # 최근 20일 평균 거래대금
            value = (close * df["Volume"]).tail(20).mean()

            # 최근 20일 변동성
            volatility = daily_return.tail(20).std()

            # 최근 5일 최대 하루 상승률
            max_up = daily_return.tail(5).max()

            # ------------------------------------------
            # 기본 필터
            # ------------------------------------------

            # 거래대금 부족
            if value < min_value:
                continue

            # 모멘텀 음수
            if momentum <= 0:
                continue

            # 최근 20일 30% 초과 상승
            if return20 > 0.30:
                continue

            # MA20 이격도 15% 초과
            if distance > 0.15:
                continue

            # 최근 5일 중 하루 20% 이상 급등
            if max_up > 0.20:
                continue

            # ------------------------------------------
            # 조건 통과 종목 저장
            # ------------------------------------------

            rows.append(
                {
                    "Code": code,
                    "Name": name,
                    "Close": now,
                    "MA20": ma20.iloc[-1],
                    "MA60": ma60.iloc[-1],
                    "MA120": ma120.iloc[-1],
                    "Return20": return20,
                    "Momentum": momentum,
                    "Distance": distance,
                    "Value": value,
                    "Volatility": volatility,
                }
            )

        except Exception:
            # 한 종목에서 오류가 발생해도 계속 진행
            continue

    return pd.DataFrame(rows)


# ==================================================
# 9. 데이터 파일 확인
# ==================================================

if not DATA_FOLDER.exists():
    st.error("stock_data 폴더가 없습니다.")
    st.stop()

if not (DATA_FOLDER / "KS11.csv").exists():
    st.error("stock_data/KS11.csv 파일이 없습니다.")
    st.stop()

if not (DATA_FOLDER / "KOSPI_list.csv").exists():
    st.error("stock_data/KOSPI_list.csv 파일이 없습니다.")
    st.stop()


# ==================================================
# 10. KOSPI 시장 상태
# ==================================================

try:
    kospi = load_market()

except Exception as e:
    st.error(f"KOSPI 데이터를 읽지 못했습니다: {e}")
    st.stop()


# MA200 계산에는 최소 200일 필요
if len(kospi) < 200:
    st.error("KOSPI 데이터가 200일보다 적습니다.")
    st.stop()


kospi_close = kospi["Close"]

# 현재 KOSPI
kospi_now = kospi_close.iloc[-1]

# KOSPI MA200
kospi_ma200 = kospi_close.rolling(200).mean().iloc[-1]

# 상승장 여부
market_up = kospi_now > kospi_ma200

# 데이터 기준일
market_date = kospi.index[-1].date()


# 시장 상태
col1, col2, col3, col4 = st.columns(4)

col1.metric("데이터 기준일", str(market_date))

col2.metric("KOSPI", f"{kospi_now:,.2f}")

col3.metric("KOSPI MA200", f"{kospi_ma200:,.2f}")

col4.metric("시장 상태", "상승장" if market_up else "하락장")


# ==================================================
# 11. 전체 종목 분석
# ==================================================

with st.spinner("KOSPI 종목 분석 중..."):
    result = analyze_stocks(MIN_VALUE)


if result.empty:
    st.warning("조건을 만족하는 종목이 없습니다.")
    st.stop()


# ==================================================
# 12. 매수 점수
# ==================================================

# 모멘텀 : 40점
result["모멘텀점수"] = result["Momentum"].rank(pct=True) * 40

# MA20 이격도 : 30점
# +5% 부근을 가장 좋게 평가
result["이격점수"] = (30 * (1 - abs(result["Distance"] - 0.05) / 0.10)).clip(0, 30)

# 거래대금 : 15점
result["유동성점수"] = result["Value"].rank(pct=True) * 15

# 안정성 : 15점
# 변동성이 낮을수록 높은 점수
result["안정성점수"] = (1 - result["Volatility"].rank(pct=True)) * 15

# 총점
result["BuyScore"] = (
    result["모멘텀점수"]
    + result["이격점수"]
    + result["유동성점수"]
    + result["안정성점수"]
)

# 점수가 높은 순으로 정렬
result = result.sort_values("BuyScore", ascending=False).reset_index(drop=True)


# ==================================================
# 13. 종목 유형 분류
# ==================================================

# % 단위로 변환
momentum_pct = result["Momentum"] * 100
return20_pct = result["Return20"] * 100
distance_pct = result["Distance"] * 100


# 위에서부터 순서대로 검사
conditions = [
    # 모멘텀이 매우 강함
    momentum_pct >= 80,
    # 최근 급등
    return20_pct >= 20,
    # MA20에서 많이 떨어져 있음
    distance_pct >= 10,
    # 추세와 과열 정도가 균형적
    (
        (momentum_pct >= 15)
        & (momentum_pct <= 50)
        & (return20_pct <= 5)
        & (distance_pct <= 6)
    ),
    # MA20 근처
    distance_pct <= 3,
]


types = ["강한추세", "급등주의", "과열주의", "균형형", "저과열"]


result["유형"] = np.select(conditions, types, default="일반")


# ==================================================
# 14. 위험도 / 해석
# ==================================================

risk_map = {
    "강한추세": "높음",
    "급등주의": "높음",
    "과열주의": "높음",
    "균형형": "낮음",
    "저과열": "낮음",
    "일반": "보통",
}


explain_map = {
    "강한추세": "추세는 매우 강하지만 이미 많이 오른 종목",
    "급등주의": "최근 급등하여 추격매수 주의",
    "과열주의": "상승 추세지만 MA20에서 다소 멀어진 상태",
    "균형형": "추세와 과열 정도의 균형이 좋은 종목",
    "저과열": "과열은 적지만 상승 힘을 더 확인할 종목",
    "일반": "무난한 상승 추세 종목",
}


result["위험도"] = result["유형"].map(risk_map)
result["해석"] = result["유형"].map(explain_map)


# ==================================================
# 15. 화면 표시용 단위
# ==================================================

result["20일(%)"] = result["Return20"] * 100
result["6-1M(%)"] = result["Momentum"] * 100
result["MA20이격(%)"] = result["Distance"] * 100

# 원 → 억원
result["거래대금(억)"] = result["Value"] / 100_000_000


# ==================================================
# 16. 전체 추천 종목
# ==================================================

st.divider()


if market_up:
    st.subheader(f"매수 후보 TOP {TOP_N}")

else:
    st.subheader(f"관심 종목 TOP {TOP_N}")

    st.warning("KOSPI가 MA200 아래에 있습니다. 신규 매수는 보수적으로 판단합니다.")


show_cols = [
    "Code",
    "Name",
    "Close",
    "BuyScore",
    "20일(%)",
    "6-1M(%)",
    "MA20이격(%)",
    "거래대금(억)",
    "유형",
    "위험도",
    "해석",
]


st.dataframe(result[show_cols].head(TOP_N).round(2), width="stretch", hide_index=True)


# ==================================================
# 17. 원하는 유형 선택
# ==================================================

if opt == "전체":
    # 모든 유형에서 BuyScore 상위 종목
    selected = result.head(CHART_N).copy()

else:
    # 선택한 유형에서 BuyScore 상위 종목
    selected = result[result["유형"] == opt].head(CHART_N).copy()


st.subheader(f"{opt} - TOP {CHART_N}")


if selected.empty:
    st.info(f"현재 조건을 만족하는 '{opt}' 종목이 없습니다.")

    st.stop()


# ==================================================
# 18. 매수가
# ==================================================

# 실제 매수가가 있으면 실제 가격 사용
# 없으면 현재가 사용
selected["매수가"] = selected["Code"].map(BUY_PRICE).fillna(selected["Close"])


# ==================================================
# 19. 손절가
# ==================================================

# MA60과 매수가 - 최대손실률 중
# 더 높은 가격을 사용
auto_stop = pd.concat(
    [selected["MA60"], selected["매수가"] * (1 - STOP_RATE)], axis=1
).max(axis=1)


# 직접 입력한 손절가가 있으면 우선 사용
selected["손절가"] = selected["Code"].map(BUY_STOP).fillna(auto_stop)


# ==================================================
# 20. R / 분할 매도
# ==================================================

# R = 매수가 - 손절가
selected["R"] = selected["매수가"] - selected["손절가"]


# 1R 도달 시 30% 매도
selected["1R(30%매도)"] = selected["매수가"] + selected["R"]


# 2R 도달 시 추가 30% 매도
selected["2R(30%매도)"] = selected["매수가"] + selected["R"] * 2


# ==================================================
# 21. 현재 매도 단계
# ==================================================

price = selected["Close"]


sell_conditions = [
    # 손절가 이하
    price <= selected["손절가"],
    # MA60 아래
    price < selected["MA60"],
    # MA20 아래
    price < selected["MA20"],
    # 2R 이상
    price >= selected["2R(30%매도)"],
    # 1R 이상
    price >= selected["1R(30%매도)"],
]


selected["현재단계"] = np.select(
    sell_conditions,
    ["손절 구간", "추세 이탈", "MA20 이탈", "2R 이상", "1R 이상"],
    default="1R 전",
)


selected["매도신호"] = np.select(
    sell_conditions,
    ["전량 손절", "매도", "주의", "30% 매도 → 남은 40% MA20 추적", "30% 매도"],
    default="보유",
)


# ==================================================
# 22. 매수 / 매도 계획 표
# ==================================================

plan_cols = [
    "Code",
    "Name",
    "Close",
    "MA20",
    "MA60",
    "매수가",
    "손절가",
    "1R(30%매도)",
    "2R(30%매도)",
    "현재단계",
    "매도신호",
]


st.dataframe(selected[plan_cols].round(0), width="stretch", hide_index=True)


# ==================================================
# 23. 캔들 차트 스타일
# ==================================================

st.divider()

st.subheader(f"{opt} 종목 차트")


# 상승 = 빨강
# 하락 = 파랑
market_colors = mpf.make_marketcolors(up="red", down="blue", inherit=True)


# 이동평균선 색상
#
# MA20  = 주황
# MA60  = 초록
# MA120 = 보라
# MA200 = 검정
style = mpf.make_mpf_style(
    base_mpf_style="yahoo",
    marketcolors=market_colors,
    mavcolors=["orange", "green", "purple", "black"],
    rc={"font.family": font},
)


# 이동평균선 범례
ma_legend = [
    Line2D([0], [0], color="orange", lw=2, label="MA20"),
    Line2D([0], [0], color="green", lw=2, label="MA60"),
    Line2D([0], [0], color="purple", lw=2, label="MA120"),
    Line2D([0], [0], color="black", lw=2, label="MA200"),
]


# ==================================================
# 24. 선택된 모든 종목 차트
# ==================================================

# CHART_N = 10이면 최대 10개의 차트 출력
for i, (_, row) in enumerate(selected.iterrows(), start=1):
    code = row["Code"]
    name = row["Name"]

    stock_file = DATA_FOLDER / f"{code}.csv"

    # --------------------------------------------------
    # 주가 데이터 읽기
    # --------------------------------------------------

    try:
        chart_df = pd.read_csv(
            stock_file, index_col="Date", parse_dates=["Date"]
        ).sort_index()

    except Exception as e:
        st.warning(f"{name} 차트 데이터를 읽지 못했습니다: {e}")

        continue

    # MA200 계산에 필요한 데이터 확인
    if len(chart_df) < 200:
        st.warning(f"{name} : MA200을 표시하기에 데이터가 부족합니다.")

    # ==================================================
    # 25. 종목 이름
    # ==================================================

    st.markdown(f"### {i}. {name} ({code})")

    # ==================================================
    # 26. 매매 정보 카드
    # ==================================================

    # --------------------------------------------------
    # 첫 번째 줄
    # 현재가 / 매수가 / 손절가 / 1R
    # --------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    show_card(c1, "현재가", f"{row['Close']:,.0f}원")

    show_card(c2, "매수가", f"{row['매수가']:,.0f}원")

    show_card(c3, "손절가", f"{row['손절가']:,.0f}원")

    show_card(c4, "1R(30%매도)", f"{row['1R(30%매도)']:,.0f}원")

    # --------------------------------------------------
    # 두 번째 줄
    # 2R / 매수점수 / 현재단계 / 매도신호
    # --------------------------------------------------

    c5, c6, c7, c8 = st.columns(4)

    show_card(c5, "2R(30%매도)", f"{row['2R(30%매도)']:,.0f}원")

    show_card(c6, "매수 점수", f"{row['BuyScore']:.1f}점")

    show_card(c7, "현재 단계", row["현재단계"])

    show_card(c8, "매도 신호", row["매도신호"])

    # ==================================================
    # 27. 차트 제목
    # ==================================================

    title = f"{name} | {row['유형']} | 위험도 {row['위험도']}\n{row['해석']}"

    # ==================================================
    # 28. 캔들 차트
    # ==================================================

    with PLOT_LOCK:
        fig, axes = mpf.plot(
            # 최근 250거래일
            chart_df.tail(250),
            type="candle",
            # 이동평균선
            mav=(20, 60, 120, 200),
            # 거래량
            volume=True,
            style=style,
            figsize=(13, 7),
            returnfig=True,
        )

        # 가격 차트
        ax = axes[0]

        # --------------------------------------------------
        # 제목
        # --------------------------------------------------

        ax.set_title(title, fontsize=11, pad=8)

        # --------------------------------------------------
        # 오른쪽 가격 표시 공간
        # --------------------------------------------------

        fig.subplots_adjust(right=0.78)

        # ==================================================
        # 29. 매수가 / 손절가 / 1R / 2R 선
        # ==================================================

        price_lines = [
            # 매수가
            ("매수가", row["매수가"], "#1565C0", "-"),
            # 손절가
            ("손절가", row["손절가"], "#D32F2F", "--"),
            # 1R
            ("1R(30%매도)", row["1R(30%매도)"], "#00838F", "-."),
            # 2R
            ("2R(30%매도)", row["2R(30%매도)"], "#C2185B", ":"),
        ]

        # 가격선 범례
        price_legend = []

        for label, value, color, line_style in price_lines:
            # ------------------------------------------
            # 가격 수평선
            # ------------------------------------------

            ax.axhline(y=value, color=color, linestyle=line_style, linewidth=1.5)

            # ------------------------------------------
            # 차트 오른쪽 끝에 가격 표시
            # ------------------------------------------

            ax.text(
                1.01,
                value,
                f"{label} {value:,.0f}원",
                # x는 차트 비율
                # y는 실제 가격
                transform=ax.get_yaxis_transform(),
                fontsize=9,
                color=color,
                va="center",
                ha="left",
                # 차트 밖에도 표시
                clip_on=False,
                bbox={
                    "facecolor": "white",
                    "edgecolor": color,
                    "alpha": 0.85,
                    "pad": 2,
                },
            )

            # ------------------------------------------
            # 범례
            # ------------------------------------------

            price_legend.append(
                Line2D(
                    [0],
                    [0],
                    color=color,
                    linestyle=line_style,
                    lw=1.5,
                    label=(f"{label} {value:,.0f}원"),
                )
            )

        # ==================================================
        # 30. 전체 범례
        # ==================================================

        ax.legend(
            handles=(ma_legend + price_legend),
            loc="upper left",
            frameon=True,
            fontsize=8,
        )

        # ==================================================
        # 31. Streamlit에 차트 표시
        # ==================================================

        st.pyplot(fig, width="stretch")

        # 다음 그래프를 위해 닫기
        plt.close(fig)

    # 종목 사이 구분선
    st.divider()


# ==================================================
# 32. 안내
# ==================================================

st.caption(
    "※ 기술적 지표를 이용한 분석 예제입니다. "
    "실제 투자 판단은 사용자가 직접 해야 합니다."
)
