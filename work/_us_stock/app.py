from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from importlib.metadata import PackageNotFoundError, distribution
from zoneinfo import ZoneInfo
from threading import RLock
import gc
import logging
import platform
import time


# macOS/Linux 열린 파일 수 제한 완화
def raise_open_file_limit(target: int = 8192) -> int | None:
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = min(max(soft, target), hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
        return int(new_soft)
    except Exception:
        return None


OPEN_FILE_LIMIT = raise_open_file_limit()

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D

# koreanize-matplotlib은 직접 import하지 않는다.
# Python 3.14에서는 이 패키지 내부의 distutils import가 실패할 수 있으므로
# 아래에서 패키지에 포함된 NanumGothic.ttf 파일만 직접 등록한다.

import mplfinance as mpf
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


# ============================================================
# Streamlit 기본 설정
# ============================================================
st.set_page_config(
    page_title="미국 주식 상승추세 스크리너",
    page_icon="📈",
    layout="wide",
)

pd.set_option("display.max_columns", 50)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

# 작은 정보 카드 스타일
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


# ============================================================
# 경로 / 공통 상수
# ============================================================
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR / "us_stock_data"
STOCK_DIR = BASE_DIR / "stocks"
MARKET_DIR = BASE_DIR / "market"
META_DIR = BASE_DIR / "metadata"
HISTORY_DIR = META_DIR / "universe_history"
SP500_FILE = META_DIR / "sp500_constituents.csv"
OUTPUT_FILE = BASE_DIR / "us_stock_analysis_result.csv"

for folder in [STOCK_DIR, MARKET_DIR, META_DIR, HISTORY_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

SP500_URL = (
    "https://raw.githubusercontent.com/"
    "datasets/s-and-p-500-companies/main/data/constituents.csv"
)
MARKET_TICKERS = ["SPY", "QQQ"]
VALID_TYPES = ["균형형", "강한추세", "저과열", "일반", "급등주의", "과열주의"]
TYPE_OPTIONS = ["전체", *VALID_TYPES]

# 자동 갱신은 마지막 저장일에서 이만큼 겹쳐 다시 받는다.
# 주말/휴장 및 수정 데이터를 안전하게 포함하면서 과도한 재다운로드를 막는다.
REFRESH_OVERLAP_DAYS = 3

# BuyScore(100점) 가중치
SCORE_WEIGHT_MOMENTUM = 45
SCORE_WEIGHT_DISTANCE = 30
SCORE_WEIGHT_STABILITY = 20
SCORE_WEIGHT_LIQUIDITY = 5
# 거리 점수는 MA20 이격이 이 값에 가까울수록 만점, 허용 오차를 벗어나면 0점
IDEAL_MA20_DIST = 0.05
MA20_DIST_TOLERANCE = 0.07

# BuyScore 절대 배점 기준.
# 백분위(순위)는 그날의 모집단 구성에 따라 같은 종목의 점수를 바꾸고,
# 크기 정보를 버린다(6-1M 15%와 154%가 비슷한 점수가 된다).
# 그래서 네 성분 모두 원시 지표를 고정 구간에 대응시킨다.
# 기본값은 S&P 500 전체 분포에서 뽑았다:
#   모멘텀 p90≈35%, 변동성 p10≈1.0%/p90≈3.2%, 거래대금 p10≈$130M/p90≈$1.55B
# 모멘텀 만점 기준은 상위 종목이 뭉개지지 않도록 p90보다 넉넉히 잡는다.
SCORE_MOMENTUM_FULL = 0.60
SCORE_VOL_FULL = 0.010
SCORE_VOL_ZERO = 0.032
SCORE_DOLLAR_MIN = 130_000_000.0
SCORE_DOLLAR_FULL = 1_550_000_000.0

# 캔들차트에 함께 그리는 이동평균과 색상
CHART_MA_PERIODS = (20, 60, 120, 200)
CHART_MA_COLORS = ("orange", "green", "purple", "black")
# 매매 판단에 필요한 구간(MA20 이격·MA60/120 기울기)이 모두 들어오는 길이.
# 종목 스크리닝의 최장 입력인 6-1M 모멘텀도 약 148 거래일이다.
DEFAULT_CHART_DAYS = 120
MIN_CHART_DAYS = 60
MAX_CHART_DAYS = 250

# 유형 분류 임계값
SURGE_DAY_GAIN5 = 0.10
SURGE_RETURN20 = 0.20
OVERHEAT_MA20_DIST = 0.09
# 분류 임계값은 모두 절대 기준이다. 백분위로 두면 그날 분석에 성공한
# 종목 구성에 따라 같은 종목의 등급이 바뀐다.
# 균형형 기본값은 기존 백분위 0.70의 전체 분포 등가값이다
# (모멘텀 p70≈18.3%, 변동성 p70≈2.10%).
BAL_MOMENTUM_MIN = 0.18
BAL_VOL_MAX = 0.021
STRONG_MOMENTUM_MIN = 0.40
STRONG_MAX_MA20_DIST = 0.10
LOW_HEAT_MA20_DIST = 0.03
LOW_HEAT_RETURN20 = 0.08

TYPE_RISK = {
    "강한추세": "높음",
    "급등주의": "높음",
    "과열주의": "높음",
    "균형형": "낮음",
    "저과열": "낮음",
    "일반": "보통",
}
TYPE_EXPLAIN = {
    "강한추세": "추세는 매우 강하지만 이미 많이 오른 종목",
    "급등주의": "최근 급등하여 추격매수에 주의할 종목",
    "과열주의": "상승추세지만 MA20에서 다소 멀어진 종목",
    "균형형": "추세·모멘텀·과열도의 균형이 좋은 종목",
    "저과열": "과열은 적지만 추가 상승 힘을 확인할 종목",
    "일반": "무난한 상승추세 종목",
}

# 사이드바 '보유 종목' 입력란의 초기값.
# 코드로 미리 채워두고 싶을 때만 사용하고, 평소에는 화면에서 입력한다.
# 예: BUY_PRICE = {"AAPL": 220.0}
# 예: BUY_STOP = {"AAPL": 205.0}
BUY_PRICE: dict[str, float] = {}
BUY_STOP: dict[str, float] = {}

# 보유 단계 판정 라벨. 조건 순서와 1:1로 대응한다.
STAGE_LABELS = ["손절 구간", "추세 이탈", "MA20 이탈", "2R 이상", "1R 이상"]
SIGNAL_LABELS = [
    "전량 손절",
    "매도",
    "주의",
    "30% 매도 → 남은 40% MA20 추적",
    "30% 매도",
]
URGENT_SIGNALS = ("전량 손절", "매도")
NOT_HELD_STAGE = "미보유"
NOT_HELD_SIGNAL = "-"

# matplotlib 동시 실행 충돌 방지
PLOT_LOCK = RLock()


def keep_selectbox_options_at_top() -> None:
    """Streamlit 1.56 selectbox의 잘못된 초기 가상 스크롤을 보정한다."""
    st.iframe(
        """
        <script>
        const parentDocument = window.parent.document;

        const resetVirtualDropdown = () => {
            const dropdowns = parentDocument.querySelectorAll(
                'ul[data-testid="stSelectboxVirtualDropdown"] > div'
            );

            dropdowns.forEach((dropdown) => {
                if (dropdown.dataset.topPositionReset === "true") {
                    return;
                }

                dropdown.dataset.topPositionReset = "true";
                window.requestAnimationFrame(() => {
                    dropdown.scrollTop = 0;
                    dropdown.dispatchEvent(
                        new Event("scroll", { bubbles: true })
                    );
                });
            });
        };

        new MutationObserver(resetVirtualDropdown).observe(
            parentDocument.body,
            { childList: true, subtree: true }
        );
        resetVirtualDropdown();
        </script>
        """,
        height=1,  # st.iframe은 0을 허용하지 않는다(사실상 보이지 않는 높이)
    )


keep_selectbox_options_at_top()


# ============================================================
# 한글 폰트
# ============================================================
def get_korean_font() -> str:
    """로컬/Streamlit Cloud 모두에서 사용할 한글 폰트를 등록한다."""

    # 1) 로컬 OS에 기본 한글 폰트가 있으면 우선 사용
    preferred = {
        "Windows": "Malgun Gothic",
        "Darwin": "AppleGothic",
    }.get(platform.system())

    available_fonts = {f.name for f in fm.fontManager.ttflist}
    if preferred and preferred in available_fonts:
        return preferred

    # 2) Streamlit Cloud: koreanize-matplotlib 패키지 안의
    #    NanumGothic.ttf만 직접 등록한다.
    #    패키지 자체를 import하지 않으므로 Python 3.14의 distutils 오류를 피한다.
    try:
        dist = distribution("koreanize-matplotlib")
        font_path = Path(dist.locate_file("koreanize_matplotlib/fonts/NanumGothic.ttf"))
        if font_path.exists():
            fm.fontManager.addfont(str(font_path))
            return fm.FontProperties(fname=str(font_path)).get_name()
    except PackageNotFoundError:
        pass
    except Exception as exc:
        logging.warning("NanumGothic 등록 실패: %s", exc)

    # 3) 시스템에 NanumGothic이 이미 설치되어 있으면 사용
    available_fonts = {f.name for f in fm.fontManager.ttflist}
    if "NanumGothic" in available_fonts:
        return "NanumGothic"

    # 마지막 대체 폰트. 한글이 깨질 수 있으므로 사이드바에 실제 폰트명을 표시한다.
    return "DejaVu Sans"


KOREAN_FONT = get_korean_font()

plt.rcParams["font.family"] = KOREAN_FONT
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.weight"] = "normal"
plt.rcParams["axes.titleweight"] = "normal"


# ============================================================
# 화면 표시 헬퍼
# ============================================================
def show_card(column, title: str, value: str) -> None:
    """종목별 매매 정보를 작은 카드로 표시한다."""
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


def display_dataframe(df: pd.DataFrame, *, height: int | None = None) -> None:
    """DataFrame을 컨테이너 너비에 맞춰 표시한다."""
    kwargs = {
        "width": "stretch",
        "hide_index": True,
    }
    if height is not None:
        kwargs["height"] = height
    st.dataframe(df, **kwargs)


# ============================================================
# 설정값 컨테이너
# ============================================================
@dataclass(frozen=True)
class ScreenParams:
    """스크리닝/점수/분류에 쓰이는 비율 단위 파라미터."""

    min_dollar_volume: float
    max_ret20: float
    max_ma20_dist: float
    max_day_gain5: float
    bal_momentum_min: float
    bal_ret20_max: float
    bal_ma20_min: float
    bal_ma20_max: float
    bal_day_gain5: float
    bal_vol_max: float
    max_stop_loss: float
    # 균형형보다 먼저 적용되는 위험 라벨 기준
    overheat_ma20_dist: float
    surge_return20: float
    surge_day_gain5: float
    # BuyScore 절대 배점 기준
    score_momentum_full: float
    score_vol_full: float
    score_vol_zero: float
    score_dollar_min: float
    score_dollar_full: float
    # 강한추세 판정 기준(절대 모멘텀)
    strong_momentum_min: float
    strong_max_ma20_dist: float
    low_heat_ma20_dist: float
    low_heat_return20: float


@dataclass(frozen=True)
class SidebarConfig:
    """사이드바에서 입력받은 모든 설정."""

    start_date: str
    batch_size: int
    chart_type: str
    min_rows: int
    top_n: int
    chart_n: int
    chart_days: int
    save_output: bool
    screen: ScreenParams
    buy_price: dict[str, float]
    buy_stop: dict[str, float]


# ============================================================
# 데이터 수집 / 검증
# ============================================================
def read_sp500_universe() -> pd.DataFrame:
    """최신 S&P 500 구성 종목을 가져오고 로컬 파일에 저장한다."""
    try:
        sp500 = pd.read_csv(SP500_URL)
    except Exception as exc:
        if SP500_FILE.exists():
            st.warning(
                f"S&P 500 목록 다운로드 실패. 기존 저장 파일을 사용합니다. ({exc})"
            )
            sp500 = pd.read_csv(SP500_FILE)
        else:
            raise RuntimeError("S&P 500 목록 다운로드 실패 + 기존 CSV 없음") from exc

    sp500 = sp500.rename(
        columns={
            "Symbol": "Ticker",
            "Security": "Name",
            "GICS Sector": "Sector",
            "GICS Sub-Industry": "Industry",
        }
    )

    required = ["Ticker", "Name", "Sector", "Industry"]
    missing_cols = [c for c in required if c not in sp500.columns]
    if missing_cols:
        raise ValueError(f"S&P 500 목록에 필요한 컬럼이 없습니다: {missing_cols}")

    # Yahoo Finance 형식: BRK.B -> BRK-B
    sp500["YahooTicker"] = (
        sp500["Ticker"].astype(str).str.replace(".", "-", regex=False)
    )
    sp500 = (
        sp500[["Ticker", "YahooTicker", "Name", "Sector", "Industry"]]
        .sort_values("Ticker")
        .reset_index(drop=True)
    )

    sp500.to_csv(SP500_FILE, index=False)

    today_ny = datetime.now(ZoneInfo("America/New_York")).date()
    snapshot_file = HISTORY_DIR / f"sp500_{today_ny}.csv"
    if not snapshot_file.exists():
        sp500.to_csv(snapshot_file, index=False)

    return sp500


def get_latest_market_info() -> tuple[datetime, str, pd.Timestamp]:
    """SPY를 이용해 최신 완료 거래일을 확인한다."""
    now_ny = datetime.now(ZoneInfo("America/New_York"))

    # 미국 동부시간 18시 전에는 당일 일봉을 사용하지 않음
    if now_ny.hour >= 18:
        download_end = now_ny.date() + timedelta(days=1)
    else:
        download_end = now_ny.date()

    download_end_str = download_end.isoformat()
    spy_start = (now_ny.date() - timedelta(days=14)).isoformat()

    spy_check = yf.download(
        "SPY",
        start=spy_start,
        end=download_end_str,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
        multi_level_index=False,
    )

    if spy_check.empty:
        raise RuntimeError("SPY 데이터를 다운로드하지 못했습니다.")

    latest_market_date = pd.Timestamp(spy_check.index[-1]).normalize()
    return now_ny, download_end_str, latest_market_date


def build_download_targets(sp500: pd.DataFrame) -> list[dict]:
    targets: list[dict] = []

    for ticker in sp500["YahooTicker"]:
        targets.append(
            {
                "Ticker": ticker,
                "Type": "Stock",
                "Path": STOCK_DIR / f"{ticker}.csv",
            }
        )

    for ticker in MARKET_TICKERS:
        targets.append(
            {
                "Ticker": ticker,
                "Type": "Market",
                "Path": MARKET_DIR / f"{ticker}.csv",
            }
        )

    return targets


def find_pending_targets(
    targets: list[dict],
    latest_market_date: pd.Timestamp,
    start_date: str,
) -> tuple[list[dict], int]:
    pending: list[dict] = []
    latest_count = 0
    latest_date_obj = latest_market_date.date()

    for item in targets:
        ticker = item["Ticker"]
        path: Path = item["Path"]
        last_date = None

        if path.exists():
            try:
                dates = pd.read_csv(path, usecols=["Date"])
                if not dates.empty:
                    last_date = pd.to_datetime(dates["Date"]).max().date()
            except Exception:
                # 읽기에 실패하면 전체 재다운로드 대상으로 처리
                last_date = None

        if last_date is not None and last_date >= latest_date_obj:
            latest_count += 1
            continue

        if last_date is None:
            item_start = start_date
        else:
            item_start_ts = pd.Timestamp(last_date) - pd.Timedelta(
                days=REFRESH_OVERLAP_DAYS
            )
            item_start_ts = max(item_start_ts, pd.Timestamp(start_date))
            item_start = item_start_ts.date().isoformat()

        pending.append(
            {
                "Ticker": ticker,
                "Type": item["Type"],
                "Path": path,
                "StartDate": item_start,
            }
        )

    return pending, latest_count


def extract_ticker_frame(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    if data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        level0 = data.columns.get_level_values(0)
        level1 = data.columns.get_level_values(1)

        if ticker in level0:
            df = data[ticker].copy()
        elif ticker in level1:
            df = data.xs(ticker, axis=1, level=1).copy()
        else:
            return None
    else:
        df = data.copy()

    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})

    keep_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df[[col for col in keep_cols if col in df.columns]]

    if "Close" not in df.columns:
        return None

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.dropna(subset=["Close"])
    if df.empty:
        return None

    return df


def update_price_data(
    pending: list[dict],
    download_end: str,
    batch_size: int,
    sleep_seconds: float = 2.0,
) -> list[str]:
    """다운로드 대상 종목을 갱신하고 실패 티커 목록을 반환한다."""
    if not pending:
        return []

    pending_df = pd.DataFrame(pending)
    failed: list[str] = []

    total = len(pending_df)
    completed = 0
    progress = st.progress(0.0, text=f"데이터 갱신 준비 중... 0/{total}")
    status = st.empty()

    for start_date, group in pending_df.groupby("StartDate", sort=False):
        group = group.reset_index(drop=True)

        for i in range(0, len(group), batch_size):
            batch = group.iloc[i : i + batch_size]
            tickers = batch["Ticker"].tolist()
            status.info(
                f"다운로드 중: {tickers[0]} ~ {tickers[-1]} "
                f"({len(tickers)}개, 시작일 {start_date})"
            )

            try:
                data = yf.download(
                    tickers,
                    start=start_date,
                    end=download_end,
                    interval="1d",
                    auto_adjust=True,
                    actions=False,
                    group_by="ticker",
                    progress=False,
                    threads=False,
                    multi_level_index=True,
                )
            except Exception:
                failed.extend(tickers)
                completed += len(batch)
                progress.progress(
                    min(completed / total, 1.0),
                    text=f"데이터 갱신 중... {completed}/{total}",
                )
                continue

            for _, row in batch.iterrows():
                ticker = row["Ticker"]
                path: Path = row["Path"]

                try:
                    df = extract_ticker_frame(data, ticker)
                    if df is None:
                        failed.append(ticker)
                        continue

                    if path.exists():
                        old = pd.read_csv(path, parse_dates=["Date"])
                        df = pd.concat([old, df], ignore_index=True)

                    df = (
                        df.drop_duplicates(subset="Date", keep="last")
                        .sort_values("Date")
                        .reset_index(drop=True)
                    )
                    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
                    df.to_csv(path, index=False)

                except Exception:
                    failed.append(ticker)

            completed += len(batch)
            progress.progress(
                min(completed / total, 1.0),
                text=f"데이터 갱신 중... {completed}/{total}",
            )
            del data
            gc.collect()
            time.sleep(sleep_seconds)

    progress.progress(1.0, text=f"데이터 갱신 완료: {total}/{total}")
    status.empty()
    return sorted(set(failed))


def validate_saved_data(
    targets: list[dict], latest_market_date: pd.Timestamp
) -> pd.DataFrame:
    summary = []
    latest_date_obj = latest_market_date.date()

    for item in targets:
        ticker = item["Ticker"]
        path: Path = item["Path"]
        rows = 0
        last_date = None
        status = "파일없음"

        if path.exists():
            try:
                temp = pd.read_csv(path, usecols=["Date"])
                rows = len(temp)
                if rows > 0:
                    last_date = pd.to_datetime(temp["Date"]).max().date()
                    status = "OK" if last_date >= latest_date_obj else "미완료"
                else:
                    status = "오류"
            except Exception:
                status = "오류"

        summary.append(
            {
                "Ticker": ticker,
                "Type": item["Type"],
                "Rows": rows,
                "LastDate": last_date,
                "Status": status,
            }
        )

    return pd.DataFrame(summary)


def get_local_latest_market_date() -> pd.Timestamp | None:
    """네트워크 확인 실패 시 로컬 SPY CSV의 마지막 날짜를 반환한다."""
    spy_file = MARKET_DIR / "SPY.csv"
    if not spy_file.exists():
        return None

    try:
        dates = pd.read_csv(spy_file, usecols=["Date"])
        if dates.empty:
            return None
        return pd.Timestamp(pd.to_datetime(dates["Date"]).max()).normalize()
    except Exception:
        return None


def save_output_csv(candidates: pd.DataFrame) -> None:
    """분석 결과를 원자적으로 저장한다.

    이 파일은 앱이 다시 읽지 않는 순수 산출물이고, 화면의 다운로드 버튼도
    메모리 데이터를 쓴다. 여러 세션이 같은 경로에 쓰면 마지막 실행 결과만
    남으므로, 임시 파일에 먼저 쓰고 교체해 반쯤 쓰인 파일이 남지 않게 한다.
    """
    temp_file = OUTPUT_FILE.with_name(OUTPUT_FILE.name + ".tmp")
    candidates.to_csv(temp_file, index=False)
    temp_file.replace(OUTPUT_FILE)


def check_required_files() -> list[str]:
    required_files = [
        SP500_FILE,
        MARKET_DIR / "SPY.csv",
        MARKET_DIR / "QQQ.csv",
    ]
    return [str(file) for file in required_files if not file.exists()]


# ============================================================
# 분석 (캐시)
# ============================================================
@st.cache_data(show_spinner=False)
def analyze_market() -> tuple[pd.DataFrame, pd.Timestamp, float, bool | None]:
    market_rows = []

    for ticker in MARKET_TICKERS:
        file = MARKET_DIR / f"{ticker}.csv"
        df = pd.read_csv(file, parse_dates=["Date"])
        df = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
        df["MA200"] = df["Close"].rolling(200).mean()
        df["Momentum6_1M"] = df["Close"].shift(22) / df["Close"].shift(126) - 1

        last = df.iloc[-1]
        # MA200을 계산할 데이터가 부족하면 NaN이 된다. 이때 False로 접으면
        # "데이터 부족"이 "하락장"으로 둔갑하므로 None(판정 불가)으로 남긴다.
        above_ma200 = (
            None if pd.isna(last["MA200"]) else bool(last["Close"] > last["MA200"])
        )
        market_rows.append(
            {
                "Ticker": ticker,
                "Date": last["Date"],
                "Close": last["Close"],
                "MA200": last["MA200"],
                "AboveMA200": above_ma200,
                "Momentum6_1M": last["Momentum6_1M"],
            }
        )

    market = pd.DataFrame(market_rows)
    spy_date = pd.Timestamp(market.loc[market["Ticker"] == "SPY", "Date"].iloc[0])
    spy_mom = float(market.loc[market["Ticker"] == "SPY", "Momentum6_1M"].iloc[0])
    # DataFrame이 bool dtype으로 추론되면 .iloc[0]은 numpy.bool_을 돌려준다.
    # np.True_ is True 가 False이므로 호출부의 동일성 비교가 깨진다.
    # 여기서 순수 파이썬 bool | None 로 정규화한다.
    raw_ok = market.loc[market["Ticker"] == "SPY", "AboveMA200"].iloc[0]
    spy_market_ok = None if pd.isna(raw_ok) else bool(raw_ok)
    return market, spy_date, spy_mom, spy_market_ok


@st.cache_data(show_spinner=False)
def analyze_stocks(
    sp500: pd.DataFrame,
    spy_date: pd.Timestamp,
    spy_mom: float,
    *,
    min_rows: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    errors = []

    total = len(sp500)
    progress = st.progress(0.0, text=f"종목 분석 준비 중... 0/{total}")

    for idx, (_, info) in enumerate(sp500.iterrows(), start=1):
        ticker = info["YahooTicker"]
        file = STOCK_DIR / f"{ticker}.csv"

        if not file.exists():
            errors.append([ticker, "파일없음"])
            progress.progress(idx / total, text=f"종목 분석 중... {idx}/{total}")
            continue

        try:
            df = pd.read_csv(file, parse_dates=["Date"])
            df = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
            df = df[df["Date"] <= spy_date].copy()

            if len(df) < min_rows:
                errors.append([ticker, "데이터부족"])
                progress.progress(idx / total, text=f"종목 분석 중... {idx}/{total}")
                continue

            # 이동평균
            df["MA20"] = df["Close"].rolling(20).mean()
            df["MA60"] = df["Close"].rolling(60).mean()
            df["MA120"] = df["Close"].rolling(120).mean()

            # 수익률 / 모멘텀
            df["Return1D"] = df["Close"].pct_change()
            df["Return20"] = df["Close"] / df["Close"].shift(20) - 1
            df["Momentum6_1M"] = df["Close"].shift(22) / df["Close"].shift(126) - 1

            # 이격 / 유동성 / 변동성
            df["MA20Dist"] = df["Close"] / df["MA20"] - 1
            df["DollarVolume"] = df["Close"] * df["Volume"]
            df["AvgDollar20"] = df["DollarVolume"].rolling(20).mean()
            df["Volatility20"] = df["Return1D"].rolling(20).std()
            df["MaxDayGain5"] = df["Return1D"].rolling(5).max()

            # 이동평균 상승 여부
            df["MA20Up"] = df["MA20"] > df["MA20"].shift(5)
            df["MA60Up"] = df["MA60"] > df["MA60"].shift(5)
            df["MA120Up"] = df["MA120"] > df["MA120"].shift(5)

            last = df.iloc[-1]
            if last["Date"].date() != spy_date.date():
                errors.append([ticker, "최신일불일치"])
                progress.progress(idx / total, text=f"종목 분석 중... {idx}/{total}")
                continue

            trend = bool(
                last["Close"] > last["MA20"] > last["MA60"] > last["MA120"]
                and last["MA20Up"]
                and last["MA60Up"]
                and last["MA120Up"]
            )

            relative_momentum = last["Momentum6_1M"] - spy_mom

            rows.append(
                {
                    "Ticker": ticker,
                    "Name": info["Name"],
                    "Sector": info["Sector"],
                    "Industry": info["Industry"],
                    "Date": last["Date"],
                    "Close": last["Close"],
                    "MA20": last["MA20"],
                    "MA60": last["MA60"],
                    "MA120": last["MA120"],
                    "Momentum6_1M": last["Momentum6_1M"],
                    "RelativeMomentum": relative_momentum,
                    "Return20": last["Return20"],
                    "MA20Dist": last["MA20Dist"],
                    "MaxDayGain5": last["MaxDayGain5"],
                    "AvgDollar20": last["AvgDollar20"],
                    "Volatility20": last["Volatility20"],
                    "Trend": trend,
                }
            )

        except Exception as exc:
            errors.append([ticker, str(exc)[:120]])

        progress.progress(idx / total, text=f"종목 분석 중... {idx}/{total}")

    progress.empty()
    result = pd.DataFrame(rows)
    error_df = pd.DataFrame(errors, columns=["Ticker", "Reason"])
    return result, error_df


# ============================================================
# 스크리닝 / 점수 / 분류 / 매매 계획
# ============================================================
def _apply_screen_flags(result: pd.DataFrame, params: ScreenParams) -> None:
    """개별 필터 통과 여부와 최종 ScreenOK 플래그를 채운다."""
    result["AbsMomentumOK"] = result["Momentum6_1M"] > 0
    result["RelativeMomentumOK"] = result["RelativeMomentum"] > 0
    result["LiquidityOK"] = result["AvgDollar20"] >= params.min_dollar_volume
    result["OverheatOK"] = (
        (result["Return20"] <= params.max_ret20)
        & (result["MA20Dist"] <= params.max_ma20_dist)
        & (result["MaxDayGain5"] <= params.max_day_gain5)
    )
    result["ScreenOK"] = (
        result["Trend"]
        & result["AbsMomentumOK"]
        & result["RelativeMomentumOK"]
        & result["LiquidityOK"]
        & result["OverheatOK"]
    )


def _build_filter_summary(result: pd.DataFrame, params: ScreenParams) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "조건": [
                "MA 상승추세",
                "6-1M > 0",
                "SPY 상대강도 > 0",
                f"20일 평균 거래대금 >= ${params.min_dollar_volume / 1_000_000:,.0f}M",
                "과열 필터 통과",
                "전체 조건 통과",
            ],
            "종목수": [
                int(result["Trend"].sum()),
                int(result["AbsMomentumOK"].sum()),
                int(result["RelativeMomentumOK"].sum()),
                int(result["LiquidityOK"].sum()),
                int(result["OverheatOK"].sum()),
                int(result["ScreenOK"].sum()),
            ],
        }
    )


