"""OHLCV 캐시 신선도: 파일 수정 시각이 아니라 캐시 안의 saved_at 으로 판단한다.

git clone · 파일 복사 · Google Drive 동기화는 수정 시각을 '지금' 으로 바꾼다.
수정 시각으로 판단하면 며칠 지난 캔들도 방금 받은 캐시로 보여 API 를 부르지 않는다.

- 앞부분은 실제 현재 시각으로 확인한다 (예전 코드에서 실패하던 사례).
- 뒷부분은 now_kst 를 고정해 TTL · 봉 경계 · 미래 시각을 경계값으로 확인한다.
- app.OHLCV_CACHE_DIR 를 임시 폴더로 바꾸고 되돌리지 않는다(run_all.py 의 프로세스 분리 전제).
"""
# ruff: noqa: E402  (bytecode 끄기가 import 보다 먼저 와야 한다)
import sys

sys.dont_write_bytecode = True

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from conftest_paths import HERE, app, check, finish, geometric, make_candles

SYMBOL = "KRW-TEST"
MISSING = object()
THREE_DAYS_AGO = time.time() - 3 * 24 * 3600


class FakeClient:
    """API 호출 횟수를 센다. 호출되면 새 캔들을 돌려준다."""

    def __init__(self, unit: int) -> None:
        self.unit = unit
        self.calls = 0

    def get_minute_candles(self, market, unit, count=200):
        self.calls += 1
        return make_candles(geometric(200, 0.004), unit)


def write(saved_at=MISSING, *, unit=240, mtime=None, fmt="dict") -> Path:
    """save_ohlcv 형식으로 쓴 뒤 saved_at · 형식 · 수정 시각만 바꾼다."""
    app.save_ohlcv(SYMBOL, unit, make_candles(geometric(200, 0.004), unit))
    path = app.ohlcv_cache_path(SYMBOL, unit)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if fmt == "list":
        payload = payload["records"]  # 구버전: saved_at 없는 레코드 배열
    elif saved_at is MISSING:
        payload.pop("saved_at")
    else:
        payload["saved_at"] = saved_at
    path.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def local_iso(delta: timedelta = timedelta(0)) -> str:
    """save_ohlcv 와 같은 형식: 시간대 없는 현지 시각."""
    return (datetime.now() + delta).isoformat(timespec="seconds")


def usable(path: Path, unit: int = 240, ttl: int = 60, now=None) -> bool:
    if now is None:
        return app.ohlcv_cache_is_usable(path, unit, ttl)
    return app.ohlcv_cache_is_usable(path, unit, ttl, now_kst=now)


