from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from threading import RLock
import logging
import platform
import time

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
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
TYPE_OPTIONS = ["전체"] + VALID_TYPES

# 실제 보유 종목의 매수가/직접 손절가가 있다면 여기에 입력
# 예: BUY_PRICE = {"AAPL": 220.0}
# 예: BUY_STOP = {"AAPL": 205.0}
BUY_PRICE: dict[str, float] = {}
BUY_STOP: dict[str, float] = {}

# matplotlib 동시 실행 충돌 방지
PLOT_LOCK = RLock()


# ============================================================
# 한글 폰트
# ============================================================
def get_korean_font() -> str:
    system = platform.system()
    preferred = {
        "Windows": "Malgun Gothic",
        "Darwin": "AppleGothic",
    }.get(system, "NanumGothic")

    available_fonts = {f.name for f in fm.fontManager.ttflist}
    if preferred not in available_fonts:
        return "DejaVu Sans"
    return preferred


KOREAN_FONT = get_korean_font()
plt.rcParams["font.family"] = KOREAN_FONT
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.weight"] = "normal"
plt.rcParams["axes.titleweight"] = "normal"


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


# ============================================================
# 유틸리티
# ============================================================
def read_sp500_universe() -> pd.DataFrame:
    """최신 S&P 500 구성 종목을 가져오고 로컬 파일에 저장한다."""
    try:
        sp500 = pd.read_csv(SP500_URL)
    except Exception as exc:
        if SP500_FILE.exists():
            st.warning(f"S&P 500 목록 다운로드 실패. 기존 저장 파일을 사용합니다. ({exc})")
            sp500 = pd.read_csv(SP500_FILE)
        else:
            raise RuntimeError(
                "S&P 500 목록 다운로드 실패 + 기존 CSV 없음"
            ) from exc

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
    refresh_days: int,
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
            item_start_ts = pd.Timestamp(last_date) - pd.Timedelta(days=refresh_days)
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
    sleep_seconds: float = 1.0,
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
                    threads=True,
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


def check_required_files() -> list[str]:
    required_files = [
        SP500_FILE,
        MARKET_DIR / "SPY.csv",
        MARKET_DIR / "QQQ.csv",
    ]
    return [str(file) for file in required_files if not file.exists()]


@st.cache_data(show_spinner=False)
def analyze_market() -> tuple[pd.DataFrame, pd.Timestamp, float, bool]:
    market_rows = []

    for ticker in MARKET_TICKERS:
        file = MARKET_DIR / f"{ticker}.csv"
        df = pd.read_csv(file, parse_dates=["Date"])
        df = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
        df["MA200"] = df["Close"].rolling(200).mean()
        df["Momentum6_1M"] = df["Close"].shift(22) / df["Close"].shift(126) - 1

        last = df.iloc[-1]
        market_rows.append(
            {
                "Ticker": ticker,
                "Date": last["Date"],
                "Close": last["Close"],
                "MA200": last["MA200"],
                "AboveMA200": bool(last["Close"] > last["MA200"]),
                "Momentum6_1M": last["Momentum6_1M"],
            }
        )

    market = pd.DataFrame(market_rows)
    spy_date = pd.Timestamp(market.loc[market["Ticker"] == "SPY", "Date"].iloc[0])
    spy_mom = float(
        market.loc[market["Ticker"] == "SPY", "Momentum6_1M"].iloc[0]
    )
    spy_market_ok = bool(
        market.loc[market["Ticker"] == "SPY", "AboveMA200"].iloc[0]
    )
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


