"""업비트 멀티타임프레임 스크리너 (Streamlit).

4시간봉 추세 선별 → 1시간봉 진입 확인 → FinalScore → MA/ATR 매매 계획.
실행: streamlit run app_fixed_v17.py
"""
from __future__ import annotations

import json
import platform
import time
from datetime import datetime, timedelta
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


# ============================================================
# 1. 설정
# ============================================================
API_BASE = "https://api.upbit.com/v1"

# ------------------------------------------------------------
# 캐시 폴더
# ------------------------------------------------------------
CACHE_ROOT = Path("upbit_cache")
MARKET_CACHE_DIR = CACHE_ROOT / "market"
TICKER_CACHE_DIR = CACHE_ROOT / "ticker"
OHLCV_CACHE_DIR = CACHE_ROOT / "ohlcv"

for folder in [
    MARKET_CACHE_DIR,
    TICKER_CACHE_DIR,
    OHLCV_CACHE_DIR,
]:
    folder.mkdir(parents=True, exist_ok=True)

MARKET_CACHE_FILE = MARKET_CACHE_DIR / "krw_markets.json"
TICKER_CACHE_FILE = TICKER_CACHE_DIR / "krw_ticker.json"

# ------------------------------------------------------------
# 멀티 타임프레임
# ------------------------------------------------------------
SCREEN_CANDLE_UNIT = 240  # 4시간봉: 메인 추세 스크리닝
ENTRY_CANDLE_UNIT = 60  # 1시간봉: 진입 타이밍 확인
CANDLE_COUNT = 200

# 현재 진행 중인 캔들도 계속 변하므로 캐시를 너무 오래 두지 않는다.
CACHE_EXPIRE_MINUTES = {
    60: 30,
    240: 60,
}

TICKER_CACHE_EXPIRE_MINUTES = 10
TICKER_CACHE_WARN_MINUTES = 30  # 이보다 오래되면 경고 표시
TICKER_CACHE_MAX_AGE_MINUTES = 60  # 이보다 오래되면 매매 판단에 사용하지 않음

# ------------------------------------------------------------
# 추세 조건
# ------------------------------------------------------------
MA_PERIODS = (5, 20, 60, 120)
MA_SLOPE_LOOKBACKS = {
    20: 3,  # 4시간봉 3개 = 12시간
    60: 6,  # 4시간봉 6개 = 24시간
    120: 12,  # 4시간봉 12개 = 48시간
}
REQUIRE_MA_RISING = True

MIN_CHANGE_24H = 1.0
MAX_CHANGE_24H = 30.0
MIN_TRADE_VALUE_24H = 100_000_000  # 1억원

# ------------------------------------------------------------
# 1시간봉 진입 상태 판단
# ------------------------------------------------------------
ENTRY_PULLBACK_MIN_PCT = 0.0  # MA20 아래에서는 눌림 보너스를 주지 않음
ENTRY_PULLBACK_MAX_PCT = 3.0
ENTRY_OVERHEAT_PCT = 8.0

# 결과표의 간단 판단 라벨 기준
STRONG_RISE_24H_PCT = 8.0

# ------------------------------------------------------------
# MA / ATR 기반 매수·손절·익절
# ------------------------------------------------------------
ATR_PERIOD = 14

# 거래량 / Dynamic RSI / Swing 구조
VOLUME_EMA_PERIOD = 20
RSI_PERIOD = 14
DYNAMIC_RSI_CENTER_PERIOD = 20
DYNAMIC_RSI_STD_PERIOD = 20
DYNAMIC_RSI_STD_MULTIPLIER = 1.5
SWING_LEFT_BARS = 3
SWING_RIGHT_BARS = 3

BUY_ZONE_ATR = 0.5  # 매수구간: 1시간 MA20 ± 0.5 ATR
STOP_MA60_ATR = 0.5  # MA60 아래 0.5 ATR을 구조적 손절 후보로 사용
MAX_STOP_ATR = 2.0  # 진입 기준 최대 손절폭: 2 ATR
MIN_RISK_ATR = 1.0  # 손절폭이 너무 좁아지는 것을 방지
TP1_R_MULTIPLIER = 1.5  # 1차 익절: +1.5R
TP2_R_MULTIPLIER = 2.5  # 2차 익절: +2.5R
RUNNER_TRIGGER_R = 4.0  # +4R부터 마지막 40%의 Trail을 강화

TP1_SELL_PCT = 30  # 1차 익절 시 보유수량의 30%
TP2_SELL_PCT = 30  # 2차 익절 시 보유수량의 30%
RUNNER_HOLD_PCT = 40  # 마지막 40%는 고정 익절 없이 Runner로 관리

# 1차 익절 이후 본전 보호, 2차 이후 Trail, 4R 이후 Trail 강화
TRAIL_ATR_MULTIPLIER = 2.0  # 2차 이후: 1시간 MA20 - 2 ATR
RUNNER_TRAIL_ATR_MULTIPLIER = 1.5  # 4R 이후: 1시간 MA20 - 1.5 ATR

# ------------------------------------------------------------
# 리스크 기반 포지션 사이징
# ------------------------------------------------------------
ACCOUNT_CAPITAL = 100_000_000  # 기준 계좌자금 1억원
RISK_PER_TRADE_PCT = 0.5  # 한 거래 최대 허용손실: 계좌의 0.5%
MAX_POSITION_PCT = 20.0  # 한 종목 최대 투입금: 계좌의 20%

# ------------------------------------------------------------
# 출력
# ------------------------------------------------------------
TOP_N = 20
STRATEGY_N = 5
CHART_N = 5
CHART_BARS = 60

REQUEST_INTERVAL = 0.12
MAX_RETRIES = 3

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_CSV = OUTPUT_DIR / "upbit_screener_240m_60m.csv"

# ============================================================
# 2. 한글 폰트
# ============================================================
def configure_korean_font() -> str:
    """운영체제에 맞는 한글 폰트를 선택한다."""
    font_files = [
        Path("/usr/share/fonts/SlidesCarnival/google/Nanum Gothic/NanumGothic-Regular.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for path in font_files:
        if path.exists():
            try:
                fm.fontManager.addfont(str(path))
                selected = fm.FontProperties(fname=str(path)).get_name()
                plt.rcParams["font.family"] = selected
                plt.rcParams["axes.unicode_minus"] = False
                return selected
            except (OSError, ValueError, RuntimeError):
                pass

    installed = {font.name for font in fm.fontManager.ttflist}
    if platform.system() == "Windows":
        candidates = ["Malgun Gothic", "NanumGothic"]
    elif platform.system() == "Darwin":
        candidates = ["AppleGothic", "Arial Unicode MS", "NanumGothic"]
    else:
        candidates = ["NanumGothic", "Noto Sans CJK KR", "DejaVu Sans"]

    selected = next((name for name in candidates if name in installed), "DejaVu Sans")
    plt.rcParams["font.family"] = selected
    plt.rcParams["axes.unicode_minus"] = False
    return selected


KOREAN_FONT = configure_korean_font()


# ============================================================
# 3. 캐시 경로
# ============================================================
def get_ohlcv_cache_dir(candle_unit: int) -> Path:
    """예: 60 -> upbit_cache/ohlcv/60m"""
    path = OHLCV_CACHE_DIR / f"{candle_unit}m"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_ohlcv_cache_path(symbol: str, candle_unit: int) -> Path:
    safe_symbol = symbol.replace("-", "_")
    return get_ohlcv_cache_dir(candle_unit) / f"{safe_symbol}.json"


def get_cache_expire_minutes(candle_unit: int) -> int:
    return CACHE_EXPIRE_MINUTES.get(candle_unit, 60)


def cache_is_fresh(path: Path, expire_minutes: int) -> bool:
    if not path.exists():
        return False

    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age <= timedelta(minutes=expire_minutes)


def get_current_candle_start_kst(
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> pd.Timestamp:
    """현재 진행 중인 캔들의 시작 시각(KST, tz-naive)을 반환한다.

    업비트 분봉 경계는 UTC 기준으로 정렬된다.
    따라서 240분봉은 KST 기준 01/05/09/13/17/21시에 시작한다.
    """
    if now_kst is None:
        now = pd.Timestamp.now(tz="Asia/Seoul")
    else:
        now = pd.Timestamp(now_kst)
        if now.tzinfo is None:
            now = now.tz_localize("Asia/Seoul")
        else:
            now = now.tz_convert("Asia/Seoul")

    now_utc = now.tz_convert("UTC")
    unit_ns = pd.Timedelta(minutes=candle_unit).value
    floored_ns = (now_utc.value // unit_ns) * unit_ns
    current_start_utc = pd.Timestamp(floored_ns, tz="UTC")
    return current_start_utc.tz_convert("Asia/Seoul").tz_localize(None)


def get_latest_completed_candle_start_kst(
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> pd.Timestamp:
    """가장 최근에 완료된 캔들의 시작 시각(KST)을 반환한다."""
    current_start = get_current_candle_start_kst(candle_unit, now_kst)
    return current_start - pd.Timedelta(minutes=candle_unit)


def cache_is_after_latest_candle_close(
    path: Path,
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> bool:
    """캐시가 가장 최근 봉 마감 이후에 생성/갱신됐는지 확인한다.

    일반 만료시간이 남아 있어도 새 봉이 마감된 뒤 캐시를 아직 갱신하지
    않았다면 False를 반환해 API 재조회가 일어나도록 한다.
    """
    if not path.exists():
        return False

    current_start = get_current_candle_start_kst(candle_unit, now_kst)
    cache_mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC")
    cache_mtime_kst = cache_mtime.tz_convert("Asia/Seoul").tz_localize(None)
    return cache_mtime_kst >= current_start


# ============================================================
# 4. Upbit Public API 클라이언트
# ============================================================
class UpbitPublicClient:
    """인증이 필요 없는 업비트 시세 API 클라이언트."""

    def __init__(
        self,
        request_interval: float = REQUEST_INTERVAL,
        max_retries: int = MAX_RETRIES,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "upbit-multitimeframe-screener/8.0",
            }
        )
        self.request_interval = request_interval
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def close(self) -> None:
        self.session.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval - elapsed
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
                    time.sleep(1.05)
                    continue

                if response.status_code == 418:
                    raise RuntimeError(
                        "업비트 API에서 HTTP 418 응답을 받았습니다. "
                        "잠시 후 다시 실행하세요."
                    )

                if 500 <= response.status_code < 600:
                    last_error = RuntimeError(
                        f"업비트 서버 오류: HTTP {response.status_code}"
                    )
                    time.sleep(min(2 ** (attempt - 1), 4))
                    continue

                response.raise_for_status()

                remaining = response.headers.get("Remaining-Req", "")
                if "sec=0" in remaining:
                    time.sleep(1.05)

                return response.json()

            except requests.RequestException as e:
                last_error = e
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

        df = pd.DataFrame(data)

        # Upbit 응답의 원래 timestamp(ms)와 분석용 timestamp 이름 충돌 방지
        df = df.drop(columns=["timestamp"], errors="ignore")

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

        required = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trade_value",
        ]

        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"업비트 캔들 응답 필드 누락: {missing}")

        df = df[required].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])

        numeric = ["open", "high", "low", "close", "volume", "trade_value"]
        df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])

        df = df.sort_values("timestamp").set_index("timestamp")
        df = df[~df.index.duplicated(keep="last")]

        return df


