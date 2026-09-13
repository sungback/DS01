"""load_bundle 이 CSV 경로와 같은 모양의 표를 돌려주는지 확인."""

from conftest_paths import APP, BUNDLE_FILE, DATA_FOLDER, INDEX_FILE, LIST_FILE

import ast
import logging
import sys

import pandas as pd


def load_funcs(names):
    tree = ast.parse(APP.read_text())
    wanted = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(wanted) == len(names), [n.name for n in wanted]
    for n in wanted:
        n.decorator_list = []
    ns = {
        "pd": pd,
        "DATA_FOLDER": DATA_FOLDER,
        "BUNDLE_FILE": BUNDLE_FILE,
        "INDEX_FILE": INDEX_FILE,
        "LIST_FILE": LIST_FILE,
        "logger": logging.getLogger("test"),
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(APP), "exec"), ns)
    ns["load_bundle"] = ns["load_bundle"]
    return ns


ns = load_funcs(["load_bundle", "load_market", "load_stocks"])

groups = ns["load_bundle"]("v")
print("번들 종목 수 :", len(groups))
assert len(groups) > 800, "종목 수가 너무 적습니다"

# CSV 경로와 표 모양이 같아야 한다
for code in ("005930", "000660", "005380"):
    csv = pd.read_csv(DATA_FOLDER / f"{code}.csv",
                      index_col="Date", parse_dates=["Date"]).sort_index()
    part = groups[code]
    assert list(part.columns) == list(csv.columns), f"{code}: 컬럼이 다릅니다"
    assert part.index.dtype == csv.index.dtype, f"{code}: 인덱스 dtype 이 다릅니다"
    assert part.dtypes.equals(csv.dtypes), f"{code}: 컬럼 dtype 이 다릅니다"
    assert part.equals(csv), f"{code}: 값이 다릅니다"
    print(f"  {code} : CSV 와 동일 (값·dtype)")

# 지수는 개별 종목 사전에 섞이지 않아야 한다
assert "KS11" not in groups, "KS11 이 개별 종목 사전에 섞여 있습니다"

# KOSPI 지수
market = ns["load_market"]("v")
csv_market = pd.read_csv(DATA_FOLDER / "KS11.csv",
                         index_col="Date", parse_dates=["Date"]).sort_index()
assert market.index.equals(csv_market.index), "KS11 날짜가 다릅니다"
assert market.dtypes.equals(csv_market.dtypes), "KS11 dtype 이 다릅니다"
assert market.equals(csv_market), "KS11 값이 다릅니다"
print("KS11        : CSV 와 동일 (값·dtype)")

# 종목 목록
stocks = ns["load_stocks"]("v")
csv_stocks = pd.read_csv(DATA_FOLDER / "KOSPI_list.csv", dtype={"Code": str})
csv_stocks["Code"] = (csv_stocks["Code"].astype(str)
                      .str.replace(".0", "", regex=False).str.zfill(6))
csv_stocks = csv_stocks[csv_stocks["Code"].str.endswith("0")]
csv_stocks = csv_stocks.reset_index(drop=True)
assert len(stocks) == len(csv_stocks), "종목 목록 행 수가 다릅니다"
assert list(stocks["Code"]) == list(csv_stocks["Code"]), "종목코드가 다릅니다"

# dtype 은 값을 고정하지 않고 CSV 경로와 같은지로 확인한다
assert stocks.dtypes.equals(csv_stocks.dtypes), (
    f"dtype 이 다릅니다\nCSV : {dict(csv_stocks.dtypes.astype(str))}"
    f"\nPQ  : {dict(stocks.dtypes.astype(str))}"
)
print("종목 목록    : CSV 와 동일 (값·dtype)")

print("\n=== 통과 ===")
sys.exit(0)
