"""
번들이 없을 때 CSV 에서 자동으로 만들어지는지,
데이터가 그대로면 파일을 다시 쓰지 않는지 확인한다.

네트워크를 쓰지 않도록 fdr 을 가짜로 바꿔치기한다.
"""

from conftest_paths import APP, DATA_FOLDER, SCRATCH

import ast
import hashlib
import logging
import shutil
import sys
import time
from threading import RLock

import pandas as pd

COLS = ["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change"]


class FakeFdr:
    """네트워크 대신 로컬 CSV 를 돌려준다."""

    def StockListing(self, market):
        return pd.read_csv(DATA_FOLDER / "KOSPI_list.csv", dtype={"Code": str})

    def DataReader(self, code, start=None):
        f = DATA_FOLDER / f"{code}.csv"
        if not f.exists():
            return pd.DataFrame()
        df = pd.read_csv(f, index_col="Date", parse_dates=["Date"]).sort_index()
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        return df


def load_prepare(work_dir):
    tree = ast.parse(APP.read_text())
    names = ("prepare_stock_data", "save_bundle", "build_bundle_from_csv",
             "build_index_from_csv", "data_fingerprint")
    wanted = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(wanted) == len(names), [n.name for n in wanted]
    for n in wanted:
        n.decorator_list = []

    ns = {
        "pd": pd,
        "fdr": FakeFdr(),
        "hashlib": hashlib,
        "logger": logging.getLogger("test"),
        "DATA_LOCK": RLock(),
        "DATA_FOLDER": work_dir / "stock_data",
        "BUNDLE_FILE": work_dir / "stock_data.parquet",
        "INDEX_FILE": work_dir / "kospi_index.parquet",
        "LIST_FILE": work_dir / "kospi_list.parquet",
        "BUNDLE_COLUMNS": COLS,
        "START": "2024-01-01",
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(APP), "exec"), ns)
    return ns


# CSV 만 있고 번들이 없는 작업 폴더를 만든다
work = SCRATCH / "prepare_work"
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
shutil.copytree(DATA_FOLDER, work / "stock_data")

ns = load_prepare(work)

# ① 번들이 없으면 CSV 에서 만들어져야 한다
info1 = ns["prepare_stock_data"]()
made = [(work / n).exists() for n in
        ("stock_data.parquet", "kospi_index.parquet", "kospi_list.parquet")]
print("① 번들 3개 자동 생성 :", made)
assert all(made), "번들이 만들어지지 않았습니다"
print("   기준일 :", info1["market_date"], "| 종목 :", info1["stock_count"])

fp1 = ns["data_fingerprint"]()

# ② 같은 데이터로 다시 실행하면 파일을 다시 쓰지 않아야 한다
time.sleep(1.1)
info2 = ns["prepare_stock_data"]()
fp2 = ns["data_fingerprint"]()

print(f"② 재실행 후 지문 : {fp1} → {fp2}")
assert fp1 == fp2, "데이터가 같은데 번들이 다시 쓰였습니다 (캐시가 매번 버려집니다)"
print("   지문 유지 : 확인")

# ③ 반환 사전의 키가 그대로인지
for key in ("market_date", "stock_count", "stats", "error_codes", "data_version"):
    assert key in info2, f"반환값에 {key} 가 없습니다"
print("③ 반환 키 : 확인")

# ④ 개별 종목 dtype 이 int64 로 유지되는지
bundle = pd.read_parquet(work / "stock_data.parquet")
for col in ("Open", "High", "Low", "Close", "Volume"):
    assert bundle[col].dtype == "int64", f"{col} dtype: {bundle[col].dtype}"
assert "KS11" not in set(bundle["Code"]), "KS11 이 개별 종목 번들에 섞였습니다"
print("④ 종목 OHLCV int64 유지 / KS11 분리 : 확인")

shutil.rmtree(work, ignore_errors=True)
print("\n=== 통과 ===")
sys.exit(0)