def _add_universe_percentiles(result: pd.DataFrame) -> None:
    """분석에 성공한 전체 종목 안에서의 백분위를 참고용으로 붙인다.

    분류 임계값과 BuyScore가 모두 절대 기준으로 바뀐 뒤로 이 값들은
    판정에 쓰이지 않는다. 내려받는 CSV에서 "이 종목이 전체 중 몇 등인가"를
    확인할 수 있도록 계산만 남겨둔다. 후보가 아니라 전체 종목을 모집단으로
    삼아야 그날의 필터 설정에 따라 값이 출렁이지 않는다.
    """
    result["MomentumPct"] = result["Momentum6_1M"].rank(pct=True)
    result["LiquidityPct"] = result["AvgDollar20"].rank(pct=True)
    result["VolatilityPct"] = result["Volatility20"].rank(pct=True)


def _score_candidates(candidates: pd.DataFrame, params: ScreenParams) -> None:
    """절대 척도로 BuyScore(100점)를 계산한다.

    네 성분 모두 원시 지표를 고정 구간에 대응시킨다. 가중치는 "최대 배점"을
    뜻하며, 어떤 성분이 실제로 순위를 얼마나 갈랐는지는 후보군의 분산에
    따라 달라진다. 그 차이는 build_score_influence()로 화면에서 확인한다.
    """
    momentum_fit = (
        candidates["Momentum6_1M"] / params.score_momentum_full
    ).clip(0, 1)
    distance_fit = (
        1 - (candidates["MA20Dist"] - IDEAL_MA20_DIST).abs() / MA20_DIST_TOLERANCE
    ).clip(0, 1)
    stability_fit = (
        (params.score_vol_zero - candidates["Volatility20"])
        / (params.score_vol_zero - params.score_vol_full)
    ).clip(0, 1)
    # 거래대금은 종목 간 편차가 100배를 넘으므로 로그 척도로 본다.
    dollar_ratio = (candidates["AvgDollar20"] / params.score_dollar_min).clip(
        lower=1e-9
    )
    liquidity_fit = (
        np.log10(dollar_ratio)
        / np.log10(params.score_dollar_full / params.score_dollar_min)
    ).clip(0, 1)

    candidates["MomentumScore"] = momentum_fit * SCORE_WEIGHT_MOMENTUM
    candidates["DistanceScore"] = distance_fit * SCORE_WEIGHT_DISTANCE
    candidates["StabilityScore"] = stability_fit * SCORE_WEIGHT_STABILITY
    candidates["LiquidityScore"] = liquidity_fit * SCORE_WEIGHT_LIQUIDITY
    candidates["BuyScore"] = (
        candidates["MomentumScore"]
        + candidates["DistanceScore"]
        + candidates["StabilityScore"]
        + candidates["LiquidityScore"]
    )


