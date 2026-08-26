from __future__ import annotations

import html
import json
import platform
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests
import streamlit as st


# =============================================================================
# 1. 고정 전략 설정
# =============================================================================
API_BASE = "https://api.upbit.com/v1"
SCREEN_CANDLE_UNIT = 240
ENTRY_CANDLE_UNIT = 60
CANDLE_COUNT = 200

MA_PERIODS = (5, 20, 60, 120)
MA_SLOPE_LOOKBACKS = {20: 3, 60: 6, 120: 12}
REQUIRE_MA_RISING = True

ENTRY_PULLBACK_MIN_PCT = 0.0
ENTRY_PULLBACK_MAX_PCT = 3.0
ENTRY_OVERHEAT_PCT = 8.0
STRONG_RISE_24H_PCT = 8.0

ATR_PERIOD = 14
VOLUME_EMA_PERIOD = 20
RSI_PERIOD = 14
DYNAMIC_RSI_CENTER_PERIOD = 20
DYNAMIC_RSI_STD_PERIOD = 20
DYNAMIC_RSI_STD_MULTIPLIER = 1.5
SWING_LEFT_BARS = 3
SWING_RIGHT_BARS = 3

BUY_ZONE_ATR = 0.5
STOP_MA60_ATR = 0.5
MAX_STOP_ATR = 2.0
MIN_RISK_ATR = 1.0
TP1_R_MULTIPLIER = 1.5
TP2_R_MULTIPLIER = 2.5
RUNNER_TRIGGER_R = 4.0
TRAIL_ATR_MULTIPLIER = 2.0
RUNNER_TRAIL_ATR_MULTIPLIER = 1.5

TP1_SELL_PCT = 30
TP2_SELL_PCT = 30
RUNNER_HOLD_PCT = 40

CHART_BARS = 60
REQUEST_INTERVAL = 0.12
MAX_RETRIES = 3

REQUIRED_OHLCV_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_value",
)

CACHE_ROOT = Path("upbit_cache")
MARKET_CACHE_DIR = CACHE_ROOT / "market"
TICKER_CACHE_DIR = CACHE_ROOT / "ticker"
OHLCV_CACHE_DIR = CACHE_ROOT / "ohlcv"
OUTPUT_DIR = Path("output")

