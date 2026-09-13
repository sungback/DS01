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
# 1. 설정 및 글로벌 변수
# ============================================================
API_BASE = "https://api.upbit.com/v1"

CACHE_ROOT = Path("upbit_cache")
MARKET_CACHE_DIR = CACHE_ROOT / "market"
TICKER_CACHE_DIR = CACHE_ROOT / "ticker"
OHLCV_CACHE_DIR = CACHE_ROOT / "ohlcv"

for folder in [MARKET_CACHE_DIR, TICKER_CACHE_DIR, OHLCV_CACHE_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

MARKET_CACHE_FILE = MARKET_CACHE_DIR / "krw_markets.json"
TICKER_CACHE_FILE = TICKER_CACHE_DIR / "krw_ticker.json"

SCREEN_CANDLE_UNIT = 240
ENTRY_CANDLE_UNIT = 60
CANDLE_COUNT = 200

CACHE_EXPIRE_MINUTES = {60: 30, 240: 60}
TICKER_CACHE_EXPIRE_MINUTES = 10
TICKER_CACHE_WARN_MINUTES = 30
TICKER_CACHE_MAX_AGE_MINUTES = 60

MA_PERIODS = (5, 20, 60, 120)
MA_SLOPE_LOOKBACKS = {20: 3, 60: 6, 120: 12}
REQUIRE_MA_RISING = True

MIN_CHANGE_24H = 1.0
MAX_CHANGE_24H = 30.0
MIN_TRADE_VALUE_24H = 100_000_000

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

TP1_SELL_PCT = 30
TP2_SELL_PCT = 30
RUNNER_HOLD_PCT = 40

TRAIL_ATR_MULTIPLIER = 2.0
RUNNER_TRAIL_ATR_MULTIPLIER = 1.5

ACCOUNT_CAPITAL = 100_000_000
RISK_PER_TRADE_PCT = 0.5
MAX_POSITION_PCT = 20.0

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
# 2. 한글 폰트 및 유틸
# ============================================================
def configure_korean_font() -> str:
    installed = {font.name for font in fm.fontManager.ttflist}
    sys_name = platform.system()
    if sys_name == "Windows": candidates = ["Malgun Gothic", "NanumGothic"]
    elif sys_name == "Darwin": candidates = ["AppleGothic", "Arial Unicode MS", "NanumGothic"]
    else: candidates = ["NanumGothic", "Noto Sans CJK KR", "DejaVu Sans"]
    
    selected = next((name for name in candidates if name in installed), "DejaVu Sans")
    plt.rcParams["font.family"] = selected
    plt.rcParams["axes.unicode_minus"] = False
    return selected

KOREAN_FONT = configure_korean_font()

def format_price(value) -> str:
    if value is None or pd.isna(value): return "-"
    value, abs_value = float(value), abs(float(value))
    if abs_value >= 1_000: text = f"{value:,.0f}"
    elif abs_value >= 100: text = f"{value:,.1f}"
    elif abs_value >= 1: text = f"{value:,.2f}"
    elif abs_value >= 0.01: text = f"{value:,.4f}"
    else: text = f"{value:,.8f}"
    return text.rstrip("0").rstrip(".") if "." in text else text

# ============================================================
# 3. API 통신 및 캐시 관리
# ============================================================
class UpbitPublicClient:
    def __init__(self, request_interval=REQUEST_INTERVAL, max_retries=MAX_RETRIES):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "upbit-screener/8.0"})
        self.request_interval = request_interval
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def get(self, path: str, params: Optional[dict] = None):
        url = f"{API_BASE}{path}"
        for attempt in range(1, self.max_retries + 1):
            elapsed = time.monotonic() - self._last_request_at
            if (wait := self.request_interval - elapsed) > 0: time.sleep(wait)
            try:
                res = self.session.get(url, params=params, timeout=8)
                self._last_request_at = time.monotonic()
                if res.status_code == 429: time.sleep(1.05); continue
                if res.status_code == 418: raise RuntimeError("HTTP 418 차단")
                if 500 <= res.status_code < 600: time.sleep(min(2 ** (attempt - 1), 4)); continue
                res.raise_for_status()
                return res.json()
            except requests.RequestException:
                time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError("Upbit API 호출 실패")

    def get_markets(self) -> list[dict]: return self.get("/market/all")
    def get_krw_tickers(self) -> list[dict]: return self.get("/ticker/all", {"quote_currencies": "KRW"})
    def get_minute_candles(self, market: str, unit: int, count: int = CANDLE_COUNT) -> pd.DataFrame:
        data = self.get(f"/candles/minutes/{unit}", {"market": market, "count": min(count, 200)})
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        # 🔥 Duplicate Keys 에러 완벽 차단 방어막 🔥
        if "timestamp" in df.columns: df = df.drop(columns=["timestamp"])
        df = df.loc[:, ~df.columns.duplicated()]
        
        df = df.rename(columns={
            "candle_date_time_kst": "timestamp", "opening_price": "open",
            "high_price": "high", "low_price": "low", "trade_price": "close",
            "candle_acc_trade_volume": "volume", "candle_acc_trade_price": "trade_value"
        })
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        df[["open", "high", "low", "close", "volume", "trade_value"]] = df[["open", "high", "low", "close", "volume", "trade_value"]].apply(pd.to_numeric)
        return df.sort_values("timestamp").set_index("timestamp").loc[lambda x: ~x.index.duplicated(keep="last")]

def get_ohlcv_cache_path(symbol: str, candle_unit: int) -> Path:
    path = OHLCV_CACHE_DIR / f"{candle_unit}m"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{symbol.replace('-', '_')}.json"

def cache_is_fresh(path: Path, expire_minutes: int) -> bool:
    if not path.exists(): return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age <= timedelta(minutes=expire_minutes)