# ============================================================
# 5. OHLCV 캐시
# ============================================================
def load_ohlcv_cache(
    symbol: str,
    candle_unit: int,
    allow_stale: bool = False,
) -> Optional[pd.DataFrame]:
    path = get_ohlcv_cache_path(symbol, candle_unit)

    if not path.exists():
        return None

    if not allow_stale and not cache_is_fresh(
        path,
        get_cache_expire_minutes(candle_unit),
    ):
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        if isinstance(payload, dict) and "records" in payload:
            records = payload["records"]
        elif isinstance(payload, list):
            # 기존 캐시 형식 호환
            records = payload
        else:
            return None

        df = pd.DataFrame(records)
        if df.empty or "timestamp" not in df.columns:
            return None

        # 혹시 과거 캐시에 중복 timestamp 컬럼이 생겼더라도 안전하게 처리
        df = df.loc[:, ~df.columns.duplicated()].copy()

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])

        numeric = [
            c
            for c in ["open", "high", "low", "close", "volume", "trade_value"]
            if c in df.columns
        ]
        df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")

        df = df.set_index("timestamp").sort_index()
        df = df[~df.index.duplicated(keep="last")]

        return df

    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_ohlcv_cache(
    symbol: str,
    candle_unit: int,
    df: pd.DataFrame,
) -> None:
    if df is None or df.empty:
        return

    try:
        save_df = df.reset_index().copy()
        first_col = save_df.columns[0]

        if first_col != "timestamp":
            save_df = save_df.rename(columns={first_col: "timestamp"})

        save_df = save_df.loc[:, ~save_df.columns.duplicated()].copy()
        save_df["timestamp"] = save_df["timestamp"].astype(str)

        records = json.loads(save_df.to_json(orient="records", force_ascii=False))

        payload = {
            "version": 5,
            "market": symbol,
            "candle_unit_minutes": candle_unit,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "records": records,
        }

        path = get_ohlcv_cache_path(symbol, candle_unit)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    except Exception as e:
        print(f"⚠️ {symbol} {candle_unit}m 캐시 저장 실패: {e}")


def get_ohlcv(
    client: UpbitPublicClient,
    symbol: str,
    candle_unit: int,
    offline_mode: bool,
) -> tuple[Optional[pd.DataFrame], str]:
    """
    반환 source:
      cache / api / stale / missing

    온라인 모드에서는 두 가지를 모두 만족할 때만 캐시를 사용한다.
    1) 일반 캐시 만료시간 이내
    2) 가장 최근 캔들 마감 이후 한 번 이상 갱신된 캐시

    따라서 새 1시간봉/4시간봉이 마감되면 기존 캐시의 남은 TTL과 관계없이
    다음 분석에서 API를 다시 조회한다.
    """
    path = get_ohlcv_cache_path(symbol, candle_unit)

    if offline_mode:
        df = load_ohlcv_cache(symbol, candle_unit, allow_stale=True)
        if df is None:
            return None, "missing"
        fresh = cache_is_fresh(path, get_cache_expire_minutes(candle_unit))
        boundary_ok = cache_is_after_latest_candle_close(path, candle_unit)
        return df, "cache" if fresh and boundary_ok else "stale"

    # 온라인: TTL이 남아 있어도 새 봉이 마감된 뒤 갱신되지 않은 캐시는 사용하지 않는다.
    df = load_ohlcv_cache(symbol, candle_unit, allow_stale=False)
    if df is not None and cache_is_after_latest_candle_close(path, candle_unit):
        return df, "cache"

    try:
        df = client.get_minute_candles(
            market=symbol,
            unit=candle_unit,
            count=CANDLE_COUNT,
        )

        if df is not None and not df.empty:
            save_ohlcv_cache(symbol, candle_unit, df)
            return df, "api"

    except Exception as api_error:
        stale = load_ohlcv_cache(
            symbol,
            candle_unit,
            allow_stale=True,
        )

        if stale is not None:
            print(
                f"⚠️ {symbol} {candle_unit}m: API 실패 → 오래된 캐시 사용 ({api_error})"
            )
            return stale, "stale"

        raise

    return None, "missing"


# ============================================================
# 6. 마켓 / 티커 캐시
# ============================================================
def load_market_cache() -> tuple[list[str], dict[str, str]]:
    if not MARKET_CACHE_FILE.exists():
        return [], {}

    try:
        with MARKET_CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return (
            data.get("krw_pairs", []),
            data.get("symbol_korean_map", {}),
        )
    except (OSError, json.JSONDecodeError, TypeError):
        return [], {}


def save_market_cache(
    krw_pairs: list[str],
    symbol_korean_map: dict[str, str],
) -> None:
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "krw_pairs": krw_pairs,
        "symbol_korean_map": symbol_korean_map,
    }

    with MARKET_CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def get_ticker_cache_age_minutes() -> float:
    """티커 캐시 저장 후 경과 시간을 분 단위로 반환한다."""
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

    # saved_at을 읽지 못하면 파일 수정시각을 보조 기준으로 사용한다.
    modified = datetime.fromtimestamp(TICKER_CACHE_FILE.stat().st_mtime)
    return max(0.0, (datetime.now() - modified).total_seconds() / 60)


def load_ticker_cache(allow_stale: bool = False) -> dict[str, dict]:
    if not TICKER_CACHE_FILE.exists():
        return {}

    if not allow_stale and not cache_is_fresh(
        TICKER_CACHE_FILE,
        TICKER_CACHE_EXPIRE_MINUTES,
    ):
        return {}

    try:
        with TICKER_CACHE_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        records = payload.get("records", [])
        return {item["market"]: item for item in records if "market" in item}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_ticker_cache(tickers: list[dict]) -> None:
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "records": tickers,
    }

    with TICKER_CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


# ============================================================
# 7. 환경 / 마켓 정보
# ============================================================
def count_ohlcv_cache(candle_unit: int) -> int:
    return len(list(get_ohlcv_cache_dir(candle_unit).glob("KRW_*.json")))


def get_environment_status(client: UpbitPublicClient) -> dict:
    print("\n" + "=" * 68)
    print("업비트 멀티 타임프레임 환경 확인")
    print("=" * 68)

    try:
        markets = client.get_markets()
        api_ok = bool(markets)
        reason = "업비트 Public API 정상"
    except Exception as e:
        markets = []
        api_ok = False
        reason = str(e)

    print(f"API 상태       : {'정상' if api_ok else '실패'}")
    print(f"240m 캐시      : {count_ohlcv_cache(240)}개")
    print(f"60m 캐시       : {count_ohlcv_cache(60)}개")
    print(f"캐시 루트      : {CACHE_ROOT.resolve()}")

    if not api_ok:
        print(f"API 오류       : {reason}")
        print("동작 모드      : 오프라인/캐시 우선")
    else:
        print("동작 모드      : 온라인")

    print("=" * 68)

    return {
        "api_ok": api_ok,
        "offline_mode": not api_ok,
        "markets": markets,
    }


def load_market_info(
    client: UpbitPublicClient,
    status: dict,
) -> tuple[list[str], dict[str, str]]:
    if status["api_ok"]:
        try:
            markets = status["markets"] or client.get_markets()
            krw_markets = [
                m for m in markets if str(m.get("market", "")).startswith("KRW-")
            ]

            krw_pairs = [m["market"] for m in krw_markets]
            name_map = {
                m["market"]: m.get(
                    "korean_name",
                    m["market"].replace("KRW-", ""),
                )
                for m in krw_markets
            }

            save_market_cache(krw_pairs, name_map)
            return krw_pairs, name_map

        except Exception as e:
            print(f"⚠️ 마켓 목록 API 실패: {e}")

    krw_pairs, name_map = load_market_cache()

    if krw_pairs:
        print(f"📂 마켓 캐시 사용: {len(krw_pairs)}개")
        return krw_pairs, name_map

    default_pairs = [
        "KRW-BTC",
        "KRW-ETH",
        "KRW-XRP",
        "KRW-SOL",
        "KRW-ADA",
        "KRW-DOGE",
        "KRW-DOT",
        "KRW-LINK",
    ]

    print("⚠️ 마켓 캐시가 없어 기본 코인만 사용합니다.")
    return default_pairs, {pair: pair.replace("KRW-", "") for pair in default_pairs}


def load_ticker_map(
    client: UpbitPublicClient,
    offline_mode: bool,
) -> tuple[dict[str, dict], dict]:
    """티커와 데이터 신선도 정보를 함께 반환한다.

    30분 초과 캐시는 경고하고, 60분 초과 캐시는 매매 판단에 사용하지 않는다.
    """
    if not offline_mode:
        try:
            tickers = client.get_krw_tickers()
            save_ticker_cache(tickers)
            return (
                {item["market"]: item for item in tickers},
                {
                    "source": "api",
                    "age_minutes": 0.0,
                    "warning": False,
                    "usable_for_trading": True,
                },
            )
        except Exception as e:
            print(f"⚠️ 전체 현재가 조회 실패: {e}")

    age = get_ticker_cache_age_minutes()
    cached = load_ticker_cache(allow_stale=True)

    if not cached:
        return {}, {
            "source": "missing",
            "age_minutes": age,
            "warning": True,
            "usable_for_trading": False,
        }

    if age > TICKER_CACHE_MAX_AGE_MINUTES:
        print(
            f"⚠️ 티커 캐시가 {age:.0f}분 경과했습니다. "
            f"{TICKER_CACHE_MAX_AGE_MINUTES}분을 초과해 매매 판단에 사용하지 않습니다."
        )
        return {}, {
            "source": "stale_blocked",
            "age_minutes": age,
            "warning": True,
            "usable_for_trading": False,
        }

    warning = age > TICKER_CACHE_WARN_MINUTES
    if warning:
        print(f"⚠️ 티커 캐시 사용: {len(cached)}개 / {age:.0f}분 경과")
    else:
        print(f"📂 티커 캐시 사용: {len(cached)}개 / {age:.0f}분 경과")

    return cached, {
        "source": "cache",
        "age_minutes": age,
        "warning": warning,
        "usable_for_trading": True,
    }


# ============================================================
# 8. 지표 계산
# ============================================================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """가격/거래량/모멘텀 지표를 한 번에 계산한다."""
    df = df.copy()

    for period in MA_PERIODS:
        df[f"MA{period}"] = df["close"].rolling(period).mean()

    # ATR(True Range의 이동평균)
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df[f"ATR{ATR_PERIOD}"] = true_range.rolling(ATR_PERIOD).mean()
    df["ATR_Pct"] = df[f"ATR{ATR_PERIOD}"] / df["close"].replace(0, np.nan) * 100

    # Volume EMA20 + VolumeRatio
    df[f"VolumeEMA{VOLUME_EMA_PERIOD}"] = df["volume"].ewm(
        span=VOLUME_EMA_PERIOD,
        adjust=False,
        min_periods=VOLUME_EMA_PERIOD,
    ).mean()
    df["VolumeRatio"] = (
        df["volume"] / df[f"VolumeEMA{VOLUME_EMA_PERIOD}"].replace(0, np.nan)
    )

    # Wilder 방식에 가까운 RSI14
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(
        alpha=1 / RSI_PERIOD,
        adjust=False,
        min_periods=RSI_PERIOD,
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / RSI_PERIOD,
        adjust=False,
        min_periods=RSI_PERIOD,
    ).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    df[f"RSI{RSI_PERIOD}"] = rsi.clip(0, 100)

    # Dynamic RSI Zone: RSI EMA20 ± 1.5 × 최근 20봉 RSI 표준편차
    rsi_col = f"RSI{RSI_PERIOD}"
    df["RSI_Dynamic_Center"] = df[rsi_col].ewm(
        span=DYNAMIC_RSI_CENTER_PERIOD,
        adjust=False,
        min_periods=DYNAMIC_RSI_CENTER_PERIOD,
    ).mean()
    rsi_std = df[rsi_col].rolling(DYNAMIC_RSI_STD_PERIOD).std()
    df["RSI_Dynamic_Upper"] = (
        df["RSI_Dynamic_Center"] + DYNAMIC_RSI_STD_MULTIPLIER * rsi_std
    ).clip(0, 100)
    df["RSI_Dynamic_Lower"] = (
        df["RSI_Dynamic_Center"] - DYNAMIC_RSI_STD_MULTIPLIER * rsi_std
    ).clip(0, 100)

    return df