MARKET_UNKNOWN_LABEL = "판정 불가"


def market_state_label(spy_market_ok: bool | None) -> str:
    """시장 상태를 상승장/방어장/판정 불가 세 갈래로 표현한다."""
    if spy_market_ok is None:
        return MARKET_UNKNOWN_LABEL
    return "상승장" if spy_market_ok else "방어장"


def _classify_types(candidates: pd.DataFrame, params: ScreenParams) -> None:
    """유형(급등주의/과열주의/균형형/강한추세/저과열/일반)과 위험도·설명을 채운다."""
    # 앞 조건이 우선한다.
    balanced = (
        (candidates["Momentum6_1M"] >= params.bal_momentum_min)
        & candidates["Return20"].between(0, params.bal_ret20_max)
        & candidates["MA20Dist"].between(params.bal_ma20_min, params.bal_ma20_max)
        & (candidates["MaxDayGain5"] <= params.bal_day_gain5)
        & (candidates["Volatility20"] <= params.bal_vol_max)
    )
    surge = (candidates["MaxDayGain5"] > params.surge_day_gain5) | (
        candidates["Return20"] > params.surge_return20
    )
    overheated = candidates["MA20Dist"] > params.overheat_ma20_dist
    strong = (candidates["Momentum6_1M"] >= params.strong_momentum_min) & (
        candidates["MA20Dist"] <= params.strong_max_ma20_dist
    )
    low_heat = (candidates["MA20Dist"] < params.low_heat_ma20_dist) & (
        candidates["Return20"] < params.low_heat_return20
    )

    candidates["Type"] = np.select(
        [surge, overheated, balanced, strong, low_heat],
        ["급등주의", "과열주의", "균형형", "강한추세", "저과열"],
        default="일반",
    )
    candidates["Risk"] = candidates["Type"].map(TYPE_RISK)
    candidates["Explain"] = candidates["Type"].map(TYPE_EXPLAIN)


