"""load_bundle 이 CSV 경로와 같은 모양의 표를 돌려주는지 확인."""

from conftest_paths import (APP, BUNDLE_FILE, INDEX_FILE, LIST_FILE,
                            csv_source, has_real_csv)

DATA_FOLDER = csv_source()

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
print("CSV 출처     :", DATA_FOLDER.name,
      "(진짜 CSV)" if has_real_csv() else "(번들에서 생성)")
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

# 앱이 실제로 쓰는 컬럼만 검사한다.
#
# 목록 전체의 dtype 을 CSV 와 비교하지 않는 이유:
# CSV 왕복은 타입을 뭉갠다. 예를 들어 ChangeCode 는 원본이 문자열 '2','3','1'
# 인데 CSV 를 거치면 int64 가 되고, Dept 는 전부 결측이라 float64 로 추론된다.
# parquet 은 fdr 원본 타입을 그대로 보존하므로 오히려 충실하다.
# CSV 의 손실된 추론을 재현하라고 요구하는 것은 요구사항이 아니다.
for col in ("Code", "Name"):
    assert stocks[col].dtype == csv_stocks[col].dtype, (
        f"{col} dtype 이 다릅니다: {stocks[col].dtype} vs {csv_stocks[col].dtype}"
    )
    assert list(stocks[col]) == list(csv_stocks[col]), f"{col} 값이 다릅니다"

print("종목 목록    : Code·Name 값·dtype 동일")

print("\n=== 통과 ===")
sys.exit(0)