def detect_swing_points(
    df: pd.DataFrame,
    left: int = SWING_LEFT_BARS,
    right: int = SWING_RIGHT_BARS,
) -> pd.DataFrame:
    """좌우 Pivot 봉을 이용해 HH/HL/LH/LL Swing 포인트를 찾는다."""
    if df is None or df.empty or len(df) < left + right + 3:
        return pd.DataFrame(columns=["timestamp", "kind", "label", "price"])

    highs = []
    lows = []
    for i in range(left, len(df) - right):
        high = float(df["high"].iloc[i])
        low = float(df["low"].iloc[i])
        left_high = float(df["high"].iloc[i-left:i].max())
        right_high = float(df["high"].iloc[i+1:i+1+right].max())
        left_low = float(df["low"].iloc[i-left:i].min())
        right_low = float(df["low"].iloc[i+1:i+1+right].min())

        if high > left_high and high >= right_high:
            highs.append((df.index[i], high))
        if low < left_low and low <= right_low:
            lows.append((df.index[i], low))

    points = []
    previous_high = None
    for ts, price in highs:
        label = "H" if previous_high is None else ("HH" if price > previous_high else "LH")
        points.append({"timestamp": ts, "kind": "high", "label": label, "price": price})
        previous_high = price

    previous_low = None
    for ts, price in lows:
        label = "L" if previous_low is None else ("HL" if price > previous_low else "LL")
        points.append({"timestamp": ts, "kind": "low", "label": label, "price": price})
        previous_low = price

    if not points:
        return pd.DataFrame(columns=["timestamp", "kind", "label", "price"])
    return pd.DataFrame(points).sort_values("timestamp").reset_index(drop=True)


def classify_swing_structure(points: pd.DataFrame) -> str:
    """가장 최근 확정 Swing High/Low를 HH/HL 형태로 요약한다."""
    if points is None or points.empty:
        return "데이터 부족"
    high_labels = points.loc[points["label"].isin(["HH", "LH"]), "label"]
    low_labels = points.loc[points["label"].isin(["HL", "LL"]), "label"]
    if high_labels.empty or low_labels.empty:
        return "데이터 부족"
    return f"{high_labels.iloc[-1]}/{low_labels.iloc[-1]}"


def calculate_btc_regime(df: pd.DataFrame) -> dict:
    """BTC 4시간봉의 추세/수익률 4개 조건으로 시장 국면을 분류한다."""
    empty = {
        "label": "확인 불가",
        "score": np.nan,
        "change_24h": np.nan,
        "return_7d": np.nan,
        "ma120_dist_pct": np.nan,
        "ma20_slope_24h_pct": np.nan,
    }
    if df is None or df.empty:
        return empty

    work = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    if len(work) < 130:
        return empty
    work = add_indicators(work)
    latest = work.iloc[-1]
    ma120 = latest.get("MA120", np.nan)
    ma20 = latest.get("MA20", np.nan)
    ma20_past = work["MA20"].iloc[-7] if len(work) >= 7 else np.nan
    if pd.isna(ma120) or pd.isna(ma20) or pd.isna(ma20_past):
        return empty

    close = float(latest["close"])
    change_24h = calculate_rolling_change_24h(work)
    return_7d = (close / float(work["close"].iloc[-43]) - 1) * 100 if len(work) >= 43 else np.nan
    ma120_dist = (close / float(ma120) - 1) * 100
    ma20_slope = (float(ma20) / float(ma20_past) - 1) * 100

    conditions = [
        close > float(ma120),
        float(ma20) > float(ma20_past),
        pd.notna(change_24h) and change_24h > 0,
        pd.notna(return_7d) and return_7d > 0,
    ]
    score = int(sum(bool(x) for x in conditions))
    if score <= 1:
        label = "Q1 Weak"
    elif score == 2:
        label = "Q2 Neutral"
    elif score == 3:
        label = "Q3 Strong"
    else:
        label = "Q4 Very Strong"

    return {
        "label": label,
        "score": score,
        "change_24h": float(change_24h),
        "return_7d": float(return_7d),
        "ma120_dist_pct": float(ma120_dist),
        "ma20_slope_24h_pct": float(ma20_slope),
    }