def get_current_candle_start_kst(candle_unit: int, now_kst: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    now = pd.Timestamp.now(tz="Asia/Seoul") if now_kst is None else pd.Timestamp(now_kst).tz_convert("Asia/Seoul")
    now_utc = now.tz_convert("UTC")
    unit_ns = pd.Timedelta(minutes=candle_unit).value
    floored_ns = (now_utc.value // unit_ns) * unit_ns
    return pd.Timestamp(floored_ns, tz="UTC").tz_convert("Asia/Seoul").tz_localize(None)

def cache_is_after_latest_candle_close(path: Path, candle_unit: int) -> bool:
    if not path.exists(): return False
    current_start = get_current_candle_start_kst(candle_unit)
    cache_mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").tz_convert("Asia/Seoul").tz_localize(None)
    return cache_mtime >= current_start

def load_ohlcv_cache(symbol: str, candle_unit: int, allow_stale: bool = False) -> Optional[pd.DataFrame]:
    path = get_ohlcv_cache_path(symbol, candle_unit)
    if not path.exists(): return None
    if not allow_stale and not cache_is_fresh(path, CACHE_EXPIRE_MINUTES.get(candle_unit, 60)): return None
    
    try:
        with path.open("r", encoding="utf-8") as f: payload = json.load(f)
        records = payload.get("records", payload) if isinstance(payload, dict) else payload
        df = pd.DataFrame(records)
        if df.empty or "timestamp" not in df.columns: return None
        df = df.loc[:, ~df.columns.duplicated()].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
        return df.loc[~df.index.duplicated(keep="last")]
    except Exception: return None

def save_ohlcv_cache(symbol: str, candle_unit: int, df: pd.DataFrame):
    if df is None or df.empty: return
    try:
        save_df = df.reset_index().rename(columns={df.index.name or "index": "timestamp"})
        save_df["timestamp"] = save_df["timestamp"].astype(str)
        records = json.loads(save_df.to_json(orient="records", force_ascii=False))
        path = get_ohlcv_cache_path(symbol, candle_unit)
        with path.open("w", encoding="utf-8") as f:
            json.dump({"version": 5, "market": symbol, "candle_unit_minutes": candle_unit, "saved_at": datetime.now().isoformat(), "records": records}, f, ensure_ascii=False)
    except Exception: pass

def get_ohlcv(client: UpbitPublicClient, symbol: str, candle_unit: int, offline_mode: bool) -> tuple[Optional[pd.DataFrame], str]:
    path = get_ohlcv_cache_path(symbol, candle_unit)
    if offline_mode:
        df = load_ohlcv_cache(symbol, candle_unit, allow_stale=True)
        if df is None: return None, "missing"
        fresh = cache_is_fresh(path, CACHE_EXPIRE_MINUTES.get(candle_unit, 60))
        return df, "cache" if fresh and cache_is_after_latest_candle_close(path, candle_unit) else "stale"

    df = load_ohlcv_cache(symbol, candle_unit, allow_stale=False)
    if df is not None and cache_is_after_latest_candle_close(path, candle_unit): return df, "cache"

    try:
        df = client.get_minute_candles(symbol, candle_unit)
        if not df.empty:
            save_ohlcv_cache(symbol, candle_unit, df)
            return df, "api"
    except Exception:
        if stale := load_ohlcv_cache(symbol, candle_unit, allow_stale=True): return stale, "stale"
    return None, "missing"

def get_environment_status(client: UpbitPublicClient) -> dict:
    try:
        markets = client.get_markets()
        return {"api_ok": True, "offline_mode": False, "markets": markets}
    except Exception:
        return {"api_ok": False, "offline_mode": True, "markets": []}

def load_market_info(client: UpbitPublicClient, status: dict) -> tuple[list[str], dict[str, str]]:
    if status["api_ok"]:
        try:
            krw_markets = [m for m in status["markets"] if m.get("market", "").startswith("KRW-")]
            pairs, n_map = [m["market"] for m in krw_markets], {m["market"]: m.get("korean_name", m["market"].replace("KRW-", "")) for m in krw_markets}
            with MARKET_CACHE_FILE.open("w", encoding="utf-8") as f: json.dump({"krw_pairs": pairs, "symbol_korean_map": n_map}, f, ensure_ascii=False)
            return pairs, n_map
        except Exception: pass

    try:
        with MARKET_CACHE_FILE.open("r", encoding="utf-8") as f: data = json.load(f)
        if pairs := data.get("krw_pairs"): return pairs, data.get("symbol_korean_map", {})
    except Exception: pass
    
    defaults = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
    return defaults, {p: p.replace("KRW-", "") for p in defaults}

def load_ticker_map(client: UpbitPublicClient, offline_mode: bool) -> tuple[dict[str, dict], dict]:
    age = float('inf')
    if TICKER_CACHE_FILE.exists():
        try:
            with TICKER_CACHE_FILE.open("r", encoding="utf-8") as f: payload = json.load(f)
            age = max(0.0, (datetime.now() - datetime.fromisoformat(payload.get("saved_at", ""))).total_seconds() / 60)
        except Exception:
            age = max(0.0, (datetime.now() - datetime.fromtimestamp(TICKER_CACHE_FILE.stat().st_mtime)).total_seconds() / 60)

    if not offline_mode:
        try:
            tickers = client.get_krw_tickers()
            with TICKER_CACHE_FILE.open("w", encoding="utf-8") as f: json.dump({"saved_at": datetime.now().isoformat(), "records": tickers}, f, ensure_ascii=False)
            return {t["market"]: t for t in tickers}, {"source": "api", "age_minutes": 0.0, "warning": False, "usable_for_trading": True}
        except Exception: pass

    cached = {}
    if TICKER_CACHE_FILE.exists():
        try:
            with TICKER_CACHE_FILE.open("r", encoding="utf-8") as f: payload = json.load(f)
            cached = {t["market"]: t for t in payload.get("records", [])}
        except Exception: pass

    if not cached: return {}, {"source": "missing", "age_minutes": age, "warning": True, "usable_for_trading": False}
    if age > TICKER_CACHE_MAX_AGE_MINUTES: return {}, {"source": "stale_blocked", "age_minutes": age, "warning": True, "usable_for_trading": False}
    return cached, {"source": "cache", "age_minutes": age, "warning": age > TICKER_CACHE_WARN_MINUTES, "usable_for_trading": True}

# ============================================================
# 4. 분석 및 전략 로직
# ============================================================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for p in MA_PERIODS: df[f"MA{p}"] = df["close"].rolling(p).mean()

    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df[f"ATR{ATR_PERIOD}"] = tr.rolling(ATR_PERIOD).mean()
    df["ATR_Pct"] = df[f"ATR{ATR_PERIOD}"] / df["close"] * 100

    df[f"VolumeEMA{VOLUME_EMA_PERIOD}"] = df["volume"].ewm(span=VOLUME_EMA_PERIOD, adjust=False).mean()
    df["VolumeRatio"] = df["volume"] / df[f"VolumeEMA{VOLUME_EMA_PERIOD}"].replace(0, np.nan)

    delta = df["close"].diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    df[f"RSI{RSI_PERIOD}"] = (100 - (100 / (1 + (gain / loss.replace(0, np.nan))))).clip(0, 100)

    rsi_col = f"RSI{RSI_PERIOD}"
    df["RSI_Dynamic_Center"] = df[rsi_col].ewm(span=DYNAMIC_RSI_CENTER_PERIOD, adjust=False).mean()
    rsi_std = df[rsi_col].rolling(DYNAMIC_RSI_STD_PERIOD).std()
    df["RSI_Dynamic_Upper"] = (df["RSI_Dynamic_Center"] + DYNAMIC_RSI_STD_MULTIPLIER * rsi_std).clip(0, 100)
    df["RSI_Dynamic_Lower"] = (df["RSI_Dynamic_Center"] - DYNAMIC_RSI_STD_MULTIPLIER * rsi_std).clip(0, 100)
    return df

def detect_swing_points(df: pd.DataFrame, left: int = SWING_LEFT_BARS, right: int = SWING_RIGHT_BARS) -> pd.DataFrame:
    if df is None or df.empty or len(df) < left + right + 3: return pd.DataFrame(columns=["timestamp", "kind", "label", "price"])
    highs, lows = [], []
    for i in range(left, len(df) - right):
        h, l = float(df["high"].iloc[i]), float(df["low"].iloc[i])
        if h > float(df["high"].iloc[i-left:i].max()) and h >= float(df["high"].iloc[i+1:i+1+right].max()): highs.append((df.index[i], h))
        if l < float(df["low"].iloc[i-left:i].min()) and l <= float(df["low"].iloc[i+1:i+1+right].min()): lows.append((df.index[i], l))

    points, prev_h, prev_l = [], None, None
    for ts, p in highs:
        points.append({"timestamp": ts, "kind": "high", "label": "H" if prev_h is None else ("HH" if p > prev_h else "LH"), "price": p}); prev_h = p
    for ts, p in lows:
        points.append({"timestamp": ts, "kind": "low", "label": "L" if prev_l is None else ("HL" if p > prev_l else "LL"), "price": p}); prev_l = p
    return pd.DataFrame(points).sort_values("timestamp").reset_index(drop=True) if points else pd.DataFrame(columns=["timestamp", "kind", "label", "price"])

def classify_swing_structure(points: pd.DataFrame) -> str:
    if points.empty: return "데이터 부족"
    h_lbls, l_lbls = points.loc[points["label"].isin(["HH", "LH"]), "label"], points.loc[points["label"].isin(["HL", "LL"]), "label"]
    return f"{h_lbls.iloc[-1]}/{l_lbls.iloc[-1]}" if not h_lbls.empty and not l_lbls.empty else "데이터 부족"

def keep_completed_candles(df: pd.DataFrame, candle_unit: int) -> pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame() if df is None else df.copy()
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    return df.loc[df.index + pd.Timedelta(minutes=candle_unit) <= now].copy()

def calculate_rolling_change_24h(df: pd.DataFrame) -> float:
    if df.empty: return np.nan
    past = df.loc[df.index <= (df.index[-1] - pd.Timedelta(hours=24)), "close"]
    return (float(df["close"].iloc[-1]) / float(past.iloc[-1]) - 1) * 100 if not past.empty and float(past.iloc[-1]) > 0 else np.nan

def is_uptrend(df: pd.DataFrame) -> tuple[bool, bool, dict[int, float]]:
    latest = df.iloc[-1]
    ordered = latest["MA5"] > latest["MA20"] > latest["MA60"] > latest["MA120"]
    slope_pct, rising_flags = {}, []
    for p, lb in MA_SLOPE_LOOKBACKS.items():
        if len(df) <= lb: return ordered, False, slope_pct
        c_ma, p_ma = float(df[f"MA{p}"].iloc[-1]), float(df[f"MA{p}"].iloc[-1 - lb])
        if pd.isna(c_ma) or pd.isna(p_ma) or p_ma <= 0: return ordered, False, slope_pct
        slope_pct[p] = (c_ma / p_ma - 1) * 100
        rising_flags.append(c_ma > p_ma)
    return ordered, all(rising_flags), slope_pct

def calculate_btc_regime(df: pd.DataFrame) -> dict:
    empty = {"label": "확인 불가", "score": np.nan, "change_24h": np.nan, "return_7d": np.nan, "ma120_dist_pct": np.nan, "ma20_slope_24h_pct": np.nan}
    if df is None or df.empty: return empty
    work = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    if len(work) < max(130, 43): return empty
    work = add_indicators(work)
    latest = work.iloc[-1]
    
    if pd.isna(latest.get("MA120")) or pd.isna(latest.get("MA20")) or len(work) < 7: return empty
    
    cl, ma120, ma20, ma20_past = float(latest["close"]), float(latest["MA120"]), float(latest["MA20"]), float(work["MA20"].iloc[-7])
    chg_24h = calculate_rolling_change_24h(work)
    ret_7d = (cl / float(work["close"].iloc[-43]) - 1) * 100 if len(work) >= 43 else np.nan
    
    score = sum([cl > ma120, ma20 > ma20_past, pd.notna(chg_24h) and chg_24h > 0, pd.notna(ret_7d) and ret_7d > 0])
    lbl = ["Q1 Weak", "Q2 Neutral", "Q3 Strong", "Q4 Very Strong"][score-1 if score>0 else 0] if score <= 4 else "Q4 Very Strong"
    
    return {"label": lbl, "score": score, "change_24h": float(chg_24h), "return_7d": float(ret_7d), "ma120_dist_pct": (cl / ma120 - 1) * 100, "ma20_slope_24h_pct": (ma20 / ma20_past - 1) * 100}

def analyze_screen_symbol(symbol: str, name: str, df: pd.DataFrame, ticker: Optional[dict]) -> Optional[dict]:
    df = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    if df.empty or len(df) < max(MA_PERIODS) + max(MA_SLOPE_LOOKBACKS.values()): return None
    df = add_indicators(df)
    latest = df.iloc[-1]
    swings = detect_swing_points(df)
    
    if latest[[f"MA{x}" for x in MA_PERIODS]].isna().any(): return None
    ordered, ma_rising, slope_pct = is_uptrend(df)
    if not ordered or (REQUIRE_MA_RISING and not ma_rising): return None
    
    chg_24h = calculate_rolling_change_24h(df)
    if pd.isna(chg_24h) or not (MIN_CHANGE_24H <= chg_24h <= MAX_CHANGE_24H): return None
    
    c_price = float(ticker.get("trade_price", latest["close"])) if ticker else float(latest["close"])
    t_val = float(ticker.get("acc_trade_price_24h", latest.get("trade_value", np.nan))) if ticker else float(latest.get("trade_value", np.nan))
    if pd.isna(t_val) or t_val < MIN_TRADE_VALUE_24H: return None
    
    return {
        "symbol": symbol, "korean_name": name, "price": c_price, "change_24h": chg_24h, "trade_value_24h": t_val,
        "MA5_240m": float(latest["MA5"]), "MA20_240m": float(latest["MA20"]), "MA60_240m": float(latest["MA60"]), "MA120_240m": float(latest["MA120"]),
        "ma_rising_240m": ma_rising, "MA20_slope_pct_240m": slope_pct.get(20, np.nan), "MA60_slope_pct_240m": slope_pct.get(60, np.nan), "MA120_slope_pct_240m": slope_pct.get(120, np.nan),
        "last_completed_240m": df.index[-1], "RSI14_240m": float(latest.get("RSI14", np.nan)), "RSI_dynamic_upper_240m": float(latest.get("RSI_Dynamic_Upper", np.nan)),
        "RSI_dynamic_center_240m": float(latest.get("RSI_Dynamic_Center", np.nan)), "RSI_dynamic_lower_240m": float(latest.get("RSI_Dynamic_Lower", np.nan)),
        "VolumeEMA20_240m": float(latest.get("VolumeEMA20", np.nan)), "VolumeRatio_240m": float(latest.get("VolumeRatio", np.nan)), "ATR_Pct_240m": float(latest.get("ATR_Pct", np.nan)),
        "swing_structure": classify_swing_structure(swings), "swing_points": swings, "df_240m": df
    }

def analyze_entry_timing(df: pd.DataFrame, current_price: Optional[float] = None) -> dict:
    empty = {"entry_status": "데이터 부족", "entry_score": 0, "entry_distance_ma20_pct": np.nan, "MA5_60m": np.nan, "MA20_60m": np.nan, "MA60_60m": np.nan, "close_60m": np.nan, "entry_price": np.nan, "entry_above_ma20": False, "entry_short_ordered": False, "entry_ma5_rising": False, "entry_close_rising": False, "ATR14_60m": np.nan, "last_completed_60m": pd.NaT}
    df = keep_completed_candles(df, ENTRY_CANDLE_UNIT)
    if df.empty or len(df) < 65: return empty
    
    df = add_indicators(df)
    latest = df.iloc[-1]
    if pd.isna(latest["MA5"]) or pd.isna(latest["MA20"]) or pd.isna(latest["MA60"]) or pd.isna(latest[f"ATR{ATR_PERIOD}"]): return empty
    
    ma5, ma20, ma60, atr, c_cl = float(latest["MA5"]), float(latest["MA20"]), float(latest["MA60"]), float(latest[f"ATR{ATR_PERIOD}"]), float(latest["close"])
    ep = float(current_price) if current_price and not pd.isna(current_price) and current_price > 0 else c_cl
    dist = (ep / ma20 - 1) * 100
    
    m5_r = len(df) >= 4 and df["MA5"].iloc[-1] > df["MA5"].iloc[-4]
    cl_r = len(df) >= 2 and df["close"].iloc[-1] > df["close"].iloc[-2]
    sh_ord = ma5 > ma20 > ma60
    
    score = sum([ep >= ma20, sh_ord, m5_r, cl_r])
    if ENTRY_PULLBACK_MIN_PCT <= dist <= ENTRY_PULLBACK_MAX_PCT: score += 2
    
    if ep < ma20: status = "MA20 하회"
    elif dist > ENTRY_OVERHEAT_PCT: status = "과열 주의"
    elif ENTRY_PULLBACK_MIN_PCT <= dist <= ENTRY_PULLBACK_MAX_PCT: status = "진입 관심" if sh_ord and m5_r and cl_r else "눌림 확인"
    else: status = "눌림 대기"
    
    return {"entry_status": status, "entry_score": score, "entry_distance_ma20_pct": dist, "MA5_60m": ma5, "MA20_60m": ma20, "MA60_60m": ma60, "close_60m": c_cl, "entry_price": ep, "entry_above_ma20": ep >= ma20, "entry_short_ordered": sh_ord, "entry_ma5_rising": m5_r, "entry_close_rising": cl_r, "ATR14_60m": atr, "last_completed_60m": df.index[-1]}

def calculate_final_score(item: dict) -> dict:
    _clamp = lambda v, l, h: max(l, min(v, h))
    t_s = sum([10.0 * _clamp((float(item.get(f"MA{p}_slope_pct_240m", 0) or 0)) / t, 0.0, 1.0) for p, t in {20: 2.0, 60: 1.5, 120: 1.0}.items()])
    e_s = 10.0 * sum([item.get("entry_above_ma20", False), item.get("entry_short_ordered", False), item.get("entry_ma5_rising", False), item.get("entry_close_rising", False)])
    dist = item.get("entry_distance_ma20_pct", np.nan)
    m_s = 0.0 if pd.isna(dist) else 20.0 if 0 <= dist <= 3 else 15.0 if 3 < dist <= 5 else 8.0 if 5 < dist <= 8 else 5.0 if -1 <= dist < 0 else 0.0
    
    chg, tv = float(item.get("change_24h", 0) or 0), float(item.get("trade_value_24h", 0) or 0)
    mom_s = 6.0 if 3 <= chg <= 8 else 4.0 if 1 <= chg < 3 else 3.0 if 8 < chg <= 12 else 0.0
    liq_s = 4.0 if tv >= 10e9 else 3.0 if tv >= 3e9 else 2.0 if tv >= 1e9 else 1.0 if tv >= MIN_TRADE_VALUE_24H else 0.0
    
    pen = (15.0 if pd.notna(dist) and dist > ENTRY_OVERHEAT_PCT else 0.0) + (10.0 if pd.notna(dist) and dist < 0 else 0.0) + (10.0 if chg > 12.0 else 0.0)
    fs = _clamp(t_s + e_s + m_s + mom_s + liq_s - pen, 0.0, 100.0)
    
    return {"final_score": round(fs, 1), "score_trend_4h": round(t_s, 1), "score_entry_1h": round(e_s, 1), "score_ma20_position": round(m_s, 1), "score_market_quality": round(mom_s + liq_s, 1), "score_penalty": round(pen, 1)}

def calculate_ma_atr_strategy(item: dict) -> dict:
    ep, ma20, ma60, atr = float(item.get("price", np.nan)), float(item.get("MA20_60m", np.nan)), float(item.get("MA60_60m", np.nan)), float(item.get("ATR14_60m", np.nan))
    empty = {"strategy_available": False, "buy_zone_low": np.nan, "buy_zone_high": np.nan, "buy_reference": np.nan, "stop_price": np.nan, "breakeven_stop": np.nan, "trailing_stop_normal": np.nan, "trailing_stop_tight": np.nan, "trailing_stop_current": np.nan, "take_profit_1": np.nan, "take_profit_2": np.nan, "runner_trigger_4r": np.nan, "runner_mode": "데이터 부족", "risk_per_unit": np.nan, "risk_pct": np.nan, "atr14": atr, "risk_budget": np.nan, "position_amount": np.nan, "position_quantity": np.nan, "actual_risk_amount": np.nan, "actual_risk_pct": np.nan, "position_capped": False}
    
    if any(pd.isna(x) for x in [ep, ma20, ma60, atr]) or ep <= 0 or ma20 <= 0 or atr <= 0: return empty
    
    b_l, b_h = max(0.0, ma20 - BUY_ZONE_ATR * atr), ma20 + BUY_ZONE_ATR * atr
    b_ref = b_h if ep > b_h else (ma20 + 0.10 * atr if ep < b_l else ep)
    
    stop = max(ma60 - STOP_MA60_ATR * atr, b_ref - MAX_STOP_ATR * atr)
    stop = min(stop, b_l - 0.25 * atr)
    
    rpu = max(b_ref - stop, MIN_RISK_ATR * atr)
    stop = max(0.0, b_ref - rpu)
    if rpu <= 0: empty["runner_mode"] = "손절폭 오류"; return empty

    tp1, tp2, tr_4r = b_ref + TP1_R_MULTIPLIER * rpu, b_ref + TP2_R_MULTIPLIER * rpu, b_ref + RUNNER_TRIGGER_R * rpu
    t_n, t_t = max(b_ref, ma20 - TRAIL_ATR_MULTIPLIER * atr), max(b_ref, ma20 - RUNNER_TRAIL_ATR_MULTIPLIER * atr)
    
    r_pct = (rpu / b_ref * 100) if b_ref > 0 else np.nan
    r_budg = ACCOUNT_CAPITAL * RISK_PER_TRADE_PCT / 100
    pos_amt = min((r_budg / rpu) * b_ref, ACCOUNT_CAPITAL * MAX_POSITION_PCT / 100, ACCOUNT_CAPITAL)
    
    return {
        "strategy_available": True, "buy_zone_low": b_l, "buy_zone_high": b_h, "buy_reference": b_ref, "stop_price": stop, "breakeven_stop": b_ref,
        "trailing_stop_normal": t_n, "trailing_stop_tight": t_t, "trailing_stop_current": t_t if ep >= tr_4r else t_n,
        "take_profit_1": tp1, "take_profit_2": tp2, "runner_trigger_4r": tr_4r, "runner_mode": "4R 이후 강화 Trail(1.5ATR)" if ep >= tr_4r else "기본 Trail(2ATR)",
        "risk_per_unit": rpu, "risk_pct": r_pct, "atr14": atr, "risk_budget": r_budg, "position_amount": pos_amt, "position_quantity": pos_amt / b_ref,
        "actual_risk_amount": (pos_amt / b_ref) * rpu, "actual_risk_pct": ((pos_amt / b_ref) * rpu) / ACCOUNT_CAPITAL * 100, "position_capped": pos_amt + 1e-9 < (r_budg / rpu) * b_ref
    }

def classify_candidate(item: dict) -> str:
    s, c = item.get("entry_status", "미확인"), float(item.get("change_24h", 0) or 0)
    if s == "진입 관심": return "강한상승+진입 가능" if c >= STRONG_RISE_24H_PCT else "우선관찰"
    if s in {"눌림 확인", "눌림 대기"}: return "눌림 기다리기"
    return "과열 주의" if s == "과열 주의" else "반등 확인 필요" if s in {"MA20 하회", "추세 확인 필요"} else "확인 필요"

def make_final_investment_advice(item: dict) -> tuple[str, str]:
    """시장/상대강도/Swing/진입/RSI/거래량을 종합한 규칙 기반 참고 판단. (원본 100% 동일)"""
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
    rsi_over_dynamic = pd.notna(rsi) and pd.notna(dyn_upper) and float(rsi) >= float(dyn_upper)
    rsi_below_dynamic = pd.notna(rsi) and pd.notna(dyn_lower) and float(rsi) < float(dyn_lower)

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
        reasons.extend([f"{regime}", "BTC 대비 상대강도 우위", "HH/HL 상승 구조"])
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
        reasons.extend(["HH/HL 상승 구조", "RS vs BTC 양수"])
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

def plot_candle_with_strategy(df: pd.DataFrame, item: dict, strategy: dict) -> plt.Figure:
    comp = keep_completed_candles(df, SCREEN_CANDLE_UNIT)
    if not {f"VolumeEMA{VOLUME_EMA_PERIOD}", f"RSI{RSI_PERIOD}", "RSI_Dynamic_Upper", "RSI_Dynamic_Center", "RSI_Dynamic_Lower"}.issubset(comp.columns): comp = add_indicators(comp)
    df_plot = comp.tail(CHART_BARS).copy()

    cp, bl, bh, sp, tp1, tp2, rt, ts = item["price"], strategy["buy_zone_low"], strategy["buy_zone_high"], strategy["stop_price"], strategy["take_profit_1"], strategy["take_profit_2"], strategy["runner_trigger_4r"], strategy["trailing_stop_current"]
    b_c, s_c, t_c, se_c, c_c = ["#C62828", "#EF5350"], "#6D4C41", "#455A64", ["#00796B", "#009688", "#26A69A"], "#111111"
    m_c = {5: "#7B1FA2", 20: "#F57C00", 60: "#388E3C", 120: "#1565C0"}

    adds = []
    for p in MA_PERIODS:
        if f"MA{p}" in df_plot.columns: adds.append(mpf.make_addplot(df_plot[f"MA{p}"], color=m_c[p], width=1.0, panel=0))
    adds.extend([
        mpf.make_addplot(df_plot[f"VolumeEMA{VOLUME_EMA_PERIOD}"], panel=1, color="#616161", width=1.1),
        mpf.make_addplot(df_plot[f"RSI{RSI_PERIOD}"], panel=2, color="#7B1FA2", width=1.3, ylabel="RSI"),
        mpf.make_addplot(df_plot["RSI_Dynamic_Upper"], panel=2, color="#C62828", width=0.9),
        mpf.make_addplot(df_plot["RSI_Dynamic_Center"], panel=2, color="#616161", width=0.9),
        mpf.make_addplot(df_plot["RSI_Dynamic_Lower"], panel=2, color="#1565C0", width=0.9),
    ])

    style = mpf.make_mpf_style(marketcolors=mpf.make_marketcolors(up="red", down="blue", edge="inherit", wick="inherit", volume="inherit"), rc={"font.family": KOREAN_FONT, "axes.unicode_minus": False})
    fig, axes = mpf.plot(df_plot, type="candle", style=style, ylabel="가격 (원)", ylabel_lower="거래량", addplot=adds,
                         hlines={"hlines": [bl, bh, sp, tp1, tp2, rt, ts, cp], "colors": [*b_c, s_c, *se_c, t_c, c_c], "linestyle": "--", "linewidths": 1.0, "alpha": 0.85},
                         volume=True, panel_ratios=(6, 2, 2), figsize=(14, 10), returnfig=True, warn_too_much_data=1000)

    p_ax, v_ax, r_ax = axes[0], axes[2] if len(axes) >= 4 else axes[0], axes[4] if len(axes) >= 6 else axes[-1]
    p_ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: format_price(v)))

    # ⭐ 범례 완벽 복구 ⭐
    ph = [
        plt.Line2D([0], [0], color=b_c[0], linestyle="--", label=f"매수하단: {format_price(bl)}원"),
        plt.Line2D([0], [0], color=b_c[1], linestyle="--", label=f"매수상단: {format_price(bh)}원"),
        plt.Line2D([0], [0], color=s_c, linestyle="--", label=f"손절: {format_price(sp)}원"),
        plt.Line2D([0], [0], color=se_c[0], linestyle="--", label=f"1차익절 30%: {format_price(tp1)}원"),
        plt.Line2D([0], [0], color=se_c[1], linestyle="--", label=f"2차익절 30%: {format_price(tp2)}원"),
        plt.Line2D([0], [0], color=se_c[2], linestyle="--", label=f"Runner강화(4R): {format_price(rt)}원"),
        plt.Line2D([0], [0], color=t_c, linestyle="--", label=f"Runner Trail: {format_price(ts)}원"),
        plt.Line2D([0], [0], color=c_c, linestyle="--", linewidth=1.5, label=f"현재가: {format_price(cp)}원"),
    ]
    for p in MA_PERIODS: ph.append(plt.Line2D([0], [0], color=m_c[p], linewidth=1.5, label=f"MA{p}"))
    p_ax.legend(handles=ph, loc="upper left", fontsize=7.5, ncol=2)

    swings = item.get("swing_points") if isinstance(item.get("swing_points"), pd.DataFrame) else detect_swing_points(comp)
    vs = swings[swings["timestamp"].isin(df_plot.index)] if not swings.empty else swings
    rng = max(float(df_plot["high"].max() - df_plot["low"].min()), 1e-12)
    for _, pt in vs.iterrows():
        if pt["label"] not in {"HH", "HL", "LH", "LL"}: continue
        loc = df_plot.index.get_indexer([pt["timestamp"]])[0]
        if loc < 0: continue
        pr, is_h = float(pt["price"]), pt["kind"] == "high"
        p_ax.scatter(loc, pr + rng * (0.018 if is_h else -0.018), marker="v" if is_h else "^", s=30, color="#D32F2F" if pt["label"] in {"HH", "HL"} else "#1565C0", zorder=6)
        p_ax.text(loc, pr + rng * (0.040 if is_h else -0.040), str(pt["label"]), ha="center", va="bottom" if is_h else "top", fontsize=7.5, fontweight="bold", color="#D32F2F" if pt["label"] in {"HH", "HL"} else "#1565C0")

    v_ax.legend(handles=[plt.Line2D([0], [0], color="#616161", linewidth=1.2, label=f"Volume EMA{VOLUME_EMA_PERIOD}")], loc="upper left", fontsize=7.5)
    r_ax.set_ylim(0, 100)
    for y in [70, 50, 30]: r_ax.axhline(y, color="#BDBDBD", linestyle="--" if y != 50 else ":", linewidth=0.7, alpha=0.6)
    r_ax.legend(handles=[
        plt.Line2D([0], [0], color="#7B1FA2", linewidth=1.3, label=f"RSI{RSI_PERIOD}"),
        plt.Line2D([0], [0], color="#C62828", linewidth=0.9, label="Dynamic Upper"),
        plt.Line2D([0], [0], color="#616161", linewidth=0.9, label="Dynamic Center"),
        plt.Line2D([0], [0], color="#1565C0", linewidth=0.9, label="Dynamic Lower"),
    ], loc="upper left", fontsize=7.2, ncol=2)
    
    if not df_plot.empty:
        n = len(df_plot)
        t_pos = sorted(set(np.linspace(0, n - 1, min(7, n), dtype=int).tolist() + [n - 1]))
        r_ax.set_xticks(t_pos)
        r_ax.set_xticklabels([pd.Timestamp(df_plot.index[p]).strftime("%m/%d %H:%M") for p in t_pos], rotation=45, ha="right")

    fig.subplots_adjust(left=0.08, right=0.95, top=0.98, bottom=0.11, hspace=0.08)
    return fig

