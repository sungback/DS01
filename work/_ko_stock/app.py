# ==================================================
# KOSPI 추세 투자 분석 - Streamlit
# ==================================================

import logging

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

# 이 앱에서 발생한 오류를 기록할 로거
logger = logging.getLogger(__name__)

import hashlib
import platform
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# import 하는 것만으로 NanumGothic 폰트를 matplotlib에 등록한다.
# 나눔폰트가 없는 Streamlit Cloud(리눅스)에서 한글이 깨지지 않게 해 준다.
import koreanize_matplotlib  # noqa: F401
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

# 최근 600일 데이터를 사용
START = (datetime.now() - timedelta(days=600)).strftime("%Y-%m-%d")

# app.py와 같은 위치의 stock_data 폴더를 사용
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "stock_data"

# 폴더가 없으면 자동 생성
DATA_FOLDER.mkdir(parents=True, exist_ok=True)

# 파일 캐시 확인 주기: 1시간
DATA_REFRESH_SECONDS = 60 * 60

# 매수가와 손절가는 화면의 '보유 종목 입력' 표에서 직접 입력한다.
# 입력한 값은 st.session_state["positions"]에 종목코드 기준으로 보관한다.

# 데이터 파일 동시 갱신 충돌 방지
DATA_LOCK = RLock()

# matplotlib 동시 실행 충돌 방지
PLOT_LOCK = RLock()


# ==================================================
# 4. 한글 폰트
# ==================================================

# 운영체제에 따라 한글 폰트 선택
# 리눅스의 NanumGothic은 위에서 import한 koreanize_matplotlib이 등록해 준다.
font = {"Windows": "Malgun Gothic", "Darwin": "AppleGothic"}.get(
    platform.system(), "NanumGothic"
)

# 설치된 폰트 확인
available_fonts = {f.name for f in fm.fontManager.ttflist}

# 해당 폰트가 없으면 한글이 등록된 NanumGothic으로 대체
if font not in available_fonts:
    font = "NanumGothic" if "NanumGothic" in available_fonts else "DejaVu Sans"

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

# 캔들 차트에 표시할 거래일 수
CHART_DAYS = st.sidebar.selectbox(
    "차트 기간",
    [60, 120, 250],
    index=0,
    format_func=lambda x: f"{x}일",
)

min_value_uk = st.sidebar.number_input(
    "최소 평균 거래대금(억원)", min_value=1.0, max_value=1000.0, value=10.0, step=1.0
)

# 억원 → 원
MIN_VALUE = min_value_uk * 100_000_000

stop_rate_pct = st.sidebar.slider("최대 손실률(%)", min_value=3, max_value=20, value=8)

STOP_RATE = stop_rate_pct / 100