def keep_completed_candles(
    df: pd.DataFrame,
    candle_unit: int,
    now_kst: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """진행 중인 캔들을 제외하고 완료된 캔들만 반환한다.

    Upbit의 candle_date_time_kst는 캔들 시작 시각이다.
    따라서 시작시각 + 봉 길이가 현재 KST보다 작거나 같은 캔들만 완료된 봉이다.
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    if now_kst is None:
        now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    else:
        now = pd.Timestamp(now_kst)
        if now.tzinfo is not None:
            now = now.tz_convert("Asia/Seoul").tz_localize(None)

    candle_end = df.index + pd.Timedelta(minutes=candle_unit)
    return df.loc[candle_end <= now].copy()


def calculate_rolling_change_24h(df: pd.DataFrame) -> float:
    if df.empty:
        return np.nan

    latest_time = df.index[-1]
    target_time = latest_time - pd.Timedelta(hours=24)

    past = df.loc[df.index <= target_time, "close"]
    if past.empty:
        return np.nan

    previous_price = float(past.iloc[-1])
    current_price = float(df["close"].iloc[-1])

    if previous_price <= 0:
        return np.nan

    return (current_price / previous_price - 1) * 100


def calculate_trade_value_24h(df: pd.DataFrame) -> float:
    if df.empty:
        return np.nan

    latest_time = df.index[-1]
    start_time = latest_time - pd.Timedelta(hours=24)
    recent = df.loc[df.index > start_time]

    if "trade_value" in recent.columns:
        return float(recent["trade_value"].sum())

    if {"close", "volume"}.issubset(recent.columns):
        return float((recent["close"] * recent["volume"]).sum())

    return np.nan


def is_uptrend(df: pd.DataFrame) -> tuple[bool, bool, dict[int, float]]:
    """정배열과 MA별 차등 상승 여부/상승률을 계산한다.

    4시간봉 기준:
      MA20  : 3봉 전(12시간)과 비교
      MA60  : 6봉 전(24시간)과 비교
      MA120 : 12봉 전(48시간)과 비교
    """
    latest = df.iloc[-1]

    ordered = latest["MA5"] > latest["MA20"] > latest["MA60"] > latest["MA120"]

    slope_pct: dict[int, float] = {}
    rising_flags = []

    for period, lookback in MA_SLOPE_LOOKBACKS.items():
        if len(df) <= lookback:
            return ordered, False, slope_pct

        current_ma = float(df[f"MA{period}"].iloc[-1])
        past_ma = float(df[f"MA{period}"].iloc[-1 - lookback])

        if pd.isna(current_ma) or pd.isna(past_ma) or past_ma <= 0:
            return ordered, False, slope_pct

        pct = (current_ma / past_ma - 1) * 100
        slope_pct[period] = pct
        rising_flags.append(current_ma > past_ma)

    return ordered, all(rising_flags), slope_pct


# ============================================================
# 9. 4시간봉 메인 스크리닝
# ============================================================
def analyze_screen_symbol(
    symbol: str,
    korean_name: str,
    df: pd.DataFrame,
    ticker: Optional[dict],
) -> Optional[dict]:
    # 4시간봉 메인 추세는 완료된 캔들만 사용한다.
    df = keep_completed_candles(df, SCREEN_CANDLE_UNIT)

    min_required = max(MA_PERIODS) + max(MA_SLOPE_LOOKBACKS.values())
    if df is None or df.empty or len(df) < min_required:
        return None

    df = add_indicators(df)
    latest = df.iloc[-1]
    swing_points = detect_swing_points(df)
    swing_structure = classify_swing_structure(swing_points)

    if latest[[f"MA{x}" for x in MA_PERIODS]].isna().any():
        return None

    ordered, ma_rising, ma_slope_pct = is_uptrend(df)

    if not ordered:
        return None

    if REQUIRE_MA_RISING and not ma_rising:
        return None

    change_24h = calculate_rolling_change_24h(df)
    if pd.isna(change_24h):
        return None

    if not (MIN_CHANGE_24H <= change_24h <= MAX_CHANGE_24H):
        return None

    if ticker:
        current_price = float(ticker.get("trade_price", latest["close"]))
        trade_value_24h = float(ticker.get("acc_trade_price_24h", np.nan))
    else:
        current_price = float(latest["close"])
        trade_value_24h = calculate_trade_value_24h(df)

    if pd.isna(trade_value_24h) or trade_value_24h < MIN_TRADE_VALUE_24H:
        return None

    return {
        "symbol": symbol,
        "korean_name": korean_name,
        "price": current_price,
        "change_24h": change_24h,
        "trade_value_24h": trade_value_24h,
        "MA5_240m": float(latest["MA5"]),
        "MA20_240m": float(latest["MA20"]),
        "MA60_240m": float(latest["MA60"]),
        "MA120_240m": float(latest["MA120"]),
        "ma_rising_240m": ma_rising,
        "MA20_slope_pct_240m": ma_slope_pct.get(20, np.nan),
        "MA60_slope_pct_240m": ma_slope_pct.get(60, np.nan),
        "MA120_slope_pct_240m": ma_slope_pct.get(120, np.nan),
        "last_completed_240m": df.index[-1],
        "RSI14_240m": float(latest.get("RSI14", np.nan)),
        "RSI_dynamic_upper_240m": float(latest.get("RSI_Dynamic_Upper", np.nan)),
        "RSI_dynamic_center_240m": float(latest.get("RSI_Dynamic_Center", np.nan)),
        "RSI_dynamic_lower_240m": float(latest.get("RSI_Dynamic_Lower", np.nan)),
        "VolumeEMA20_240m": float(latest.get("VolumeEMA20", np.nan)),
        "VolumeRatio_240m": float(latest.get("VolumeRatio", np.nan)),
        "ATR_Pct_240m": float(latest.get("ATR_Pct", np.nan)),
        "swing_structure": swing_structure,
        "swing_points": swing_points,
        "df_240m": df,
    }


# ============================================================
# 10. 1시간봉 진입 타이밍
# ============================================================
def analyze_entry_timing(
    df: pd.DataFrame,
    current_price: Optional[float] = None,
) -> dict:
    """
    4시간봉에서 상승 추세가 확인된 종목을 대상으로
    1시간봉 MA20 이격과 단기 방향을 이용해 진입 상태를 분류한다.

    중요:
    - MA5/20/60과 단기 방향은 1시간봉 데이터로 계산한다.
    - MA20 이격과 MA20 위/아래 판단은 최신 ticker 현재가를 우선 사용한다.
    - 현재가가 MA20 아래이면 눌림목 보너스(+2점)를 주지 않는다.
    """
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

    # 1시간 지표도 완료된 캔들만 사용한다.
    # 실시간 ticker 가격은 MA20 이격/위치 판단에만 사용한다.
    df = keep_completed_candles(df, ENTRY_CANDLE_UNIT)

    if df is None or df.empty or len(df) < 65:
        return empty

    df = add_indicators(df)
    latest = df.iloc[-1]

    if (
        pd.isna(latest["MA5"])
        or pd.isna(latest["MA20"])
        or pd.isna(latest["MA60"])
        or pd.isna(latest[f"ATR{ATR_PERIOD}"])
    ):
        return empty

    candle_close = float(latest["close"])
    ma5 = float(latest["MA5"])
    ma20 = float(latest["MA20"])
    ma60 = float(latest["MA60"])
    atr = float(latest[f"ATR{ATR_PERIOD}"])

    if ma20 <= 0 or atr <= 0:
        return empty

    # 최신 ticker 가격이 있으면 그것을 현재 진입 판단 가격으로 사용한다.
    if current_price is None or pd.isna(current_price) or current_price <= 0:
        entry_price = candle_close
    else:
        entry_price = float(current_price)

    distance = (entry_price / ma20 - 1) * 100

    ma5_rising = len(df) >= 4 and df["MA5"].iloc[-1] > df["MA5"].iloc[-4]
    close_rising = len(df) >= 2 and df["close"].iloc[-1] > df["close"].iloc[-2]
    short_ordered = ma5 > ma20 > ma60

    score = 0

    if entry_price >= ma20:
        score += 1
    if short_ordered:
        score += 1
    if ma5_rising:
        score += 1
    if close_rising:
        score += 1

    # MA20 위 0~3% 구간만 좋은 눌림 위치로 +2점.
    # MA20 아래에서는 싸 보이더라도 재돌파 확인 전까지 보너스를 주지 않는다.
    if ENTRY_PULLBACK_MIN_PCT <= distance <= ENTRY_PULLBACK_MAX_PCT:
        score += 2

    if entry_price < ma20:
        status = "MA20 하회"
    elif distance > ENTRY_OVERHEAT_PCT:
        status = "과열 주의"
    elif ENTRY_PULLBACK_MIN_PCT <= distance <= ENTRY_PULLBACK_MAX_PCT:
        if short_ordered and ma5_rising and close_rising:
            status = "진입 관심"
        else:
            status = "눌림 확인"
    else:
        status = "눌림 대기"

    return {
        "entry_status": status,
        "entry_score": score,
        "entry_distance_ma20_pct": distance,
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
        "last_completed_60m": df.index[-1],
    }


# ============================================================
# 11. FinalScore 계산
# ============================================================
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def calculate_final_score(item: dict) -> dict:
    """최종 후보 순위를 위한 100점 만점 점수를 계산한다.

    구성:
      - 4시간 추세 강도 : 30점
      - 1시간 진입 구조 : 40점
      - 1시간 MA20 위치 : 20점
      - 과열/유동성     : 10점
    """
    # 1) 4시간 추세 강도: MA별 차등 lookback 상승률을 10점씩 환산
    # 너무 가파른 상승이 점수를 무한히 끌어올리지 않도록 상한을 둔다.
    trend_thresholds = {20: 2.0, 60: 1.5, 120: 1.0}
    trend_score = 0.0

    for period, threshold in trend_thresholds.items():
        raw_slope = item.get(f"MA{period}_slope_pct_240m", 0)
        slope = 0.0 if pd.isna(raw_slope) else float(raw_slope)
        part = 10.0 * _clamp(slope / threshold, 0.0, 1.0)
        trend_score += part

    # 2) 1시간 진입 구조: 4개 조건 x 10점
    entry_flags = [
        item.get("entry_above_ma20", False),
        item.get("entry_short_ordered", False),
        item.get("entry_ma5_rising", False),
        item.get("entry_close_rising", False),
    ]
    entry_score_40 = 10.0 * sum(bool(x) for x in entry_flags)

    # 3) MA20 위치: 좋은 눌림(0~3%)에 가장 높은 점수
    distance = item.get("entry_distance_ma20_pct", np.nan)
    if pd.isna(distance):
        ma20_position_score = 0.0
    elif 0 <= distance <= 3:
        ma20_position_score = 20.0
    elif 3 < distance <= 5:
        ma20_position_score = 15.0
    elif 5 < distance <= 8:
        ma20_position_score = 8.0
    elif -1 <= distance < 0:
        ma20_position_score = 5.0
    else:
        ma20_position_score = 0.0

    # 4) 과열/유동성: 24h 상승률 3~8%를 가장 선호하고, 거래대금 가점
    change = float(item.get("change_24h", 0) or 0)
    if 3 <= change <= 8:
        momentum_score = 6.0
    elif 1 <= change < 3:
        momentum_score = 4.0
    elif 8 < change <= 12:
        momentum_score = 3.0
    else:
        momentum_score = 0.0

    trade_value = float(item.get("trade_value_24h", 0) or 0)
    if trade_value >= 10_000_000_000:  # 100억원 이상
        liquidity_score = 4.0
    elif trade_value >= 3_000_000_000:  # 30억원 이상
        liquidity_score = 3.0
    elif trade_value >= 1_000_000_000:  # 10억원 이상
        liquidity_score = 2.0
    elif trade_value >= MIN_TRADE_VALUE_24H:
        liquidity_score = 1.0
    else:
        liquidity_score = 0.0

    market_quality_score = momentum_score + liquidity_score

    # 5) 명시적 패널티: 점수와 사람이 읽는 판단이 모순되지 않도록 한다.
    penalty_overheat = (
        15.0 if pd.notna(distance) and distance > ENTRY_OVERHEAT_PCT else 0.0
    )
    penalty_below_ma20 = 10.0 if pd.notna(distance) and distance < 0 else 0.0
    penalty_daily_surge = 10.0 if change > 12.0 else 0.0
    penalty_total = penalty_overheat + penalty_below_ma20 + penalty_daily_surge

    final_score = (
        trend_score
        + entry_score_40
        + ma20_position_score
        + market_quality_score
        - penalty_total
    )
    final_score = _clamp(final_score, 0.0, 100.0)

    return {
        "final_score": round(final_score, 1),
        "score_trend_4h": round(trend_score, 1),
        "score_entry_1h": round(entry_score_40, 1),
        "score_ma20_position": round(ma20_position_score, 1),
        "score_market_quality": round(market_quality_score, 1),
        "score_penalty": round(penalty_total, 1),
        "penalty_overheat": round(penalty_overheat, 1),
        "penalty_below_ma20": round(penalty_below_ma20, 1),
        "penalty_daily_surge": round(penalty_daily_surge, 1),
    }


# ============================================================
# 가격 표시 함수
# ============================================================
def format_price(value) -> str:
    """과학 표기법 없이 가격을 읽기 쉬운 일반 숫자로 표시한다."""
    if value is None or pd.isna(value):
        return "-"

    value = float(value)
    abs_value = abs(value)

    if abs_value >= 1_000:
        text = f"{value:,.0f}"
    elif abs_value >= 100:
        text = f"{value:,.1f}"
    elif abs_value >= 1:
        text = f"{value:,.2f}"
    elif abs_value >= 0.01:
        text = f"{value:,.4f}"
    else:
        text = f"{value:,.8f}"

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text


# ============================================================
# 12. MA / ATR 기반 매수·손절·익절 전략
# ============================================================
def calculate_ma_atr_strategy(item: dict) -> dict:
    """1시간봉 MA20/MA60과 ATR14로 동적 매매 계획을 계산한다.

    원칙
    - 매수구간: MA20 ± 0.5 ATR
    - 초기 손절: MA60 - 0.5 ATR과 최대 2 ATR 손실선 중 더 가까운 쪽
    - 1차 30%: +1.5R, 이후 남은 물량 손절선을 계획 진입가(본전)로 상향
    - 2차 30%: +2.5R, 이후 마지막 40%에 MA20 - 2 ATR Trail 적용
    - 마지막 40%: 고정 익절하지 않고 Runner로 유지
    - +4R 도달 이후 Runner Trail을 MA20 - 1.5 ATR로 강화
    - Trail은 실제 보유 중 완료된 1시간봉마다 다시 계산하며 아래로 내리지 않는다.
    - 포지션 크기는 계좌자금 × 거래당 허용위험 / 1개당 손절위험으로 계산하고
      한 종목 최대 투입비중으로 한 번 더 제한한다.
    """
    current_price = float(item.get("price", np.nan))
    ma20 = float(item.get("MA20_60m", np.nan))
    ma60 = float(item.get("MA60_60m", np.nan))
    atr = float(item.get("ATR14_60m", np.nan))

    values = [current_price, ma20, ma60, atr]
    if any(pd.isna(x) for x in values) or current_price <= 0 or ma20 <= 0 or atr <= 0:
        return {
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
            "runner_mode": "데이터 부족",
            "risk_per_unit": np.nan,
            "risk_pct": np.nan,
            "atr14": atr,
            "risk_budget": np.nan,
            "position_amount": np.nan,
            "position_quantity": np.nan,
            "actual_risk_amount": np.nan,
            "actual_risk_pct": np.nan,
            "position_capped": False,
        }

    buy_zone_low = max(0.0, ma20 - BUY_ZONE_ATR * atr)
    buy_zone_high = ma20 + BUY_ZONE_ATR * atr

    if current_price > buy_zone_high:
        buy_reference = buy_zone_high
    elif current_price < buy_zone_low:
        buy_reference = ma20 + 0.10 * atr
    else:
        buy_reference = current_price

    ma60_stop = ma60 - STOP_MA60_ATR * atr
    atr_stop = buy_reference - MAX_STOP_ATR * atr
    stop_price = max(ma60_stop, atr_stop)
    stop_price = min(stop_price, buy_zone_low - 0.25 * atr)

    min_risk = MIN_RISK_ATR * atr
    risk_per_unit = buy_reference - stop_price
    if risk_per_unit < min_risk:
        risk_per_unit = min_risk
        stop_price = buy_reference - risk_per_unit

    stop_price = max(0.0, stop_price)
    risk_per_unit = buy_reference - stop_price
    if risk_per_unit <= 0:
        return {
            "strategy_available": False,
            "buy_zone_low": buy_zone_low,
            "buy_zone_high": buy_zone_high,
            "buy_reference": buy_reference,
            "stop_price": stop_price,
            "breakeven_stop": np.nan,
            "trailing_stop_normal": np.nan,
            "trailing_stop_tight": np.nan,
            "trailing_stop_current": np.nan,
            "take_profit_1": np.nan,
            "take_profit_2": np.nan,
            "runner_trigger_4r": np.nan,
            "runner_mode": "손절폭 오류",
            "risk_per_unit": risk_per_unit,
            "risk_pct": np.nan,
            "atr14": atr,
            "risk_budget": np.nan,
            "position_amount": np.nan,
            "position_quantity": np.nan,
            "actual_risk_amount": np.nan,
            "actual_risk_pct": np.nan,
            "position_capped": False,
        }

    take_profit_1 = buy_reference + TP1_R_MULTIPLIER * risk_per_unit
    take_profit_2 = buy_reference + TP2_R_MULTIPLIER * risk_per_unit
    runner_trigger_4r = buy_reference + RUNNER_TRIGGER_R * risk_per_unit

    breakeven_stop = buy_reference
    trailing_stop_normal = max(
        breakeven_stop,
        ma20 - TRAIL_ATR_MULTIPLIER * atr,
    )
    trailing_stop_tight = max(
        breakeven_stop,
        ma20 - RUNNER_TRAIL_ATR_MULTIPLIER * atr,
    )

    # 현재가가 이미 4R 이상이라면 강화 Trail 기준을 보여준다.
    if current_price >= runner_trigger_4r:
        trailing_stop_current = trailing_stop_tight
        runner_mode = "4R 이후 강화 Trail(1.5ATR)"
    else:
        trailing_stop_current = trailing_stop_normal
        runner_mode = "기본 Trail(2ATR)"

    risk_pct = (risk_per_unit / buy_reference * 100) if buy_reference > 0 else np.nan

    # 리스크 기반 포지션 사이징
    risk_budget = ACCOUNT_CAPITAL * RISK_PER_TRADE_PCT / 100
    max_position_amount = ACCOUNT_CAPITAL * MAX_POSITION_PCT / 100
    raw_quantity = risk_budget / risk_per_unit
    raw_position_amount = raw_quantity * buy_reference
    position_amount = min(raw_position_amount, max_position_amount, ACCOUNT_CAPITAL)
    position_quantity = position_amount / buy_reference
    actual_risk_amount = position_quantity * risk_per_unit
    actual_risk_pct = actual_risk_amount / ACCOUNT_CAPITAL * 100
    position_capped = position_amount + 1e-9 < raw_position_amount

    return {
        "strategy_available": True,
        "buy_zone_low": buy_zone_low,
        "buy_zone_high": buy_zone_high,
        "buy_reference": buy_reference,
        "stop_price": stop_price,
        "breakeven_stop": breakeven_stop,
        "trailing_stop_normal": trailing_stop_normal,
        "trailing_stop_tight": trailing_stop_tight,
        "trailing_stop_current": trailing_stop_current,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "runner_trigger_4r": runner_trigger_4r,
        "runner_mode": runner_mode,
        "risk_per_unit": risk_per_unit,
        "risk_pct": risk_pct,
        "atr14": atr,
        "risk_budget": risk_budget,
        "position_amount": position_amount,
        "position_quantity": position_quantity,
        "actual_risk_amount": actual_risk_amount,
        "actual_risk_pct": actual_risk_pct,
        "position_capped": position_capped,
    }


# ============================================================
# 13. 차트
# ============================================================
def plot_candle_with_strategy(
    df: pd.DataFrame,
    item: dict,
    strategy: dict,
) -> plt.Figure:
    completed = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    required_extra = {
        f"VolumeEMA{VOLUME_EMA_PERIOD}",
        f"RSI{RSI_PERIOD}",
        "RSI_Dynamic_Upper",
        "RSI_Dynamic_Center",
        "RSI_Dynamic_Lower",
    }
    if not required_extra.issubset(completed.columns):
        completed = add_indicators(completed)
    df_plot = completed.tail(CHART_BARS).copy()

    current_price = item["price"]
    buy_low = strategy["buy_zone_low"]
    buy_high = strategy["buy_zone_high"]
    stop_price = strategy["stop_price"]
    tp1 = strategy["take_profit_1"]
    tp2 = strategy["take_profit_2"]
    runner_trigger = strategy["runner_trigger_4r"]
    trail_stop = strategy["trailing_stop_current"]

    buy_colors = ["#C62828", "#EF5350"]
    stop_color = "#6D4C41"
    trail_color = "#455A64"
    sell_colors = ["#00796B", "#009688", "#26A69A"]
    current_color = "#111111"
    ma_colors = {5: "#7B1FA2", 20: "#F57C00", 60: "#388E3C", 120: "#1565C0"}

    add_plots = []
    for period in MA_PERIODS:
        col = f"MA{period}"
        if col in df_plot.columns:
            add_plots.append(mpf.make_addplot(df_plot[col], color=ma_colors[period], width=1.0, panel=0))

    volume_ema_col = f"VolumeEMA{VOLUME_EMA_PERIOD}"
    add_plots.append(
        mpf.make_addplot(
            df_plot[volume_ema_col],
            panel=1,
            color="#616161",
            width=1.1,
        )
    )

    # Dynamic RSI 전용 세 번째 패널
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

    raw_hlines = [
        (buy_colors[0], buy_low),
        (buy_colors[1], buy_high),
        (stop_color, stop_price),
        (sell_colors[0], tp1),
        (sell_colors[1], tp2),
        (sell_colors[2], runner_trigger),
        (trail_color, trail_stop),
        (current_color, current_price),
    ]
    valid_hlines = [
        (color, value)
        for color, value in raw_hlines
        if value is not None and pd.notna(value) and np.isfinite(float(value))
    ]
    plot_kwargs = dict(
        type="candle",
        style=style,
        ylabel="가격 (원)",
        ylabel_lower="거래량",
        addplot=add_plots,
        volume=True,
        panel_ratios=(6, 2, 2),
        figsize=(14, 10),
        returnfig=True,
        warn_too_much_data=1000,
    )
    if valid_hlines:
        plot_kwargs["hlines"] = {
            "hlines": [value for _, value in valid_hlines],
            "colors": [color for color, _ in valid_hlines],
            "linestyle": "--",
            "linewidths": 1.0,
            "alpha": 0.85,
        }
    fig, axes = mpf.plot(df_plot, **plot_kwargs)

    price_ax = axes[0]
    volume_ax = axes[2] if len(axes) >= 4 else axes[0]
    rsi_ax = axes[4] if len(axes) >= 6 else axes[-1]
    price_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: format_price(value)))

    price_handles = [
        plt.Line2D([0], [0], color=buy_colors[0], linestyle="--", label=f"매수구간 하단: {format_price(buy_low)}원"),
        plt.Line2D([0], [0], color=buy_colors[1], linestyle="--", label=f"매수구간 상단: {format_price(buy_high)}원"),
        plt.Line2D([0], [0], color=stop_color, linestyle="--", label=f"손절: {format_price(stop_price)}원"),
        plt.Line2D([0], [0], color=sell_colors[0], linestyle="--", label=f"1차 익절 30%: {format_price(tp1)}원"),
        plt.Line2D([0], [0], color=sell_colors[1], linestyle="--", label=f"2차 익절 30%: {format_price(tp2)}원"),
        plt.Line2D([0], [0], color=sell_colors[2], linestyle="--", label=f"Runner 강화(4R): {format_price(runner_trigger)}원"),
        plt.Line2D([0], [0], color=trail_color, linestyle="--", label=f"Runner Trail: {format_price(trail_stop)}원"),
        plt.Line2D([0], [0], color=current_color, linestyle="--", linewidth=1.5, label=f"현재가: {format_price(current_price)}원"),
    ]
    for period in MA_PERIODS:
        price_handles.append(plt.Line2D([0], [0], color=ma_colors[period], linewidth=1.5, label=f"MA{period}"))
    price_ax.legend(handles=price_handles, loc="upper left", fontsize=7.5, ncol=2)

    # HH/HL/LH/LL: 좌우 3봉이 확인된 Pivot만 표시
    swing_points = item.get("swing_points")
    if swing_points is None or not isinstance(swing_points, pd.DataFrame):
        swing_points = detect_swing_points(completed)
    visible_swings = swing_points[swing_points["timestamp"].isin(df_plot.index)] if not swing_points.empty else swing_points
    chart_range = max(float(df_plot["high"].max() - df_plot["low"].min()), 1e-12)
    for _, point in visible_swings.iterrows():
        label = str(point["label"])
        if label not in {"HH", "HL", "LH", "LL"}:
            continue
        ts = point["timestamp"]
        loc = df_plot.index.get_indexer([ts])[0]
        if loc < 0:
            continue
        price = float(point["price"])
        is_high = point["kind"] == "high"
        marker_y = price + chart_range * 0.018 if is_high else price - chart_range * 0.018
        text_y = price + chart_range * 0.040 if is_high else price - chart_range * 0.040
        marker = "v" if is_high else "^"
        marker_color = "#D32F2F" if label in {"HH", "HL"} else "#1565C0"
        price_ax.scatter(loc, marker_y, marker=marker, s=30, color=marker_color, zorder=6, clip_on=False)
        price_ax.text(loc, text_y, label, ha="center", va="bottom" if is_high else "top", fontsize=7.5, fontweight="bold", color=marker_color, clip_on=False)

    volume_ax.legend(
        handles=[plt.Line2D([0], [0], color="#616161", linewidth=1.2, label=f"Volume EMA{VOLUME_EMA_PERIOD}")],
        loc="upper left", fontsize=7.5
    )

    rsi_ax.set_ylim(0, 100)
    rsi_ax.axhline(70, color="#BDBDBD", linestyle="--", linewidth=0.7, alpha=0.6)
    rsi_ax.axhline(50, color="#BDBDBD", linestyle=":", linewidth=0.7, alpha=0.6)
    rsi_ax.axhline(30, color="#BDBDBD", linestyle="--", linewidth=0.7, alpha=0.6)
    rsi_ax.legend(
        handles=[
            plt.Line2D([0], [0], color="#7B1FA2", linewidth=1.3, label=f"RSI{RSI_PERIOD}"),
            plt.Line2D([0], [0], color="#C62828", linewidth=0.9, label="Dynamic Upper"),
            plt.Line2D([0], [0], color="#616161", linewidth=0.9, label="Dynamic Center"),
            plt.Line2D([0], [0], color="#1565C0", linewidth=0.9, label="Dynamic Lower"),
        ],
        loc="upper left", fontsize=7.2, ncol=2,
    )

    # 마지막 완료봉 시각을 X축의 마지막 tick으로 강제 표시
    if not df_plot.empty:
        n = len(df_plot)
        tick_count = min(7, n)
        tick_positions = np.linspace(0, n - 1, tick_count, dtype=int).tolist()
        tick_positions.append(n - 1)
        tick_positions = sorted(set(tick_positions))
        tick_labels = [pd.Timestamp(df_plot.index[pos]).strftime("%m/%d %H:%M") for pos in tick_positions]
        rsi_ax.set_xticks(tick_positions)
        rsi_ax.set_xticklabels(tick_labels, rotation=45, ha="right")

    fig.subplots_adjust(left=0.08, right=0.95, top=0.98, bottom=0.11, hspace=0.08)
    return fig


# ============================================================
# 14. 결과표 / 핵심 판단
# ============================================================
def classify_candidate(item: dict) -> str:
    """복잡한 지표를 사용자가 빠르게 읽을 수 있는 한 줄 판단으로 변환한다."""
    status = item.get("entry_status", "미확인")
    change_24h = float(item.get("change_24h", 0) or 0)

    if status == "진입 관심":
        if change_24h >= STRONG_RISE_24H_PCT:
            return "강한상승+진입 가능"
        return "우선관찰"

    if status in {"눌림 확인", "눌림 대기"}:
        return "눌림 기다리기"

    if status == "과열 주의":
        return "과열 주의"

    if status in {"MA20 하회", "추세 확인 필요"}:
        return "반등 확인 필요"

    return "확인 필요"


def make_final_investment_advice(item: dict) -> tuple[str, str]:
    """시장/상대강도/Swing/진입/RSI/거래량을 종합한 규칙 기반 참고 판단."""
    regime = str(item.get("btc_regime", "확인 불가"))
    rs = item.get("rs_vs_btc_24h", np.nan)
    swing = str(item.get("swing_structure", "데이터 부족"))
    entry = str(item.get("entry_status", "미확인"))
    distance = item.get("entry_distance_ma20_pct", np.nan)
    rsi = item.get("RSI14_240m", np.nan)
    dyn_upper = item.get("RSI_dynamic_upper_240m", np.nan)
    dyn_lower = item.get("RSI_dynamic_lower_240m", np.nan)
    volume_ratio = item.get("VolumeRatio_240m", np.nan)

    rs_positive = pd.notna(rs) and float(rs) > 0
    rs_strong = pd.notna(rs) and float(rs) >= 2.0
    volume_ok = pd.notna(volume_ratio) and float(volume_ratio) >= 1.0
    volume_strong = pd.notna(volume_ratio) and float(volume_ratio) >= 1.5
    rsi_over_dynamic = (
        pd.notna(rsi) and pd.notna(dyn_upper) and float(rsi) >= float(dyn_upper)
    )
    rsi_below_dynamic = (
        pd.notna(rsi) and pd.notna(dyn_lower) and float(rsi) < float(dyn_lower)
    )

    reasons = []

    # 1) 가장 먼저 시장/구조 리스크를 체크한다.
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

    # 2) 추격매수 위험
    if entry == "과열 주의" or (pd.notna(distance) and float(distance) > ENTRY_OVERHEAT_PCT):
        reasons.append("1시간 MA20 이격이 큼")
        if rsi_over_dynamic:
            reasons.append("RSI가 Dynamic Upper 부근/이상")
        return "추격매수 자제", " · ".join(reasons) + " → MA20 근처 눌림이나 재돌파 확인을 기다리세요."

    if entry == "MA20 하회":
        reasons.append("현재가가 1시간 MA20 아래")
        if rsi_below_dynamic:
            reasons.append("RSI도 Dynamic Lower 아래")
        return "반등 확인 후 접근", " · ".join(reasons) + " → 1시간 MA20 회복과 거래량 동반을 확인하는 것이 우선입니다."

    # 3) 적극 관심 구간
    strong_market = regime.startswith("Q3") or regime.startswith("Q4")
    good_swing = swing == "HH/HL"
    good_entry = entry in {"진입 관심", "눌림 확인"}

    if strong_market and good_swing and rs_positive and good_entry:
        reasons.extend([f"{regime}", "BTC 대비 상대강도 우위", "HH/HL 상승 구조"] )
        if volume_strong:
            reasons.append("거래량이 EMA20 대비 강함")
        elif volume_ok:
            reasons.append("거래량이 평균 이상")
        else:
            reasons.append("거래량 확인 필요")
        if rsi_over_dynamic:
            return "눌림 후 분할매수 관심", " · ".join(reasons) + " · RSI가 상단에 가까워 즉시 추격보다 눌림 진입이 유리합니다."
        if rs_strong and volume_ok:
            return "분할매수 관심", " · ".join(reasons) + " → 계획 매수구간과 손절선을 지키는 전제에서 우선순위가 높은 후보입니다."
        return "매수 관심", " · ".join(reasons) + " → 진입구간 도달 여부를 확인한 뒤 분할 접근을 고려할 수 있습니다."

    # 4) 상승 구조는 유지되나 아직 진입 신호가 약한 경우
    if good_swing and rs_positive:
        reasons.extend(["HH/HL 상승 구조", "RS vs BTC 양수"] )
        if entry in {"눌림 대기", "눌림 확인"}:
            reasons.append("아직 최적 진입 위치 대기")
        if not volume_ok:
            reasons.append("거래량 확증 부족")
        return "눌림 대기", " · ".join(reasons) + " → 가격을 쫓기보다 1시간 MA20 부근의 반등 확인이 좋습니다."

    # 5) 애매한 구조
    if swing in {"HH/LL", "LH/HL"}:
        reasons.append(f"Swing 구조가 {swing}로 혼재")
    if not rs_positive:
        reasons.append("BTC 대비 상대강도가 약함")
    if entry in {"눌림 대기", "눌림 확인"}:
        reasons.append("진입 신호가 아직 완성되지 않음")

    if not reasons:
        reasons.append("핵심 조건이 아직 충분히 정렬되지 않음")
    return "관망", " · ".join(reasons) + " → 추가 확인 전에는 신규 진입 우선순위를 낮게 두는 편이 좋습니다."


def make_result_table(results: list[dict]) -> pd.DataFrame:
    rows = []

    for item in results:
        final = calculate_final_score(item)
        item.update(final)

        strategy = calculate_ma_atr_strategy(item)
        item.update(strategy)

        final_action, final_advice = make_final_investment_advice(item)
        item["final_action"] = final_action
        item["final_advice"] = final_advice

        rows.append(
            {
                "symbol": item["symbol"],
                "korean_name": item["korean_name"],
                "judgement": classify_candidate(item),
                "final_action": item.get("final_action", "관망"),
                "final_advice": item.get("final_advice", "추가 확인이 필요합니다."),
                "final_score": item["final_score"],
                "price": float(item["price"]),
                "change_24h": round(item["change_24h"], 2),
                "btc_regime": item.get("btc_regime", "확인 불가"),
                "rs_vs_btc_24h": item.get("rs_vs_btc_24h", np.nan),
                "swing_structure": item.get("swing_structure", "데이터 부족"),
                "rsi14_240m": item.get("RSI14_240m", np.nan),
                "volume_ratio_240m": item.get("VolumeRatio_240m", np.nan),
                "atr_pct_240m": item.get("ATR_Pct_240m", np.nan),
                "trade_value_24h": round(item["trade_value_24h"]),
                "MA20_240m": float(item["MA20_240m"]),
                "MA60_240m": float(item["MA60_240m"]),
                "MA120_240m": float(item["MA120_240m"]),
                "MA20_slope_pct_240m": item.get("MA20_slope_pct_240m", np.nan),
                "MA60_slope_pct_240m": item.get("MA60_slope_pct_240m", np.nan),
                "MA120_slope_pct_240m": item.get("MA120_slope_pct_240m", np.nan),
                "ma_rising_240m": item["ma_rising_240m"],
                "last_completed_240m": item.get("last_completed_240m"),
                "last_completed_60m": item.get("last_completed_60m"),
                "entry_status": item.get("entry_status", "미확인"),
                "entry_score": item.get("entry_score", 0),
                "entry_distance_ma20_pct": item.get(
                    "entry_distance_ma20_pct",
                    np.nan,
                ),
                "MA20_60m": item.get("MA20_60m", np.nan),
                "entry_price": item.get("entry_price", np.nan),
                "ATR14_60m": item.get("ATR14_60m", np.nan),
                "buy_zone_low": item.get("buy_zone_low", np.nan),
                "buy_zone_high": item.get("buy_zone_high", np.nan),
                "buy_reference": item.get("buy_reference", np.nan),
                "stop_price": item.get("stop_price", np.nan),
                "breakeven_stop": item.get("breakeven_stop", np.nan),
                "trailing_stop_normal": item.get("trailing_stop_normal", np.nan),
                "trailing_stop_tight": item.get("trailing_stop_tight", np.nan),
                "trailing_stop_current": item.get("trailing_stop_current", np.nan),
                "take_profit_1": item.get("take_profit_1", np.nan),
                "take_profit_2": item.get("take_profit_2", np.nan),
                "runner_trigger_4r": item.get("runner_trigger_4r", np.nan),
                "runner_mode": item.get("runner_mode", ""),
                "risk_pct": item.get("risk_pct", np.nan),
                "risk_budget": item.get("risk_budget", np.nan),
                "position_amount": item.get("position_amount", np.nan),
                "position_quantity": item.get("position_quantity", np.nan),
                "actual_risk_amount": item.get("actual_risk_amount", np.nan),
                "actual_risk_pct": item.get("actual_risk_pct", np.nan),
                "position_capped": item.get("position_capped", False),
                "score_trend_4h": item["score_trend_4h"],
                "score_entry_1h": item["score_entry_1h"],
                "score_ma20_position": item["score_ma20_position"],
                "score_market_quality": item["score_market_quality"],
                "score_penalty": item.get("score_penalty", 0.0),
                "penalty_overheat": item.get("penalty_overheat", 0.0),
                "penalty_below_ma20": item.get("penalty_below_ma20", 0.0),
                "penalty_daily_surge": item.get("penalty_daily_surge", 0.0),
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # FinalScore를 최우선으로 사용하고 동점일 때 진입점수/거래대금으로 정렬한다.
    return df.sort_values(
        ["final_score", "entry_score", "trade_value_24h", "change_24h"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def make_compact_display_table(result_table: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """화면에는 실제 판단에 필요한 핵심 컬럼만 보여준다."""
    top = result_table.head(top_n).copy()
    top["매수구간"] = top.apply(
        lambda row: (
            f"{format_price(row['buy_zone_low'])}~{format_price(row['buy_zone_high'])}"
            if pd.notna(row["buy_zone_low"]) and pd.notna(row["buy_zone_high"])
            else "-"
        ),
        axis=1,
    )

    return top[
        [
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
    ].rename(
        columns={
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
    )


# ============================================================
# 15. Streamlit 실행부
# ============================================================

def make_summary_lines(result_table: pd.DataFrame, top_n: int) -> list[str]:
    """상위 후보를 판단별로 묶어 Streamlit에 표시할 문장으로 반환한다."""
    top = result_table.head(top_n).copy()

    groups = [
        ("우선관찰", "추세 양호 + 1시간 MA20 근접"),
        ("강한상승+진입 가능", "조건은 좋지만 급등폭 주의"),
        ("눌림 기다리기", "추세 유지, 더 좋은 가격 대기"),
        ("과열 주의", "MA20 이격이 커 추격 자제"),
        ("반등 확인 필요", "1시간 MA20 회복 확인"),
        ("확인 필요", "추가 데이터 확인"),
    ]

    lines = []
    for label, note in groups:
        selected = top.loc[
            top["judgement"] == label,
            ["symbol", "korean_name"],
        ]
        if selected.empty:
            continue

        names = ", ".join(
            f"{row['symbol'].replace('KRW-', '')}({row['korean_name']})"
            for _, row in selected.iterrows()
        )
        lines.append(f"**{label} ({len(selected)})**: {names}  → {note}")

    return lines


def make_strategy_display_table(sorted_results: list[dict], count: int) -> pd.DataFrame:
    """상위 종목의 MA/ATR 매매 계획을 표 형태로 반환한다."""
    rows = []

    for item in sorted_results[:count]:
        strategy = calculate_ma_atr_strategy(item)
        if not strategy["strategy_available"]:
            continue

        rows.append(
            {
                "종목": item["symbol"],
                "한글명": item["korean_name"],
                "상태": item.get("entry_status", "미확인"),
                "현재가": item["price"],
                "매수구간 하단": strategy["buy_zone_low"],
                "매수구간 상단": strategy["buy_zone_high"],
                "손절": strategy["stop_price"],
                "손절폭(%)": strategy["risk_pct"],
                "1차 익절(30%)": strategy["take_profit_1"],
                "2차 익절(30%)": strategy["take_profit_2"],
                "4R Runner 강화": strategy["runner_trigger_4r"],
                "현재 Trail": strategy["trailing_stop_current"],
                "Runner 모드": strategy["runner_mode"],
                "권장 매수금": strategy["position_amount"],
                "예상 최대손실": strategy["actual_risk_amount"],
                "실제 계좌위험(%)": strategy["actual_risk_pct"],
                "종목비중 제한": strategy["position_capped"],
            }
        )

    return pd.DataFrame(rows)


def run_analysis(progress_bar=None, status_box=None) -> dict:
    """원본 main()의 분석 부분을 Streamlit에서 재사용할 수 있게 결과 객체로 반환한다."""
    client = UpbitPublicClient()
    try:
        return _run_analysis_body(client, progress_bar, status_box)
    finally:
        client.close()


def _run_analysis_body(client, progress_bar=None, status_box=None) -> dict:

    if status_box is not None:
        status_box.info("업비트 API 및 캐시 상태를 확인하는 중입니다.")

    status = get_environment_status(client)
    offline_mode = status["offline_mode"]

    krw_pairs, korean_name_map = load_market_info(client, status)
    if not krw_pairs:
        raise RuntimeError("분석할 KRW 마켓이 없습니다.")

    ticker_map, ticker_info = load_ticker_map(client, offline_mode)
    if not ticker_info["usable_for_trading"]:
        raise RuntimeError(
            "최신 ticker 데이터가 없어 매매 후보 계산을 중단했습니다. "
            "API 연결 또는 60분 이내 ticker 캐시를 확보한 뒤 다시 실행하세요."
        )

    if ticker_map:
        target_pairs = [
            symbol
            for symbol in krw_pairs
            if float(ticker_map.get(symbol, {}).get("acc_trade_price_24h", 0) or 0)
            >= MIN_TRADE_VALUE_24H
        ]
    else:
        target_pairs = krw_pairs

    # BTC 시장 환경은 모든 알트 후보에 공통으로 적용한다.
    btc_df_240m = None
    btc_source_240 = "missing"
    btc_regime = {"label": "확인 불가", "score": np.nan, "change_24h": np.nan}
    try:
        btc_df_240m, btc_source_240 = get_ohlcv(
            client=client,
            symbol="KRW-BTC",
            candle_unit=SCREEN_CANDLE_UNIT,
            offline_mode=offline_mode,
        )
        btc_regime = calculate_btc_regime(btc_df_240m)
    except Exception as e:
        errors_btc_context = [("KRW-BTC", f"BTC regime: {e}")]
    else:
        errors_btc_context = []

    results = []
    source_count_240 = {"cache": 0, "api": 0, "stale": 0, "missing": 0}
    source_count_60 = {"cache": 0, "api": 0, "stale": 0, "missing": 0}
    errors = list(errors_btc_context)

    total_steps = max(1, len(target_pairs))

    # 1단계: 4시간봉 추세 스크리닝
    for idx, symbol in enumerate(target_pairs, start=1):
        if status_box is not None:
            status_box.info(
                f"1/2 · 4시간봉 분석 {idx}/{len(target_pairs)} · {symbol}"
            )
        if progress_bar is not None:
            progress_bar.progress(min(0.70, 0.70 * idx / total_steps))

        try:
            if symbol == "KRW-BTC" and btc_df_240m is not None:
                df_240m, source = btc_df_240m, btc_source_240
            else:
                df_240m, source = get_ohlcv(
                    client=client,
                    symbol=symbol,
                    candle_unit=SCREEN_CANDLE_UNIT,
                    offline_mode=offline_mode,
                )
            source_count_240[source] = source_count_240.get(source, 0) + 1

            if df_240m is None:
                continue

            result = analyze_screen_symbol(
                symbol=symbol,
                korean_name=korean_name_map.get(
                    symbol,
                    symbol.replace("KRW-", ""),
                ),
                df=df_240m,
                ticker=ticker_map.get(symbol),
            )

            if result:
                btc_change_24h = btc_regime.get("change_24h", np.nan)
                result["btc_regime"] = btc_regime.get("label", "확인 불가")
                result["btc_regime_score"] = btc_regime.get("score", np.nan)
                result["btc_change_24h"] = btc_change_24h
                result["rs_vs_btc_24h"] = (
                    float(result["change_24h"]) - float(btc_change_24h)
                    if pd.notna(btc_change_24h)
                    else np.nan
                )
                results.append(result)

        except Exception as e:
            errors.append((symbol, f"240m: {e}"))

    if not results:
        if progress_bar is not None:
            progress_bar.progress(1.0)
        return {
            "status": status,
            "offline_mode": offline_mode,
            "krw_pairs": krw_pairs,
            "target_pairs": target_pairs,
            "ticker_info": ticker_info,
            "btc_regime": btc_regime,
            "results": [],
            "result_table": pd.DataFrame(),
            "sorted_results": [],
            "source_count_240": source_count_240,
            "source_count_60": source_count_60,
            "errors": errors,
        }

    # 2단계: 1시간봉 진입 타이밍 확인
    entry_targets = results
    entry_total = max(1, len(entry_targets))

    for idx, item in enumerate(entry_targets, start=1):
        symbol = item["symbol"]
        if status_box is not None:
            status_box.info(
                f"2/2 · 1시간봉 진입 확인 {idx}/{len(entry_targets)} · {symbol}"
            )
        if progress_bar is not None:
            progress_bar.progress(0.70 + 0.30 * idx / entry_total)

        try:
            df_60m, source = get_ohlcv(
                client=client,
                symbol=symbol,
                candle_unit=ENTRY_CANDLE_UNIT,
                offline_mode=offline_mode,
            )
            source_count_60[source] = source_count_60.get(source, 0) + 1

            entry = analyze_entry_timing(
                df_60m,
                current_price=item["price"],
            )
            item.update(entry)
            item["df_60m"] = df_60m

        except Exception as e:
            errors.append((symbol, f"60m: {e}"))
            item.update(
                analyze_entry_timing(
                    pd.DataFrame(),
                    current_price=item["price"],
                )
            )
            item["df_60m"] = pd.DataFrame()

    result_table = make_result_table(results)
    result_by_symbol = {item["symbol"]: item for item in results}
    sorted_results = [
        result_by_symbol[symbol]
        for symbol in result_table["symbol"]
        if symbol in result_by_symbol
    ]

    # 기존 CSV 파일 저장도 유지한다.
    result_table.to_csv(
        RESULT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    if progress_bar is not None:
        progress_bar.progress(1.0)
    if status_box is not None:
        status_box.success("분석이 완료되었습니다.")

    return {
        "status": status,
        "offline_mode": offline_mode,
        "krw_pairs": krw_pairs,
        "target_pairs": target_pairs,
        "ticker_info": ticker_info,
        "btc_regime": btc_regime,
        "results": results,
        "result_table": result_table,
        "sorted_results": sorted_results,
        "source_count_240": source_count_240,
        "source_count_60": source_count_60,
        "errors": errors,
    }


def render_main_table(result_table: pd.DataFrame, top_n: int) -> None:
    compact = make_compact_display_table(result_table, top_n)

    st.dataframe(
        compact,
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
        strategy = calculate_ma_atr_strategy(item)
        if not strategy["strategy_available"]:
            continue

        title = (
            f"{item['korean_name']} · {item['symbol']} · "
            f"FinalScore {item.get('final_score', 0):.1f}"
        )

        with st.expander(title, expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("현재가", f"{format_price(item['price'])}원")
            c2.metric("24시간", f"{item['change_24h']:+.2f}%")
            c3.metric("진입 상태", item.get("entry_status", "미확인"))
            c4.metric("ATR14", format_price(strategy["atr14"]))

            st.markdown(
                f"""
- **최종 판단:** {item.get('final_action', '관망')}
- **투자 조언:** {item.get('final_advice', '추가 확인이 필요합니다.')}
- **매수구간:** {format_price(strategy['buy_zone_low'])} ~ {format_price(strategy['buy_zone_high'])}원
- **손절:** {format_price(strategy['stop_price'])}원 · 계획 진입가 대비 **-{strategy['risk_pct']:.2f}%**
- **1차 익절:** {format_price(strategy['take_profit_1'])}원에서 30%
- **2차 익절:** {format_price(strategy['take_profit_2'])}원에서 30%
- **Runner:** 남은 40% 유지, {format_price(strategy['runner_trigger_4r'])}원(4R)부터 Trail 2ATR → 1.5ATR 강화
- **현재 Trail 참고:** {format_price(strategy['trailing_stop_current'])}원 · {strategy['runner_mode']}
- **권장 매수금:** {strategy['position_amount']:,.0f}원 · 예상 최대손실 {strategy['actual_risk_amount']:,.0f}원 ({strategy['actual_risk_pct']:.2f}% of account)
                """
            )

            if strategy["position_capped"]:
                st.caption("종목당 최대 투자비중 제한이 적용된 포지션입니다.")
            st.caption(
                "Trail은 완료된 1시간봉마다 다시 계산하고, 실제 운용 시 기존 Trail보다 낮추지 않는 방식입니다."
            )


def render_charts(sorted_results: list[dict], default_count: int) -> None:
    available = [
        item
        for item in sorted_results
        if item.get("df_240m") is not None and not item["df_240m"].empty
    ]
    if not available:
        st.info("표시할 4시간봉 차트 데이터가 없습니다.")
        return

    labels = {
        f"{item['symbol']} · {item['korean_name']} · {item.get('final_score', 0):.1f}": item
        for item in available
    }
    default_labels = list(labels.keys())[: min(default_count, len(labels))]

    selected_labels = st.multiselect(
        "차트로 볼 종목",
        options=list(labels.keys()),
        default=default_labels,
    )

    for idx, label in enumerate(selected_labels):
        item = labels[label]
        strategy = calculate_ma_atr_strategy(item)
        if not strategy["strategy_available"]:
            continue

        st.markdown(
            f"""
            <div style="text-align:center; font-size:1.55rem; font-weight:700;
                        margin:0.25rem 0 0.15rem 0; line-height:1.35;">
                {item['korean_name']} ({item['symbol']}) - 4시간봉
            </div>
            """,
            unsafe_allow_html=True,
        )
        last_completed = item.get("last_completed_240m")
        if last_completed is None or pd.isna(last_completed):
            completed_df = keep_completed_candles(item["df_240m"], SCREEN_CANDLE_UNIT)
            last_completed = completed_df.index[-1] if not completed_df.empty else pd.NaT

        last_completed_text = (
            pd.Timestamp(last_completed).strftime("%Y-%m-%d %H:%M KST")
            if pd.notna(last_completed)
            else "확인 불가"
        )

        st.markdown(
            f"""
            <div style="text-align:center; color:#7a7f8c; font-size:0.90rem;
                        margin:0 0 0.45rem 0; line-height:1.4;">
                현재가 {format_price(item['price'])}원 |
                24시간 {item['change_24h']:+.2f}% |
                RS vs BTC {item.get('rs_vs_btc_24h', np.nan):+.2f}% |
                {item.get('btc_regime', '확인 불가')} |
                Swing {item.get('swing_structure', '데이터 부족')}<br>
                RSI14 {item.get('RSI14_240m', np.nan):.1f} |
                VolumeRatio {item.get('VolumeRatio_240m', np.nan):.2f}x |
                ATR% {item.get('ATR_Pct_240m', np.nan):.2f}% |
                Dynamic RSI {item.get('RSI_dynamic_lower_240m', np.nan):.1f} ~ {item.get('RSI_dynamic_upper_240m', np.nan):.1f} |
                마지막 완료봉 {last_completed_text}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"<div style='text-align:center; background:#f8f9fb; border:1px solid #e5e7eb; "
            f"border-radius:8px; padding:0.55rem 0.8rem; margin:0 0 0.55rem 0; font-size:0.88rem;'>"
            f"<b>최종 판단: {item.get('final_action', '관망')}</b><br>"
            f"{item.get('final_advice', '추가 확인이 필요합니다.')}"
            f"</div>",
            unsafe_allow_html=True,
        )

        fig = plot_candle_with_strategy(
            df=item["df_240m"],
            item=item,
            strategy=strategy,
        )
        st.pyplot(fig, width="stretch")
        plt.close(fig)

        if idx < len(selected_labels) - 1:
            st.divider()


