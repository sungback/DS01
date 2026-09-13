"""번들 빌더가 CSV 내용을 손실 없이 옮기는지 확인."""

from conftest_paths import APP, PROJECT, csv_source, has_real_csv

DATA_FOLDER = csv_source()

import ast
import logging
import sys

import pandas as pd

BUNDLE_COLUMNS = ["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change"]


def load_funcs(names):
    """app.py 를 실행하지 않고 함수만 꺼내 온다."""
    tree = ast.parse(APP.read_text())
    wanted = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(wanted) == len(names), [n.name for n in wanted]
    for n in wanted:
        n.decorator_list = []
    ns = {
        "pd": pd,
        "DATA_FOLDER": DATA_FOLDER,
        "BUNDLE_COLUMNS": BUNDLE_COLUMNS,
        "logger": logging.getLogger("test"),
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(APP), "exec"), ns)
    return ns


ns = load_funcs(["build_bundle_from_csv", "build_index_from_csv"])
bundle = ns["build_bundle_from_csv"]()

assert bundle is not None, "번들이 만들어지지 않았습니다"

print("CSV 출처  :", DATA_FOLDER.name,
      "(진짜 CSV)" if has_real_csv() else "(번들에서 생성)")
print("컬럼 순서 :", list(bundle.columns))
assert list(bundle.columns) == BUNDLE_COLUMNS, "컬럼 순서가 다릅니다"

csv_codes = {f.stem for f in DATA_FOLDER.glob("*.csv")
              if f.stem not in ("KOSPI_list", "KS11")}
bundle_codes = set(bundle["Code"].unique())
missing = csv_codes - bundle_codes
print(f"CSV 종목 {len(csv_codes)}개 / 번들 종목 {len(bundle_codes)}개")

# 빈 CSV 는 번들에 안 들어갈 수 있으므로, 누락분은 모두 비어 있어야 한다
for code in missing:
    df = pd.read_csv(DATA_FOLDER / f"{code}.csv")
    assert df.empty, f"{code}: 내용이 있는데 번들에서 빠졌습니다"

samples = [c for c in ("005930", "000660", "005380") if c in bundle_codes]
assert samples, "표본 종목이 번들에 없습니다"

for code in samples:
    csv = pd.read_csv(DATA_FOLDER / f"{code}.csv",
                      index_col="Date", parse_dates=["Date"]).sort_index()
    part = (bundle[bundle["Code"] == code]
            .drop(columns="Code").set_index("Date").sort_index())
    assert csv.equals(part), f"{code}: 값이 다릅니다"
    assert csv.index.dtype == part.index.dtype, f"{code}: 인덱스 dtype 이 다릅니다"
    print(f"  {code} : 값·dtype 동일")

# 지수는 개별 종목과 dtype 이 달라 같은 표에 담지 않는다
assert "KS11" not in bundle_codes, "KS11 이 개별 종목 번들에 섞여 있습니다"

for col in ("Open", "High", "Low", "Close", "Volume"):
    assert bundle[col].dtype == "int64", f"{col} 이 int64 가 아닙니다: {bundle[col].dtype}"
print("종목 OHLCV int64 유지 : 확인")

index_df = ns["build_index_from_csv"]()
assert index_df is not None, "KOSPI 지수 표가 만들어지지 않았습니다"

csv_index = pd.read_csv(DATA_FOLDER / "KS11.csv",
                        index_col="Date", parse_dates=["Date"]).sort_index()
assert index_df.equals(csv_index), "KS11 값이 다릅니다"
assert index_df.dtypes.equals(csv_index.dtypes), "KS11 dtype 이 다릅니다"
print("KOSPI 지수 별도 표     : CSV 와 동일")

assert bundle.equals(
    bundle.sort_values(["Code", "Date"]).reset_index(drop=True)
), "Code, Date 순으로 정렬되어 있지 않습니다"
print("정렬      : 확인")

print("\n=== 통과 ===")
sys.exit(0)