# 파일 캐시와 Streamlit 분석 캐시를 함께 새로고침
if st.sidebar.button("주가/분석 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption("주가 파일은 1시간마다 최신 여부를 자동 확인합니다.")


# ==================================================
# 6. 작은 카드 출력 함수
# ==================================================


def to_price(value):
    """
    표에 입력한 값을 가격 숫자로 바꾼다.

    비어 있거나 숫자가 아니거나 0 이하이면 None(미입력)으로 본다.
    """

    if value is None or pd.isna(value):
        return None

    try:
        value = float(value)

    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def won(value):
    """가격을 원 단위 글자로 바꾼다. 값이 없으면 '-' 로 표시한다."""

    if pd.isna(value):
        return "-"

    return f"{value:,.0f}원"


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
# 7. 파일 저장 / 데이터 지문
# ==================================================


def save_if_changed(df, path, **kwargs):
    """
    내용이 실제로 달라졌을 때만 CSV로 저장한다.

    같은 내용을 그대로 덮어쓰면 파일 수정시각만 바뀐다.
    그러면 아래 data_fingerprint 값이 매번 달라져
    화면 계산 결과 캐시가 쓸데없이 버려진다.

    인코딩은 항상 UTF-8로 고정한다.
    to_csv 의 기본값과 같아야 하고, 윈도우에서 종목명이 깨지지 않는다.
    """

    text = df.to_csv(**kwargs)

    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False

        except Exception as e:
            # 읽지 못하면 파일이 깨진 것이므로 새로 쓴다.
            logger.warning("%s 비교 실패, 새로 저장합니다: %s", path.name, e)

    path.write_text(text, encoding="utf-8")

    return True


def data_fingerprint():
    """
    stock_data 폴더 상태를 짧은 글자로 요약한다.

    파일이 하나도 바뀌지 않으면 같은 값이 나온다.
    이 값을 캐시 키로 쓰면 데이터가 그대로일 때 캐시가 유지된다.
    """

    parts = []

    for f in sorted(DATA_FOLDER.glob("*.csv")):
        info = f.stat()
        parts.append(f"{f.name}:{info.st_size}:{info.st_mtime_ns}")

    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


# ==================================================
# 8. 주가 파일 캐시 준비
# ==================================================


@st.cache_data(ttl=DATA_REFRESH_SECONDS, show_spinner=False)
def prepare_stock_data():
    """
    stock_data 폴더의 파일을 확인한다.

    - KOSPI 종목 목록이 없으면 새로 저장
    - KOSPI 지수와 개별 종목이 오래되었으면 부족한 날짜만 갱신
    - 이미 최신이면 다운로드 생략
    """

    stats = {
        "신규 다운로드": 0,
        "기존 파일 갱신": 0,
        "이미 최신": 0,
        "새 데이터 없음": 0,
        "오류": 0,
    }

    # 오류가 난 종목코드 예시 (사이드바 표시용)
    error_codes = []

    with DATA_LOCK:
        # ----------------------------------------------
        # ① KOSPI 종목 목록
        # ----------------------------------------------
        list_file = DATA_FOLDER / "KOSPI_list.csv"

        try:
            stocks = fdr.StockListing("KOSPI")

        except Exception as e:
            # 인터넷 오류 시 기존 목록 사용
            logger.warning("KOSPI 종목 목록 조회 실패, 저장된 목록을 사용합니다: %s", e)

            if not list_file.exists():
                raise RuntimeError(
                    "KOSPI 종목 목록을 받지 못했고 저장된 KOSPI_list.csv도 없습니다."
                )

            stocks = pd.read_csv(list_file, dtype={"Code": str})

        # 종목코드를 6자리 문자열로 통일
        stocks["Code"] = (
            stocks["Code"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.zfill(6)
        )

        # 일반 종목만 사용
        stocks = stocks[stocks["Code"].str.endswith("0")].copy()

        # 다음 실행을 위해 저장 (내용이 같으면 건너뛴다)
        save_if_changed(stocks, list_file, index=False)

        # ----------------------------------------------
        # ② KOSPI 지수
        # ----------------------------------------------
        kospi_file = DATA_FOLDER / "KS11.csv"

        if not kospi_file.exists():
            kospi = fdr.DataReader("KS11", START)

            if kospi.empty:
                raise RuntimeError("KOSPI 데이터를 가져오지 못했습니다.")

            kospi.index = pd.to_datetime(kospi.index)
            kospi = kospi.sort_index()

        else:
            kospi = pd.read_csv(
                kospi_file,
                index_col="Date",
                parse_dates=["Date"],
            ).sort_index()

            if kospi.empty:
                kospi = fdr.DataReader("KS11", START)

                if kospi.empty:
                    raise RuntimeError("KOSPI 데이터를 가져오지 못했습니다.")

                kospi.index = pd.to_datetime(kospi.index)
                kospi = kospi.sort_index()

            else:
                try:
                    # 마지막 날짜보다 5일 앞부터 다시 받는다.
                    start = (
                        kospi.index[-1] - pd.Timedelta(days=5)
                    ).strftime("%Y-%m-%d")

                    new = fdr.DataReader("KS11", start)

                    if not new.empty:
                        new.index = pd.to_datetime(new.index)
                        new = new.sort_index()

                        kospi = pd.concat([kospi, new])
                        kospi = kospi[
                            ~kospi.index.duplicated(keep="last")
                        ].sort_index()

                except Exception as e:
                    # 갱신 실패 시 기존 KOSPI 파일을 계속 사용
                    logger.warning(
                        "KOSPI 지수 갱신 실패, 기존 파일을 사용합니다: %s", e
                    )

        # 최근 600일만 유지
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=600)
        kospi = kospi[kospi.index >= cutoff]

        if kospi.empty:
            raise RuntimeError("KOSPI 데이터가 없습니다.")

        save_if_changed(kospi, kospi_file, index_label="Date")

        # 전체 시장의 최신 거래일
        market_date = kospi.index[-1].date()

        # ----------------------------------------------
        # ③ 개별 종목 주가
        # ----------------------------------------------
        for _, stock in stocks.iterrows():
            code = stock["Code"]
            stock_file = DATA_FOLDER / f"{code}.csv"

            try:
                # 파일이 없으면 최근 600일 전체 다운로드
                if not stock_file.exists():
                    df = fdr.DataReader(code, START)

                    if df.empty:
                        stats["새 데이터 없음"] += 1
                        continue

                    df.index = pd.to_datetime(df.index)
                    df = df.sort_index()
                    save_if_changed(df, stock_file, index_label="Date")

                    stats["신규 다운로드"] += 1
                    continue

                # 기존 파일 읽기
                df = pd.read_csv(
                    stock_file,
                    index_col="Date",
                    parse_dates=["Date"],
                ).sort_index()

                # 파일은 있지만 비어 있으면 다시 전체 다운로드
                if df.empty:
                    df = fdr.DataReader(code, START)

                    if df.empty:
                        stats["새 데이터 없음"] += 1
                        continue

                    df.index = pd.to_datetime(df.index)
                    df = df.sort_index()
                    save_if_changed(df, stock_file, index_label="Date")

                    stats["신규 다운로드"] += 1
                    continue

                # 이미 최신 거래일까지 있으면 다운로드 생략
                last_date = df.index[-1].date()

                if last_date >= market_date:
                    stats["이미 최신"] += 1
                    continue

                # 부족한 최근 날짜만 다운로드
                start = (
                    df.index[-1] - pd.Timedelta(days=5)
                ).strftime("%Y-%m-%d")

                new = fdr.DataReader(code, start)

                if new.empty:
                    stats["새 데이터 없음"] += 1
                    continue

                new.index = pd.to_datetime(new.index)
                new = new.sort_index()

                # 기존 데이터 + 새 데이터
                df = pd.concat([df, new])
                df = df[
                    ~df.index.duplicated(keep="last")
                ].sort_index()

                # 최근 600일만 유지
                df = df[df.index >= cutoff]

                save_if_changed(df, stock_file, index_label="Date")
                stats["기존 파일 갱신"] += 1

            except Exception as e:
                # 한 종목 오류가 전체 앱 실행을 막지 않도록 한다.
                logger.warning("%s 주가 갱신 실패: %s", code, e)

                stats["오류"] += 1

                # 사이드바에 보여 줄 예시 종목코드
                if len(error_codes) < 5:
                    error_codes.append(code)

                continue

    # 파일이 하나도 바뀌지 않으면 이 값도 그대로다.
    # 그래서 1시간마다 다시 확인해도 계산 결과 캐시는 유지된다.
    data_version = f"{market_date}-{data_fingerprint()}"

    return {
        "market_date": str(market_date),
        "stock_count": len(stocks),
        "stats": stats,
        "error_codes": error_codes,
        "data_version": data_version,
    }


# ==================================================
# 8. 데이터 읽기 함수
# ==================================================


@st.cache_data(show_spinner=False)
def load_market(data_version):
    """KOSPI 지수 읽기"""

    # data_version은 파일이 갱신되었을 때 캐시를 무효화하기 위한 값
    _ = data_version

    df = pd.read_csv(
        DATA_FOLDER / "KS11.csv",
        index_col="Date",
        parse_dates=["Date"],
    )

    return df.sort_index()


@st.cache_data(show_spinner=False)
def load_stocks(data_version):
    """KOSPI 종목 목록 읽기"""

    _ = data_version

    df = pd.read_csv(
        DATA_FOLDER / "KOSPI_list.csv",
        dtype={"Code": str},
    )

    # 종목코드를 6자리 문자열로 변경
    # 예: 5930 → 005930
    df["Code"] = (
        df["Code"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(6)
    )

    return df


# ==================================================
# 9. 전체 종목 분석 함수
# ==================================================


@st.cache_data(show_spinner=False)
def compute_metrics(data_version):
    """
    모든 KOSPI 종목의 투자 지표를 계산한다.

    사이드바 값(거래대금 기준 등)에는 의존하지 않는다.
    그래서 슬라이더를 움직여도 이 결과는 캐시에서 그대로 재사용되고,
    835개 CSV를 다시 읽지 않는다.

    (지표표, 오류정보) 를 돌려준다.
    """

    stocks = load_stocks(data_version)
    rows = []

    # 읽거나 계산하지 못한 종목
    errors = []

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
            #
            # 거래대금 기준은 사이드바에서 바뀌는 값이므로
            # 여기서 거르지 않고 Value 컬럼으로 내보낸다.
            # ------------------------------------------

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

        except Exception as e:
            # 한 종목에서 오류가 발생해도 계속 진행한다.
            # 다만 조용히 넘기면 '조건을 만족하는 종목이 없습니다' 와
            # 구분이 되지 않으므로 반드시 기록해 둔다.
            logger.warning("%s 분석 실패: %s", code, e)

            errors.append(code)

            continue

    error_info = {
        "count": len(errors),
        "codes": errors[:5],
        "total": len(stocks),
    }

    return pd.DataFrame(rows), error_info


# ==================================================
# 10. 주가 데이터 자동 확인 / 갱신
# ==================================================

try:
    with st.spinner("주가 데이터 확인 중..."):
        data_info = prepare_stock_data()

except Exception as e:
    st.error(f"주가 데이터를 준비하지 못했습니다: {e}")
    st.stop()


data_version = data_info["data_version"]

# 캐시 처리 결과를 사이드바에 간단히 표시
data_status = st.sidebar.expander("주가 데이터 상태")

with data_status:
    st.write("기준일 :", data_info["market_date"])
    st.write("분석 종목 :", data_info["stock_count"])

    for label, value in data_info["stats"].items():
        st.write(f"{label} : {value}")

    if data_info["error_codes"]:
        st.write("갱신 오류 예시 :", ", ".join(data_info["error_codes"]))


# ==================================================
# 11. KOSPI 시장 상태
# ==================================================

try:
    kospi = load_market(data_version)

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
# 12. 전체 종목 분석
# ==================================================

with st.spinner("KOSPI 종목 분석 중..."):
    metrics, analyze_errors = compute_metrics(data_version)


# 분석 단계에서 읽지 못한 종목을 사이드바 패널에 덧붙인다.
# 조용히 넘기면 아래 '조건을 만족하는 종목이 없습니다' 와 구분되지 않는다.
with data_status:
    st.write(
        "분석 오류 :",
        f"{analyze_errors['count']} / {analyze_errors['total']}",
    )

    if analyze_errors["codes"]:
        st.write("분석 오류 예시 :", ", ".join(analyze_errors["codes"]))


# 거래대금 필터는 파일을 다시 읽지 않고 계산 결과에만 적용한다.
result = metrics[metrics["Value"] >= MIN_VALUE].reset_index(drop=True).copy()


if result.empty:
    st.warning("조건을 만족하는 종목이 없습니다.")
    st.stop()


# ==================================================
# 13. 매수 점수
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
# 14. 종목 유형 분류
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
# 15. 위험도 / 해석
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
# 16. 화면 표시용 단위
# ==================================================

result["20일(%)"] = result["Return20"] * 100
result["6-1M(%)"] = result["Momentum"] * 100
result["MA20이격(%)"] = result["Distance"] * 100

# 원 → 억원
result["거래대금(억)"] = result["Value"] / 100_000_000


# ==================================================
# 17. 전체 추천 종목
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
# 18. 원하는 유형 선택
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
# 19. 보유 종목 입력 (매수가 / 손절가)
# ==================================================

# 입력한 값은 종목코드를 기준으로 보관한다.
# 종목 유형이나 차트 개수를 바꿔 목록이 달라져도 값이 그대로 유지된다.
positions = st.session_state.setdefault("positions", {})


st.markdown("#### 보유 종목 입력")

st.caption(
    "표의 매수가 칸을 직접 입력하면 그 종목만 실제 매도 단계를 계산합니다. "
    "손절가를 비워 두면 MA60과 최대 손실률 중 높은 값을 자동으로 사용합니다."
)


# 표에 넣을 값을 세션에서 가져온다.
editor_df = selected[["Code", "Name", "Close"]].copy()

editor_df["매수가"] = [positions.get(c, {}).get("매수가") for c in editor_df["Code"]]

editor_df["손절가"] = [positions.get(c, {}).get("손절가") for c in editor_df["Code"]]


edited = st.data_editor(
    editor_df,
    hide_index=True,
    width="stretch",
    # 종목 정보는 수정할 수 없다.
    disabled=["Code", "Name", "Close"],
    column_config={
        "Close": st.column_config.NumberColumn("현재가", format="%.0f"),
        "매수가": st.column_config.NumberColumn(
            "매수가",
            min_value=0.0,
            format="%.0f",
            help="실제로 매수한 가격. 비워 두면 미보유로 봅니다.",
        ),
        "손절가": st.column_config.NumberColumn(
            "손절가",
            min_value=0.0,
            format="%.0f",
            help="비워 두면 MA60과 최대 손실률 중 높은 값으로 자동 계산합니다.",
        ),
    },
)


# 편집한 내용을 세션에 다시 저장한다.
for code, buy, stop in zip(edited["Code"], edited["매수가"], edited["손절가"]):
    buy = to_price(buy)
    stop = to_price(stop)

    if buy is None and stop is None:
        # 둘 다 지웠으면 보유 목록에서 제거
        positions.pop(code, None)

    else:
        positions[code] = {"매수가": buy, "손절가": stop}


# ==================================================
# 20. 매수가 / 손절가
# ==================================================

selected["매수가"] = pd.to_numeric(
    pd.Series(
        [positions.get(c, {}).get("매수가") for c in selected["Code"]],
        index=selected.index,
        dtype="object",
    ),
    errors="coerce",
)


# 매수가를 입력한 종목만 보유 종목으로 본다.
held = selected["매수가"].notna()


# 직접 입력한 손절가
manual_stop = pd.to_numeric(
    pd.Series(
        [positions.get(c, {}).get("손절가") for c in selected["Code"]],
        index=selected.index,
        dtype="object",
    ),
    errors="coerce",
)


# 자동 손절가
# MA60과 매수가 - 최대손실률 중 더 높은 가격을 사용
auto_stop = pd.concat(
    [selected["MA60"], selected["매수가"] * (1 - STOP_RATE)], axis=1
).max(axis=1)


# 직접 입력한 손절가가 있으면 우선 사용
# 매수가가 없는 종목은 손절가도 계산하지 않는다.
selected["손절가"] = manual_stop.fillna(auto_stop).where(held)


# ==================================================
# 21. R / 분할 매도
# ==================================================

# R = 매수가 - 손절가
selected["R"] = selected["매수가"] - selected["손절가"]


# 1R 도달 시 30% 매도
selected["1R(30%매도)"] = selected["매수가"] + selected["R"]


# 2R 도달 시 추가 30% 매도
selected["2R(30%매도)"] = selected["매수가"] + selected["R"] * 2


# ==================================================
# 22. 현재 매도 단계
# ==================================================

price = selected["Close"]


sell_conditions = [
    # 매수가를 입력하지 않음
    ~held,
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
    ["미보유", "손절 구간", "추세 이탈", "MA20 이탈", "2R 이상", "1R 이상"],
    default="1R 전",
)


selected["매도신호"] = np.select(
    sell_conditions,
    ["-", "전량 손절", "매도", "주의", "30% 매도 → 남은 40% MA20 추적", "30% 매도"],
    default="보유",
)


# ==================================================
# 23. 매수 / 매도 계획 표
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
# 24. 캔들 차트 스타일
# ==================================================

st.divider()

st.subheader(f"{opt} 종목 차트")


# 상승 = 빨강
# 하락 = 파랑
market_colors = mpf.make_marketcolors(up="red", down="#4A90E2", inherit=True)


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
# 25. 선택된 모든 종목 차트
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
    # 26. 종목 이름
    # ==================================================

    st.markdown(f"### {i}. {name} ({code})")

    # ==================================================
    # 27. 매매 정보 카드
    # ==================================================

    # --------------------------------------------------
    # 첫 번째 줄
    # 현재가 / 매수가 / 손절가 / 1R
    # --------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    show_card(c1, "현재가", won(row["Close"]))

    show_card(c2, "매수가", won(row["매수가"]))

    show_card(c3, "손절가", won(row["손절가"]))

    show_card(c4, "1R(30%매도)", won(row["1R(30%매도)"]))

    # --------------------------------------------------
    # 두 번째 줄
    # 2R / 매수점수 / 현재단계 / 매도신호
    # --------------------------------------------------

    c5, c6, c7, c8 = st.columns(4)

    show_card(c5, "2R(30%매도)", won(row["2R(30%매도)"]))

    show_card(c6, "매수 점수", f"{row['BuyScore']:.1f}점")

    show_card(c7, "현재 단계", row["현재단계"])

    show_card(c8, "매도 신호", row["매도신호"])

    # ==================================================
    # 28. 차트 제목
    # ==================================================

    title = f"{name} | {row['유형']} | 위험도 {row['위험도']}\n{row['해석']}"

    # ==================================================
    # 29. 캔들 차트
    # ==================================================

    # 이동평균선은 전체 데이터로 먼저 계산한 뒤
    # 사용자가 선택한 기간만 화면에 표시한다.
    # 이렇게 해야 60일 차트에서도 MA120 / MA200을 표시할 수 있다.
    plot_df = chart_df.copy()
    for period in (20, 60, 120, 200):
        plot_df[f"MA{period}"] = plot_df["Close"].rolling(period).mean()

    plot_df = plot_df.tail(CHART_DAYS)

    ma_colors = {20: "orange", 60: "green", 120: "purple", 200: "black"}
    ma_addplots = [
        mpf.make_addplot(plot_df[f"MA{period}"], color=ma_colors[period], width=1.2)
        for period in (20, 60, 120, 200)
        if plot_df[f"MA{period}"].notna().any()
    ]

    with PLOT_LOCK:
        fig, axes = mpf.plot(
            # 사이드바에서 선택한 최근 거래일
            plot_df,
            type="candle",
            # 이동평균선
            addplot=ma_addplots,
            # 거래량
            volume=True,
            # 가격 영역을 조금 더 넓게, 거래량 영역은 조금 낮게 표시
            panel_ratios=(4, 1),
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

        # 가격 차트와 거래량 차트 사이의 기본 간격은 그대로 유지한다.
        # 대신 거래량 막대 폭만 아주 조금 줄여 좌우에 여유를 준다.
        if len(axes) >= 3:
            volume_ax = axes[2]
            for bar in volume_ax.patches:
                old_width = bar.get_width()
                new_width = old_width * 0.88
                bar.set_x(bar.get_x() + (old_width - new_width) / 2)
                bar.set_width(new_width)

        # ==================================================
        # 30. 매수가 / 손절가 / 1R / 2R 선
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

        # 매수가를 입력하지 않은 종목은 그릴 가격선이 없다.
        price_lines = [item for item in price_lines if not pd.isna(item[1])]

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
        # 31. 전체 범례
        # ==================================================

        ax.legend(
            handles=(ma_legend + price_legend),
            loc="upper left",
            frameon=True,
            fontsize=8,
        )

        # ==================================================
        # 32. Streamlit에 차트 표시
        # ==================================================

        st.pyplot(fig, width="stretch")

        # 다음 그래프를 위해 닫기
        plt.close(fig)

    # 종목 사이 구분선
    st.divider()


# ==================================================
# 33. 안내
# ==================================================

st.caption(
    "※ 기술적 지표를 이용한 분석 예제입니다. "
    "실제 투자 판단은 사용자가 직접 해야 합니다."
)