for folder in (MARKET_CACHE_DIR, TICKER_CACHE_DIR, OHLCV_CACHE_DIR, OUTPUT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

MARKET_CACHE_FILE = MARKET_CACHE_DIR / "krw_markets.json"
TICKER_CACHE_FILE = TICKER_CACHE_DIR / "krw_ticker.json"
RESULT_CSV = OUTPUT_DIR / "upbit_screener_240m_60m.csv"


@dataclass(frozen=True)
class AppSettings:
    """사이드바에서 변경하는 실행 설정.

    계산 함수가 전역변수를 직접 참조하지 않도록 한 곳에 모은다.
    """

    min_change_24h: float = 1.0
    max_change_24h: float = 30.0
    min_trade_value_24h: float = 100_000_000.0

    account_capital: float = 100_000_000.0
    risk_per_trade_pct: float = 0.5
    max_position_pct: float = 20.0

    top_n: int = 20
    strategy_n: int = 5
    chart_n: int = 5
    cache_minutes: int = 60

    @property
    def ticker_cache_warn_minutes(self) -> int:
        return max(10, int(self.cache_minutes * 0.5))

    @property
    def ticker_cache_max_age_minutes(self) -> int:
        return self.cache_minutes

    def ohlcv_cache_expire_minutes(self, candle_unit: int) -> int:
        if candle_unit == 60:
            return min(60, max(10, int(self.cache_minutes * 0.5)))
        if candle_unit == 240:
            return self.cache_minutes
        return self.cache_minutes

    def analysis_signature(self) -> tuple:
        """재분석이 필요한 설정만 비교한다.

        TOP/전략/차트 개수는 화면 출력값이라 기존 분석에 바로 적용 가능하다.
        """
        return (
            self.min_change_24h,
            self.max_change_24h,
            self.min_trade_value_24h,
            self.account_capital,
            self.risk_per_trade_pct,
            self.max_position_pct,
            self.cache_minutes,
        )


DEFAULT_SETTINGS = AppSettings()


# =============================================================================
# 2. 공통 유틸리티
# =============================================================================
def configure_korean_font() -> str:
    installed = {font.name for font in fm.fontManager.ttflist}
    system = platform.system()

    if system == "Windows":
        candidates = ["Malgun Gothic", "NanumGothic"]
    elif system == "Darwin":
        candidates = ["AppleGothic", "Arial Unicode MS", "NanumGothic"]
    else:
        candidates = ["NanumGothic", "Noto Sans CJK KR", "DejaVu Sans"]

    selected = next((name for name in candidates if name in installed), "DejaVu Sans")
    plt.rcParams["font.family"] = selected
    plt.rcParams["axes.unicode_minus"] = False
    return selected


KOREAN_FONT = configure_korean_font()


def format_price(value) -> str:
    if value is None or pd.isna(value):
        return "-"

    value = float(value)
    absolute = abs(value)
    if absolute >= 1_000:
        text = f"{value:,.0f}"
    elif absolute >= 100:
        text = f"{value:,.1f}"
    elif absolute >= 1:
        text = f"{value:,.2f}"
    elif absolute >= 0.01:
        text = f"{value:,.4f}"
    else:
        text = f"{value:,.8f}"

    return text.rstrip("0").rstrip(".") if "." in text else text




def as_float(value, default=np.nan) -> float:
    """외부 API의 None/문자열/NaN 값을 안전하게 실수로 변환한다."""
    try:
        number = float(value)
        return number if np.isfinite(number) else float(default)
    except (TypeError, ValueError):
        return float(default)

def parse_number(text_value: str, name: str, *, integer: bool = False):
    cleaned = str(text_value).replace(",", "").strip()
    if not cleaned:
        raise ValueError(f"{name} 값을 입력하세요.")

    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{name}에는 숫자만 입력하세요.") from exc

    return int(value) if integer else value


def write_json_atomic(path: Path, payload: dict) -> None:
    """중간에 프로그램이 종료돼도 기존 캐시가 깨지지 않도록 원자적으로 저장한다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp.replace(path)


def get_ohlcv_cache_dir(candle_unit: int) -> Path:
    path = OHLCV_CACHE_DIR / f"{candle_unit}m"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_ohlcv_cache_path(symbol: str, candle_unit: int) -> Path:
    return get_ohlcv_cache_dir(candle_unit) / f"{symbol.replace('-', '_')}.json"


def file_age_minutes(path: Path) -> float:
    if not path.exists():
        return float("inf")
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return max(0.0, age.total_seconds() / 60)


def cache_is_fresh(path: Path, expire_minutes: int) -> bool:
    return path.exists() and file_age_minutes(path) <= expire_minutes


def get_current_candle_start_kst(
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> pd.Timestamp:
    """업비트 분봉 경계(UTC 정렬)를 KST의 tz-naive 시각으로 반환한다."""
    now = pd.Timestamp.now(tz="Asia/Seoul") if now_kst is None else pd.Timestamp(now_kst)
    if now.tzinfo is None:
        now = now.tz_localize("Asia/Seoul")
    else:
        now = now.tz_convert("Asia/Seoul")

    now_utc = now.tz_convert("UTC")
    unit_ns = pd.Timedelta(minutes=candle_unit).value
    floored_ns = (now_utc.value // unit_ns) * unit_ns
    return pd.Timestamp(floored_ns, tz="UTC").tz_convert("Asia/Seoul").tz_localize(None)


def get_latest_completed_candle_start_kst(
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> pd.Timestamp:
    return get_current_candle_start_kst(candle_unit, now_kst) - pd.Timedelta(
        minutes=candle_unit
    )


def cache_matches_latest_close(
    path: Path,
    df: Optional[pd.DataFrame],
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> bool:
    """캐시가 최신 봉 마감 이후 생성됐고 최신 완료봉을 포함하는지 확인한다."""
    if not path.exists() or df is None or df.empty:
        return False

    current_start = get_current_candle_start_kst(candle_unit, now_kst)
    latest_completed = get_latest_completed_candle_start_kst(candle_unit, now_kst)

    mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC")
    mtime_kst = mtime.tz_convert("Asia/Seoul").tz_localize(None)

    return mtime_kst >= current_start and df.index.max() >= latest_completed


# =============================================================================
# 3. Upbit Public API / 캐시
# =============================================================================
class UpbitPublicClient:
    def __init__(
        self,
        request_interval: float = REQUEST_INTERVAL,
        max_retries: int = MAX_RETRIES,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "upbit-multitimeframe-screener/final",
            }
        )
        self.request_interval = request_interval
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def close(self) -> None:
        self.session.close()

    def _throttle(self) -> None:
        wait = self.request_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, params: Optional[dict] = None):
        url = f"{API_BASE}{path}"
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=8)
                self._last_request_at = time.monotonic()

                if response.status_code == 429:
                    last_error = RuntimeError("업비트 요청 한도 초과: HTTP 429")
                    time.sleep(1.05)
                    continue
                if response.status_code == 418:
                    raise RuntimeError("업비트 API가 요청을 일시 제한했습니다. 잠시 후 다시 실행하세요.")
                if 500 <= response.status_code < 600:
                    last_error = RuntimeError(f"업비트 서버 오류: HTTP {response.status_code}")
                    time.sleep(min(2 ** (attempt - 1), 4))
                    continue

                response.raise_for_status()
                if "sec=0" in response.headers.get("Remaining-Req", ""):
                    time.sleep(1.05)
                return response.json()

            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(2 ** (attempt - 1), 4))

        raise RuntimeError(f"Upbit API 호출 실패: {last_error}")

    def get_markets(self) -> list[dict]:
        return self.get("/market/all")

    def get_krw_tickers(self) -> list[dict]:
        return self.get("/ticker/all", {"quote_currencies": "KRW"})

    def get_minute_candles(
        self,
        market: str,
        unit: int,
        count: int = CANDLE_COUNT,
    ) -> pd.DataFrame:
        data = self.get(
            f"/candles/minutes/{unit}",
            {"market": market, "count": min(count, 200)},
        )
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data).drop(columns=["timestamp"], errors="ignore")
        df = df.rename(
            columns={
                "candle_date_time_kst": "timestamp",
                "opening_price": "open",
                "high_price": "high",
                "low_price": "low",
                "trade_price": "close",
                "candle_acc_trade_volume": "volume",
                "candle_acc_trade_price": "trade_value",
            }
        )

        required = ("timestamp", *REQUIRED_OHLCV_COLUMNS)
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ValueError(f"업비트 캔들 응답 필드 누락: {missing}")

        df = df[list(required)].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df[list(REQUIRED_OHLCV_COLUMNS)] = df[list(REQUIRED_OHLCV_COLUMNS)].apply(
            pd.to_numeric, errors="coerce"
        )
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        return (
            df.sort_values("timestamp")
            .set_index("timestamp")
            .loc[lambda x: ~x.index.duplicated(keep="last")]
        )


def load_ohlcv_cache(symbol: str, candle_unit: int) -> Optional[pd.DataFrame]:
    path = get_ohlcv_cache_path(symbol, candle_unit)
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return None

        df = pd.DataFrame(records)
        if df.empty or "timestamp" not in df.columns:
            return None

        df = df.loc[:, ~df.columns.duplicated()].copy()
        missing = [c for c in REQUIRED_OHLCV_COLUMNS if c not in df.columns]
        if missing:
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df[list(REQUIRED_OHLCV_COLUMNS)] = df[list(REQUIRED_OHLCV_COLUMNS)].apply(
            pd.to_numeric, errors="coerce"
        )
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        if df.empty:
            return None

        return (
            df.sort_values("timestamp")
            .set_index("timestamp")
            .loc[lambda x: ~x.index.duplicated(keep="last")]
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_ohlcv_cache(symbol: str, candle_unit: int, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return

    try:
        save_df = df.reset_index().copy()
        if save_df.columns[0] != "timestamp":
            save_df = save_df.rename(columns={save_df.columns[0]: "timestamp"})
        save_df = save_df.loc[:, ~save_df.columns.duplicated()].copy()
        save_df["timestamp"] = save_df["timestamp"].astype(str)

        payload = {
            "version": 6,
            "market": symbol,
            "candle_unit_minutes": candle_unit,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "records": save_df.to_dict(orient="records"),
        }
        write_json_atomic(get_ohlcv_cache_path(symbol, candle_unit), payload)
    except Exception:
        # 캐시 저장 실패는 분석 자체를 중단할 이유가 없다.
        pass


def get_ohlcv(
    client: UpbitPublicClient,
    symbol: str,
    candle_unit: int,
    offline_mode: bool,
    settings: AppSettings,
) -> tuple[Optional[pd.DataFrame], str]:
    path = get_ohlcv_cache_path(symbol, candle_unit)
    cached = load_ohlcv_cache(symbol, candle_unit)
    expire = settings.ohlcv_cache_expire_minutes(candle_unit)

    if offline_mode:
        if cached is None:
            return None, "missing"
        fresh = cache_is_fresh(path, expire)
        boundary_ok = cache_matches_latest_close(path, cached, candle_unit)
        return cached, "cache" if fresh and boundary_ok else "stale"

    if (
        cached is not None
        and cache_is_fresh(path, expire)
        and cache_matches_latest_close(path, cached, candle_unit)
    ):
        return cached, "cache"

    try:
        df = client.get_minute_candles(symbol, candle_unit, CANDLE_COUNT)
        if not df.empty:
            save_ohlcv_cache(symbol, candle_unit, df)
            return df, "api"
    except Exception:
        if cached is not None:
            return cached, "stale"
        raise

    return None, "missing"


def load_market_cache() -> tuple[list[str], dict[str, str]]:
    if not MARKET_CACHE_FILE.exists():
        return [], {}
    try:
        with MARKET_CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        pairs = data.get("krw_pairs", [])
        names = data.get("symbol_korean_map", {})
        return (pairs, names) if isinstance(pairs, list) and isinstance(names, dict) else ([], {})
    except (OSError, json.JSONDecodeError, TypeError):
        return [], {}


def save_market_cache(pairs: list[str], names: dict[str, str]) -> None:
    try:
        write_json_atomic(
            MARKET_CACHE_FILE,
            {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "krw_pairs": pairs,
                "symbol_korean_map": names,
            },
        )
    except OSError:
        pass


def load_ticker_cache() -> dict[str, dict]:
    if not TICKER_CACHE_FILE.exists():
        return {}
    try:
        with TICKER_CACHE_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        records = payload.get("records", [])
        if not isinstance(records, list):
            return {}
        return {row["market"]: row for row in records if isinstance(row, dict) and "market" in row}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_ticker_cache(tickers: list[dict]) -> None:
    try:
        write_json_atomic(
            TICKER_CACHE_FILE,
            {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "records": tickers,
            },
        )
    except OSError:
        pass


def get_ticker_cache_age_minutes() -> float:
    if not TICKER_CACHE_FILE.exists():
        return float("inf")
    try:
        with TICKER_CACHE_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        saved_at = payload.get("saved_at")
        if saved_at:
            saved = datetime.fromisoformat(saved_at)
            return max(0.0, (datetime.now() - saved).total_seconds() / 60)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return file_age_minutes(TICKER_CACHE_FILE)


def get_environment_status(client: UpbitPublicClient) -> dict:
    try:
        markets = client.get_markets()
        return {"api_ok": bool(markets), "offline_mode": not bool(markets), "markets": markets}
    except Exception as exc:
        return {
            "api_ok": False,
            "offline_mode": True,
            "markets": [],
            "reason": str(exc),
        }


def load_market_info(
    client: UpbitPublicClient,
    status: dict,
) -> tuple[list[str], dict[str, str]]:
    if status["api_ok"]:
        try:
            markets = status["markets"] or client.get_markets()
            krw_markets = [m for m in markets if str(m.get("market", "")).startswith("KRW-")]
            pairs = [m["market"] for m in krw_markets]
            names = {
                m["market"]: m.get("korean_name", m["market"].replace("KRW-", ""))
                for m in krw_markets
            }
            save_market_cache(pairs, names)
            return pairs, names
        except Exception:
            pass

    pairs, names = load_market_cache()
    if pairs:
        return pairs, names

    defaults = [
        "KRW-BTC",
        "KRW-ETH",
        "KRW-XRP",
        "KRW-SOL",
        "KRW-ADA",
        "KRW-DOGE",
        "KRW-DOT",
        "KRW-LINK",
    ]
    return defaults, {pair: pair.replace("KRW-", "") for pair in defaults}


def load_ticker_map(
    client: UpbitPublicClient,
    offline_mode: bool,
    settings: AppSettings,
) -> tuple[dict[str, dict], dict]:
    if not offline_mode:
        try:
            tickers = client.get_krw_tickers()
            if not tickers:
                raise RuntimeError("업비트 ticker 응답이 비어 있습니다.")
            save_ticker_cache(tickers)
            return (
                {item["market"]: item for item in tickers if "market" in item},
                {
                    "source": "api",
                    "age_minutes": 0.0,
                    "warning": False,
                    "usable_for_trading": True,
                },
            )
        except Exception:
            pass

    age = get_ticker_cache_age_minutes()
    cached = load_ticker_cache()
    if not cached:
        return {}, {
            "source": "missing",
            "age_minutes": age,
            "warning": True,
            "usable_for_trading": False,
        }

    if age > settings.ticker_cache_max_age_minutes:
        return {}, {
            "source": "stale_blocked",
            "age_minutes": age,
            "warning": True,
            "usable_for_trading": False,
        }

    return cached, {
        "source": "cache",
        "age_minutes": age,
        "warning": age > settings.ticker_cache_warn_minutes,
        "usable_for_trading": True,
    }


# =============================================================================
# 4. 지표 / 시장 구조
# =============================================================================
def keep_completed_candles(
    df: Optional[pd.DataFrame],
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    now = pd.Timestamp.now(tz="Asia/Seoul") if now_kst is None else pd.Timestamp(now_kst)
    if now.tzinfo is not None:
        now = now.tz_convert("Asia/Seoul").tz_localize(None)

    candle_end = df.index + pd.Timedelta(minutes=candle_unit)
    return df.loc[candle_end <= now].copy()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for period in MA_PERIODS:
        out[f"MA{period}"] = out["close"].rolling(period).mean()

    prev_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out[f"ATR{ATR_PERIOD}"] = true_range.rolling(ATR_PERIOD).mean()
    out["ATR_Pct"] = out[f"ATR{ATR_PERIOD}"] / out["close"].replace(0, np.nan) * 100

    volume_ema_col = f"VolumeEMA{VOLUME_EMA_PERIOD}"
    out[volume_ema_col] = out["volume"].ewm(
        span=VOLUME_EMA_PERIOD,
        adjust=False,
        min_periods=VOLUME_EMA_PERIOD,
    ).mean()
    out["VolumeRatio"] = out["volume"] / out[volume_ema_col].replace(0, np.nan)

    delta = out["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    rsi_col = f"RSI{RSI_PERIOD}"
    out[rsi_col] = rsi.clip(0, 100)

    center = out[rsi_col].ewm(
        span=DYNAMIC_RSI_CENTER_PERIOD,
        adjust=False,
        min_periods=DYNAMIC_RSI_CENTER_PERIOD,
    ).mean()
    std = out[rsi_col].rolling(DYNAMIC_RSI_STD_PERIOD).std()
    out["RSI_Dynamic_Center"] = center
    out["RSI_Dynamic_Upper"] = (center + DYNAMIC_RSI_STD_MULTIPLIER * std).clip(0, 100)
    out["RSI_Dynamic_Lower"] = (center - DYNAMIC_RSI_STD_MULTIPLIER * std).clip(0, 100)
    return out


def detect_swing_points(
    df: pd.DataFrame,
    left: int = SWING_LEFT_BARS,
    right: int = SWING_RIGHT_BARS,
) -> pd.DataFrame:
    columns = ["timestamp", "kind", "label", "price"]
    if df is None or df.empty or len(df) < left + right + 3:
        return pd.DataFrame(columns=columns)

    highs: list[tuple[pd.Timestamp, float]] = []
    lows: list[tuple[pd.Timestamp, float]] = []

    for i in range(left, len(df) - right):
        high = float(df["high"].iloc[i])
        low = float(df["low"].iloc[i])
        left_high = float(df["high"].iloc[i - left : i].max())
        right_high = float(df["high"].iloc[i + 1 : i + 1 + right].max())
        left_low = float(df["low"].iloc[i - left : i].min())
        right_low = float(df["low"].iloc[i + 1 : i + 1 + right].min())

        # 같은 가격의 고점/저점이 연속될 때 중복 Pivot을 만드는 것을 줄이기 위해
        # 양쪽 모두보다 명확히 높은/낮은 봉만 Pivot으로 인정한다.
        if high > max(left_high, right_high):
            highs.append((df.index[i], high))
        if low < min(left_low, right_low):
            lows.append((df.index[i], low))

    points: list[dict] = []
    previous_high = None
    for timestamp, price in highs:
        label = "H" if previous_high is None else ("HH" if price > previous_high else "LH")
        points.append({"timestamp": timestamp, "kind": "high", "label": label, "price": price})
        previous_high = price

    previous_low = None
    for timestamp, price in lows:
        label = "L" if previous_low is None else ("HL" if price > previous_low else "LL")
        points.append({"timestamp": timestamp, "kind": "low", "label": label, "price": price})
        previous_low = price

    return (
        pd.DataFrame(points, columns=columns).sort_values("timestamp").reset_index(drop=True)
        if points
        else pd.DataFrame(columns=columns)
    )


def classify_swing_structure(points: pd.DataFrame) -> str:
    if points is None or points.empty:
        return "데이터 부족"

    highs = points.loc[points["label"].isin(["HH", "LH"]), "label"]
    lows = points.loc[points["label"].isin(["HL", "LL"]), "label"]
    if highs.empty or lows.empty:
        return "데이터 부족"
    return f"{highs.iloc[-1]}/{lows.iloc[-1]}"


def calculate_rolling_change_24h(df: pd.DataFrame) -> float:
    if df.empty:
        return np.nan

    latest_time = df.index[-1]
    past = df.loc[df.index <= latest_time - pd.Timedelta(hours=24), "close"]
    if past.empty or float(past.iloc[-1]) <= 0:
        return np.nan
    return (float(df["close"].iloc[-1]) / float(past.iloc[-1]) - 1) * 100


def calculate_trade_value_24h(df: pd.DataFrame) -> float:
    if df.empty:
        return np.nan

    recent = df.loc[df.index > df.index[-1] - pd.Timedelta(hours=24)]
    if "trade_value" in recent.columns:
        return float(recent["trade_value"].sum())
    return float((recent["close"] * recent["volume"]).sum())


def is_uptrend(df: pd.DataFrame) -> tuple[bool, bool, dict[int, float]]:
    latest = df.iloc[-1]
    ordered = latest["MA5"] > latest["MA20"] > latest["MA60"] > latest["MA120"]

    slopes: dict[int, float] = {}
    rising: list[bool] = []
    for period, lookback in MA_SLOPE_LOOKBACKS.items():
        current_ma = float(df[f"MA{period}"].iloc[-1])
        past_ma = float(df[f"MA{period}"].iloc[-1 - lookback])
        if pd.isna(current_ma) or pd.isna(past_ma) or past_ma <= 0:
            return bool(ordered), False, slopes
        slopes[period] = (current_ma / past_ma - 1) * 100
        rising.append(current_ma > past_ma)

    return bool(ordered), all(rising), slopes


def calculate_btc_regime(df: Optional[pd.DataFrame]) -> dict:
    empty = {
        "label": "확인 불가",
        "score": np.nan,
        "change_24h": np.nan,
        "return_7d": np.nan,
        "ma120_dist_pct": np.nan,
        "ma20_slope_24h_pct": np.nan,
    }
    work = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    if len(work) < 130:
        return empty

    work = add_indicators(work)
    latest = work.iloc[-1]
    ma120 = latest.get("MA120", np.nan)
    ma20 = latest.get("MA20", np.nan)
    ma20_past = work["MA20"].iloc[-7]
    if any(pd.isna(v) for v in (ma120, ma20, ma20_past)):
        return empty

    close = float(latest["close"])
    change_24h = calculate_rolling_change_24h(work)
    return_7d = (close / float(work["close"].iloc[-43]) - 1) * 100
    ma120_dist = (close / float(ma120) - 1) * 100
    ma20_slope = (float(ma20) / float(ma20_past) - 1) * 100

    score = sum(
        (
            close > float(ma120),
            float(ma20) > float(ma20_past),
            pd.notna(change_24h) and change_24h > 0,
            return_7d > 0,
        )
    )
    labels = {0: "Q1 Weak", 1: "Q1 Weak", 2: "Q2 Neutral", 3: "Q3 Strong", 4: "Q4 Very Strong"}
    return {
        "label": labels[int(score)],
        "score": int(score),
        "change_24h": float(change_24h),
        "return_7d": float(return_7d),
        "ma120_dist_pct": float(ma120_dist),
        "ma20_slope_24h_pct": float(ma20_slope),
    }


# =============================================================================
# 5. 후보 분석 / 점수 / 매매 계획
# =============================================================================
def analyze_screen_symbol(
    symbol: str,
    korean_name: str,
    df: pd.DataFrame,
    ticker: Optional[dict],
    settings: AppSettings,
) -> Optional[dict]:
    work = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    min_required = max(MA_PERIODS) + max(MA_SLOPE_LOOKBACKS.values())
    if len(work) < min_required:
        return None

    work = add_indicators(work)
    latest = work.iloc[-1]
    if latest[[f"MA{x}" for x in MA_PERIODS]].isna().any():
        return None

    ordered, ma_rising, slopes = is_uptrend(work)
    if not ordered or (REQUIRE_MA_RISING and not ma_rising):
        return None

    change_24h = calculate_rolling_change_24h(work)
    if pd.isna(change_24h) or not (
        settings.min_change_24h <= change_24h <= settings.max_change_24h
    ):
        return None

    if ticker:
        current_price = as_float(ticker.get("trade_price"), float(latest["close"]))
        trade_value = as_float(ticker.get("acc_trade_price_24h"), np.nan)
    else:
        current_price = float(latest["close"])
        trade_value = calculate_trade_value_24h(work)

    if pd.isna(trade_value) or trade_value < settings.min_trade_value_24h:
        return None

    swing_points = detect_swing_points(work)
    return {
        "symbol": symbol,
        "korean_name": korean_name,
        "price": current_price,
        "change_24h": float(change_24h),
        "trade_value_24h": float(trade_value),
        **{f"MA{p}_240m": float(latest[f"MA{p}"]) for p in MA_PERIODS},
        "ma_rising_240m": ma_rising,
        **{f"MA{p}_slope_pct_240m": slopes.get(p, np.nan) for p in (20, 60, 120)},
        "last_completed_240m": work.index[-1],
        "RSI14_240m": float(latest.get("RSI14", np.nan)),
        "RSI_dynamic_upper_240m": float(latest.get("RSI_Dynamic_Upper", np.nan)),
        "RSI_dynamic_center_240m": float(latest.get("RSI_Dynamic_Center", np.nan)),
        "RSI_dynamic_lower_240m": float(latest.get("RSI_Dynamic_Lower", np.nan)),
        "VolumeEMA20_240m": float(latest.get("VolumeEMA20", np.nan)),
        "VolumeRatio_240m": float(latest.get("VolumeRatio", np.nan)),
        "ATR_Pct_240m": float(latest.get("ATR_Pct", np.nan)),
        "swing_structure": classify_swing_structure(swing_points),
        "swing_points": swing_points,
        "df_240m": work,
    }


def analyze_entry_timing(
    df: Optional[pd.DataFrame],
    current_price: Optional[float] = None,
) -> dict:
    empty = {
        "entry_status": "데이터 부족",
        "entry_score": 0,
        "entry_distance_ma20_pct": np.nan,
        "MA5_60m": np.nan,
        "MA20_60m": np.nan,
        "MA60_60m": np.nan,
        "close_60m": np.nan,
        "entry_price": np.nan,
        "entry_above_ma20": False,
        "entry_short_ordered": False,
        "entry_ma5_rising": False,
        "entry_close_rising": False,
        "ATR14_60m": np.nan,
        "last_completed_60m": pd.NaT,
    }

    work = keep_completed_candles(df, ENTRY_CANDLE_UNIT)
    if len(work) < 65:
        return empty

    work = add_indicators(work)
    latest = work.iloc[-1]
    required = ["MA5", "MA20", "MA60", f"ATR{ATR_PERIOD}"]
    if latest[required].isna().any():
        return empty

    candle_close = float(latest["close"])
    ma5, ma20, ma60 = (float(latest[f"MA{x}"]) for x in (5, 20, 60))
    atr = float(latest[f"ATR{ATR_PERIOD}"])
    if ma20 <= 0 or atr <= 0:
        return empty

    entry_price = (
        candle_close
        if current_price is None or pd.isna(current_price) or current_price <= 0
        else float(current_price)
    )
    distance = (entry_price / ma20 - 1) * 100
    ma5_rising = bool(work["MA5"].iloc[-1] > work["MA5"].iloc[-4])
    close_rising = bool(work["close"].iloc[-1] > work["close"].iloc[-2])
    short_ordered = ma5 > ma20 > ma60

    score = sum((entry_price >= ma20, short_ordered, ma5_rising, close_rising))
    if ENTRY_PULLBACK_MIN_PCT <= distance <= ENTRY_PULLBACK_MAX_PCT:
        score += 2

    if entry_price < ma20:
        status = "MA20 하회"
    elif distance > ENTRY_OVERHEAT_PCT:
        status = "과열 주의"
    elif ENTRY_PULLBACK_MIN_PCT <= distance <= ENTRY_PULLBACK_MAX_PCT:
        status = "진입 관심" if short_ordered and ma5_rising and close_rising else "눌림 확인"
    else:
        status = "눌림 대기"

    return {
        "entry_status": status,
        "entry_score": int(score),
        "entry_distance_ma20_pct": float(distance),
        "MA5_60m": ma5,
        "MA20_60m": ma20,
        "MA60_60m": ma60,
        "close_60m": candle_close,
        "entry_price": entry_price,
        "entry_above_ma20": entry_price >= ma20,
        "entry_short_ordered": short_ordered,
        "entry_ma5_rising": ma5_rising,
        "entry_close_rising": close_rising,
        "ATR14_60m": atr,
        "last_completed_60m": work.index[-1],
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def calculate_final_score(item: dict, settings: AppSettings) -> dict:
    trend_score = 0.0
    for period, threshold in {20: 2.0, 60: 1.5, 120: 1.0}.items():
        slope = item.get(f"MA{period}_slope_pct_240m", np.nan)
        slope = 0.0 if pd.isna(slope) else float(slope)
        trend_score += 10.0 * clamp(slope / threshold, 0.0, 1.0)

    entry_score = 10.0 * sum(
        bool(item.get(key, False))
        for key in (
            "entry_above_ma20",
            "entry_short_ordered",
            "entry_ma5_rising",
            "entry_close_rising",
        )
    )

    distance = item.get("entry_distance_ma20_pct", np.nan)
    if pd.isna(distance):
        ma20_score = 0.0
    elif 0 <= distance <= 3:
        ma20_score = 20.0
    elif 3 < distance <= 5:
        ma20_score = 15.0
    elif 5 < distance <= 8:
        ma20_score = 8.0
    elif -1 <= distance < 0:
        ma20_score = 5.0
    else:
        ma20_score = 0.0

    change = float(item.get("change_24h", 0) or 0)
    momentum_score = 6.0 if 3 <= change <= 8 else 4.0 if 1 <= change < 3 else 3.0 if 8 < change <= 12 else 0.0

    trade_value = float(item.get("trade_value_24h", 0) or 0)
    if trade_value >= 10_000_000_000:
        liquidity_score = 4.0
    elif trade_value >= 3_000_000_000:
        liquidity_score = 3.0
    elif trade_value >= 1_000_000_000:
        liquidity_score = 2.0
    elif trade_value >= settings.min_trade_value_24h:
        liquidity_score = 1.0
    else:
        liquidity_score = 0.0

    market_score = momentum_score + liquidity_score
    penalty_overheat = 15.0 if pd.notna(distance) and distance > ENTRY_OVERHEAT_PCT else 0.0
    penalty_below = 10.0 if pd.notna(distance) and distance < 0 else 0.0
    penalty_surge = 10.0 if change > 12.0 else 0.0
    penalty = penalty_overheat + penalty_below + penalty_surge

    final_score = clamp(trend_score + entry_score + ma20_score + market_score - penalty, 0.0, 100.0)
    return {
        "final_score": round(final_score, 1),
        "score_trend_4h": round(trend_score, 1),
        "score_entry_1h": round(entry_score, 1),
        "score_ma20_position": round(ma20_score, 1),
        "score_market_quality": round(market_score, 1),
        "score_penalty": round(penalty, 1),
        "penalty_overheat": round(penalty_overheat, 1),
        "penalty_below_ma20": round(penalty_below, 1),
        "penalty_daily_surge": round(penalty_surge, 1),
    }


def empty_strategy(reason: str = "데이터 부족", **values) -> dict:
    result = {
        "strategy_available": False,
        "buy_zone_low": np.nan,
        "buy_zone_high": np.nan,
        "buy_reference": np.nan,
        "stop_price": np.nan,
        "breakeven_stop": np.nan,
        "trailing_stop_normal": np.nan,
        "trailing_stop_tight": np.nan,
        "trailing_stop_current": np.nan,
        "take_profit_1": np.nan,
        "take_profit_2": np.nan,
        "runner_trigger_4r": np.nan,
        "runner_mode": reason,
        "risk_per_unit": np.nan,
        "risk_pct": np.nan,
        "atr14": np.nan,
        "risk_budget": np.nan,
        "position_amount": np.nan,
        "position_quantity": np.nan,
        "actual_risk_amount": np.nan,
        "actual_risk_pct": np.nan,
        "position_capped": False,
    }
    result.update(values)
    return result


def calculate_ma_atr_strategy(item: dict, settings: AppSettings) -> dict:
    current_price = float(item.get("price", np.nan))
    ma20 = float(item.get("MA20_60m", np.nan))
    ma60 = float(item.get("MA60_60m", np.nan))
    atr = float(item.get("ATR14_60m", np.nan))

    if any(pd.isna(v) for v in (current_price, ma20, ma60, atr)) or min(current_price, ma20, ma60, atr) <= 0:
        return empty_strategy(atr14=atr)

    buy_low = max(0.0, ma20 - BUY_ZONE_ATR * atr)
    buy_high = ma20 + BUY_ZONE_ATR * atr
    if current_price > buy_high:
        buy_reference = buy_high
    elif current_price < buy_low:
        buy_reference = ma20 + 0.10 * atr
    else:
        buy_reference = current_price

    stop_price = max(ma60 - STOP_MA60_ATR * atr, buy_reference - MAX_STOP_ATR * atr)
    stop_price = min(stop_price, buy_low - 0.25 * atr)

    min_risk = MIN_RISK_ATR * atr
    risk_per_unit = buy_reference - stop_price
    if risk_per_unit < min_risk:
        risk_per_unit = min_risk
        stop_price = buy_reference - risk_per_unit

    stop_price = max(0.0, stop_price)
    risk_per_unit = buy_reference - stop_price
    if risk_per_unit <= 0:
        return empty_strategy(
            "손절폭 오류",
            buy_zone_low=buy_low,
            buy_zone_high=buy_high,
            buy_reference=buy_reference,
            stop_price=stop_price,
            risk_per_unit=risk_per_unit,
            atr14=atr,
        )

    tp1 = buy_reference + TP1_R_MULTIPLIER * risk_per_unit
    tp2 = buy_reference + TP2_R_MULTIPLIER * risk_per_unit
    runner_trigger = buy_reference + RUNNER_TRIGGER_R * risk_per_unit
    breakeven = buy_reference
    trail_normal = max(breakeven, ma20 - TRAIL_ATR_MULTIPLIER * atr)
    trail_tight = max(breakeven, ma20 - RUNNER_TRAIL_ATR_MULTIPLIER * atr)

    if current_price >= runner_trigger:
        trail_current = trail_tight
        runner_mode = "4R 이후 강화 Trail(1.5ATR)"
    else:
        trail_current = trail_normal
        runner_mode = "기본 Trail(2ATR)"

    risk_pct = risk_per_unit / buy_reference * 100
    risk_budget = settings.account_capital * settings.risk_per_trade_pct / 100
    max_position_amount = settings.account_capital * settings.max_position_pct / 100
    raw_quantity = risk_budget / risk_per_unit
    raw_position_amount = raw_quantity * buy_reference
    position_amount = min(raw_position_amount, max_position_amount, settings.account_capital)
    position_quantity = position_amount / buy_reference
    actual_risk_amount = position_quantity * risk_per_unit
    actual_risk_pct = actual_risk_amount / settings.account_capital * 100

    return {
        "strategy_available": True,
        "buy_zone_low": buy_low,
        "buy_zone_high": buy_high,
        "buy_reference": buy_reference,
        "stop_price": stop_price,
        "breakeven_stop": breakeven,
        "trailing_stop_normal": trail_normal,
        "trailing_stop_tight": trail_tight,
        "trailing_stop_current": trail_current,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "runner_trigger_4r": runner_trigger,
        "runner_mode": runner_mode,
        "risk_per_unit": risk_per_unit,
        "risk_pct": risk_pct,
        "atr14": atr,
        "risk_budget": risk_budget,
        "position_amount": position_amount,
        "position_quantity": position_quantity,
        "actual_risk_amount": actual_risk_amount,
        "actual_risk_pct": actual_risk_pct,
        "position_capped": position_amount + 1e-9 < raw_position_amount,
    }


def classify_candidate(item: dict) -> str:
    status = item.get("entry_status", "미확인")
    change = float(item.get("change_24h", 0) or 0)
    if status == "진입 관심":
        return "강한상승+진입 가능" if change >= STRONG_RISE_24H_PCT else "우선관찰"
    if status in {"눌림 확인", "눌림 대기"}:
        return "눌림 기다리기"
    if status == "과열 주의":
        return "과열 주의"
    if status in {"MA20 하회", "추세 확인 필요"}:
        return "반등 확인 필요"
    return "확인 필요"


def make_final_investment_advice(item: dict) -> tuple[str, str]:
    regime = str(item.get("btc_regime", "확인 불가"))
    rs = item.get("rs_vs_btc_24h", np.nan)
    swing = str(item.get("swing_structure", "데이터 부족"))
    entry = str(item.get("entry_status", "미확인"))
    distance = item.get("entry_distance_ma20_pct", np.nan)
    rsi = item.get("RSI14_240m", np.nan)
    upper = item.get("RSI_dynamic_upper_240m", np.nan)
    lower = item.get("RSI_dynamic_lower_240m", np.nan)
    volume_ratio = item.get("VolumeRatio_240m", np.nan)

    rs_positive = pd.notna(rs) and float(rs) > 0
    rs_strong = pd.notna(rs) and float(rs) >= 2.0
    volume_ok = pd.notna(volume_ratio) and float(volume_ratio) >= 1.0
    volume_strong = pd.notna(volume_ratio) and float(volume_ratio) >= 1.5
    rsi_over = pd.notna(rsi) and pd.notna(upper) and float(rsi) >= float(upper)
    rsi_below = pd.notna(rsi) and pd.notna(lower) and float(rsi) < float(lower)

    reasons: list[str] = []
    if regime.startswith("Q1"):
        reasons.append("BTC 시장이 Q1 약세")
        if not rs_positive:
            reasons.append("BTC 대비 상대강도도 약함")
        if swing == "LH/LL":
            reasons.append("4시간봉이 LH/LL 하락 구조")
        return "신규매수 보류", " · ".join(reasons) + " → 시장 회복과 구조 반전을 먼저 확인하세요."

    if swing == "LH/LL":
        reasons.append("4시간봉이 LH/LL 하락 구조")
        if not rs_positive:
            reasons.append("RS vs BTC가 음수")
        return "관망 / 반등 확인", " · ".join(reasons) + " → 최소한 HL 또는 HH 전환을 확인한 뒤 접근하는 편이 낫습니다."

    if entry == "과열 주의" or (pd.notna(distance) and float(distance) > ENTRY_OVERHEAT_PCT):
        reasons.append("1시간 MA20 이격이 큼")
        if rsi_over:
            reasons.append("RSI가 Dynamic Upper 부근/이상")
        return "추격매수 자제", " · ".join(reasons) + " → MA20 근처 눌림이나 재돌파 확인을 기다리세요."

    if entry == "MA20 하회":
        reasons.append("현재가가 1시간 MA20 아래")
        if rsi_below:
            reasons.append("RSI도 Dynamic Lower 아래")
        return "반등 확인 후 접근", " · ".join(reasons) + " → 1시간 MA20 회복과 거래량 동반을 확인하는 것이 우선입니다."

    strong_market = regime.startswith(("Q3", "Q4"))
    good_swing = swing == "HH/HL"
    good_entry = entry in {"진입 관심", "눌림 확인"}

    if strong_market and good_swing and rs_positive and good_entry:
        reasons.extend([regime, "BTC 대비 상대강도 우위", "HH/HL 상승 구조"])
        reasons.append(
            "거래량이 EMA20 대비 강함"
            if volume_strong
            else "거래량이 평균 이상"
            if volume_ok
            else "거래량 확인 필요"
        )
        if rsi_over:
            return "눌림 후 분할매수 관심", " · ".join(reasons) + " · RSI가 상단에 가까워 즉시 추격보다 눌림 진입이 유리합니다."
        if rs_strong and volume_ok:
            return "분할매수 관심", " · ".join(reasons) + " → 계획 매수구간과 손절선을 지키는 전제에서 우선순위가 높은 후보입니다."
        return "매수 관심", " · ".join(reasons) + " → 진입구간 도달 여부를 확인한 뒤 분할 접근을 고려할 수 있습니다."

    if good_swing and rs_positive:
        reasons.extend(["HH/HL 상승 구조", "RS vs BTC 양수"])
        if entry in {"눌림 대기", "눌림 확인"}:
            reasons.append("아직 최적 진입 위치 대기")
        if not volume_ok:
            reasons.append("거래량 확증 부족")
        return "눌림 대기", " · ".join(reasons) + " → 가격을 쫓기보다 1시간 MA20 부근의 반등 확인이 좋습니다."

    if swing in {"HH/LL", "LH/HL"}:
        reasons.append(f"Swing 구조가 {swing}로 혼재")
    if not rs_positive:
        reasons.append("BTC 대비 상대강도가 약함")
    if entry in {"눌림 대기", "눌림 확인"}:
        reasons.append("진입 신호가 아직 완성되지 않음")

    if not reasons:
        reasons.append("핵심 조건이 아직 충분히 정렬되지 않음")
    return "관망", " · ".join(reasons) + " → 추가 확인 전에는 신규 진입 우선순위를 낮게 두는 편이 좋습니다."


def finalize_results(results: list[dict], settings: AppSettings) -> pd.DataFrame:
    rows = []
    for item in results:
        item.update(calculate_final_score(item, settings))
        item.update(calculate_ma_atr_strategy(item, settings))
        action, advice = make_final_investment_advice(item)
        item["final_action"] = action
        item["final_advice"] = advice

        rows.append(
            {
                "symbol": item["symbol"],
                "korean_name": item["korean_name"],
                "judgement": classify_candidate(item),
                "final_action": action,
                "final_advice": advice,
                "final_score": item["final_score"],
                "price": item["price"],
                "change_24h": round(item["change_24h"], 2),
                "btc_regime": item.get("btc_regime", "확인 불가"),
                "rs_vs_btc_24h": item.get("rs_vs_btc_24h", np.nan),
                "swing_structure": item.get("swing_structure", "데이터 부족"),
                "rsi14_240m": item.get("RSI14_240m", np.nan),
                "volume_ratio_240m": item.get("VolumeRatio_240m", np.nan),
                "atr_pct_240m": item.get("ATR_Pct_240m", np.nan),
                "trade_value_24h": round(item["trade_value_24h"]),
                **{f"MA{p}_240m": item.get(f"MA{p}_240m", np.nan) for p in (20, 60, 120)},
                **{f"MA{p}_slope_pct_240m": item.get(f"MA{p}_slope_pct_240m", np.nan) for p in (20, 60, 120)},
                "ma_rising_240m": item.get("ma_rising_240m", False),
                "last_completed_240m": item.get("last_completed_240m"),
                "last_completed_60m": item.get("last_completed_60m"),
                "entry_status": item.get("entry_status", "미확인"),
                "entry_score": item.get("entry_score", 0),
                "entry_distance_ma20_pct": item.get("entry_distance_ma20_pct", np.nan),
                "MA20_60m": item.get("MA20_60m", np.nan),
                "entry_price": item.get("entry_price", np.nan),
                "ATR14_60m": item.get("ATR14_60m", np.nan),
                **{key: item.get(key, np.nan) for key in (
                    "buy_zone_low",
                    "buy_zone_high",
                    "buy_reference",
                    "stop_price",
                    "breakeven_stop",
                    "trailing_stop_normal",
                    "trailing_stop_tight",
                    "trailing_stop_current",
                    "take_profit_1",
                    "take_profit_2",
                    "runner_trigger_4r",
                    "risk_pct",
                    "risk_budget",
                    "position_amount",
                    "position_quantity",
                    "actual_risk_amount",
                    "actual_risk_pct",
                )},
                "runner_mode": item.get("runner_mode", ""),
                "position_capped": item.get("position_capped", False),
                **{key: item.get(key, 0.0) for key in (
                    "score_trend_4h",
                    "score_entry_1h",
                    "score_ma20_position",
                    "score_market_quality",
                    "score_penalty",
                    "penalty_overheat",
                    "penalty_below_ma20",
                    "penalty_daily_surge",
                )},
            }
        )

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values(
            ["final_score", "entry_score", "trade_value_24h", "change_24h"],
            ascending=[False, False, False, False],
        )
        .reset_index(drop=True)
    )


# =============================================================================
# 6. 전체 분석 실행
# =============================================================================
def run_analysis(settings: AppSettings, progress_bar=None, status_box=None) -> dict:
    client = UpbitPublicClient()
    try:
        if status_box is not None:
            status_box.info("업비트 API 및 캐시 상태를 확인하는 중입니다.")

        status = get_environment_status(client)
        pairs, name_map = load_market_info(client, status)
        if not pairs:
            raise RuntimeError("분석할 KRW 마켓이 없습니다.")

        # 마켓 목록 API가 일시 실패해도 ticker API는 독립적으로 한 번 확인한다.
        # 둘 다 실패한 경우에만 캔들 조회를 오프라인/캐시 우선으로 전환한다.
        ticker_map, ticker_info = load_ticker_map(client, False, settings)
        offline_mode = status["offline_mode"] and ticker_info.get("source") != "api"
        if not ticker_info["usable_for_trading"]:
            raise RuntimeError(
                "최신 ticker 데이터가 없습니다. API 연결 또는 허용시간 이내의 ticker 캐시가 필요합니다."
            )

        target_pairs = [
            symbol
            for symbol in pairs
            if as_float(ticker_map.get(symbol, {}).get("acc_trade_price_24h"), 0.0)
            >= settings.min_trade_value_24h
        ] if ticker_map else pairs

        source_count_240 = {"cache": 0, "api": 0, "stale": 0, "missing": 0}
        source_count_60 = {"cache": 0, "api": 0, "stale": 0, "missing": 0}
        errors: list[tuple[str, str]] = []

        btc_df = None
        btc_source = "missing"
        btc_regime = {"label": "확인 불가", "score": np.nan, "change_24h": np.nan}
        try:
            btc_df, btc_source = get_ohlcv(
                client, "KRW-BTC", SCREEN_CANDLE_UNIT, offline_mode, settings
            )
            btc_regime = calculate_btc_regime(btc_df)
        except Exception as exc:
            errors.append(("KRW-BTC", f"BTC regime: {exc}"))

        results: list[dict] = []
        total = max(1, len(target_pairs))

        for idx, symbol in enumerate(target_pairs, start=1):
            if status_box is not None:
                status_box.info(f"1/2 · 4시간봉 분석 {idx}/{len(target_pairs)} · {symbol}")
            if progress_bar is not None:
                progress_bar.progress(min(0.70, 0.70 * idx / total))

            try:
                if symbol == "KRW-BTC" and btc_df is not None:
                    df_240m, source = btc_df, btc_source
                else:
                    df_240m, source = get_ohlcv(
                        client, symbol, SCREEN_CANDLE_UNIT, offline_mode, settings
                    )
                source_count_240[source] = source_count_240.get(source, 0) + 1
                if df_240m is None:
                    continue

                item = analyze_screen_symbol(
                    symbol,
                    name_map.get(symbol, symbol.replace("KRW-", "")),
                    df_240m,
                    ticker_map.get(symbol),
                    settings,
                )
                if item is None:
                    continue

                btc_change = btc_regime.get("change_24h", np.nan)
                item.update(
                    {
                        "btc_regime": btc_regime.get("label", "확인 불가"),
                        "btc_regime_score": btc_regime.get("score", np.nan),
                        "btc_change_24h": btc_change,
                        "rs_vs_btc_24h": (
                            float(item["change_24h"]) - float(btc_change)
                            if pd.notna(btc_change)
                            else np.nan
                        ),
                    }
                )
                results.append(item)
            except Exception as exc:
                errors.append((symbol, f"240m: {exc}"))

        if results:
            total_entry = len(results)
            for idx, item in enumerate(results, start=1):
                symbol = item["symbol"]
                if status_box is not None:
                    status_box.info(f"2/2 · 1시간봉 진입 확인 {idx}/{total_entry} · {symbol}")
                if progress_bar is not None:
                    progress_bar.progress(0.70 + 0.30 * idx / total_entry)

                try:
                    df_60m, source = get_ohlcv(
                        client, symbol, ENTRY_CANDLE_UNIT, offline_mode, settings
                    )
                    source_count_60[source] = source_count_60.get(source, 0) + 1
                    item.update(analyze_entry_timing(df_60m, current_price=item["price"]))
                    item["df_60m"] = df_60m if df_60m is not None else pd.DataFrame()
                except Exception as exc:
                    errors.append((symbol, f"60m: {exc}"))
                    item.update(analyze_entry_timing(None, current_price=item["price"]))
                    item["df_60m"] = pd.DataFrame()

        result_table = finalize_results(results, settings)
        by_symbol = {item["symbol"]: item for item in results}
        sorted_results = (
            [by_symbol[s] for s in result_table["symbol"] if s in by_symbol]
            if not result_table.empty
            else []
        )

        if not result_table.empty:
            try:
                result_table.to_csv(RESULT_CSV, index=False, encoding="utf-8-sig")
            except OSError as exc:
                errors.append(("CSV", f"저장 실패: {exc}"))

        if progress_bar is not None:
            progress_bar.progress(1.0)
        if status_box is not None:
            status_box.success("분석이 완료되었습니다.")

        return {
            "status": status,
            "offline_mode": offline_mode,
            "krw_pairs": pairs,
            "target_pairs": target_pairs,
            "ticker_info": ticker_info,
            "btc_regime": btc_regime,
            "results": results,
            "result_table": result_table,
            "sorted_results": sorted_results,
            "source_count_240": source_count_240,
            "source_count_60": source_count_60,
            "errors": errors,
            "settings": asdict(settings),
            "settings_signature": settings.analysis_signature(),
        }
    finally:
        client.close()


# =============================================================================
# 7. 표 / 차트용 데이터
# =============================================================================
def make_compact_display_table(result_table: pd.DataFrame, top_n: int) -> pd.DataFrame:
    top = result_table.head(top_n).copy()
    top["매수구간"] = top.apply(
        lambda row: (
            f"{format_price(row['buy_zone_low'])}~{format_price(row['buy_zone_high'])}"
            if pd.notna(row["buy_zone_low"]) and pd.notna(row["buy_zone_high"])
            else "-"
        ),
        axis=1,
    )

    columns = [
        "symbol",
        "korean_name",
        "judgement",
        "final_action",
        "final_advice",
        "final_score",
        "price",
        "change_24h",
        "btc_regime",
        "rs_vs_btc_24h",
        "swing_structure",
        "매수구간",
        "stop_price",
        "take_profit_1",
        "take_profit_2",
        "runner_trigger_4r",
    ]
    names = {
        "symbol": "종목",
        "korean_name": "한글명",
        "judgement": "판단",
        "final_action": "최종 판단",
        "final_advice": "투자 조언",
        "final_score": "FinalScore",
        "price": "현재가",
        "change_24h": "24h 등락",
        "btc_regime": "BTC Regime",
        "rs_vs_btc_24h": "RS vs BTC",
        "swing_structure": "Swing 구조",
        "stop_price": "손절",
        "take_profit_1": "1차익절(30%)",
        "take_profit_2": "2차익절(30%)",
        "runner_trigger_4r": "Runner강화(4R)",
    }
    return top[columns].rename(columns=names)


def make_summary_lines(result_table: pd.DataFrame, top_n: int) -> list[str]:
    groups = [
        ("우선관찰", "추세 양호 + 1시간 MA20 근접"),
        ("강한상승+진입 가능", "조건은 좋지만 급등폭 주의"),
        ("눌림 기다리기", "추세 유지, 더 좋은 가격 대기"),
        ("과열 주의", "MA20 이격이 커 추격 자제"),
        ("반등 확인 필요", "1시간 MA20 회복 확인"),
        ("확인 필요", "추가 데이터 확인"),
    ]

    top = result_table.head(top_n)
    lines = []
    for label, note in groups:
        selected = top.loc[top["judgement"] == label, ["symbol", "korean_name"]]
        if selected.empty:
            continue
        names = ", ".join(
            f"{row['symbol'].replace('KRW-', '')}({row['korean_name']})"
            for _, row in selected.iterrows()
        )
        lines.append(f"**{label} ({len(selected)})**: {names} → {note}")
    return lines


def make_strategy_display_table(sorted_results: list[dict], count: int) -> pd.DataFrame:
    rows = []
    for item in sorted_results[:count]:
        if not item.get("strategy_available", False):
            continue
        rows.append(
            {
                "종목": item["symbol"],
                "한글명": item["korean_name"],
                "상태": item.get("entry_status", "미확인"),
                "현재가": item["price"],
                "매수구간 하단": item["buy_zone_low"],
                "매수구간 상단": item["buy_zone_high"],
                "손절": item["stop_price"],
                "손절폭(%)": item["risk_pct"],
                "1차 익절(30%)": item["take_profit_1"],
                "2차 익절(30%)": item["take_profit_2"],
                "4R Runner 강화": item["runner_trigger_4r"],
                "현재 Trail": item["trailing_stop_current"],
                "Runner 모드": item["runner_mode"],
                "권장 매수금": item["position_amount"],
                "예상 최대손실": item["actual_risk_amount"],
                "실제 계좌위험(%)": item["actual_risk_pct"],
                "종목비중 제한": item["position_capped"],
            }
        )
    return pd.DataFrame(rows)


# =============================================================================
# 8. 차트
# =============================================================================
def plot_candle_with_strategy(df: pd.DataFrame, item: dict) -> plt.Figure:
    completed = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    required = {
        f"VolumeEMA{VOLUME_EMA_PERIOD}",
        f"RSI{RSI_PERIOD}",
        "RSI_Dynamic_Upper",
        "RSI_Dynamic_Center",
        "RSI_Dynamic_Lower",
    }
    if not required.issubset(completed.columns):
        completed = add_indicators(completed)
    df_plot = completed.tail(CHART_BARS).copy()

    if df_plot.empty:
        raise ValueError("차트에 표시할 완료된 4시간봉이 없습니다.")

    values = {
        "current": item["price"],
        "buy_low": item["buy_zone_low"],
        "buy_high": item["buy_zone_high"],
        "stop": item["stop_price"],
        "tp1": item["take_profit_1"],
        "tp2": item["take_profit_2"],
        "runner": item["runner_trigger_4r"],
        "trail": item["trailing_stop_current"],
    }

    buy_colors = ["#C62828", "#EF5350"]
    stop_color = "#6D4C41"
    trail_color = "#455A64"
    sell_colors = ["#00796B", "#009688", "#26A69A"]
    current_color = "#111111"
    ma_colors = {5: "#7B1FA2", 20: "#F57C00", 60: "#388E3C", 120: "#1565C0"}

    add_plots = [
        mpf.make_addplot(df_plot[f"MA{period}"], color=ma_colors[period], width=1.0, panel=0)
        for period in MA_PERIODS
        if f"MA{period}" in df_plot.columns
    ]
    add_plots.append(
        mpf.make_addplot(
            df_plot[f"VolumeEMA{VOLUME_EMA_PERIOD}"], panel=1, color="#616161", width=1.1
        )
    )
    add_plots.extend(
        [
            mpf.make_addplot(df_plot[f"RSI{RSI_PERIOD}"], panel=2, color="#7B1FA2", width=1.3, ylabel="RSI"),
            mpf.make_addplot(df_plot["RSI_Dynamic_Upper"], panel=2, color="#C62828", width=0.9),
            mpf.make_addplot(df_plot["RSI_Dynamic_Center"], panel=2, color="#616161", width=0.9),
            mpf.make_addplot(df_plot["RSI_Dynamic_Lower"], panel=2, color="#1565C0", width=0.9),
        ]
    )

    market_colors = mpf.make_marketcolors(
        up="red", down="blue", edge="inherit", wick="inherit", volume="inherit"
    )
    style = mpf.make_mpf_style(
        marketcolors=market_colors,
        rc={"font.family": KOREAN_FONT, "axes.unicode_minus": False},
    )

    fig, axes = mpf.plot(
        df_plot,
        type="candle",
        style=style,
        ylabel="가격 (원)",
        ylabel_lower="거래량",
        addplot=add_plots,
        hlines={
            "hlines": list(values.values()),
            "colors": [*buy_colors, stop_color, *sell_colors, trail_color, current_color],
            "linestyle": "--",
            "linewidths": 1.0,
            "alpha": 0.85,
        },
        volume=True,
        panel_ratios=(6, 2, 2),
        figsize=(14, 10),
        returnfig=True,
        warn_too_much_data=1000,
    )

    price_ax = axes[0]
    volume_ax = axes[2] if len(axes) >= 4 else axes[0]
    rsi_ax = axes[4] if len(axes) >= 6 else axes[-1]
    price_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: format_price(value)))

    handles = [
        plt.Line2D([0], [0], color=buy_colors[0], linestyle="--", label=f"매수구간 하단: {format_price(values['buy_low'])}원"),
        plt.Line2D([0], [0], color=buy_colors[1], linestyle="--", label=f"매수구간 상단: {format_price(values['buy_high'])}원"),
        plt.Line2D([0], [0], color=stop_color, linestyle="--", label=f"손절: {format_price(values['stop'])}원"),
        plt.Line2D([0], [0], color=sell_colors[0], linestyle="--", label=f"1차 익절 30%: {format_price(values['tp1'])}원"),
        plt.Line2D([0], [0], color=sell_colors[1], linestyle="--", label=f"2차 익절 30%: {format_price(values['tp2'])}원"),
        plt.Line2D([0], [0], color=sell_colors[2], linestyle="--", label=f"Runner 강화(4R): {format_price(values['runner'])}원"),
        plt.Line2D([0], [0], color=trail_color, linestyle="--", label=f"Runner Trail: {format_price(values['trail'])}원"),
        plt.Line2D([0], [0], color=current_color, linestyle="--", linewidth=1.5, label=f"현재가: {format_price(values['current'])}원"),
    ]
    handles.extend(
        plt.Line2D([0], [0], color=ma_colors[p], linewidth=1.5, label=f"MA{p}")
        for p in MA_PERIODS
    )
    price_ax.legend(handles=handles, loc="upper left", fontsize=7.5, ncol=2)

    swing_points = item.get("swing_points")
    if not isinstance(swing_points, pd.DataFrame):
        swing_points = detect_swing_points(completed)
    if not swing_points.empty:
        visible = swing_points[swing_points["timestamp"].isin(df_plot.index)]
        chart_range = max(float(df_plot["high"].max() - df_plot["low"].min()), 1e-12)
        for _, point in visible.iterrows():
            label = str(point["label"])
            if label not in {"HH", "HL", "LH", "LL"}:
                continue
            loc = df_plot.index.get_indexer([point["timestamp"]])[0]
            if loc < 0:
                continue
            price = float(point["price"])
            is_high = point["kind"] == "high"
            marker_y = price + chart_range * 0.018 if is_high else price - chart_range * 0.018
            text_y = price + chart_range * 0.040 if is_high else price - chart_range * 0.040
            color = "#D32F2F" if label in {"HH", "HL"} else "#1565C0"
            price_ax.scatter(loc, marker_y, marker="v" if is_high else "^", s=30, color=color, zorder=6, clip_on=False)
            price_ax.text(
                loc,
                text_y,
                label,
                ha="center",
                va="bottom" if is_high else "top",
                fontsize=7.5,
                fontweight="bold",
                color=color,
                clip_on=False,
            )

    volume_ax.legend(
        handles=[plt.Line2D([0], [0], color="#616161", linewidth=1.2, label=f"Volume EMA{VOLUME_EMA_PERIOD}")],
        loc="upper left",
        fontsize=7.5,
    )

    rsi_ax.set_ylim(0, 100)
    for level, style_line in ((70, "--"), (50, ":"), (30, "--")):
        rsi_ax.axhline(level, color="#BDBDBD", linestyle=style_line, linewidth=0.7, alpha=0.6)
    rsi_ax.legend(
        handles=[
            plt.Line2D([0], [0], color="#7B1FA2", linewidth=1.3, label=f"RSI{RSI_PERIOD}"),
            plt.Line2D([0], [0], color="#C62828", linewidth=0.9, label="Dynamic Upper"),
            plt.Line2D([0], [0], color="#616161", linewidth=0.9, label="Dynamic Center"),
            plt.Line2D([0], [0], color="#1565C0", linewidth=0.9, label="Dynamic Lower"),
        ],
        loc="upper left",
        fontsize=7.2,
        ncol=2,
    )

    n = len(df_plot)
    ticks = sorted(set(np.linspace(0, n - 1, min(7, n), dtype=int).tolist() + [n - 1]))
    rsi_ax.set_xticks(ticks)
    rsi_ax.set_xticklabels(
        [pd.Timestamp(df_plot.index[pos]).strftime("%m/%d %H:%M") for pos in ticks],
        rotation=45,
        ha="right",
    )

    fig.subplots_adjust(left=0.08, right=0.95, top=0.98, bottom=0.11, hspace=0.08)
    return fig


# =============================================================================
# 9. Streamlit UI
# =============================================================================
APP_CSS = """
<style>
header[data-testid="stHeader"], div[data-testid="stToolbar"] {display:none !important;}
.block-container {padding-top:1.2rem !important; padding-bottom:1rem !important; max-width:1500px;}
section[data-testid="stSidebar"] {width:295px !important; min-width:295px !important; background:#f3f5f9 !important; border-right:1px solid #e5e7eb;}
section[data-testid="stSidebar"] > div {width:295px !important; background:#f3f5f9 !important;}
section[data-testid="stSidebar"] .block-container {padding:0.45rem 0.90rem 0.55rem !important;}
.main-app-title {font-size:2.55rem; font-weight:800; line-height:1.24; letter-spacing:-0.03em; color:#2b2d3a; margin:0.25rem 0 0.7rem;}
.main-app-subtitle {font-size:0.97rem; color:#7b8190; margin:0 0 1rem;}
.main-top-divider {border:0; height:1px; background:#e5e7eb; margin:0.8rem 0 1.4rem;}
.info-banner {background:#eef2ff; border-radius:10px; padding:0.95rem 1rem; color:#1d4ed8; font-size:1rem; margin-bottom:1.2rem;}
.sidebar-section-title {font-size:1.05rem; font-weight:800; color:#2f3342; margin:0.32rem 0 0.30rem;}
.sidebar-gap {height:0.55rem;}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {gap:0.10rem !important;}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {gap:0.42rem !important;}
section[data-testid="stSidebar"] div[data-testid="stSlider"] {margin:0 0 0.08rem !important; padding:0 !important;}
section[data-testid="stSidebar"] div[data-testid="stSlider"] label {font-size:0.82rem !important; margin-bottom:0 !important;}
section[data-testid="stSidebar"] div[data-testid="stSlider"] [data-baseweb="slider"] * {font-size:0.90rem !important;}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] {margin:0 !important; padding:0 !important;}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] label {font-size:0.82rem !important; margin-bottom:0.08rem !important;}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] div[data-baseweb="input"] {min-height:2.05rem !important; height:2.05rem !important; border-radius:0.55rem !important;}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input {min-height:2.05rem !important; height:2.05rem !important; padding:0 0.55rem !important; font-size:0.93rem !important;}
section[data-testid="stSidebar"] div[data-testid="stButton"] button {min-height:2.15rem !important; height:2.15rem !important; margin-top:0.20rem !important; font-size:0.90rem !important; font-weight:700 !important; border-radius:10px !important;}
</style>
"""


def read_sidebar_settings() -> tuple[Optional[AppSettings], bool]:
    defaults = DEFAULT_SETTINGS
    with st.sidebar:
        st.markdown('<div class="sidebar-section-title">⚙ 분석 설정 · FINAL</div>', unsafe_allow_html=True)
        cache_minutes = st.slider("캐시 만료(분)", 10, 180, defaults.cache_minutes, 5)
        st.markdown('<div class="sidebar-gap"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">💰 포지션 리스크</div>', unsafe_allow_html=True)
        account_text = st.text_input("계좌 자금(원)", value=f"{defaults.account_capital:,.0f}")
        c1, c2 = st.columns(2)
        with c1:
            risk_text = st.text_input("위험(%)", value=f"{defaults.risk_per_trade_pct:.2f}")
        with c2:
            max_position_text = st.text_input("비중(%)", value=f"{defaults.max_position_pct:.2f}")
        st.markdown('<div class="sidebar-gap"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">🔍 필터링 조건</div>', unsafe_allow_html=True)
        min_change = st.slider("최소 변동률(%)", -10.0, 20.0, defaults.min_change_24h, 0.5)
        max_change = st.slider("최대 변동률(%)", 5.0, 50.0, defaults.max_change_24h, 0.5)
        min_trade_text = st.text_input("최소 거래대금(원)", value=f"{defaults.min_trade_value_24h:,.0f}")
        st.markdown('<div class="sidebar-gap"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">📋 출력</div>', unsafe_allow_html=True)
        o1, o2, o3 = st.columns(3)
        with o1:
            top_text = st.text_input("TOP", value=str(defaults.top_n))
        with o2:
            strategy_text = st.text_input("전략", value=str(defaults.strategy_n))
        with o3:
            chart_text = st.text_input("차트", value=str(defaults.chart_n))

        run_clicked = st.button("🚀 분석 실행", type="primary", width="stretch")

    try:
        settings = AppSettings(
            min_change_24h=float(min_change),
            max_change_24h=float(max_change),
            min_trade_value_24h=parse_number(min_trade_text, "최소 거래대금"),
            account_capital=parse_number(account_text, "계좌 자금"),
            risk_per_trade_pct=parse_number(risk_text, "거래 위험"),
            max_position_pct=parse_number(max_position_text, "최대 비중"),
            top_n=parse_number(top_text, "TOP", integer=True),
            strategy_n=parse_number(strategy_text, "전략", integer=True),
            chart_n=parse_number(chart_text, "차트", integer=True),
            cache_minutes=int(cache_minutes),
        )
    except ValueError as exc:
        st.sidebar.error(str(exc))
        return None, run_clicked

    errors = []
    if settings.min_change_24h > settings.max_change_24h:
        errors.append("최소 변동률은 최대 변동률보다 클 수 없습니다.")
    if settings.min_trade_value_24h < 1:
        errors.append("최소 거래대금은 1원 이상이어야 합니다.")
    if settings.account_capital < 100_000:
        errors.append("계좌 자금은 100,000원 이상이어야 합니다.")
    if not 0.05 <= settings.risk_per_trade_pct <= 10:
        errors.append("거래 위험은 0.05~10% 범위여야 합니다.")
    if not 1 <= settings.max_position_pct <= 100:
        errors.append("최대 비중은 1~100% 범위여야 합니다.")
    if not 5 <= settings.top_n <= 50:
        errors.append("TOP은 5~50 범위여야 합니다.")
    if not 1 <= settings.strategy_n <= 20:
        errors.append("전략은 1~20 범위여야 합니다.")
    if not 1 <= settings.chart_n <= 10:
        errors.append("차트는 1~10 범위여야 합니다.")

    if errors:
        for message in errors:
            st.sidebar.error(message)
        return None, run_clicked
    return settings, run_clicked


def render_main_table(result_table: pd.DataFrame, top_n: int) -> None:
    st.dataframe(
        make_compact_display_table(result_table, top_n),
        width="stretch",
        hide_index=True,
        column_config={
            "FinalScore": st.column_config.NumberColumn(format="%.1f"),
            "현재가": st.column_config.NumberColumn(format="localized"),
            "24h 등락": st.column_config.NumberColumn(format="%+.2f%%"),
            "RS vs BTC": st.column_config.NumberColumn(format="%+.2f%%"),
            "손절": st.column_config.NumberColumn(format="localized"),
            "1차익절(30%)": st.column_config.NumberColumn(format="localized"),
            "2차익절(30%)": st.column_config.NumberColumn(format="localized"),
            "Runner강화(4R)": st.column_config.NumberColumn(format="localized"),
        },
    )


def render_strategy_cards(sorted_results: list[dict], count: int) -> None:
    for item in sorted_results[:count]:
        if not item.get("strategy_available", False):
            continue

        title = f"{item['korean_name']} · {item['symbol']} · FinalScore {item.get('final_score', 0):.1f}"
        with st.expander(title, expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("현재가", f"{format_price(item['price'])}원")
            c2.metric("24시간", f"{item['change_24h']:+.2f}%")
            c3.metric("진입 상태", item.get("entry_status", "미확인"))
            c4.metric("ATR14", format_price(item["atr14"]))

            st.markdown(
                f"""
- **최종 판단:** {item.get('final_action', '관망')}
- **투자 조언:** {item.get('final_advice', '추가 확인이 필요합니다.')}
- **매수구간:** {format_price(item['buy_zone_low'])} ~ {format_price(item['buy_zone_high'])}원
- **손절:** {format_price(item['stop_price'])}원 · 계획 진입가 대비 **-{item['risk_pct']:.2f}%**
- **1차 익절:** {format_price(item['take_profit_1'])}원에서 {TP1_SELL_PCT}%
- **2차 익절:** {format_price(item['take_profit_2'])}원에서 {TP2_SELL_PCT}%
- **Runner:** 남은 {RUNNER_HOLD_PCT}% 유지, {format_price(item['runner_trigger_4r'])}원(4R)부터 Trail 2ATR → 1.5ATR 강화
- **현재 Trail:** {format_price(item['trailing_stop_current'])}원 · {item['runner_mode']}
- **권장 매수금:** {item['position_amount']:,.0f}원 · 예상 최대손실 {item['actual_risk_amount']:,.0f}원 ({item['actual_risk_pct']:.2f}% of account)
                """
            )
            if item["position_capped"]:
                st.caption("종목당 최대 투자비중 제한이 적용된 포지션입니다.")
            st.caption("Trail은 완료된 1시간봉마다 다시 계산하고 실제 운용 시 기존 Trail보다 낮추지 않습니다.")


def render_charts(sorted_results: list[dict], default_count: int) -> None:
    available = [
        item
        for item in sorted_results
        if item.get("strategy_available", False)
        and isinstance(item.get("df_240m"), pd.DataFrame)
        and not item["df_240m"].empty
    ]
    if not available:
        st.info("표시할 4시간봉 차트 데이터가 없습니다.")
        return

    labels = {
        f"{item['symbol']} · {item['korean_name']} · {item.get('final_score', 0):.1f}": item
        for item in available
    }
    selected = st.multiselect(
        "차트로 볼 종목",
        options=list(labels),
        default=list(labels)[: min(default_count, len(labels))],
    )

    for idx, label in enumerate(selected):
        item = labels[label]
        name = html.escape(str(item["korean_name"]))
        symbol = html.escape(str(item["symbol"]))
        action = html.escape(str(item.get("final_action", "관망")))
        advice = html.escape(str(item.get("final_advice", "추가 확인이 필요합니다.")))

        st.markdown(
            f'<div style="text-align:center;font-size:1.55rem;font-weight:700;margin:.25rem 0 .15rem;line-height:1.35;">{name} ({symbol}) - 4시간봉</div>',
            unsafe_allow_html=True,
        )

        last_completed = item.get("last_completed_240m", pd.NaT)
        last_text = (
            pd.Timestamp(last_completed).strftime("%Y-%m-%d %H:%M KST")
            if pd.notna(last_completed)
            else "확인 불가"
        )
        st.markdown(
            f"""
            <div style="text-align:center;color:#7a7f8c;font-size:.90rem;margin:0 0 .45rem;line-height:1.4;">
                현재가 {format_price(item['price'])}원 |
                24시간 {item['change_24h']:+.2f}% |
                RS vs BTC {item.get('rs_vs_btc_24h', np.nan):+.2f}% |
                {html.escape(str(item.get('btc_regime', '확인 불가')))} |
                Swing {html.escape(str(item.get('swing_structure', '데이터 부족')))}<br>
                RSI14 {item.get('RSI14_240m', np.nan):.1f} |
                VolumeRatio {item.get('VolumeRatio_240m', np.nan):.2f}x |
                ATR% {item.get('ATR_Pct_240m', np.nan):.2f}% |
                Dynamic RSI {item.get('RSI_dynamic_lower_240m', np.nan):.1f} ~ {item.get('RSI_dynamic_upper_240m', np.nan):.1f} |
                마지막 완료봉 {last_text}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="text-align:center;background:#f8f9fb;border:1px solid #e5e7eb;border-radius:8px;padding:.55rem .8rem;margin:0 0 .55rem;font-size:.88rem;"><b>최종 판단: {action}</b><br>{advice}</div>',
            unsafe_allow_html=True,
        )

        fig = plot_candle_with_strategy(item["df_240m"], item)
        st.pyplot(fig, width="stretch")
        plt.close(fig)
        if idx < len(selected) - 1:
            st.divider()


def render_analysis(analysis: dict, settings: AppSettings) -> None:
    result_table = analysis["result_table"]
    sorted_results = analysis["sorted_results"]
    ticker_info = analysis["ticker_info"]

    if result_table.empty:
        st.warning("현재 조건을 만족하는 코인이 없습니다.")
        if analysis["errors"]:
            st.dataframe(pd.DataFrame(analysis["errors"], columns=["종목", "오류"]), width="stretch")
        return

    ticker_text = "실시간 API" if ticker_info["source"] == "api" else f"캐시 {ticker_info['age_minutes']:.0f}분"
    metrics = st.columns(5)
    metrics[0].metric("전체 KRW 마켓", f"{len(analysis['krw_pairs'])}개")
    metrics[1].metric("캔들 분석 대상", f"{len(analysis['target_pairs'])}개")
    metrics[2].metric("4시간봉 후보", f"{len(analysis['results'])}개")
    metrics[3].metric("오류", f"{len(analysis['errors'])}개")
    metrics[4].metric("티커", ticker_text)

    if analysis["offline_mode"]:
        st.warning("업비트 API 연결 실패로 캐시 우선/오프라인 모드가 사용되었습니다.")
    elif ticker_info.get("warning"):
        st.warning(f"현재 ticker는 약 {ticker_info['age_minutes']:.0f}분 전 캐시입니다. 결과는 참고용으로 사용하세요.")

    if analysis["source_count_240"].get("stale", 0) or analysis["source_count_60"].get("stale", 0):
        st.warning("일부 OHLCV가 오래된 캐시를 사용했습니다. 해당 종목의 결과는 신뢰도를 낮춰 보세요.")

    st.caption(f"분석 시각: {st.session_state.get('analysis_time', '-')}")

    st.subheader(f"상위 {min(settings.top_n, len(result_table))}개 후보")
    st.caption("Swing: HH=이전보다 높은 고점 · HL=이전보다 높은 저점 · LH=이전보다 낮은 고점 · LL=이전보다 낮은 저점 (HH/HL은 상승 구조, LH/LL은 하락 구조)")
    render_main_table(result_table, settings.top_n)
    st.caption("※ ‘최종 판단/투자 조언’은 현재 데이터에 따른 규칙 기반 참고 신호이며 확정적인 수익을 의미하지 않습니다.")

    st.markdown("---")
    st.subheader("핵심 해석")
    lines = make_summary_lines(result_table, settings.top_n)
    if lines:
        for line in lines:
            st.markdown(f"- {line}")
    else:
        st.info("표시할 판단 그룹이 없습니다.")

    st.markdown("---")
    st.subheader("MA / ATR 기반 매수·손절·익절 + Runner")
    st.caption("1차 30% +1.5R, 2차 30% +2.5R, 마지막 40% Runner")
    render_strategy_cards(sorted_results, settings.strategy_n)

    strategy_table = make_strategy_display_table(sorted_results, settings.strategy_n)
    if not strategy_table.empty:
        with st.expander("전략 표로 보기", expanded=False):
            money_columns = {
                name: st.column_config.NumberColumn(format="localized")
                for name in (
                    "현재가",
                    "매수구간 하단",
                    "매수구간 상단",
                    "손절",
                    "1차 익절(30%)",
                    "2차 익절(30%)",
                    "4R Runner 강화",
                    "현재 Trail",
                    "권장 매수금",
                    "예상 최대손실",
                )
            }
            st.dataframe(strategy_table, width="stretch", hide_index=True, column_config=money_columns)

    st.markdown("---")
    st.subheader("캔들 차트")
    render_charts(sorted_results, settings.chart_n)

    st.markdown("---")
    st.subheader("전체 분석 데이터")
    st.dataframe(result_table, width="stretch", hide_index=True)
    csv_bytes = result_table.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "CSV 다운로드",
        data=csv_bytes,
        file_name="upbit_coin_analyzer_results.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.subheader("오류 내역")
    if analysis["errors"]:
        st.dataframe(pd.DataFrame(analysis["errors"], columns=["종목", "오류"]), width="stretch", hide_index=True)
    else:
        st.success("분석 중 수집된 오류가 없습니다.")


def streamlit_main() -> None:
    st.set_page_config(page_title="업비트 코인 분석기", page_icon="📊", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)

    settings, run_clicked = read_sidebar_settings()
    if settings is None:
        return

    st.markdown('<div class="main-app-title">📊 업비트 코인 분석기</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="main-app-subtitle">4시간봉 추세 선별 → 1시간봉 진입 확인 → FinalScore → MA/ATR 매매 계획</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"등락 {settings.min_change_24h:.1f}~{settings.max_change_24h:.1f}% · "
        f"거래대금 {settings.min_trade_value_24h:,.0f}원 · 계좌 {settings.account_capital:,.0f}원 · "
        f"위험 {settings.risk_per_trade_pct:.2f}% · 최대비중 {settings.max_position_pct:.0f}% · "
        f"TOP {settings.top_n} / 전략 {settings.strategy_n} / 차트 {settings.chart_n}"
    )
    st.markdown('<hr class="main-top-divider">', unsafe_allow_html=True)

    if run_clicked:
        progress = st.progress(0.0)
        status_box = st.empty()
        try:
            st.session_state["analysis"] = run_analysis(settings, progress, status_box)
            st.session_state["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as exc:
            progress.empty()
            status_box.empty()
            st.exception(exc)
            return

    analysis = st.session_state.get("analysis")
    if not analysis:
        st.markdown(
            '<div class="info-banner">👉 좌측 사이드바에서 설정을 조정하고 분석 실행 버튼을 클릭하세요.</div>',
            unsafe_allow_html=True,
        )
        st.subheader("기본 선별 구조")
        st.markdown(
            """
1. 4시간봉 MA 정배열 + MA20/60/120 상승 확인
2. 24시간 등락률과 거래대금으로 1차 필터
3. BTC Regime + RS vs BTC + Swing 구조를 별도 평가
4. 1시간봉 MA20 위치와 단기 방향으로 진입 타이밍 확인
5. Volume EMA20 / Dynamic RSI로 거래량·모멘텀 확인
6. FinalScore로 후보 순위 결정
7. MA20/MA60/ATR14로 매수·손절·익절·Runner 계획 계산
            """
        )
        return

    saved_signature = tuple(analysis.get("settings_signature", ()))
    if saved_signature and saved_signature != settings.analysis_signature():
        st.warning("분석에 영향을 주는 설정이 변경되었습니다. 현재 결과는 이전 설정 기준입니다. 새 설정을 반영하려면 ‘분석 실행’을 다시 누르세요.")

    render_analysis(analysis, settings)


if __name__ == "__main__":
    streamlit_main()