# ============================================================
# 5. UI 및 Streamlit 메인 로직
# ============================================================
def run_analysis(progress_bar, status_box) -> dict:
    client = UpbitPublicClient()
    status = get_environment_status(client)
    krw_pairs, name_map = load_market_info(client, status)
    ticker_map, ticker_info = load_ticker_map(client, status["offline_mode"])
    
    if not ticker_info["usable_for_trading"]: raise RuntimeError("최신 ticker 데이터가 없어 중단합니다.")
    target_pairs = [p for p in krw_pairs if float(ticker_map.get(p, {}).get("acc_trade_price_24h", 0)) >= MIN_TRADE_VALUE_24H]

    btc_df, _ = get_ohlcv(client, "KRW-BTC", SCREEN_CANDLE_UNIT, status["offline_mode"])
    btc_regime = calculate_btc_regime(btc_df) if btc_df is not None else {"label": "확인 불가", "change_24h": np.nan}

    results, errors = [], []
    for idx, sym in enumerate(target_pairs):
        status_box.info(f"1/2 · 4시간봉 분석 {idx+1}/{len(target_pairs)} · {sym}")
        progress_bar.progress(min(0.7, 0.7 * (idx+1)/len(target_pairs)))
        try:
            df, _ = get_ohlcv(client, sym, SCREEN_CANDLE_UNIT, status["offline_mode"])
            res = analyze_screen_symbol(sym, name_map.get(sym, sym), df, ticker_map.get(sym))
            if res:
                res["btc_regime"], res["btc_change_24h"] = btc_regime.get("label", "확인 불가"), btc_regime.get("change_24h", np.nan)
                res["rs_vs_btc_24h"] = float(res["change_24h"]) - float(res["btc_change_24h"]) if pd.notna(res["btc_change_24h"]) else np.nan
                results.append(res)
        except Exception as e: errors.append((sym, f"240m: {e}"))

    for idx, item in enumerate(results):
        status_box.info(f"2/2 · 1시간봉 분석 {idx+1}/{len(results)} · {item['symbol']}")
        progress_bar.progress(0.7 + 0.3 * ((idx+1)/len(results)))
        try:
            df, _ = get_ohlcv(client, item["symbol"], ENTRY_CANDLE_UNIT, status["offline_mode"])
            item.update(analyze_entry_timing(df, item["price"]))
            item["df_60m"] = df
        except Exception as e: errors.append((item["symbol"], f"60m: {e}"))

    final_rows = []
    for item in results:
        item.update(calculate_final_score(item))
        item.update(calculate_ma_atr_strategy(item))
        item["final_action"], item["final_advice"] = make_final_investment_advice(item)
        item["judgement"] = classify_candidate(item)
        final_rows.append(item)

    df_res = pd.DataFrame(final_rows).sort_values(["final_score", "entry_score", "trade_value_24h", "change_24h"], ascending=[False, False, False, False]).reset_index(drop=True) if final_rows else pd.DataFrame()
    if not df_res.empty: df_res.to_csv(RESULT_CSV, index=False, encoding="utf-8-sig")
    
    progress_bar.progress(1.0); status_box.success("분석이 완료되었습니다.")
    return {"df_res": df_res, "ticker_info": ticker_info, "krw_pairs": krw_pairs, "target_pairs": target_pairs, "errors": errors, "offline_mode": status["offline_mode"]}