with tempfile.TemporaryDirectory(prefix="coin_fresh_") as tmp:
    app.OHLCV_CACHE_DIR = Path(tmp) / "ohlcv"

    # --- 1) clone · 동기화 사례: 내용은 오래됐는데 수정 시각은 지금 ----------------
    path = write(local_iso(timedelta(days=-3)))  # 방금 쓴 파일 = 수정 시각 지금
    check("저장 3일 전 + 수정 시각 지금 → 쓰지 않음", not usable(path))

    client = FakeClient(240)
    got = app.fetch_ohlcv(client, SYMBOL, 240, app.Settings(), offline=False)
    check("clone 직후 오래된 캐시 → API 재조회", got.source == "api" and client.calls == 1, (got.source, client.calls))
    again = app.fetch_ohlcv(client, SYMBOL, 240, app.Settings(), offline=False)
    check("재조회로 다시 쓴 캐시는 곧바로 재사용", again.source == "cache" and client.calls == 1, (again.source, client.calls))

    # --- 2) 반대 사례: 내용은 방금 저장, 수정 시각만 오래됨 -------------------------
    path = write(local_iso(), mtime=THREE_DAYS_AGO)
    check("저장 지금 + 수정 시각 3일 전 → 사용", usable(path))

    app.save_ohlcv(SYMBOL, 240, make_candles(geometric(200, 0.004), 240))
    path = app.ohlcv_cache_path(SYMBOL, 240)
    os.utime(path, (THREE_DAYS_AGO, THREE_DAYS_AGO))
    check("save_ohlcv 가 쓴 캐시는 수정 시각과 무관하게 사용", usable(path))

    # --- 3) 저장 시각을 알 수 없으면 쓰지 않는다 (수정 시각으로 대신하지 않음) -------
    check("saved_at 없음 + 수정 시각 지금 → 쓰지 않음", not usable(write(MISSING)))
    list_path = write(fmt="list")
    check("구버전 배열 형식 + 수정 시각 지금 → 쓰지 않음", not usable(list_path))
    offline = app.fetch_ohlcv(FakeClient(240), SYMBOL, 240, app.Settings(), offline=True)
    check("구버전 캐시도 오프라인에서는 오래된 캐시로 읽음", offline.ok and offline.source == "stale", offline.source)

    for label, value in [("문자 abc", "abc"), ("null", None), ("숫자", 12345), ("빈 문자열", "")]:
        try:
            check(f"saved_at {label} → 쓰지 않음", not usable(write(value)))
        except Exception as exc:
            check(f"saved_at {label} → 예외 없이 처리", False, repr(exc))

    corrupt = app.ohlcv_cache_path(SYMBOL, 240)
    corrupt.write_text("{broken", encoding="utf-8")
    check("깨진 JSON → 쓰지 않음", not usable(corrupt))
    check("파일 없음 → 쓰지 않음", not usable(Path(tmp) / "none.json"))

    # --- 4) 시간대가 적힌 saved_at 은 어느 시간대든 같은 순간으로 본다 -------------
    utc_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    check("UTC 로 적힌 지금 → 사용", usable(write(utc_now, mtime=THREE_DAYS_AGO)))
    kst_now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
    check("KST 로 적힌 지금 → 사용", usable(write(kst_now, mtime=THREE_DAYS_AGO)))

    # --- 5) 서버 시간대가 UTC 여도 자기가 쓴 캐시를 바로 쓴다 (Streamlit Cloud) ------
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import time; from pathlib import Path;"
        "from conftest_paths import app, make_candles, geometric;"
        "app.OHLCV_CACHE_DIR = Path(sys.argv[2]);"
        "app.save_ohlcv('KRW-UTC', 240, make_candles(geometric(200, 0.004), 240));"
        "p = app.ohlcv_cache_path('KRW-UTC', 240);"
        "print(time.strftime('%z'), app.ohlcv_cache_is_usable(p, 240, 60))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(HERE), str(Path(tmp) / "utc")],
        capture_output=True,
        text=True,
        env={**os.environ, "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-300:]
    check("TZ=UTC 프로세스가 쓴 캐시를 같은 프로세스가 사용", out == "+0000 True", out)

    # --- 6) 경계값 (now 고정: KST 22:55, 240분봉 21:00 시작, 60분봉 22:00 시작) -----
    NOW = pd.Timestamp("2026-09-13 22:55")

    def at(hhmmss: str) -> Path:
        return write(f"2026-09-13T{hhmmss}+09:00", mtime=THREE_DAYS_AGO)

    check("5분 전 저장 → 사용", usable(at("22:50:00"), now=NOW))
    check("85분 전 저장, TTL 60 → 만료", not usable(at("21:30:00"), ttl=60, now=NOW))
    check("85분 전 저장, TTL 90 → 사용", usable(at("21:30:00"), ttl=90, now=NOW))
    check("현재 봉 시작(21:00) 1분 전 저장 → 새 봉 열려 재조회", not usable(at("20:59:00"), ttl=180, now=NOW))
    check("현재 봉 시작(21:00) 정각 저장 → 사용", usable(at("21:00:00"), ttl=180, now=NOW))
    check("60분봉: 22:00 저장 → 사용", usable(write("2026-09-13T22:00:00+09:00", unit=60), unit=60, now=NOW))
    check("60분봉: 21:59 저장 → 재조회", not usable(write("2026-09-13T21:59:00+09:00", unit=60), unit=60, now=NOW))
    check("35분 뒤로 기록된 저장 시각(시계 어긋남) → 쓰지 않음", not usable(at("23:30:00"), now=NOW))
    check("30초 뒤로 기록된 저장 시각 → 허용", usable(at("22:55:30"), now=NOW))

finish()