def apply_screen_and_score(
    result: pd.DataFrame,
    *,
    min_dollar_volume: float,
    max_ret20: float,
    max_ma20_dist: float,
    max_day_gain5: float,
    bal_mom_pct: float,
    bal_ret20_max: float,
    bal_ma20_min: float,
    bal_ma20_max: float,
    bal_day_gain5: float,
    bal_vol_pct: float,
    max_stop_loss: float,
    spy_market_ok: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = result.copy()

    result["AbsMomentumOK"] = result["Momentum6_1M"] > 0
    result["RelativeMomentumOK"] = result["RelativeMomentum"] > 0
    result["LiquidityOK"] = result["AvgDollar20"] >= min_dollar_volume
    result["OverheatOK"] = (
        (result["Return20"] <= max_ret20)
        & (result["MA20Dist"] <= max_ma20_dist)
        & (result["MaxDayGain5"] <= max_day_gain5)
    )
    result["ScreenOK"] = (
        result["Trend"]
        & result["AbsMomentumOK"]
        & result["RelativeMomentumOK"]
        & result["LiquidityOK"]
        & result["OverheatOK"]
    )

    filter_summary = pd.DataFrame(
        {
            "조건": [
                "MA 상승추세",
                "6-1M > 0",
                "SPY 상대강도 > 0",
                f"20일 평균 거래대금 >= ${min_dollar_volume / 1_000_000:,.0f}M",
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

    candidates = result[result["ScreenOK"]].copy()
    if candidates.empty:
        return candidates, filter_summary

    # 후보 종목 내 percentile
    candidates["MomentumPct"] = candidates["Momentum6_1M"].rank(pct=True)
    candidates["LiquidityPct"] = candidates["AvgDollar20"].rank(pct=True)
    candidates["VolatilityPct"] = candidates["Volatility20"].rank(pct=True)

    # BuyScore 100점
    candidates["MomentumScore"] = candidates["MomentumPct"] * 45
    candidates["DistanceScore"] = (
        1 - abs(candidates["MA20Dist"] - 0.05) / 0.07
    ).clip(0, 1) * 30
    candidates["StabilityScore"] = (1 - candidates["VolatilityPct"]) * 20
    candidates["LiquidityScore"] = candidates["LiquidityPct"] * 5
    candidates["BuyScore"] = (
        candidates["MomentumScore"]
        + candidates["DistanceScore"]
        + candidates["StabilityScore"]
        + candidates["LiquidityScore"]
    )

    # 유형 분류: 앞 조건 우선
    balanced = (
        (candidates["MomentumPct"] >= bal_mom_pct)
        & candidates["Return20"].between(0, bal_ret20_max)
        & candidates["MA20Dist"].between(bal_ma20_min, bal_ma20_max)
        & (candidates["MaxDayGain5"] <= bal_day_gain5)
        & (candidates["VolatilityPct"] <= bal_vol_pct)
    )
    surge = (candidates["MaxDayGain5"] > 0.10) | (candidates["Return20"] > 0.20)
    overheated = candidates["MA20Dist"] > 0.09
    strong = (candidates["MomentumPct"] >= 0.85) & (candidates["MA20Dist"] <= 0.10)
    low_heat = (candidates["MA20Dist"] < 0.03) & (candidates["Return20"] < 0.08)

    candidates["Type"] = np.select(
        [surge, overheated, balanced, strong, low_heat],
        ["급등주의", "과열주의", "균형형", "강한추세", "저과열"],
        default="일반",
    )

    # 유형별 위험도 / 설명
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
        "급등주의": "최근 급등하여 추격매수에 주의할 종목",
        "과열주의": "상승추세지만 MA20에서 다소 멀어진 종목",
        "균형형": "추세·모멘텀·과열도의 균형이 좋은 종목",
        "저과열": "과열은 적지만 추가 상승 힘을 확인할 종목",
        "일반": "무난한 상승추세 종목",
    }
    candidates["Risk"] = candidates["Type"].map(risk_map)
    candidates["Explain"] = candidates["Type"].map(explain_map)

    # --------------------------------------------------------
    # 매매 계획
    # --------------------------------------------------------
    # BUY_PRICE에 실제 보유 매수가가 있으면 우선 사용하고,
    # 없으면 현재가를 신규 매수가로 사용한다.
    candidates["EntryPrice"] = (
        candidates["Ticker"].map(BUY_PRICE).fillna(candidates["Close"])
    )

    # MA60 또는 최대 허용 손실률 중 더 높은 가격을 자동 손절가로 사용
    auto_stop = np.maximum(
        candidates["MA60"],
        candidates["EntryPrice"] * (1 - max_stop_loss),
    )
    candidates["StopPrice"] = (
        candidates["Ticker"].map(BUY_STOP).fillna(pd.Series(auto_stop, index=candidates.index))
    )

    candidates["R"] = candidates["EntryPrice"] - candidates["StopPrice"]
    candidates["Target1R"] = candidates["EntryPrice"] + candidates["R"]
    candidates["Target2R"] = candidates["EntryPrice"] + 2 * candidates["R"]

    price = candidates["Close"]
    sell_conditions = [
        price <= candidates["StopPrice"],
        price < candidates["MA60"],
        price < candidates["MA20"],
        price >= candidates["Target2R"],
        price >= candidates["Target1R"],
    ]
    candidates["CurrentStage"] = np.select(
        sell_conditions,
        ["손절 구간", "추세 이탈", "MA20 이탈", "2R 이상", "1R 이상"],
        default="1R 전",
    )
    candidates["SellSignal"] = np.select(
        sell_conditions,
        ["전량 손절", "매도", "주의", "30% 매도 → 남은 40% MA20 추적", "30% 매도"],
        default="보유",
    )
    candidates["BuyAllowed"] = "허용" if spy_market_ok else "중단"

    candidates = candidates.sort_values("BuyScore", ascending=False).reset_index(drop=True)
    candidates["Rank"] = np.arange(1, len(candidates) + 1)

    # 화면 표시용 단위
    candidates["Momentum6_1M_%"] = candidates["Momentum6_1M"] * 100
    candidates["RelativeMomentum_%"] = candidates["RelativeMomentum"] * 100
    candidates["Return20_%"] = candidates["Return20"] * 100
    candidates["MA20Dist_%"] = candidates["MA20Dist"] * 100
    candidates["Volatility20_%"] = candidates["Volatility20"] * 100
    candidates["AvgDollar20_M"] = candidates["AvgDollar20"] / 1_000_000

    return candidates, filter_summary


def build_trade_plan(candidates: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()

    trade_plan = candidates[
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
    ].head(top_n).copy()

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

    price_cols = ["현재가", "MA20", "MA60", "매수가", "손절가", "1R(30%매도)", "2R(30%매도)"]
    trade_plan[price_cols] = trade_plan[price_cols].round(2)
    trade_plan["BuyScore"] = trade_plan["BuyScore"].round(2)
    return trade_plan


def make_candle_chart(
    ticker: str,
    candidates: pd.DataFrame,
    spy_date: pd.Timestamp,
    chart_days: int = 250,
):
    """MA20/60/120/200과 매수가·손절가·1R·2R을 포함한 캔들차트."""
    df = pd.read_csv(STOCK_DIR / f"{ticker}.csv", parse_dates=["Date"])
    df = (
        df[df["Date"] <= spy_date]
        .sort_values("Date")
        .drop_duplicates("Date")
        .tail(chart_days)
        .copy()
    )
    df = df.set_index("Date")

    if df.empty:
        raise ValueError("차트 데이터가 없습니다.")

    info = candidates.loc[candidates["Ticker"] == ticker].iloc[0]

    # 미국식 캔들 색상 대신 KOSPI 버전과 동일하게 상승=빨강, 하락=파랑
    market_colors = mpf.make_marketcolors(up="red", down="blue", inherit=True)

    mav_periods = (20, 60, 120, 200) if len(df) >= 200 else (20, 60, 120)
    mav_colors = ["orange", "green", "purple", "black"][: len(mav_periods)]

    mpf_style = mpf.make_mpf_style(
        base_mpf_style="yahoo",
        marketcolors=market_colors,
        mavcolors=mav_colors,
        rc={
            "font.family": KOREAN_FONT,
            "font.weight": "normal",
            "axes.titleweight": "normal",
            "axes.unicode_minus": False,
        },
    )

    with PLOT_LOCK:
        fig, axes = mpf.plot(
            df[["Open", "High", "Low", "Close", "Volume"]],
            type="candle",
            mav=mav_periods,
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
        ax.set_title(title, fontsize=11, pad=8)

        # 오른쪽에 매매 가격 라벨을 표시할 공간 확보
        fig.subplots_adjust(right=0.78)

        ma_labels = ["MA20", "MA60", "MA120", "MA200"][: len(mav_periods)]
        ma_legend = [
            Line2D([0], [0], color=color, lw=2, label=label)
            for color, label in zip(mav_colors, ma_labels)
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
            fontsize=8,
        )

    return fig


def display_dataframe(df: pd.DataFrame, *, height: int | None = None) -> None:
    kwargs = {
        "use_container_width": True,
        "hide_index": True,
    }
    if height is not None:
        kwargs["height"] = height
    st.dataframe(df, **kwargs)


# ============================================================
# Session state
# ============================================================
for key, default in {
    "auto_update_done": False,
    "auto_update_info": None,
    "auto_update_error": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================
# 화면
# ============================================================
st.title("📈 미국 주식 상승추세 스크리너")
st.caption(
    "앱을 열면 S&P 500 + SPY/QQQ 데이터를 자동으로 확인·갱신한 뒤 "
    "상승추세·모멘텀·상대강도·유동성·과열도를 이용해 후보 종목을 자동 분석합니다."
)

with st.sidebar:
    st.header("분석 설정")

    with st.expander("자동 데이터 갱신 설정", expanded=False):
        start_date = st.text_input("최초 다운로드 시작일", "2015-01-01")
        refresh_days = st.number_input(
            "기존 데이터 재다운로드 기간(일)",
            min_value=30,
            max_value=1000,
            value=400,
            step=10,
        )
        batch_size = st.number_input(
            "다운로드 배치 크기",
            min_value=10,
            max_value=200,
            value=100,
            step=10,
        )
        st.caption(
            "앱 세션 시작 시 최신 거래일을 한 번 확인합니다. "
            "이미 최신인 종목은 다운로드하지 않습니다."
        )

    # 필요할 때만 네트워크 갱신을 다시 수행
    if st.button("🔄 지금 강제 갱신", type="primary", use_container_width=True):
        st.session_state.auto_update_done = False
        st.session_state.auto_update_info = None
        st.session_state.auto_update_error = None
        st.cache_data.clear()
        st.rerun()

    with st.expander("기본 필터", expanded=True):
        min_rows = st.number_input("최소 데이터 행 수", 120, 1000, 130, 10)
        min_dollar_volume_m = st.number_input(
            "20일 평균 거래대금 최소($M)", 1.0, 1000.0, 20.0, 5.0
        )
        max_ret20_pct = st.number_input("20일 수익률 상한(%)", 1.0, 100.0, 25.0, 1.0)
        max_ma20_dist_pct = st.number_input("MA20 이격 상한(%)", 1.0, 50.0, 12.0, 1.0)
        max_day_gain5_pct = st.number_input(
            "최근 5일 최대 일간상승률 상한(%)", 1.0, 50.0, 15.0, 1.0
        )

    with st.expander("균형형 분류 기준", expanded=False):
        bal_mom_pct_pct = st.slider("모멘텀 백분위 최소", 0, 100, 70, 5)
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
        bal_vol_pct_pct = st.slider("균형형 변동성 백분위 최대", 0, 100, 70, 5)

    with st.expander("매매/출력 설정", expanded=False):
        max_stop_loss_pct = st.number_input("최대 손절폭(%)", 1.0, 30.0, 8.0, 0.5)
        top_n = st.number_input("추천 종목 수", 5, 100, 20, 5)
        chart_type = st.selectbox("종목 유형", TYPE_OPTIONS, index=0)
        chart_n = st.number_input("차트 개수", 1, 30, 10, 1)
        chart_days = st.slider("차트 표시 거래일", 120, 500, 250, 10)

    if st.button("분석 캐시 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption(f"OS: {platform.system()} | matplotlib font: {KOREAN_FONT}")
    st.caption(f"데이터 폴더: {BASE_DIR.resolve()}")


# ============================================================
# 1. 앱 시작 시 데이터 자동 확인 / 자동 갱신
# ============================================================
if not st.session_state.auto_update_done:
    try:
        with st.spinner("S&P 500 목록과 최신 미국 거래일을 확인하는 중입니다..."):
            auto_sp500 = read_sp500_universe()
            now_ny, download_end, latest_market_date = get_latest_market_info()
            targets = build_download_targets(auto_sp500)
            pending, latest_count = find_pending_targets(
                targets,
                latest_market_date,
                start_date,
                int(refresh_days),
            )

        pending_count = len(pending)

        if pending:
            st.info(
                f"최신 완료 거래일 {latest_market_date.date()} 기준으로 "
                f"{pending_count:,}개 종목을 자동 갱신합니다."
            )
            failed = update_price_data(
                pending,
                download_end,
                int(batch_size),
            )
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
auto_info = st.session_state.auto_update_info or {}
auto_error = st.session_state.auto_update_error

st.subheader("데이터 상태")

if auto_info.get("mode") == "online":
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
                display_dataframe(problem.head(100))
else:
    st.warning(
        "온라인 최신 데이터 확인에 실패했습니다. 저장된 로컬 CSV가 있으면 해당 데이터로 분석을 계속합니다."
    )
    if auto_error:
        with st.expander("자동 갱신 오류 상세"):
            st.code(auto_error)
    st.caption(f"로컬 SPY 마지막 날짜: {auto_info.get('latest_market_date', '확인 불가')}")


# ============================================================
# 3. 필수 파일 확인
# ============================================================
missing = check_required_files()
if missing:
    st.error(
        "자동 갱신 후에도 분석에 필요한 파일이 없습니다. "
        "네트워크 연결을 확인한 뒤 사이드바의 '지금 강제 갱신'을 실행하세요.\n\n"
        + "\n".join(f"- {file}" for file in missing)
    )
    st.stop()


# ============================================================
# 4. 자동 분석
# ============================================================
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
            min_rows=int(min_rows),
        )

        if result.empty:
            st.error("분석 가능한 종목이 없습니다.")
            st.stop()

        candidates, filter_summary = apply_screen_and_score(
            result,
            min_dollar_volume=min_dollar_volume_m * 1_000_000,
            max_ret20=max_ret20_pct / 100,
            max_ma20_dist=max_ma20_dist_pct / 100,
            max_day_gain5=max_day_gain5_pct / 100,
            bal_mom_pct=bal_mom_pct_pct / 100,
            bal_ret20_max=bal_ret20_max_pct / 100,
            bal_ma20_min=bal_ma20_min_pct / 100,
            bal_ma20_max=bal_ma20_max_pct / 100,
            bal_day_gain5=bal_day_gain5_pct / 100,
            bal_vol_pct=bal_vol_pct_pct / 100,
            max_stop_loss=max_stop_loss_pct / 100,
            spy_market_ok=spy_market_ok,
        )

        if not candidates.empty:
            candidates.to_csv(OUTPUT_FILE, index=False)

except Exception as exc:
    st.exception(exc)
    st.stop()


# ============================================================
# 5. 시장 상태
# ============================================================
spy_row = market.loc[market["Ticker"] == "SPY"].iloc[0]
market_state = "상승장" if spy_market_ok else "방어장"

m1, m2, m3, m4 = st.columns(4)
m1.metric("분석 기준일", str(pd.Timestamp(spy_date).date()))
m2.metric("SPY", f"${spy_row['Close']:,.2f}")
m3.metric("SPY MA200", f"${spy_row['MA200']:,.2f}")
m4.metric("시장 상태", market_state)

if not spy_market_ok:
    st.warning(
        "SPY가 MA200 아래에 있습니다. 신규 매수는 중단하거나 보수적으로 판단하는 구간입니다."
    )

a1, a2 = st.columns(2)
a1.metric("분석 성공", f"{len(result):,}개")
a2.metric("최종 후보", f"{len(candidates):,}개")

with st.expander("SPY / QQQ 시장 상태와 필터 통과 현황", expanded=False):
    market_show = market.copy()
    market_show["Date"] = pd.to_datetime(market_show["Date"]).dt.date
    market_show["Momentum6_1M_%"] = market_show["Momentum6_1M"] * 100
    market_show["AboveMA200"] = market_show["AboveMA200"].map(
        {True: "위", False: "아래"}
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
# 6. 추천 결과
# ============================================================
if candidates.empty:
    st.warning("현재 설정에서 모든 조건을 통과한 종목이 없습니다.")
    st.stop()

show_cols = [
    "Rank",
    "Ticker",
    "Name",
    "Sector",
    "Type",
    "Risk",
    "BuyScore",
    "Momentum6_1M_%",
    "RelativeMomentum_%",
    "Return20_%",
    "MA20Dist_%",
    "Volatility20_%",
    "AvgDollar20_M",
    "BuyAllowed",
    "Explain",
]

title_prefix = "매수 후보" if spy_market_ok else "관심 종목"
st.markdown(f"#### {title_prefix} TOP {min(int(top_n), len(candidates))}")
display_dataframe(candidates[show_cols].head(int(top_n)).round(2))

csv_bytes = candidates.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "분석 결과 CSV 다운로드",
    data=csv_bytes,
    file_name="us_stock_analysis_result.csv",
    mime="text/csv",
)

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
    balanced_cols = [
        "Rank",
        "Ticker",
        "Name",
        "Sector",
        "BuyScore",
        "Momentum6_1M_%",
        "RelativeMomentum_%",
        "Return20_%",
        "MA20Dist_%",
        "Volatility20_%",
    ]
    balanced_result = candidates[candidates["Type"] == "균형형"]
    if balanced_result.empty:
        st.info("균형형 종목이 없습니다.")
    else:
        display_dataframe(balanced_result[balanced_cols].head(int(top_n)).round(2))


# ============================================================
# 7. 선택 유형 / 매매 계획 / 모든 차트
# ============================================================
if chart_type == "전체":
    selected = candidates.head(int(chart_n)).copy()
else:
    selected = (
        candidates[candidates["Type"] == chart_type]
        .sort_values("BuyScore", ascending=False)
        .head(int(chart_n))
        .copy()
    )

st.divider()
st.subheader(f"{chart_type} - TOP {int(chart_n)}")

if selected.empty:
    st.info(f"현재 조건을 만족하는 '{chart_type}' 종목이 없습니다.")
else:
    selected_cols = [
        "Rank",
        "Ticker",
        "Name",
        "Sector",
        "Type",
        "Risk",
        "BuyScore",
        "Momentum6_1M_%",
        "RelativeMomentum_%",
        "Return20_%",
        "MA20Dist_%",
        "Explain",
    ]
    display_dataframe(selected[selected_cols].round(2))

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

        try:
            fig = make_candle_chart(
                ticker,
                candidates,
                pd.Timestamp(spy_date),
                chart_days=int(chart_days),
            )
            st.pyplot(fig, width="stretch")
            plt.close(fig)
        except Exception as exc:
            st.warning(f"{ticker} 차트 생성 실패: {exc}")

        st.divider()


st.caption(
    "주의: 이 앱의 스크리닝 결과는 투자 판단을 자동으로 대신하지 않습니다. "
    "데이터 지연·결측과 시장 급변 가능성을 함께 확인하세요."
)