def streamlit_main():
    global MIN_CHANGE_24H, MAX_CHANGE_24H, MIN_TRADE_VALUE_24H
    global ACCOUNT_CAPITAL, RISK_PER_TRADE_PCT, MAX_POSITION_PCT
    global TOP_N, STRATEGY_N, CHART_N
    global TICKER_CACHE_EXPIRE_MINUTES, TICKER_CACHE_WARN_MINUTES, TICKER_CACHE_MAX_AGE_MINUTES

    st.set_page_config(page_title="업비트 코인 분석기", page_icon="📊", layout="wide")

    # ⭐ 사이드바 스크롤 완벽 제거를 위한 초압축 CSS 세밀 조정 ⭐
    st.markdown("""
        <style>
        header[data-testid="stHeader"] {display:none !important;}
        div[data-testid="stToolbar"] {display:none !important;}
        .block-container { padding-top: 1.2rem !important; padding-bottom: 1rem !important; max-width: 1500px; }
        
        /* 사이드바 여백 및 갭 극단적 압축 */
        section[data-testid="stSidebar"] { width: 300px !important; min-width: 300px !important; background: #f3f5f9 !important; border-right: 1px solid #e5e7eb; }
        section[data-testid="stSidebar"] .block-container { padding: 0.8rem 0.6rem 0.2rem 0.6rem !important; overflow-y: hidden !important; }
        section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] { gap: 0rem !important; }
        
        /* 사이드바 내부 요소 디테일 조정 */
        .sidebar-section-title { font-size: 0.95rem; font-weight: 800; color: #2f3342; margin: 0.25rem 0 0.1rem 0; }
        section[data-testid="stSidebar"] div[data-testid="stSlider"] { margin: 0 !important; padding-bottom: 0 !important; }
        section[data-testid="stSidebar"] div[data-testid="stSlider"] label { font-size: 0.75rem !important; margin-bottom: 0 !important; padding-bottom: 0 !important; }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] { margin-bottom: 0.15rem !important; }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] label { font-size: 0.75rem !important; margin-bottom: 0.05rem !important; }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] div[data-baseweb="input"] { height: 1.9rem !important; min-height: 1.9rem !important; border-radius: 0.4rem !important; }
        section[data-testid="stSidebar"] div[data-testid="stTextInput"] input { height: 1.9rem !important; min-height: 1.9rem !important; padding: 0 0.4rem !important; font-size: 0.85rem !important; }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button { height: 2.1rem !important; min-height: 2.1rem !important; font-size: 0.9rem !important; font-weight: 700 !important; border-radius: 6px !important; margin-top: 0.2rem !important; }
        
        /* 컬럼 간격 조정 */
        div[data-testid="stHorizontalBlock"] { gap: 0.4rem !important; }

        /* 메인 컨텐츠 CSS */
        .main-app-title { font-size: 2.55rem; font-weight: 800; line-height: 1.24; letter-spacing: -0.03em; color: #2b2d3a; margin: 0.25rem 0 0.7rem 0; }
        .main-app-subtitle { font-size: 0.97rem; color: #7b8190; margin: 0 0 1rem 0; }
        .main-top-divider { border: 0; height: 1px; background: #e5e7eb; margin: 0.8rem 0 1.4rem 0; }
        .info-banner { background: #eef2ff; border-radius: 10px; padding: 0.95rem 1rem; color: #1d4ed8; font-size: 1rem; margin-bottom: 1.2rem; }
        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown('<div class="sidebar-section-title">⚙ 분석 설정 · FINAL</div>', unsafe_allow_html=True)
        cache_minutes = st.slider("캐시 만료(분)", 10, 180, int(TICKER_CACHE_MAX_AGE_MINUTES), 5)
        
        st.markdown('<div class="sidebar-section-title">💰 포지션 리스크</div>', unsafe_allow_html=True)
        account_capital_text = st.text_input("계좌 자금(원)", value=f"{ACCOUNT_CAPITAL:,.0f}")
        col_r1, col_r2 = st.columns(2)
        risk_per_trade_text = col_r1.text_input("위험(%)", value=f"{RISK_PER_TRADE_PCT:.2f}")
        max_position_text = col_r2.text_input("비중(%)", value=f"{MAX_POSITION_PCT:.2f}")
        
        st.markdown('<div class="sidebar-section-title">🔍 필터링 조건</div>', unsafe_allow_html=True)
        min_change = st.slider("최소 변동률(%)", -10.0, 20.0, float(MIN_CHANGE_24H), 0.5)
        max_change = st.slider("최대 변동률(%)", 5.0, 50.0, float(MAX_CHANGE_24H), 0.5)
        min_trade_text = st.text_input("최소 거래대금(원)", value=f"{MIN_TRADE_VALUE_24H:,.0f}")
        
        st.markdown('<div class="sidebar-section-title">📋 출력</div>', unsafe_allow_html=True)
        col_o1, col_o2, col_o3 = st.columns(3)
        top_n_text = col_o1.text_input("TOP", value=str(int(TOP_N)))
        strategy_n_text = col_o2.text_input("전략", value=str(int(STRATEGY_N)))
        chart_n_text = col_o3.text_input("차트", value=str(int(CHART_N)))

        run_clicked = st.button("🚀 분석 실행", type="primary", use_container_width=True)

    try:
        MIN_TRADE_VALUE_24H = float(min_trade_text.replace(",", ""))
        ACCOUNT_CAPITAL = float(account_capital_text.replace(",", ""))
        RISK_PER_TRADE_PCT = float(risk_per_trade_text)
        MAX_POSITION_PCT = float(max_position_text)
        TOP_N, STRATEGY_N, CHART_N = int(top_n_text), int(strategy_n_text), int(chart_n_text)
        MIN_CHANGE_24H, MAX_CHANGE_24H = float(min_change), float(max_change)
        
        TICKER_CACHE_MAX_AGE_MINUTES = int(cache_minutes)
        TICKER_CACHE_WARN_MINUTES = max(10, int(cache_minutes * 0.5))
        TICKER_CACHE_EXPIRE_MINUTES = min(30, max(5, int(cache_minutes * 0.25)))
        CACHE_EXPIRE_MINUTES[60] = min(60, max(10, int(cache_minutes * 0.5)))
        CACHE_EXPIRE_MINUTES[240] = int(cache_minutes)
    except ValueError:
        st.sidebar.error("숫자를 정확히 입력하세요.")
        return

    st.markdown('<div class="main-app-title">📊 업비트 코인 분석기</div>', unsafe_allow_html=True)
    st.markdown('<div class="main-app-subtitle">4시간봉 추세 선별 → 1시간봉 진입 확인 → FinalScore → MA/ATR 매매 계획</div>', unsafe_allow_html=True)
    st.caption(f"등락 {MIN_CHANGE_24H:.1f}~{MAX_CHANGE_24H:.1f}% · 거래대금 {MIN_TRADE_VALUE_24H:,.0f}원 · 계좌 {ACCOUNT_CAPITAL:,.0f}원 · 위험 {RISK_PER_TRADE_PCT:.2f}% · 최대비중 {MAX_POSITION_PCT:.0f}% · TOP {TOP_N} / 전략 {STRATEGY_N} / 차트 {CHART_N}")
    st.markdown('<hr class="main-top-divider">', unsafe_allow_html=True)

    if run_clicked:
        pb, sb = st.progress(0.0), st.empty()
        try:
            st.session_state["analysis"] = run_analysis(pb, sb)
            st.session_state["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            pb.empty(); sb.empty(); st.exception(e); return

    analysis = st.session_state.get("analysis")
    if not analysis:
        st.markdown('<div class="info-banner">👉 좌측 사이드바에서 설정을 조정하고 분석 실행 버튼을 클릭하세요.</div>', unsafe_allow_html=True)
        st.subheader("기본 선별 구조")
        st.markdown("1. 4시간봉 MA 정배열 + MA20/60/120 상승 확인\n2. 24시간 등락률과 거래대금으로 1차 필터\n3. BTC Regime + RS vs BTC + Swing 구조를 별도 평가\n4. 1시간봉 MA20 위치와 단기 방향으로 진입 타이밍 확인\n5. Volume EMA20 / Dynamic RSI로 거래량·모멘텀 확인\n6. FinalScore로 후보 순위 결정\n7. MA20/MA60/ATR14로 매수·손절·익절·Runner 계획 계산")
        return

    df_res, ticker_info = analysis["df_res"], analysis["ticker_info"]
    if df_res.empty: st.warning("현재 조건을 만족하는 코인이 없습니다."); return

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("전체 KRW 마켓", f"{len(analysis['krw_pairs'])}개")
    m2.metric("캔들 분석 대상", f"{len(analysis['target_pairs'])}개")
    m3.metric("4시간봉 후보", f"{len(df_res)}개")
    m4.metric("오류", f"{len(analysis['errors'])}개")
    m5.metric("티커", "실시간 API" if ticker_info["source"] == "api" else f"캐시 {ticker_info['age_minutes']:.0f}분")

    if analysis["offline_mode"]: st.warning("업비트 API 연결 실패로 캐시 우선/오프라인 모드가 사용되었습니다.")
    elif ticker_info.get("warning"): st.warning(f"현재 ticker는 약 {ticker_info['age_minutes']:.0f}분 전 캐시입니다. 결과는 참고용으로 사용하세요.")
    st.caption(f"분석 시각: {st.session_state.get('analysis_time', '-')}")

    st.subheader(f"상위 {min(TOP_N, len(df_res))}개 후보")
    st.caption("Swing: HH=이전보다 높은 고점 · HL=이전보다 높은 저점 · LH=이전보다 낮은 고점 · LL=이전보다 낮은 저점 (HH/HL은 상승 구조, LH/LL은 하락 구조)")
    
    disp_df = df_res.head(TOP_N).copy()
    disp_df["매수구간"] = disp_df.apply(lambda row: f"{format_price(row['buy_zone_low'])}~{format_price(row['buy_zone_high'])}" if pd.notna(row["buy_zone_low"]) and pd.notna(row["buy_zone_high"]) else "-", axis=1)
    disp_cols = ["symbol", "korean_name", "judgement", "final_action", "final_advice", "final_score", "price", "change_24h", "btc_regime", "rs_vs_btc_24h", "swing_structure", "매수구간", "stop_price", "take_profit_1", "take_profit_2", "runner_trigger_4r"]
    disp_rename = {"symbol": "종목", "korean_name": "한글명", "judgement": "판단", "final_action": "최종 판단", "final_advice": "투자 조언", "final_score": "FinalScore", "price": "현재가", "change_24h": "24h 등락", "btc_regime": "BTC Regime", "rs_vs_btc_24h": "RS vs BTC", "swing_structure": "Swing 구조", "stop_price": "손절", "take_profit_1": "1차익절(30%)", "take_profit_2": "2차익절(30%)", "runner_trigger_4r": "Runner강화(4R)"}
    
    st.dataframe(disp_df[disp_cols].rename(columns=disp_rename), width="stretch", hide_index=True, column_config={
        "FinalScore": st.column_config.NumberColumn(format="%.1f"), "현재가": st.column_config.NumberColumn(format="localized"),
        "24h 등락": st.column_config.NumberColumn(format="%+.2f%%"), "RS vs BTC": st.column_config.NumberColumn(format="%+.2f%%"),
        "손절": st.column_config.NumberColumn(format="localized"), "1차익절(30%)": st.column_config.NumberColumn(format="localized"),
        "2차익절(30%)": st.column_config.NumberColumn(format="localized"), "Runner강화(4R)": st.column_config.NumberColumn(format="localized"),
    })
    st.caption("※ ‘최종 판단/투자 조언’은 현재 데이터에 따른 규칙 기반 참고 신호이며, 확정적인 수익을 의미하지 않습니다.")

    st.markdown("---")
    st.subheader("핵심 해석")
    groups = [("우선관찰", "추세 양호 + 1시간 MA20 근접"), ("강한상승+진입 가능", "조건은 좋지만 급등폭 주의"), ("눌림 기다리기", "추세 유지, 더 좋은 가격 대기"), ("과열 주의", "MA20 이격이 커 추격 자제"), ("반등 확인 필요", "1시간 MA20 회복 확인"), ("확인 필요", "추가 데이터 확인")]
    for label, note in groups:
        sel = disp_df.loc[disp_df["judgement"] == label, ["symbol", "korean_name"]]
        if not sel.empty: st.markdown(f"- **{label} ({len(sel)})**: {', '.join(f'{r.symbol.replace('KRW-', '')}({r.korean_name})' for _, r in sel.iterrows())}  → {note}")

    st.markdown("---")
    st.subheader("MA / ATR 기반 매수·손절·익절 + Runner")
    st.caption("1차 30% +1.5R, 2차 30% +2.5R, 마지막 40% Runner")
    strat_rows = []
    for _, item in df_res.head(STRATEGY_N).iterrows():
        if not item.get("strategy_available"): continue
        with st.expander(f"{item['korean_name']} · {item['symbol']} · FinalScore {item.get('final_score', 0):.1f}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("현재가", f"{format_price(item['price'])}원")
            c2.metric("24시간", f"{item['change_24h']:+.2f}%")
            c3.metric("진입 상태", item.get("entry_status", "미확인"))
            c4.metric("ATR14", format_price(item["ATR14_60m"]))
            st.markdown(f"- **최종 판단:** {item.get('final_action', '관망')}\n- **투자 조언:** {item.get('final_advice', '추가 확인이 필요합니다.')}\n- **매수구간:** {format_price(item['buy_zone_low'])} ~ {format_price(item['buy_zone_high'])}원\n- **손절:** {format_price(item['stop_price'])}원 · 계획 진입가 대비 **-{item['risk_pct']:.2f}%**\n- **1차 익절:** {format_price(item['take_profit_1'])}원에서 30%\n- **2차 익절:** {format_price(item['take_profit_2'])}원에서 30%\n- **Runner:** 남은 40% 유지, {format_price(item['runner_trigger_4r'])}원(4R)부터 Trail 2ATR → 1.5ATR 강화\n- **현재 Trail 참고:** {format_price(item['trailing_stop_current'])}원 · {item['runner_mode']}\n- **권장 매수금:** {item['position_amount']:,.0f}원 · 예상 최대손실 {item['actual_risk_amount']:,.0f}원 ({item['actual_risk_pct']:.2f}% of account)")
            if item["position_capped"]: st.caption("종목당 최대 투자비중 제한이 적용된 포지션입니다.")
            st.caption("Trail은 완료된 1시간봉마다 다시 계산하고, 실제 운용 시 기존 Trail보다 낮추지 않는 방식입니다.")
        strat_rows.append({"종목": item["symbol"], "한글명": item["korean_name"], "상태": item.get("entry_status", "미확인"), "현재가": item["price"], "매수구간 하단": item["buy_zone_low"], "매수구간 상단": item["buy_zone_high"], "손절": item["stop_price"], "손절폭(%)": item["risk_pct"], "1차 익절(30%)": item["take_profit_1"], "2차 익절(30%)": item["take_profit_2"], "4R Runner 강화": item["runner_trigger_4r"], "현재 Trail": item["trailing_stop_current"], "Runner 모드": item["runner_mode"], "권장 매수금": item["position_amount"], "예상 최대손실": item["actual_risk_amount"], "실제 계좌위험(%)": item["actual_risk_pct"], "종목비중 제한": item["position_capped"]})

    if strat_rows:
        with st.expander("전략 표로 보기", expanded=False):
            st.dataframe(pd.DataFrame(strat_rows), width="stretch", hide_index=True, column_config={"현재가": st.column_config.NumberColumn(format="localized"), "매수구간 하단": st.column_config.NumberColumn(format="localized"), "매수구간 상단": st.column_config.NumberColumn(format="localized"), "손절": st.column_config.NumberColumn(format="localized"), "1차 익절(30%)": st.column_config.NumberColumn(format="localized"), "2차 익절(30%)": st.column_config.NumberColumn(format="localized"), "4R Runner 강화": st.column_config.NumberColumn(format="localized"), "현재 Trail": st.column_config.NumberColumn(format="localized"), "권장 매수금": st.column_config.NumberColumn(format="localized"), "예상 최대손실": st.column_config.NumberColumn(format="localized")})

    st.markdown("---")
    st.subheader("캔들 차트")
    avail = [item for _, item in df_res.iterrows() if item.get("df_240m") is not None and not item["df_240m"].empty]
    if not avail: st.info("표시할 4시간봉 차트 데이터가 없습니다.")
    else:
        labels = {f"{i['symbol']} · {i['korean_name']} · {i.get('final_score', 0):.1f}": i for i in avail}
        sel_labels = st.multiselect("차트로 볼 종목", options=list(labels.keys()), default=list(labels.keys())[:min(CHART_N, len(labels))])
        for idx, lbl in enumerate(sel_labels):
            i = labels[lbl]
            if not i.get("strategy_available"): continue
            st.markdown(f"<div style='text-align:center; font-size:1.55rem; font-weight:700; margin:0.25rem 0 0.15rem 0; line-height:1.35;'>{i['korean_name']} ({i['symbol']}) - 4시간봉</div>", unsafe_allow_html=True)
            l_comp = i.get("last_completed_240m")
            if pd.isna(l_comp): l_comp = keep_completed_candles(i["df_240m"], SCREEN_CANDLE_UNIT).index[-1] if not keep_completed_candles(i["df_240m"], SCREEN_CANDLE_UNIT).empty else pd.NaT
            l_text = pd.Timestamp(l_comp).strftime("%Y-%m-%d %H:%M KST") if pd.notna(l_comp) else "확인 불가"
            
            st.markdown(f"<div style='text-align:center; color:#7a7f8c; font-size:0.90rem; margin:0 0 0.45rem 0; line-height:1.4;'>현재가 {format_price(i['price'])}원 | 24시간 {i['change_24h']:+.2f}% | RS vs BTC {i.get('rs_vs_btc_24h', np.nan):+.2f}% | {i.get('btc_regime', '확인 불가')} | Swing {i.get('swing_structure', '데이터 부족')}<br>RSI14 {i.get('RSI14_240m', np.nan):.1f} | VolumeRatio {i.get('VolumeRatio_240m', np.nan):.2f}x | ATR% {i.get('ATR_Pct_240m', np.nan):.2f}% | Dynamic RSI {i.get('RSI_dynamic_lower_240m', np.nan):.1f} ~ {i.get('RSI_dynamic_upper_240m', np.nan):.1f} | 마지막 완료봉 {l_text}</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='text-align:center; background:#f8f9fb; border:1px solid #e5e7eb; border-radius:8px; padding:0.55rem 0.8rem; margin:0 0 0.55rem 0; font-size:0.88rem;'><b>최종 판단: {i.get('final_action', '관망')}</b><br>{i.get('final_advice', '추가 확인이 필요합니다.')}</div>", unsafe_allow_html=True)
            
            fig = plot_candle_with_strategy(i["df_240m"], i.to_dict(), i.to_dict())
            st.pyplot(fig, width="stretch")
            plt.close(fig)
            if idx < len(sel_labels) - 1: st.divider()

    st.markdown("---")
    st.subheader("전체 분석 데이터")
    st.dataframe(df_res, width="stretch", hide_index=True)
    st.download_button("CSV 다운로드", data=df_res.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"), file_name="upbit_coin_analyzer_results.csv", mime="text/csv")

    st.markdown("---")
    st.subheader("오류 내역")
    if analysis["errors"]: st.dataframe(pd.DataFrame(analysis["errors"], columns=["종목", "오류"]), width="stretch", hide_index=True)
    else: st.success("분석 중 수집된 오류가 없습니다.")

if __name__ == "__main__":
    streamlit_main()