def initial_risk_stop(
    entry: pd.Series, explicit_stop: pd.Series, max_stop_loss: float
) -> pd.Series:
    """R(위험 1단위)의 기준이 되는 진입 시 손절가.

    직접 입력한 손절가가 매수가보다 낮으면 그것을 쓰고, 아니면 최대
    손절폭을 적용한다. 매수가 이상으로 지정한 손절가(이익 확정용)는
    위험의 기준이 될 수 없으므로 제외한다.
    """
    fallback = entry * (1 - max_stop_loss)
    usable = explicit_stop.notna() & (explicit_stop < entry)
    return fallback.where(~usable, explicit_stop)


def add_trade_levels(frame: pd.DataFrame, risk: pd.Series | None = None) -> None:
    """매수가와 위험 1단위(R)로부터 1R/2R 목표가를 채운다.

    risk를 주지 않으면 현재 손절가까지의 거리를 R로 쓴다(신규 진입 기준).
    보유 종목은 손절가가 MA60을 따라 올라가므로 이 방식을 쓰면
    손절가가 매수가를 넘어선 순간 R이 음수가 되고 목표가가 매수가
    아래로 내려간다. 그때는 진입 시 감수한 손실폭을 R로 고정한다.
    """
    frame["R"] = frame["EntryPrice"] - frame["StopPrice"] if risk is None else risk
    frame["Target1R"] = frame["EntryPrice"] + frame["R"]
    frame["Target2R"] = frame["EntryPrice"] + 2 * frame["R"]