def streamlit_main() -> None:
    global MIN_CHANGE_24H, MAX_CHANGE_24H, MIN_TRADE_VALUE_24H
    global ACCOUNT_CAPITAL, RISK_PER_TRADE_PCT, MAX_POSITION_PCT
    global TOP_N, STRATEGY_N, CHART_N
    global TICKER_CACHE_EXPIRE_MINUTES, TICKER_CACHE_WARN_MINUTES, TICKER_CACHE_MAX_AGE_MINUTES

    st.set_page_config(
        page_title="업비트 코인 분석기",
        page_icon="📊",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] {display:none !important;}
        div[data-testid="stToolbar"] {display:none !important;}
        .block-container {
            padding-top: 1.2rem !important;
            padding-bottom: 1rem !important;
            max-width: 1500px;
        }
        section[data-testid="stSidebar"] {
            width: 295px !important;
            min-width: 295px !important;
            background: #f3f5f9 !important;
            border-right: 1px solid #e5e7eb;
        }
        section[data-testid="stSidebar"] > div {
            width: 295px !important;
            background: #f3f5f9 !important;
        }
        section[data-testid="stSidebar"] .block-container {
            padding: 0.45rem 0.90rem 0.55rem 0.90rem !important;
        }
        .main-app-title {
            font-size: 2.55rem;
            font-weight: 800;
            line-height: 1.24;
            letter-spacing: -0.03em;
            color: #2b2d3a;
            margin: 0.25rem 0 0.7rem 0;
        }
        .main-app-subtitle {
            font-size: 0.97rem;
            color: #7b8190;
            margin: 0 0 1rem 0;
        }
        .main-top-divider {
            border: 0;
            height: 1px;
            background: #e5e7eb;
            margin: 0.8rem 0 1.4rem 0;
        }
        .info-banner {
            background: #eef2ff;
            border-radius: 10px;
            padding: 0.95rem 1rem;
            color: #1d4ed8;
            font-size: 1rem;
            margin-bottom: 1.2rem;
        }
        .sidebar-section-title {
            font-size: 1.05rem;
            font-weight: 800;
            color: #2f3342;
            margin: 0.32rem 0 0.30rem 0;
        }
        section[data-testid="stSidebar"] label {
            font-size: 0.82rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] input {
            font-size: 0.92rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
            gap: 0.55rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button,
        section[data-testid="stSidebar"] div[data-testid="stFormSubmitButton"] button {
            min-height: 2.35rem !important;
            height: 2.35rem !important;
            font-size: 1rem !important;
            font-weight: 700 !important;
            border-radius: 10px !important;
            margin-top: 0.45rem !important;
        }
        .sidebar-summary-box { display: none; }
        .sidebar-gap { height: 0.55rem; }
        section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
            gap: 0.10rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stSlider"] {
            margin: 0 0 0.08rem 0 !important;
            padding: 0 !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stSlider"] label {
            font-size: 0.82rem !important;
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stSlider"] [data-baseweb="slider"] * {
            font-size: 0.90rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] {
            margin: 0 !important;
            padding: 0 !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] label {
            font-size: 0.82rem !important;
            margin-bottom: 0.08rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] div[data-baseweb="input"] {
            min-height: 2.05rem !important;
            height: 2.05rem !important;
            border-radius: 0.55rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] input {
            min-height: 2.05rem !important;
            height: 2.05rem !important;
            padding: 0 0.55rem !important;
            font-size: 0.93rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
            gap: 0.42rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button {
            min-height: 2.15rem !important;
            height: 2.15rem !important;
            margin-top: 0.20rem !important;
            font-size: 0.90rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown('<div class="sidebar-section-title">⚙ 분석 설정 · v17</div>', unsafe_allow_html=True)
        cache_minutes = st.slider(
            "캐시 만료(분)", 10, 180, int(TICKER_CACHE_MAX_AGE_MINUTES), 5
        )
        st.markdown('<div class="sidebar-gap"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">💰 포지션 리스크</div>', unsafe_allow_html=True)
        account_capital_text = st.text_input("계좌 자금(원)", value=f"{ACCOUNT_CAPITAL:,.0f}")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            risk_per_trade_text = st.text_input("위험(%)", value=f"{RISK_PER_TRADE_PCT:.2f}")
        with col_r2:
            max_position_text = st.text_input("비중(%)", value=f"{MAX_POSITION_PCT:.2f}")
        st.markdown('<div class="sidebar-gap"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">🔍 필터링 조건</div>', unsafe_allow_html=True)
        min_change = st.slider("최소 변동률(%)", -10.0, 20.0, float(MIN_CHANGE_24H), 0.5)
        max_change = st.slider("최대 변동률(%)", 5.0, 50.0, float(MAX_CHANGE_24H), 0.5)
        min_trade_text = st.text_input("최소 거래대금(원)", value=f"{MIN_TRADE_VALUE_24H:,.0f}")
        st.markdown('<div class="sidebar-gap"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">📋 출력</div>', unsafe_allow_html=True)
        col_o1, col_o2, col_o3 = st.columns(3)
        with col_o1:
            top_n_text = st.text_input("TOP", value=str(int(TOP_N)))
        with col_o2:
            strategy_n_text = st.text_input("전략", value=str(int(STRATEGY_N)))
        with col_o3:
            chart_n_text = st.text_input("차트", value=str(int(CHART_N)))

        run_clicked = st.button("🚀 분석 실행", type="primary", width="stretch")

    def _parse_number(text_value: str, name: str, *, integer: bool = False):
        cleaned = str(text_value).replace(",", "").strip()
        if cleaned == "":
            raise ValueError(f"{name} 값을 입력하세요.")
        try:
            value = float(cleaned)
        except ValueError as exc:
            raise ValueError(f"{name}에는 숫자만 입력하세요.") from exc
        return int(value) if integer else value

    try:
        min_trade_value = _parse_number(min_trade_text, "최소 거래대금")
        account_capital = _parse_number(account_capital_text, "계좌 자금")
        risk_per_trade = _parse_number(risk_per_trade_text, "거래 위험")
        max_position = _parse_number(max_position_text, "최대 비중")
        top_n = _parse_number(top_n_text, "TOP", integer=True)
        strategy_n = _parse_number(strategy_n_text, "전략", integer=True)
        chart_n = _parse_number(chart_n_text, "차트", integer=True)
    except ValueError as e:
        st.sidebar.error(str(e))
        return

    validation_errors = []
    if min_change > max_change:
        validation_errors.append("최소 변동률은 최대 변동률보다 클 수 없습니다.")
    if min_trade_value < 1:
        validation_errors.append("최소 거래대금은 1원 이상이어야 합니다.")
    if account_capital < 100_000:
        validation_errors.append("계좌 자금은 100,000원 이상이어야 합니다.")
    if not (0.05 <= risk_per_trade <= 10):
        validation_errors.append("거래 위험은 0.05~10% 범위여야 합니다.")
    if not (1 <= max_position <= 100):
        validation_errors.append("최대 비중은 1~100% 범위여야 합니다.")
    if not (5 <= top_n <= 50):
        validation_errors.append("TOP은 5~50 범위여야 합니다.")
    if not (1 <= strategy_n <= 20):
        validation_errors.append("전략은 1~20 범위여야 합니다.")
    if not (1 <= chart_n <= 10):
        validation_errors.append("차트는 1~10 범위여야 합니다.")

    if validation_errors:
        for message in validation_errors:
            st.sidebar.error(message)
        return

    MIN_CHANGE_24H = float(min_change)
    MAX_CHANGE_24H = float(max_change)
    MIN_TRADE_VALUE_24H = float(min_trade_value)
    ACCOUNT_CAPITAL = float(account_capital)
    RISK_PER_TRADE_PCT = float(risk_per_trade)
    MAX_POSITION_PCT = float(max_position)
    TOP_N = int(top_n)
    STRATEGY_N = int(strategy_n)
    CHART_N = int(chart_n)
    TICKER_CACHE_MAX_AGE_MINUTES = int(cache_minutes)
    TICKER_CACHE_WARN_MINUTES = max(10, int(cache_minutes * 0.5))
    TICKER_CACHE_EXPIRE_MINUTES = min(30, max(5, int(cache_minutes * 0.25)))
    CACHE_EXPIRE_MINUTES[60] = min(60, max(10, int(cache_minutes * 0.5)))
    CACHE_EXPIRE_MINUTES[240] = int(cache_minutes)

    st.markdown('<div class="main-app-title">📊 업비트 코인 분석기</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="main-app-subtitle">4시간봉 추세 선별 → 1시간봉 진입 확인 → FinalScore → MA/ATR 매매 계획</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"등락 {MIN_CHANGE_24H:.1f}~{MAX_CHANGE_24H:.1f}% · 거래대금 {MIN_TRADE_VALUE_24H:,.0f}원 · 계좌 {ACCOUNT_CAPITAL:,.0f}원 · 위험 {RISK_PER_TRADE_PCT:.2f}% · 최대비중 {MAX_POSITION_PCT:.0f}% · TOP {TOP_N} / 전략 {STRATEGY_N} / 차트 {CHART_N}"
    )
    st.markdown('<hr class="main-top-divider">', unsafe_allow_html=True)

    if run_clicked:
        progress = st.progress(0.0)
        status_box = st.empty()
        try:
            analysis = run_analysis(progress, status_box)
            st.session_state["analysis"] = analysis
            st.session_state["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            progress.empty()
            status_box.empty()
            st.exception(e)
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
1. 4시간봉: MA5 > MA20 > MA60 > MA120
2. MA20/60/120 상승 조건 확인
3. 완료된 4시간봉으로 추세 판단
4. 24시간 등락률 및 거래대금 필터
5. 1시간봉 완료 캔들 + 실시간 ticker로 진입 위치 평가
6. FinalScore 100점 기준 정렬
7. MA20/MA60/ATR14 기반 매수·손절·익절 및 Runner 계산
            """
        )
        return

    result_table = analysis["result_table"]
    sorted_results = analysis["sorted_results"]
    ticker_info = analysis["ticker_info"]

    ticker_age_text = (
        "실시간 API"
        if ticker_info["source"] == "api"
        else f"캐시 {ticker_info['age_minutes']:.0f}분"
    )

    if result_table.empty:
        st.warning("현재 조건을 만족하는 코인이 없습니다.")
        return

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("전체 KRW 마켓", f"{len(analysis['krw_pairs'])}개")
    m2.metric("캔들 분석 대상", f"{len(analysis['target_pairs'])}개")
    m3.metric("4시간봉 후보", f"{len(analysis['results'])}개")
    m4.metric("오류", f"{len(analysis['errors'])}개")
    m5.metric("티커", ticker_age_text)

    if analysis["offline_mode"]:
        st.warning("업비트 API 연결 실패로 캐시 우선/오프라인 모드가 사용되었습니다.")
    elif ticker_info.get("warning"):
        st.warning(
            f"현재 ticker는 약 {ticker_info['age_minutes']:.0f}분 전 캐시입니다. 결과는 참고용으로 사용하세요."
        )

    st.caption(f"분석 시각: {st.session_state.get('analysis_time', '-')}")

    # ========================================================
    # 결과를 탭 없이 한 페이지에서 위에서 아래로 표시
    # ========================================================
    st.subheader(f"상위 {min(TOP_N, len(result_table))}개 후보")
    st.caption("Swing: HH=이전보다 높은 고점 · HL=이전보다 높은 저점 · LH=이전보다 낮은 고점 · LL=이전보다 낮은 저점 (HH/HL은 상승 구조, LH/LL은 하락 구조)")
    render_main_table(result_table, TOP_N)
    st.caption("※ ‘최종 판단/투자 조언’은 현재 데이터에 따른 규칙 기반 참고 신호이며, 확정적인 수익을 의미하지 않습니다.")

    st.markdown("---")
    st.subheader("핵심 해석")
    summary_lines = make_summary_lines(result_table, TOP_N)
    if summary_lines:
        for line in summary_lines:
            st.markdown(f"- {line}")
    else:
        st.info("표시할 판단 그룹이 없습니다.")

    st.markdown("---")
    st.subheader("MA / ATR 기반 매수·손절·익절 + Runner")
    st.caption("1차 30% +1.5R, 2차 30% +2.5R, 마지막 40% Runner")
    render_strategy_cards(sorted_results, STRATEGY_N)

    strategy_table = make_strategy_display_table(sorted_results, STRATEGY_N)
    if not strategy_table.empty:
        with st.expander("전략 표로 보기", expanded=False):
            st.dataframe(
                strategy_table,
                width="stretch",
                hide_index=True,
                column_config={
                    "현재가": st.column_config.NumberColumn(format="localized"),
                    "매수구간 하단": st.column_config.NumberColumn(format="localized"),
                    "매수구간 상단": st.column_config.NumberColumn(format="localized"),
                    "손절": st.column_config.NumberColumn(format="localized"),
                    "1차 익절(30%)": st.column_config.NumberColumn(format="localized"),
                    "2차 익절(30%)": st.column_config.NumberColumn(format="localized"),
                    "4R Runner 강화": st.column_config.NumberColumn(format="localized"),
                    "현재 Trail": st.column_config.NumberColumn(format="localized"),
                    "권장 매수금": st.column_config.NumberColumn(format="localized"),
                    "예상 최대손실": st.column_config.NumberColumn(format="localized"),
                },
            )

    st.markdown("---")
    st.subheader("캔들 차트")
    render_charts(sorted_results, CHART_N)

    st.markdown("---")
    st.subheader("전체 분석 데이터")
    st.dataframe(result_table, width="stretch", hide_index=True)

    csv_bytes = result_table.to_csv(
        index=False,
        encoding="utf-8-sig",
    ).encode("utf-8-sig")
    st.download_button(
        "CSV 다운로드",
        data=csv_bytes,
        file_name="upbit_coin_analyzer_results.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.subheader("오류 내역")
    if analysis["errors"]:
        error_df = pd.DataFrame(analysis["errors"], columns=["종목", "오류"])
        st.dataframe(error_df, width="stretch", hide_index=True)
    else:
        st.success("분석 중 수집된 오류가 없습니다.")


if __name__ == "__main__":
    streamlit_main()