def evaluate_position(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """현재가를 손절가·이동평균·목표가와 비교해 단계와 매도 신호를 판정한다.

    실제 매수가가 있는 보유 종목에서만 의미가 있다. 스크리닝 후보는
    정의상 Close > MA20 > MA60 이고 매수가가 없으면 EntryPrice == Close 라
    다섯 조건 중 어느 것도 성립할 수 없다.
    """
    price = frame["Close"]
    conditions = [
        price <= frame["StopPrice"],
        price < frame["MA60"],
        price < frame["MA20"],
        price >= frame["Target2R"],
        price >= frame["Target1R"],
    ]
    return (
        np.select(conditions, STAGE_LABELS, default="1R 전"),
        np.select(conditions, SIGNAL_LABELS, default="보유"),
    )


def _build_trade_columns(
    candidates: pd.DataFrame,
    params: ScreenParams,
    spy_market_ok: bool | None,
    buy_price: dict[str, float],
    buy_stop: dict[str, float],
) -> None:
    """매수가/손절가/목표가와 현재 단계·매도 신호를 채운다."""
    # 보유 매수가가 있으면 우선 사용하고, 없으면 현재가를 신규 매수가로 쓴다.
    candidates["IsHeld"] = candidates["Ticker"].isin(buy_price)
    candidates["EntryPrice"] = (
        candidates["Ticker"].map(buy_price).fillna(candidates["Close"])
    )

    # MA60 또는 최대 허용 손실률 중 더 높은 가격을 자동 손절가로 사용
    auto_stop = np.maximum(
        candidates["MA60"],
        candidates["EntryPrice"] * (1 - params.max_stop_loss),
    )
    candidates["StopPrice"] = (
        candidates["Ticker"]
        .map(buy_stop)
        .fillna(pd.Series(auto_stop, index=candidates.index))
    )

    # 손절가는 MA60을 따라 올라간다. 보유 종목은 그 손절가가 매수가를
    # 넘어선 순간(수익 구간의 정상적인 상태) R이 음수가 되어 목표가가
    # 매수가 아래로 내려가므로, 진입 시 감수한 손실폭을 R로 고정한다.
    # 미보유(신규 진입)는 EntryPrice == Close 이고 후보는 Close > MA60 이라
    # 손절가까지의 거리가 그대로 양수 R이 된다.
    initial_stop = initial_risk_stop(
        candidates["EntryPrice"],
        candidates["Ticker"].map(buy_stop),
        params.max_stop_loss,
    )
    add_trade_levels(
        candidates,
        pd.Series(
            np.where(
                candidates["IsHeld"],
                candidates["EntryPrice"] - initial_stop,
                candidates["EntryPrice"] - candidates["StopPrice"],
            ),
            index=candidates.index,
        ),
    )

    # 미보유 종목은 판정 대상이 아니다. 예전에는 후보 전체를 판정했지만
    # 후보는 위 docstring의 이유로 항상 "1R 전"/"보유"만 나왔다.
    stage, signal = evaluate_position(candidates)
    candidates["CurrentStage"] = np.where(
        candidates["IsHeld"], stage, NOT_HELD_STAGE
    )
    candidates["SellSignal"] = np.where(
        candidates["IsHeld"], signal, NOT_HELD_SIGNAL
    )
    if spy_market_ok is None:
        candidates["BuyAllowed"] = MARKET_UNKNOWN_LABEL
    else:
        candidates["BuyAllowed"] = "허용" if spy_market_ok else "중단"


def _add_display_units(candidates: pd.DataFrame) -> None:
    """화면 표시용 % / $M 단위 컬럼을 추가한다."""
    candidates["Momentum6_1M_%"] = candidates["Momentum6_1M"] * 100
    candidates["RelativeMomentum_%"] = candidates["RelativeMomentum"] * 100
    candidates["Return20_%"] = candidates["Return20"] * 100
    candidates["MA20Dist_%"] = candidates["MA20Dist"] * 100
    candidates["Volatility20_%"] = candidates["Volatility20"] * 100
    candidates["AvgDollar20_M"] = candidates["AvgDollar20"] / 1_000_000


def apply_screen_and_score(
    result: pd.DataFrame,
    params: ScreenParams,
    *,
    spy_market_ok: bool | None,
    buy_price: dict[str, float],
    buy_stop: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """스크리닝 → 점수 → 유형 분류 → 매매 계획까지 수행한다."""
    result = result.copy()

    _add_universe_percentiles(result)
    _apply_screen_flags(result, params)
    filter_summary = _build_filter_summary(result, params)

    candidates = result[result["ScreenOK"]].copy()
    if candidates.empty:
        return candidates, filter_summary

    _score_candidates(candidates, params)
    _classify_types(candidates, params)
    _build_trade_columns(candidates, params, spy_market_ok, buy_price, buy_stop)

    candidates = candidates.sort_values("BuyScore", ascending=False).reset_index(
        drop=True
    )
    candidates["Rank"] = np.arange(1, len(candidates) + 1)

    _add_display_units(candidates)

    return candidates, filter_summary


def build_trade_plan(candidates: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()

    trade_plan = (
        candidates[
            [
                "Rank",
                "Ticker",
                "Name",
                "Type",
                "Risk",
                "BuyScore",
                "Close",
                "MA20",
                "MA60",
                "EntryPrice",
                "StopPrice",
                "Target1R",
                "Target2R",
                "CurrentStage",
                "SellSignal",
            ]
        ]
        .head(top_n)
        .copy()
    )

    trade_plan = trade_plan.rename(
        columns={
            "Type": "유형",
            "Risk": "위험도",
            "Close": "현재가",
            "EntryPrice": "매수가",
            "StopPrice": "손절가",
            "Target1R": "1R(30%매도)",
            "Target2R": "2R(30%매도)",
            "CurrentStage": "현재단계",
            "SellSignal": "매도신호",
        }
    )

    price_cols = [
        "현재가",
        "MA20",
        "MA60",
        "매수가",
        "손절가",
        "1R(30%매도)",
        "2R(30%매도)",
    ]
    trade_plan[price_cols] = trade_plan[price_cols].round(2)
    trade_plan["BuyScore"] = trade_plan["BuyScore"].round(2)
    return trade_plan


SCORE_COMPONENTS = {
    "모멘텀": ("MomentumScore", SCORE_WEIGHT_MOMENTUM),
    "MA20 이격": ("DistanceScore", SCORE_WEIGHT_DISTANCE),
    "안정성": ("StabilityScore", SCORE_WEIGHT_STABILITY),
    "유동성": ("LiquidityScore", SCORE_WEIGHT_LIQUIDITY),
}
INFLUENCE_ALERT_GAP = 10.0


def build_score_influence(candidates: pd.DataFrame) -> pd.DataFrame:
    """각 성분이 실제로 순위를 얼마나 갈랐는지 계산한다.

    배점은 "최대 몇 점까지 딸 수 있는가"일 뿐이고, 순위를 실제로 가르는
    힘은 후보들 사이에서 그 성분이 얼마나 벌어졌는가(표준편차)로 정해진다.
    스크리닝을 통과한 축은 이미 값이 비슷해져 있으므로, 많이 거른 축일수록
    배점에 비해 실제 영향력이 작아진다. 둘이 크게 벌어지면 그 성분의 배점
    기준이 지금 후보군과 맞지 않는다는 신호다.
    """
    if len(candidates) < 2:
        return pd.DataFrame()

    spreads = {
        name: float(candidates[col].std())
        for name, (col, _) in SCORE_COMPONENTS.items()
    }
    total_spread = sum(spreads.values())
    if not np.isfinite(total_spread) or total_spread <= 0:
        return pd.DataFrame()

    total_weight = sum(weight for _, weight in SCORE_COMPONENTS.values())
    rows = []
    for name, (col, weight) in SCORE_COMPONENTS.items():
        declared = weight / total_weight * 100
        actual = spreads[name] / total_spread * 100
        rows.append(
            {
                "성분": name,
                "배점": weight,
                "선언 비중(%)": declared,
                "실제 기여(%)": actual,
                "차이(%p)": actual - declared,
                "평균 점수": float(candidates[col].mean()),
                "점수 폭": float(candidates[col].max() - candidates[col].min()),
            }
        )
    return pd.DataFrame(rows).round(1)


def build_holdings_status(
    buy_price: dict[str, float],
    buy_stop: dict[str, float],
    params: ScreenParams,
    spy_date: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    """보유 종목을 스크리닝 통과 여부와 무관하게 평가한다.

    후보(ScreenOK)는 정의상 MA 위에 있으므로 후보 안에서만 판정하면
    손절·추세 이탈 신호가 절대 뜨지 않는다. 정작 신호가 필요한 순간은
    보유 종목이 추세를 잃고 후보에서 빠질 때이므로, 여기서는 원본 CSV를
    직접 읽어 지표를 다시 계산한다.

    반환: (평가 결과, 가격 데이터가 없어 평가하지 못한 티커 목록)
    """
    rows: list[dict] = []
    missing: list[str] = []

    for ticker, entry in sorted(buy_price.items()):
        file = STOCK_DIR / f"{ticker}.csv"
        if not file.exists():
            missing.append(ticker)
            continue

        try:
            df = pd.read_csv(file, parse_dates=["Date"])
            df = df.sort_values("Date").drop_duplicates("Date")
            df = df[df["Date"] <= spy_date]
            if df.empty:
                missing.append(ticker)
                continue

            close = df["Close"]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]

            # 손절가는 직접 입력값이 우선, 없으면 MA60까지 따라 올린다.
            explicit_stop = buy_stop.get(ticker)
            floor_stop = entry * (1 - params.max_stop_loss)
            if explicit_stop is not None:
                stop_price = float(explicit_stop)
            elif pd.notna(ma60):
                stop_price = max(float(ma60), floor_stop)
            else:
                stop_price = floor_stop

            rows.append(
                {
                    "Ticker": ticker,
                    "Date": df["Date"].iloc[-1],
                    "Close": float(close.iloc[-1]),
                    "MA20": ma20,
                    "MA60": ma60,
                    "EntryPrice": float(entry),
                    "ExplicitStop": explicit_stop,
                    "StopPrice": stop_price,
                }
            )
        except Exception:
            missing.append(ticker)

    if not rows:
        return pd.DataFrame(), missing

    held = pd.DataFrame(rows)
    # 본 분석은 최신일이 어긋난 종목을 "최신일불일치"로 제외하지만, 보유 종목은
    # 제외할 수 없다. 대신 오래된 가격으로 낸 신호임을 반드시 드러낸다.
    held["IsStale"] = held["Date"].dt.normalize() != pd.Timestamp(spy_date).normalize()
    held["ExplicitStop"] = pd.to_numeric(held["ExplicitStop"], errors="coerce")
    initial_stop = initial_risk_stop(
        held["EntryPrice"], held["ExplicitStop"], params.max_stop_loss
    )
    add_trade_levels(held, held["EntryPrice"] - initial_stop)
    stage, signal = evaluate_position(held)
    held["CurrentStage"] = stage
    held["SellSignal"] = signal
    held["Return_%"] = (held["Close"] / held["EntryPrice"] - 1) * 100
    return held, missing


# ============================================================
# 차트
# ============================================================
def make_candle_chart(
    ticker: str,
    candidates: pd.DataFrame,
    spy_date: pd.Timestamp,
    chart_days: int = DEFAULT_CHART_DAYS,
):
    """MA20/60/120/200과 매수가·손절가·1R·2R을 포함한 캔들차트.

    이동평균은 전체 이력으로 먼저 계산한 뒤 표시 구간만 잘라낸다.
    mplfinance의 mav= 옵션은 넘겨준 데이터로만 평균을 내기 때문에,
    잘라낸 뒤 계산하면 화면 왼쪽에서 긴 이동평균선이 사라진다.
    """
    history = pd.read_csv(STOCK_DIR / f"{ticker}.csv", parse_dates=["Date"])
    history = (
        history[history["Date"] <= spy_date]
        .sort_values("Date")
        .drop_duplicates("Date")
        .set_index("Date")
    )

    if history.empty:
        raise ValueError("차트 데이터가 없습니다.")

    # 전체 이력 길이가 기간보다 짧은 이동평균은 그리지 않는다.
    available_ma = [
        (period, color)
        for period, color in zip(CHART_MA_PERIODS, CHART_MA_COLORS)
        if len(history) >= period
    ]
    ma_frame = pd.DataFrame(
        {f"MA{period}": history["Close"].rolling(period).mean() for period, _ in available_ma},
        index=history.index,
    )

    df = history.tail(chart_days)
    ma_frame = ma_frame.tail(chart_days)

    info = candidates.loc[candidates["Ticker"] == ticker].iloc[0]

    # 미국식 캔들 색상 대신 KOSPI 버전과 동일하게 상승=빨강, 하락=파랑
    market_colors = mpf.make_marketcolors(up="red", down="blue", inherit=True)

    mpf_style = mpf.make_mpf_style(
        base_mpf_style="yahoo",
        marketcolors=market_colors,
        rc={
            "font.family": KOREAN_FONT,
            "font.weight": "normal",
            "axes.titleweight": "normal",
            "axes.unicode_minus": False,
        },
    )

    with PLOT_LOCK:
        ma_plots = [
            mpf.make_addplot(ma_frame[f"MA{period}"], color=color, width=1.0)
            for period, color in available_ma
        ]

        fig, axes = mpf.plot(
            df[["Open", "High", "Low", "Close", "Volume"]],
            type="candle",
            addplot=ma_plots,
            volume=True,
            style=mpf_style,
            figsize=(13, 7),
            returnfig=True,
        )

        ax = axes[0]
        title = (
            f"{info['Name']} ({ticker}) | {info['Type']} | 위험도 {info['Risk']} | "
            f"BuyScore {info['BuyScore']:.1f}\n{info['Explain']}"
        )
        ax.set_title(title, fontsize=11, pad=8, fontfamily=KOREAN_FONT)

        # 오른쪽에 매매 가격 라벨을 표시할 공간 확보
        fig.subplots_adjust(right=0.78)

        ma_legend = [
            Line2D([0], [0], color=color, lw=2, label=f"MA{period}")
            for period, color in available_ma
        ]

        price_lines = [
            ("매수가", info["EntryPrice"], "#1565C0", "-"),
            ("손절가", info["StopPrice"], "#D32F2F", "--"),
            ("1R(30%매도)", info["Target1R"], "#00838F", "-."),
            ("2R(30%매도)", info["Target2R"], "#C2185B", ":"),
        ]

        price_legend = []
        for label, value, color, line_style in price_lines:
            if pd.isna(value):
                continue

            ax.axhline(
                y=float(value),
                color=color,
                linestyle=line_style,
                linewidth=1.5,
            )
            ax.text(
                1.01,
                float(value),
                f"{label} ${float(value):,.2f}",
                transform=ax.get_yaxis_transform(),
                fontsize=9,
                fontfamily=KOREAN_FONT,
                color=color,
                va="center",
                ha="left",
                clip_on=False,
                bbox={
                    "facecolor": "white",
                    "edgecolor": color,
                    "alpha": 0.85,
                    "pad": 2,
                },
            )
            price_legend.append(
                Line2D(
                    [0],
                    [0],
                    color=color,
                    linestyle=line_style,
                    lw=1.5,
                    label=f"{label} ${float(value):,.2f}",
                )
            )

        ax.legend(
            handles=ma_legend + price_legend,
            loc="upper left",
            frameon=True,
            prop={"family": KOREAN_FONT, "size": 8},
        )

    return fig


# ============================================================
# 사이드바
# ============================================================
def init_session_state() -> None:
    for key, default in {
        "auto_update_done": False,
        "auto_update_info": None,
        "auto_update_error": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default


def _parse_holdings(
    edited: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """보유 종목 편집기의 내용을 매수가/손절가 딕셔너리로 변환한다.

    무시한 입력은 조용히 버리지 않고 사유를 함께 돌려준다. 티커만 적고
    매수가를 빠뜨린 사용자가 자기 종목이 왜 안 보이는지 알 수 있어야 한다.

    반환: (매수가, 손절가, 무시한 입력 사유 목록)
    """
    buy_price: dict[str, float] = {}
    buy_stop: dict[str, float] = {}
    issues: list[str] = []

    for _, row in edited.iterrows():
        raw = row.get("티커")
        ticker = "" if raw is None or pd.isna(raw) else str(raw).strip().upper()
        # 저장된 CSV는 Yahoo 표기(BRK-B)를 쓰므로 입력도 맞춰 정규화한다.
        ticker = ticker.replace(".", "-")

        price = row.get("매수가")
        has_price = pd.notna(price) and float(price) > 0

        if not ticker:
            if has_price:
                issues.append("티커 없이 가격만 있는 행을 건너뛰었습니다.")
            continue

        if not has_price:
            issues.append(f"{ticker}: 매수가가 없어 판정에서 제외했습니다.")
            continue

        if ticker in buy_price:
            issues.append(f"{ticker}: 중복 입력이라 마지막 행의 값을 사용합니다.")
        buy_price[ticker] = float(price)

        stop = row.get("손절가")
        if pd.notna(stop) and float(stop) > 0:
            buy_stop[ticker] = float(stop)
        else:
            buy_stop.pop(ticker, None)

    return buy_price, buy_stop, issues


def render_holdings_editor() -> tuple[dict[str, float], dict[str, float]]:
    """사이드바에서 보유 종목의 매수가·손절가를 입력받는다."""
    # 빈 표에서도 편집기가 열 타입을 올바로 잡도록 dtype을 명시한다.
    tickers = list(BUY_PRICE)
    seed = pd.DataFrame(
        {
            "티커": pd.Series(tickers, dtype="string"),
            "매수가": pd.Series(
                [BUY_PRICE[t] for t in tickers], dtype="float64"
            ),
            "손절가": pd.Series(
                [BUY_STOP.get(t) for t in tickers], dtype="float64"
            ),
        }
    )

    edited = st.data_editor(
        seed,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "티커": st.column_config.TextColumn(
                "티커", help="예: AAPL, BRK-B", max_chars=10
            ),
            "매수가": st.column_config.NumberColumn(
                "매수가", min_value=0.0, format="%.2f"
            ),
            "손절가": st.column_config.NumberColumn(
                "손절가(선택)",
                help="비워두면 MA60과 최대 손절폭 중 높은 값을 자동 사용합니다.",
                min_value=0.0,
                format="%.2f",
            ),
        },
        key="holdings_editor",
    )
    st.caption(
        "매수가를 입력한 종목만 '현재 단계'와 '매도 신호'를 판정합니다. "
        "빈 행은 무시됩니다."
    )

    buy_price, buy_stop, issues = _parse_holdings(edited)
    if issues:
        st.warning("\n".join(f"- {item}" for item in dict.fromkeys(issues)))
    return buy_price, buy_stop


def render_sidebar() -> SidebarConfig:
    with st.sidebar:
        st.header("분석 설정")

        with st.expander("자동 데이터 갱신 설정", expanded=False):
            start_date = st.text_input("최초 다운로드 시작일", "2015-01-01")
            st.caption(
                f"기존 데이터는 마지막 저장일 기준 최근 {REFRESH_OVERLAP_DAYS}일만 "
                "겹쳐 자동 갱신합니다."
            )
            batch_size = st.number_input(
                "다운로드 배치 크기",
                min_value=5,
                max_value=100,
                value=20,
                step=5,
            )
            st.caption(
                "앱 세션 시작 시 최신 거래일을 한 번 확인합니다. "
                "이미 최신인 종목은 다운로드하지 않습니다."
            )

        # 필요할 때만 네트워크 갱신을 다시 수행
        if st.button("🔄 지금 강제 갱신", type="primary", width="stretch"):
            st.session_state.auto_update_done = False
            st.session_state.auto_update_info = None
            st.session_state.auto_update_error = None
            st.cache_data.clear()
            st.rerun()

        chart_type = st.selectbox("종목 유형", TYPE_OPTIONS, index=0, key="chart_type")

        with st.expander("보유 종목", expanded=False):
            buy_price, buy_stop = render_holdings_editor()

        with st.expander("기본 필터", expanded=False):
            min_rows = st.number_input("최소 데이터 행 수", 120, 1000, 130, 10)
            # 기본값 $20M은 S&P 500 503종목이 전부 통과해 필터 구실을 못 했다.
            # 전체 분포는 p10≈$130M, 중앙값≈$346M이다.
            min_dollar_volume_m = st.number_input(
                "20일 평균 거래대금 최소($M)",
                1.0,
                5000.0,
                100.0,
                10.0,
                help="S&P 500 전체 분포: p10≈$130M, 중앙값≈$346M, p90≈$1,555M.",
            )
            max_ret20_pct = st.number_input("20일 수익률 상한(%)", 1.0, 100.0, 25.0, 1.0)
            max_ma20_dist_pct = st.number_input(
                "MA20 이격 상한(%)", 1.0, 50.0, 12.0, 1.0
            )
            max_day_gain5_pct = st.number_input(
                "최근 5일 최대 일간상승률 상한(%)", 1.0, 50.0, 15.0, 1.0
            )

        with st.expander("유형 분류 기준", expanded=False):
            st.caption(
                "적용 순서: 급등주의 → 과열주의 → 균형형 → 강한추세 → 저과열. "
                "앞 조건이 먼저 적용되므로, 급등주의·과열주의 기준을 넘어선 "
                "종목은 균형형 조건을 만족해도 균형형이 되지 않습니다."
            )
            overheat_ma20_dist_pct = st.number_input(
                "과열주의: MA20 이격 초과(%)",
                1.0,
                50.0,
                OVERHEAT_MA20_DIST * 100,
                0.5,
            )
            surge_return20_pct = st.number_input(
                "급등주의: 20일 수익률 초과(%)",
                1.0,
                100.0,
                SURGE_RETURN20 * 100,
                1.0,
            )
            surge_day_gain5_pct = st.number_input(
                "급등주의: 5일 최대 일간상승률 초과(%)",
                1.0,
                50.0,
                SURGE_DAY_GAIN5 * 100,
                1.0,
            )

            strong_momentum_min_pct = st.number_input(
                "강한추세: 6-1M 모멘텀 이상(%)",
                1.0,
                200.0,
                STRONG_MOMENTUM_MIN * 100,
                5.0,
                help="백분위가 아닌 절대 기준이라 후보 수가 달라져도 "
                "같은 종목은 같은 등급을 받습니다.",
            )

            strong_max_ma20_dist_pct = st.number_input(
                "강한추세: MA20 이격 이하(%)",
                1.0,
                50.0,
                STRONG_MAX_MA20_DIST * 100,
                0.5,
                help="모멘텀이 강해도 이 값을 넘어서면 강한추세로 보지 않습니다.",
            )
            low_heat_ma20_dist_pct = st.number_input(
                "저과열: MA20 이격 미만(%)",
                0.1,
                30.0,
                LOW_HEAT_MA20_DIST * 100,
                0.5,
            )
            low_heat_return20_pct = st.number_input(
                "저과열: 20일 수익률 미만(%)",
                0.1,
                50.0,
                LOW_HEAT_RETURN20 * 100,
                1.0,
            )

            # 기본 필터가 분류보다 먼저 적용되므로, 필터가 분류 기준보다
            # 조이면 해당 유형은 아예 나올 수 없다.
            # 과열주의: MA20Dist > 기준 이어야 하는데 필터는 <= 상한 을 요구한다.
            # 급등주의: 두 조건의 OR이므로 둘 다 막혀야 도달 불가다.
            unreachable: list[str] = []
            if max_ma20_dist_pct <= overheat_ma20_dist_pct:
                unreachable.append(
                    f"과열주의 — 기본 필터의 MA20 이격 상한"
                    f"({max_ma20_dist_pct:.1f}%)이 과열주의 기준"
                    f"({overheat_ma20_dist_pct:.1f}%) 이하입니다."
                )
            if (
                max_ret20_pct <= surge_return20_pct
                and max_day_gain5_pct <= surge_day_gain5_pct
            ):
                unreachable.append(
                    f"급등주의 — 기본 필터의 20일 수익률 상한"
                    f"({max_ret20_pct:.1f}%)과 5일 최대 상승률 상한"
                    f"({max_day_gain5_pct:.1f}%)이 각각 급등주의 기준"
                    f"({surge_return20_pct:.1f}%, {surge_day_gain5_pct:.1f}%) "
                    "이하입니다."
                )
            if unreachable:
                st.warning(
                    "기본 필터가 먼저 적용되어 아래 유형은 종목이 나올 수 "
                    "없습니다:\n" + "\n".join(f"- {item}" for item in unreachable)
                )

        with st.expander("균형형 분류 기준", expanded=False):
            bal_momentum_min_pct = st.number_input(
                "균형형: 6-1M 모멘텀 이상(%)",
                0.0,
                200.0,
                BAL_MOMENTUM_MIN * 100,
                1.0,
                help="전체 분포 참고: p60≈13%, p70≈18%, p80≈25%.",
            )
            bal_ret20_max_pct = st.number_input(
                "균형형 20일 수익률 상한(%)", 0.0, 100.0, 15.0, 1.0
            )
            bal_ma20_min_pct = st.number_input(
                "균형형 MA20 이격 최소(%)", 0.0, 30.0, 2.0, 0.5
            )
            bal_ma20_max_pct = st.number_input(
                "균형형 MA20 이격 최대(%)", 0.0, 30.0, 8.0, 0.5
            )
            bal_day_gain5_pct = st.number_input(
                "균형형 최근 5일 최대 상승률(%)", 0.0, 50.0, 10.0, 1.0
            )
            bal_vol_max_pct = st.number_input(
                "균형형: 20일 변동성 이하(%)",
                0.1,
                20.0,
                BAL_VOL_MAX * 100,
                0.1,
                help="전체 분포 참고: p60≈1.85%, p70≈2.10%, p80≈2.44%.",
            )

            # 과열·급등 기준이 먼저 적용되므로, 균형형 창이 그 값을 넘어서면
            # 넘어선 구간은 실제로 균형형이 될 수 없다.
            # MA20 이격 '최소'에는 대응하는 상한이 없어 검사 대상이 아니다.
            capped: list[str] = []
            if bal_ma20_max_pct > overheat_ma20_dist_pct:
                capped.append(
                    f"MA20 이격 최대 {bal_ma20_max_pct:.1f}% → "
                    f"{overheat_ma20_dist_pct:.1f}%(과열주의)"
                )
            if bal_ret20_max_pct > surge_return20_pct:
                capped.append(
                    f"20일 수익률 상한 {bal_ret20_max_pct:.1f}% → "
                    f"{surge_return20_pct:.1f}%(급등주의)"
                )
            if bal_day_gain5_pct > surge_day_gain5_pct:
                capped.append(
                    f"5일 최대 상승률 {bal_day_gain5_pct:.1f}% → "
                    f"{surge_day_gain5_pct:.1f}%(급등주의)"
                )
            if capped:
                st.warning(
                    "과열·급등 기준이 먼저 적용되어 아래 값은 실제로 "
                    "더 낮게 동작합니다:\n"
                    + "\n".join(f"- {item}" for item in capped)
                )

        with st.expander("BuyScore 배점 기준", expanded=False):
            st.caption(
                f"각 성분의 만점/0점 경계입니다. 배점은 모멘텀 "
                f"{SCORE_WEIGHT_MOMENTUM} · 이격 {SCORE_WEIGHT_DISTANCE} · "
                f"안정성 {SCORE_WEIGHT_STABILITY} · 유동성 "
                f"{SCORE_WEIGHT_LIQUIDITY}점이며, 이 경계 안에서 비례 배분됩니다. "
                "기본값은 S&P 500 전체 분포에서 뽑았습니다."
            )
            score_momentum_full_pct = st.number_input(
                "모멘텀 만점 기준: 6-1M(%)",
                5.0,
                300.0,
                SCORE_MOMENTUM_FULL * 100,
                5.0,
                help="이 값 이상이면 모멘텀 만점. 너무 낮으면 상위 종목이 모두 "
                "만점으로 뭉개져 변별력을 잃습니다.",
            )
            score_vol_full_pct = st.number_input(
                "안정성 만점 기준: 20일 변동성(%)",
                0.1,
                10.0,
                SCORE_VOL_FULL * 100,
                0.1,
                help="이 값 이하면 안정성 만점.",
            )
            score_vol_zero_pct = st.number_input(
                "안정성 0점 기준: 20일 변동성(%)",
                0.2,
                20.0,
                SCORE_VOL_ZERO * 100,
                0.1,
                help="이 값 이상이면 안정성 0점.",
            )
            score_dollar_min_m = st.number_input(
                "유동성 0점 기준($M)", 1.0, 5000.0, SCORE_DOLLAR_MIN / 1e6, 10.0
            )
            score_dollar_full_m = st.number_input(
                "유동성 만점 기준($M)",
                10.0,
                50000.0,
                SCORE_DOLLAR_FULL / 1e6,
                50.0,
                help="거래대금은 편차가 커서 로그 척도로 배분합니다.",
            )

            # 경계가 뒤집히면 0으로 나누게 되므로 기본값으로 되돌린다.
            if score_vol_zero_pct <= score_vol_full_pct:
                st.warning(
                    "안정성 0점 기준은 만점 기준보다 커야 합니다. "
                    "이번 계산은 기본값을 사용합니다."
                )
                score_vol_full_pct = SCORE_VOL_FULL * 100
                score_vol_zero_pct = SCORE_VOL_ZERO * 100
            if score_dollar_full_m <= score_dollar_min_m:
                st.warning(
                    "유동성 만점 기준은 0점 기준보다 커야 합니다. "
                    "이번 계산은 기본값을 사용합니다."
                )
                score_dollar_min_m = SCORE_DOLLAR_MIN / 1e6
                score_dollar_full_m = SCORE_DOLLAR_FULL / 1e6

        with st.expander("매매/출력 설정", expanded=False):
            max_stop_loss_pct = st.number_input("최대 손절폭(%)", 1.0, 30.0, 8.0, 0.5)
            top_n = st.number_input("추천 종목 수", 5, 100, 20, 5)
            chart_n = st.number_input("차트 개수", 1, 30, 10, 1)
            chart_days = st.slider(
                "차트 표시 거래일",
                MIN_CHART_DAYS,
                MAX_CHART_DAYS,
                DEFAULT_CHART_DAYS,
                10,
            )
            save_output = st.checkbox(
                "분석 결과를 파일로 저장",
                value=True,
                help=f"{OUTPUT_FILE.name}에 매 실행마다 덮어씁니다. "
                "여러 사람이 함께 쓰는 배포 환경에서는 서로의 결과를 지우므로 "
                "끄는 편이 좋습니다. 꺼도 화면의 다운로드 버튼은 그대로 "
                "동작합니다.",
            )

        if st.button("분석 캐시 새로고침", width="stretch"):
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.caption(f"OS: {platform.system()} | matplotlib font: {KOREAN_FONT}")
        if OPEN_FILE_LIMIT is not None:
            st.caption(f"열린 파일 제한(soft): {OPEN_FILE_LIMIT:,}")
        st.caption(f"데이터 폴더: {BASE_DIR.resolve()}")

    screen = ScreenParams(
        min_dollar_volume=min_dollar_volume_m * 1_000_000,
        max_ret20=max_ret20_pct / 100,
        max_ma20_dist=max_ma20_dist_pct / 100,
        max_day_gain5=max_day_gain5_pct / 100,
        bal_momentum_min=bal_momentum_min_pct / 100,
        bal_ret20_max=bal_ret20_max_pct / 100,
        bal_ma20_min=bal_ma20_min_pct / 100,
        bal_ma20_max=bal_ma20_max_pct / 100,
        bal_day_gain5=bal_day_gain5_pct / 100,
        bal_vol_max=bal_vol_max_pct / 100,
        max_stop_loss=max_stop_loss_pct / 100,
        overheat_ma20_dist=overheat_ma20_dist_pct / 100,
        surge_return20=surge_return20_pct / 100,
        surge_day_gain5=surge_day_gain5_pct / 100,
        score_momentum_full=score_momentum_full_pct / 100,
        score_vol_full=score_vol_full_pct / 100,
        score_vol_zero=score_vol_zero_pct / 100,
        score_dollar_min=score_dollar_min_m * 1_000_000,
        score_dollar_full=score_dollar_full_m * 1_000_000,
        strong_momentum_min=strong_momentum_min_pct / 100,
        strong_max_ma20_dist=strong_max_ma20_dist_pct / 100,
        low_heat_ma20_dist=low_heat_ma20_dist_pct / 100,
        low_heat_return20=low_heat_return20_pct / 100,
    )
    return SidebarConfig(
        start_date=start_date,
        batch_size=int(batch_size),
        chart_type=chart_type,
        min_rows=int(min_rows),
        top_n=int(top_n),
        chart_n=int(chart_n),
        chart_days=int(chart_days),
        save_output=bool(save_output),
        screen=screen,
        buy_price=buy_price,
        buy_stop=buy_stop,
    )


# ============================================================
# 1. 앱 시작 시 데이터 자동 확인 / 자동 갱신
# ============================================================
def run_auto_update(cfg: SidebarConfig) -> None:
    if st.session_state.auto_update_done:
        return

    try:
        with st.spinner("S&P 500 목록과 최신 미국 거래일을 확인하는 중입니다..."):
            auto_sp500 = read_sp500_universe()
            now_ny, download_end, latest_market_date = get_latest_market_info()
            targets = build_download_targets(auto_sp500)
            pending, latest_count = find_pending_targets(
                targets,
                latest_market_date,
                cfg.start_date,
            )

        pending_count = len(pending)

        if pending:
            st.info(
                f"최신 완료 거래일 {latest_market_date.date()} 기준으로 "
                f"{pending_count:,}개 종목을 자동 갱신합니다."
            )
            failed = update_price_data(pending, download_end, cfg.batch_size)
        else:
            failed = []

        summary = validate_saved_data(targets, latest_market_date)
        problem_count = int((summary["Status"] != "OK").sum())

        st.session_state.auto_update_info = {
            "mode": "online",
            "checked_at_ny": now_ny.strftime("%Y-%m-%d %H:%M"),
            "latest_market_date": str(latest_market_date.date()),
            "sp500_count": len(auto_sp500),
            "target_count": len(targets),
            "latest_count_before": latest_count,
            "updated_count": pending_count,
            "failed": failed,
            "problem_count": problem_count,
            "summary": summary,
        }
        st.session_state.auto_update_error = None

        # 방금 변경된 CSV를 분석 캐시가 즉시 다시 읽도록 비운다.
        # 갱신 대상이 없었으면 디스크가 그대로이므로 캐시를 유지한다.
        if pending:
            st.cache_data.clear()

    except Exception as exc:
        # 네트워크 문제라도 로컬 데이터가 있으면 분석은 계속한다.
        local_date = get_local_latest_market_date()
        st.session_state.auto_update_error = str(exc)
        st.session_state.auto_update_info = {
            "mode": "offline",
            "latest_market_date": (
                str(local_date.date()) if local_date is not None else "확인 불가"
            ),
            "updated_count": 0,
            "failed": [],
        }

    finally:
        # Streamlit 위젯 조작으로 rerun되어도 같은 세션에서 반복 다운로드하지 않는다.
        st.session_state.auto_update_done = True


# ============================================================
# 2. 자동 갱신 상태
# ============================================================
def render_data_status() -> None:
    auto_info = st.session_state.auto_update_info or {}
    auto_error = st.session_state.auto_update_error

    st.subheader("데이터 상태")

    if auto_info.get("mode") != "online":
        st.warning(
            "온라인 최신 데이터 확인에 실패했습니다. "
            "저장된 로컬 CSV가 있으면 해당 데이터로 분석을 계속합니다."
        )
        if auto_error:
            with st.expander("자동 갱신 오류 상세"):
                st.code(auto_error)
        st.caption(
            f"로컬 SPY 마지막 날짜: {auto_info.get('latest_market_date', '확인 불가')}"
        )
        return

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("최신 거래일", auto_info.get("latest_market_date", "-"))
    d2.metric("S&P 500", f"{auto_info.get('sp500_count', 0):,}개")
    d3.metric("이번 자동 갱신", f"{auto_info.get('updated_count', 0):,}개")
    d4.metric("데이터 문제", f"{auto_info.get('problem_count', 0):,}개")

    if auto_info.get("updated_count", 0) == 0:
        st.success("저장된 가격 데이터가 이미 최신입니다.")
    else:
        st.success(
            f"자동 갱신이 완료되었습니다. "
            f"{auto_info.get('updated_count', 0):,}개 대상을 확인·갱신했습니다."
        )

    failed = auto_info.get("failed", [])
    if failed:
        st.warning(f"다운로드/저장 실패 종목: {len(failed)}개")
        st.code(", ".join(failed[:50]))

    st.caption(
        f"미국 동부시간 확인: {auto_info.get('checked_at_ny', '-')} | "
        "필요할 때 사이드바의 '지금 강제 갱신'을 누르면 다시 확인합니다."
    )

    summary = auto_info.get("summary")
    if isinstance(summary, pd.DataFrame):
        problem = summary[summary["Status"] != "OK"]
        if not problem.empty:
            with st.expander(f"갱신되지 않은/문제가 있는 종목 ({len(problem)}개)"):
                st.markdown("##### 상태별 개수")
                status_count = (
                    problem["Status"]
                    .value_counts(dropna=False)
                    .rename_axis("Status")
                    .reset_index(name="Count")
                )
                display_dataframe(status_count)

                st.markdown("##### 마지막 저장 날짜")
                last_date_count = (
                    problem["LastDate"]
                    .value_counts(dropna=False)
                    .rename_axis("LastDate")
                    .reset_index(name="Count")
                    .head(20)
                )
                display_dataframe(last_date_count)

                st.markdown("##### 문제 종목 상세")
                display_dataframe(problem.head(100))


# ============================================================
# 3~4. 필수 파일 확인 + 자동 분석
# ============================================================
def check_required_files_or_stop() -> None:
    missing = check_required_files()
    if missing:
        st.error(
            "자동 갱신 후에도 분석에 필요한 파일이 없습니다. "
            "네트워크 연결을 확인한 뒤 사이드바의 '지금 강제 갱신'을 실행하세요.\n\n"
            + "\n".join(f"- {file}" for file in missing)
        )
        st.stop()


def run_analysis(cfg: SidebarConfig):
    st.divider()
    st.subheader("상승추세 스크리닝 + BuyScore + 매매 계획")

    try:
        with st.spinner("시장 상태와 S&P 500 종목을 자동 분석하는 중입니다..."):
            sp500 = pd.read_csv(SP500_FILE)
            market, spy_date, spy_mom, spy_market_ok = analyze_market()
            result, error_df = analyze_stocks(
                sp500,
                spy_date,
                spy_mom,
                min_rows=cfg.min_rows,
            )

            if result.empty:
                st.error("분석 가능한 종목이 없습니다.")
                st.stop()

            candidates, filter_summary = apply_screen_and_score(
                result,
                cfg.screen,
                spy_market_ok=spy_market_ok,
                buy_price=cfg.buy_price,
                buy_stop=cfg.buy_stop,
            )

            if not candidates.empty and cfg.save_output:
                save_output_csv(candidates)

    except Exception as exc:
        st.exception(exc)
        st.stop()

    return market, spy_date, spy_market_ok, result, error_df, candidates, filter_summary


# ============================================================
# 5. 시장 상태
# ============================================================
def render_market_state(
    market: pd.DataFrame,
    spy_date: pd.Timestamp,
    spy_market_ok: bool | None,
    result: pd.DataFrame,
    candidates: pd.DataFrame,
    error_df: pd.DataFrame,
    filter_summary: pd.DataFrame,
) -> None:
    spy_row = market.loc[market["Ticker"] == "SPY"].iloc[0]
    market_state = market_state_label(spy_market_ok)
    ma200 = spy_row["MA200"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("분석 기준일", str(pd.Timestamp(spy_date).date()))
    m2.metric("SPY", f"${spy_row['Close']:,.2f}")
    m3.metric("SPY MA200", "-" if pd.isna(ma200) else f"${ma200:,.2f}")
    m4.metric("시장 상태", market_state)

    if spy_market_ok is None:
        st.warning(
            "SPY의 MA200을 계산할 데이터가 부족합니다(200 거래일 미만). "
            "시장 상태를 판정할 수 없으므로 하락장으로 간주하지 않습니다. "
            "사이드바의 '지금 강제 갱신'으로 데이터를 채운 뒤 다시 확인하세요."
        )
    elif not spy_market_ok:
        st.warning(
            "SPY가 MA200 아래에 있습니다. "
            "신규 매수는 중단하거나 보수적으로 판단하는 구간입니다."
        )

    a1, a2 = st.columns(2)
    a1.metric("분석 성공", f"{len(result):,}개")
    a2.metric("최종 후보", f"{len(candidates):,}개")

    with st.expander("SPY / QQQ 시장 상태와 필터 통과 현황", expanded=False):
        market_show = market.copy()
        market_show["Date"] = pd.to_datetime(market_show["Date"]).dt.date
        market_show["Momentum6_1M_%"] = market_show["Momentum6_1M"] * 100
        market_show["AboveMA200"] = (
            market_show["AboveMA200"]
            .map({True: "위", False: "아래"})
            .fillna(MARKET_UNKNOWN_LABEL)
        )
        display_dataframe(
            market_show[
                ["Ticker", "Date", "Close", "MA200", "AboveMA200", "Momentum6_1M_%"]
            ].round(2)
        )
        st.markdown("#### 필터 통과 현황")
        display_dataframe(filter_summary)

        if error_df is not None and not error_df.empty:
            st.markdown(f"#### 제외/오류 종목 ({len(error_df)}개)")
            display_dataframe(error_df.head(200))


# ============================================================
# 5-1. 보유 종목 현황
# ============================================================
HOLDINGS_COLS = {
    "Ticker": "티커",
    "Date": "기준일",
    "Close": "현재가",
    "EntryPrice": "매수가",
    "Return_%": "수익률(%)",
    "StopPrice": "손절가",
    "Target1R": "1R(30%매도)",
    "Target2R": "2R(30%매도)",
    "MA20": "MA20",
    "MA60": "MA60",
    "CurrentStage": "현재단계",
    "SellSignal": "매도신호",
}


def render_holdings_status(held: pd.DataFrame, missing: list[str]) -> None:
    st.divider()
    st.subheader("보유 종목 현황")

    if missing:
        st.warning(
            "가격 데이터가 없어 평가하지 못한 티커: " + ", ".join(missing)
        )

    if held.empty:
        st.info(
            "사이드바 '보유 종목'에 티커와 매수가를 입력하면 "
            "현재 단계와 매도 신호를 판정합니다."
        )
        return

    stale = held[held["IsStale"]]
    if not stale.empty:
        st.warning(
            "아래 종목은 가격 데이터가 최신 거래일까지 갱신되지 않았습니다. "
            "표의 '현재가'와 매도 신호는 그 시점 기준이므로 그대로 믿으면 "
            "안 됩니다: "
            + ", ".join(
                f"{row.Ticker}({row.Date.date()})" for row in stale.itertuples()
            )
        )

    urgent = held[held["SellSignal"].isin(URGENT_SIGNALS)]
    if not urgent.empty:
        st.error(
            "매도 신호 발생: "
            + ", ".join(
                f"{row.Ticker}({row.SellSignal})" for row in urgent.itertuples()
            )
        )

    show = held[list(HOLDINGS_COLS)].rename(columns=HOLDINGS_COLS)
    show["기준일"] = pd.to_datetime(show["기준일"]).dt.date
    display_dataframe(show.round(2))
    st.caption(
        "스크리닝 통과 여부와 무관하게 보유 종목 전체를 평가합니다. "
        "추세를 잃어 후보에서 빠진 종목도 여기에서는 계속 추적됩니다. "
        "'기준일'이 위의 분석 기준일과 다르면 그 종목은 데이터가 오래된 것입니다."
    )


# ============================================================
# 6. 추천 결과
# ============================================================
_ID_COLS = ["Rank", "Ticker", "Name", "Sector"]
_PCT_COLS = [
    "Momentum6_1M_%",
    "RelativeMomentum_%",
    "Return20_%",
    "MA20Dist_%",
]

RECOMMENDATION_COLS = [
    *_ID_COLS,
    "Type",
    "Risk",
    "BuyScore",
    *_PCT_COLS,
    "Volatility20_%",
    "AvgDollar20_M",
    "BuyAllowed",
    "Explain",
]
BALANCED_COLS = [*_ID_COLS, "BuyScore", *_PCT_COLS, "Volatility20_%"]
SELECTED_COLS = [*_ID_COLS, "Type", "Risk", "BuyScore", *_PCT_COLS, "Explain"]


def render_recommendations(
    candidates: pd.DataFrame, spy_market_ok: bool | None, top_n: int
) -> None:
    title_prefix = "매수 후보" if spy_market_ok is True else "관심 종목"
    st.markdown(f"#### {title_prefix} TOP {min(top_n, len(candidates))}")
    display_dataframe(candidates[RECOMMENDATION_COLS].head(top_n).round(2))

    csv_bytes = candidates.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "분석 결과 CSV 다운로드",
        data=csv_bytes,
        file_name="us_stock_analysis_result.csv",
        mime="text/csv",
    )

    render_score_influence(candidates)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 유형별 종목 수")
        type_count = (
            candidates["Type"]
            .value_counts()
            .rename_axis("Type")
            .reset_index(name="종목수")
        )
        display_dataframe(type_count)

    with c2:
        st.markdown("#### 균형형 종목")
        balanced_result = candidates[candidates["Type"] == "균형형"]
        if balanced_result.empty:
            st.info("균형형 종목이 없습니다.")
        else:
            display_dataframe(balanced_result[BALANCED_COLS].head(top_n).round(2))


# ============================================================
# 7. 선택 유형 / 매매 계획 / 모든 차트
# ============================================================
def render_score_influence(candidates: pd.DataFrame) -> None:
    """배점과 실제 영향력이 얼마나 어긋났는지 보여준다."""
    with st.expander("BuyScore 배점 진단", expanded=False):
        st.caption(
            "'선언 비중'은 배점이 차지하는 몫이고, '실제 기여'는 후보들 사이에서 "
            "그 성분이 순위를 실제로 가른 정도입니다. 많이 걸러낸 축일수록 "
            "후보 간 값이 비슷해져 배점보다 영향력이 작아집니다. "
            "차이가 크면 사이드바의 'BuyScore 배점 기준'을 조정하세요."
        )
        influence = build_score_influence(candidates)
        if influence.empty:
            st.info("후보가 2개 이상이어야 기여도를 계산할 수 있습니다.")
            return

        display_dataframe(influence)

        worst = influence.loc[influence["차이(%p)"].abs().idxmax()]
        if abs(worst["차이(%p)"]) >= INFLUENCE_ALERT_GAP:
            direction = "크게" if worst["차이(%p)"] > 0 else "작게"
            st.warning(
                f"'{worst['성분']}'의 실제 기여가 선언 비중보다 {direction} "
                f"벗어났습니다 ({worst['선언 비중(%)']:.0f}% → "
                f"{worst['실제 기여(%)']:.0f}%, {worst['차이(%p)']:+.0f}%p)."
            )


def render_charts(
    candidates: pd.DataFrame,
    spy_date: pd.Timestamp,
    chart_type: str,
    chart_n: int,
    chart_days: int,
) -> None:
    if chart_type == "전체":
        selected = candidates.head(chart_n).copy()
    else:
        selected = (
            candidates[candidates["Type"] == chart_type]
            .sort_values("BuyScore", ascending=False)
            .head(chart_n)
            .copy()
        )

    st.divider()
    st.subheader(f"{chart_type} - TOP {chart_n}")

    if selected.empty:
        st.info(f"현재 조건을 만족하는 '{chart_type}' 종목이 없습니다.")
        return

    display_dataframe(selected[SELECTED_COLS].round(2))

    st.markdown("#### 매수 / 매도 계획")
    trade_plan = build_trade_plan(selected, len(selected))
    display_dataframe(trade_plan)

    st.divider()
    st.subheader(f"{chart_type} 종목 차트")
    st.caption(
        f"선택한 {len(selected)}개 종목을 한 화면에 모두 그립니다. "
        "아래로 스크롤하면서 현재가·손절가·목표가와 차트를 연속해서 볼 수 있습니다."
    )

    for i, (_, row) in enumerate(selected.iterrows(), start=1):
        ticker = row["Ticker"]
        name = row["Name"]

        st.markdown(f"### {i}. {name} ({ticker})")
        st.caption(f"{row['Type']} · 위험도 {row['Risk']} · {row['Explain']}")

        c1, c2, c3, c4 = st.columns(4)
        show_card(c1, "현재가", f"${row['Close']:,.2f}")
        show_card(c2, "매수가", f"${row['EntryPrice']:,.2f}")
        show_card(c3, "손절가", f"${row['StopPrice']:,.2f}")
        show_card(c4, "1R(30%매도)", f"${row['Target1R']:,.2f}")

        c5, c6, c7, c8 = st.columns(4)
        show_card(c5, "2R(30%매도)", f"${row['Target2R']:,.2f}")
        show_card(c6, "매수 점수", f"{row['BuyScore']:.1f}점")
        show_card(c7, "현재 단계", str(row["CurrentStage"]))
        show_card(c8, "매도 신호", str(row["SellSignal"]))

        fig = None
        try:
            fig = make_candle_chart(
                ticker,
                candidates,
                pd.Timestamp(spy_date),
                chart_days=chart_days,
            )
            st.pyplot(fig, width="stretch")
        except Exception as exc:
            st.warning(f"{ticker} 차트 생성 실패: {exc}")
        finally:
            if fig is not None:
                plt.close(fig)

        st.divider()


# ============================================================
# 메인
# ============================================================
def main() -> None:
    init_session_state()

    st.title("📈 미국 주식 상승추세 스크리너")
    st.caption(
        "앱을 열면 S&P 500 + SPY/QQQ 데이터를 자동으로 확인·갱신한 뒤 "
        "상승추세·모멘텀·상대강도·유동성·과열도를 이용해 후보 종목을 자동 분석합니다."
    )

    cfg = render_sidebar()

    run_auto_update(cfg)
    render_data_status()
    check_required_files_or_stop()

    (
        market,
        spy_date,
        spy_market_ok,
        result,
        error_df,
        candidates,
        filter_summary,
    ) = run_analysis(cfg)

    render_market_state(
        market,
        spy_date,
        spy_market_ok,
        result,
        candidates,
        error_df,
        filter_summary,
    )

    held, missing_held = build_holdings_status(
        cfg.buy_price, cfg.buy_stop, cfg.screen, spy_date
    )
    render_holdings_status(held, missing_held)

    if candidates.empty:
        st.warning("현재 설정에서 모든 조건을 통과한 종목이 없습니다.")
        st.stop()

    render_recommendations(candidates, spy_market_ok, cfg.top_n)
    render_charts(candidates, spy_date, cfg.chart_type, cfg.chart_n, cfg.chart_days)

    st.caption(
        "주의: 이 앱의 스크리닝 결과는 투자 판단을 자동으로 대신하지 않습니다. "
        "데이터 지연·결측과 시장 급변 가능성을 함께 확인하세요."
    )


if __name__ == "__main__":
    main()
