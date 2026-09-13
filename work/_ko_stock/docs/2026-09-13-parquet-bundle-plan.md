# parquet 번들 전환 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목당 CSV 835개를 커밋하던 방식을 parquet 번들 3개로 바꿔, 데이터 갱신이 저장소와 코드 이력을 오염시키지 않게 한다.

**Architecture:** 앱은 `stock_data.parquet`(개별 종목 OHLCV), `kospi_index.parquet`(KOSPI 지수), `kospi_list.parquet`(종목 목록)만 읽고 쓴다. `load_bundle()`이 번들을 **종목코드 → DataFrame 사전**으로 풀어 캐시하므로, 기존 CSV 경로가 만들던 표와 모양이 같아 소비 함수들의 계산 로직은 그대로 둔다. `stock_data/*.csv`는 노트북 실습용 로컬 캐시로 남기고 git 추적에서 뺀다.

**Tech Stack:** Python 3.13 / pandas 3.0.5 / pyarrow 24 (streamlit의 직접 의존성) / streamlit 1.61.1 / mplfinance

**Spec:** `work/_ko_stock/docs/2026-09-13-parquet-bundle-design.md`

## Global Constraints

- 작업 디렉터리: `work/_ko_stock`. 아래 모든 상대 경로는 여기 기준.
- 파이썬은 `/Users/back/miniforge3/bin/python3` 를 쓴다. PATH의 `python3` 에는 streamlit이 없다.
- Python 3.13 검증용 venv 는 `tests/_scratch/venv313` 에 만든다. (`tests/_scratch/` 는 git 추적 대상이 아니다.) 없으면 다음으로 만든다.
  ```bash
  cd work/_ko_stock
  /Users/back/.local/bin/uv venv --python 3.13 tests/_scratch/venv313
  /Users/back/.local/bin/uv pip install \
      --python tests/_scratch/venv313/bin/python -r requirements.txt
  ```
- 번들 파일 경로는 `BASE_DIR / "stock_data.parquet"`, `BASE_DIR / "kospi_index.parquet"`, `BASE_DIR / "kospi_list.parquet"`. `BASE_DIR` 는 app.py가 있는 폴더.
- 번들 컬럼 순서는 항상 `["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change"]`.
- 압축은 zstd, `index=False` 로 저장한다.
- 개별 종목 OHLCV dtype은 int64, `Change` 는 float64, `Date` 는 datetime64[us] 를 유지한다.
- **KOSPI 지수(KS11)는 개별 종목과 같은 표에 담지 않는다.** 지수만 OHLC 가 float64 라
  한 표로 합치면 833개 종목의 int64 가 float64 로 끌어올려진다. `kospi_index.parquet` 에 따로 둔다.
- 보관 범위는 최근 600일. 기존과 같다.
- 데이터가 실제로 바뀌지 않았으면 번들 파일을 다시 쓰지 않는다. 파일 수정시각이 바뀌면 `data_fingerprint()` 가 달라져 계산 캐시가 통째로 버려진다.
- 계산 결과와 차트 그림은 전환 전후가 같아야 한다. 기준을 낮추려면 사유를 설계 문서에 남긴다.
- 커밋 메시지 끝에 다음 두 줄을 붙인다.
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
  ```

---

## File Structure

| 파일 | 역할 |
|---|---|
| `app.py` (수정) | 데이터 접근 6곳을 번들 기반으로 교체 |
| `tests/` (신규) | 지금까지 임시 폴더에 있던 검증 스크립트를 저장소로 옮긴 곳 |
| `tests/run_all.py` (신규) | 전체 테스트 실행기. 하나의 명령으로 합격/불합격 판정 |
| `tests/conftest_paths.py` (신규) | 프로젝트 경로 상수. 각 테스트가 공유 |
| `stock_data.parquet` (신규, 커밋) | 개별 종목 OHLCV (833개) |
| `kospi_index.parquet` (신규, 커밋) | KOSPI 지수 OHLCV |
| `kospi_list.parquet` (신규, 커밋) | 종목 목록 |
| `.gitignore` (수정) | `stock_data/` 추가 |
| `requirements.txt` (수정) | `pyarrow` 명시 고정 |
| `01_stock_download.ipynb` (수정) | "번들 만들기" 셀 1개 추가 |

---

### Task 1: 테스트 하네스를 저장소로 옮긴다

지금 검증 스크립트가 전부 세션 임시 폴더에 있어 세션이 끝나면 사라진다. 이후 모든 작업이 이 테스트로 판정되므로 가장 먼저 옮긴다. **이 시점에서는 앱 코드를 바꾸지 않는다** — 현재 코드에서 전부 통과하는 기준선을 만드는 것이 목표다.

**Files:**
- Create: `tests/conftest_paths.py`
- Create: `tests/run_all.py`
- Create: `tests/test_metrics_equiv.py`, `tests/test_sell_stage.py`, `tests/test_error_log.py`, `tests/test_fingerprint.py`, `tests/test_font.py`, `tests/test_apptest.py`, `tests/test_chart_cache.py`
- Create: `tests/baseline/app_baseline.py` (동치 비교의 기준이 되는 82th 커밋 시점 app.py)

**Interfaces:**
- Produces: `tests/run_all.py` — 인자 없이 실행하면 전체 테스트를 돌리고, 모두 통과하면 종료코드 0, 하나라도 실패하면 1. 이후 모든 Task가 이 명령으로 판정한다.
- Produces: `tests/conftest_paths.py` — `PROJECT`(Path), `DATA_FOLDER`(Path), `APP`(Path), `SCRATCH`(Path) 상수.

- [ ] **Step 1: 경로 상수 파일을 만든다**

`tests/conftest_paths.py`:

```python
"""테스트가 공유하는 경로 상수."""

from pathlib import Path

# tests/ 의 부모가 프로젝트 폴더
PROJECT = Path(__file__).resolve().parent.parent

APP = PROJECT / "app.py"
DATA_FOLDER = PROJECT / "stock_data"
BUNDLE_FILE = PROJECT / "stock_data.parquet"
INDEX_FILE = PROJECT / "kospi_index.parquet"
LIST_FILE = PROJECT / "kospi_list.parquet"

# 테스트가 만드는 임시 산출물 (git 추적 안 함)
SCRATCH = PROJECT / "tests" / "_scratch"
SCRATCH.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: 기준선 app.py 를 저장한다**

동치 테스트는 "전환 전 코드"와 결과를 비교한다. 82th 커밋(`13f9656`)의 app.py 는 아직 CSV 기반이고 `analyze_stocks(min_value, data_version)` 시그니처를 쓴다. 현재 코드의 `compute_metrics(data_version)` 와 비교하기 위해 보관한다.

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p work/_ko_stock/tests/baseline
git show 13f9656:work/_ko_stock/app.py > work/_ko_stock/tests/baseline/app_baseline.py
```

- [ ] **Step 3: 기존 검증 스크립트 7개를 옮기고 경로를 상수로 바꾼다**

임시 폴더의 `test_metrics_equiv.py` `test_sell_stage.py` `test_error_log.py` `test_fingerprint.py` `test_font.py` `test_apptest.py` `test_chart_cache.py` 를 `tests/` 로 복사한 뒤, 각 파일 안에 하드코딩된 절대경로를 다음으로 교체한다.

```python
from conftest_paths import PROJECT, APP, DATA_FOLDER, SCRATCH
```

`test_metrics_equiv.py` 의 기준선 경로는 `PROJECT / "tests" / "baseline" / "app_baseline.py"` 로 바꾼다.
`test_font.py` 와 `capture_charts` 계열이 인자로 받던 출력 폴더는 `SCRATCH` 를 쓰도록 바꾼다.

- [ ] **Step 4: 실행기를 만든다**

`tests/run_all.py`:

```python
"""전체 테스트 실행기. 모두 통과하면 종료코드 0."""

import subprocess
import sys
from pathlib import Path

TESTS = [
    "test_metrics_equiv.py",
    "test_sell_stage.py",
    "test_error_log.py",
    "test_fingerprint.py",
    "test_font.py",
    "test_chart_cache.py",
    "test_apptest.py",
]

HERE = Path(__file__).resolve().parent


def main():
    failed = []

    for name in TESTS:
        proc = subprocess.run(
            [sys.executable, str(HERE / name)],
            cwd=HERE,
            capture_output=True,
            text=True,
        )
        mark = "통과" if proc.returncode == 0 else "실패"
        print(f"  {name:<26} {mark}")

        if proc.returncode != 0:
            failed.append(name)
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:])

    print()
    if failed:
        print("실패:", ", ".join(failed))
        return 1

    print(f"전체 {len(TESTS)}종 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 기준선이 초록인지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/run_all.py`
Expected: `전체 7종 통과`, 종료코드 0

하나라도 실패하면 이전한 스크립트의 경로 치환이 잘못된 것이다. 앱 코드는 아직 건드리지 않았으므로 앱 문제가 아니다.

- [ ] **Step 6: 테스트 산출물을 git 에서 제외한다**

`.gitignore` 에 추가:

```
tests/_scratch/
```

- [ ] **Step 7: 커밋**

```bash
git add work/_ko_stock/tests work/_ko_stock/.gitignore
git commit -m "$(cat <<'EOF'
검증 스크립트를 저장소 tests/ 로 이전

세션 임시 폴더에 있던 7종을 옮기고 단일 실행기를 추가한다.
이후 parquet 전환 작업의 합격 판정 기준이 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 2: 번들 빌더와 저장 함수를 만든다

CSV에서 번들을 만드는 함수와, 원자적으로 저장하는 함수를 추가한다. 아직 앱의 읽기 경로는 바꾸지 않는다.

**Files:**
- Modify: `app.py` — 7절(`파일 저장 / 데이터 지문`)에 추가
- Create: `tests/test_bundle_build.py`

**Interfaces:**
- Produces: `BUNDLE_COLUMNS: list[str]` — 번들 컬럼 순서
- Produces: `BUNDLE_FILE: Path`, `INDEX_FILE: Path`, `LIST_FILE: Path`
- Produces: `build_index_from_csv() -> pd.DataFrame | None` — `stock_data/KS11.csv` 를 읽어 지수 표로. 없으면 `None`
- Produces: `save_bundle(df: pd.DataFrame, path: Path) -> None` — 임시 파일에 쓴 뒤 교체
- Produces: `build_bundle_from_csv() -> pd.DataFrame | None` — `stock_data/*.csv` 에서 `KOSPI_list.csv` 와 `KS11.csv` 를 뺀 나머지를 모아 번들 형식으로. CSV가 하나도 없으면 `None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_bundle_build.py`:

```python
"""번들 빌더가 CSV 내용을 손실 없이 옮기는지 확인."""

import ast
import logging
import sys

import pandas as pd

from conftest_paths import APP, DATA_FOLDER, PROJECT


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
        "BUNDLE_COLUMNS": ["Code", "Date", "Open", "High", "Low",
                           "Close", "Volume", "Change"],
        "logger": logging.getLogger("test"),
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(APP), "exec"), ns)
    return ns


ns = load_funcs(["build_bundle_from_csv"])
bundle = ns["build_bundle_from_csv"]()

assert bundle is not None, "번들이 만들어지지 않았습니다"

expected_cols = ["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change"]
print("컬럼 순서 :", list(bundle.columns))
assert list(bundle.columns) == expected_cols, "컬럼 순서가 다릅니다"

# CSV 개수와 종목 수가 맞는지 (KOSPI_list 는 제외 대상)
csv_codes = {f.stem for f in DATA_FOLDER.glob("*.csv") if f.stem != "KOSPI_list"}
bundle_codes = set(bundle["Code"].unique())
missing = csv_codes - bundle_codes
print(f"CSV 종목 {len(csv_codes)}개 / 번들 종목 {len(bundle_codes)}개")

# 빈 CSV 는 번들에 안 들어갈 수 있으므로, 누락분은 모두 비어 있어야 한다
for code in missing:
    df = pd.read_csv(DATA_FOLDER / f"{code}.csv")
    assert df.empty, f"{code}: 내용이 있는데 번들에서 빠졌습니다"

# 표본 3종목의 값이 CSV 와 완전히 같은지
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

# KS11 이 Code 로 들어갔는지
assert "KS11" in bundle_codes, "KOSPI 지수(KS11)가 번들에 없습니다"
print("KS11 포함 : 확인")

# 정렬 확인
assert bundle.equals(
    bundle.sort_values(["Code", "Date"]).reset_index(drop=True)
), "Code, Date 순으로 정렬되어 있지 않습니다"
print("정렬      : 확인")

print("\n=== 통과 ===")
sys.exit(0)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_bundle_build.py`
Expected: FAIL — `AssertionError` 또는 `build_bundle_from_csv` 를 찾지 못했다는 오류

- [ ] **Step 3: app.py 에 구현을 추가한다**

3절(`기본 설정`)의 `DATA_FOLDER` 정의 아래에 경로 상수를 추가한다.

```python
# 앱이 읽고 쓰는 주가 번들
# 종목당 CSV 를 따로 두지 않고 한 파일로 모은다.
BUNDLE_FILE = BASE_DIR / "stock_data.parquet"
LIST_FILE = BASE_DIR / "kospi_list.parquet"

# 번들 컬럼 순서
BUNDLE_COLUMNS = [
    "Code",
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Change",
]
```

7절에 함수 두 개를 추가한다.

```python
def save_bundle(df, path):
    """
    번들을 파일로 저장한다.

    임시 파일에 먼저 쓰고 마지막에 교체한다.
    저장 도중 멈춰도 기존 파일이 깨지지 않는다.
    """

    temp = path.with_name(path.name + ".tmp")

    df.to_parquet(temp, compression="zstd", index=False)

    temp.replace(path)


def build_bundle_from_csv():
    """
    stock_data 폴더의 CSV 를 모아 번들 형식으로 만든다.

    예전 방식으로 받아 둔 CSV 가 있는 환경에서
    번들을 처음 만들 때 쓴다.

    CSV 가 하나도 없으면 None 을 돌려준다.
    """

    frames = []

    for file in sorted(DATA_FOLDER.glob("*.csv")):
        # 종목 목록은 주가가 아니므로 제외
        if file.stem == "KOSPI_list":
            continue

        try:
            df = pd.read_csv(
                file, index_col="Date", parse_dates=["Date"]
            ).sort_index()

        except Exception as e:
            logger.warning("%s 읽기 실패, 건너뜁니다: %s", file.name, e)
            continue

        if df.empty:
            continue

        df = df.reset_index()

        # 파일 이름이 곧 종목코드
        df["Code"] = file.stem

        frames.append(df)

    if not frames:
        return None

    bundle = pd.concat(frames, ignore_index=True)

    return (
        bundle[BUNDLE_COLUMNS]
        .sort_values(["Code", "Date"])
        .reset_index(drop=True)
    )
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_bundle_build.py`
Expected: `=== 통과 ===`, 종료코드 0

- [ ] **Step 5: 기존 테스트가 깨지지 않았는지 확인한다**

`tests/run_all.py` 의 `TESTS` 목록에 `"test_bundle_build.py"` 를 추가한 뒤:

Run: `/Users/back/miniforge3/bin/python3 tests/run_all.py`
Expected: `전체 8종 통과`

- [ ] **Step 6: 커밋**

```bash
git add work/_ko_stock/app.py work/_ko_stock/tests
git commit -m "$(cat <<'EOF'
번들 빌더와 원자적 저장 함수 추가

CSV 를 모아 parquet 번들 형식으로 만드는 build_bundle_from_csv 와
임시 파일 교체 방식으로 저장하는 save_bundle 을 추가한다.
읽기 경로는 아직 바꾸지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 3: 읽기 경로를 번들로 바꾼다

`load_bundle` 을 새로 만들고, `data_fingerprint` / `load_market` / `load_stocks` 를 번들 기반으로 교체한다. 번들 파일이 아직 없으므로, 이 Task 안에서 한 번 만들어 둔다.

**Files:**
- Modify: `app.py` — 7절 `data_fingerprint`, 8절 `load_market` / `load_stocks`, 신규 `load_bundle`
- Create: `tests/test_bundle_read.py`

**Interfaces:**
- Consumes: `BUNDLE_FILE`, `LIST_FILE`, `BUNDLE_COLUMNS`, `save_bundle`, `build_bundle_from_csv` (Task 2)
- Produces: `load_bundle(data_version: str) -> dict[str, pd.DataFrame]` — 종목코드를 키로 하고, `Date` 인덱스에 `Open/High/Low/Close/Volume/Change` 컬럼을 가진 표를 값으로 하는 사전. **기존 CSV 경로가 만들던 표와 모양이 같다.**

> **설계 문서와의 차이:** 설계 9절은 메모리 대책으로 `Code` 를 category 로 두라고 적었다.
> 이 계획은 대신 종목별로 나누면서 `Code` 컬럼을 **아예 버린다**.
> 같은 목적(문자열 중복 제거)을 더 확실히 달성하고, 덤으로 소비 함수들이
> 기존 CSV 경로와 똑같은 표를 받게 되어 계산 로직을 건드리지 않아도 된다.
> category 변환은 하지 않는다.
- Produces: `data_fingerprint()` — 시그니처 그대로. 내부만 번들 3개 기준으로 바뀜

- [ ] **Step 1: 번들 파일을 만든다**

읽기 테스트에 실제 파일이 필요하다. 다음을 한 번 실행한다.

```bash
cd work/_ko_stock
/Users/back/miniforge3/bin/python3 - <<'PYEOF'
import ast, logging
from pathlib import Path
import pandas as pd

P = Path(".").resolve()
COLS = ["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change"]

tree = ast.parse((P / "app.py").read_text())
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef)
       and n.name in ("build_bundle_from_csv", "save_bundle")]
for n in fns:
    n.decorator_list = []
ns = {"pd": pd, "DATA_FOLDER": P / "stock_data", "BUNDLE_COLUMNS": COLS,
      "logger": logging.getLogger("x")}
exec(compile(ast.Module(body=fns, type_ignores=[]), "app.py", "exec"), ns)

bundle = ns["build_bundle_from_csv"]()
ns["save_bundle"](bundle, P / "stock_data.parquet")
print("stock_data.parquet:", (P / "stock_data.parquet").stat().st_size / 1024 / 1024, "MB")

lst = pd.read_csv(P / "stock_data" / "KOSPI_list.csv", dtype={"Code": str})
lst["Code"] = lst["Code"].astype(str).str.replace(".0", "", regex=False).str.zfill(6)
ns["save_bundle"](lst, P / "kospi_list.parquet")
print("kospi_list.parquet:", (P / "kospi_list.parquet").stat().st_size / 1024, "KB")
PYEOF
```

Expected: `stock_data.parquet` 약 4.8MB, `kospi_list.parquet` 생성

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_bundle_read.py`:

```python
"""load_bundle 이 CSV 경로와 같은 모양의 표를 돌려주는지 확인."""

import ast
import logging
import sys

import pandas as pd

from conftest_paths import APP, BUNDLE_FILE, DATA_FOLDER, LIST_FILE


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
        "LIST_FILE": LIST_FILE,
        "logger": logging.getLogger("test"),
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(APP), "exec"), ns)
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
    assert part.equals(csv), f"{code}: 값이 다릅니다"
    print(f"  {code} : CSV 와 동일")

# KOSPI 지수
market = ns["load_market"]("v")
csv_market = pd.read_csv(DATA_FOLDER / "KS11.csv",
                         index_col="Date", parse_dates=["Date"]).sort_index()
assert market.index.equals(csv_market.index), "KS11 날짜가 다릅니다"
assert market["Close"].equals(csv_market["Close"]), "KS11 종가가 다릅니다"
print("KS11        : CSV 와 동일")

# 종목 목록
stocks = ns["load_stocks"]("v")
csv_stocks = pd.read_csv(DATA_FOLDER / "KOSPI_list.csv", dtype={"Code": str})
csv_stocks["Code"] = (csv_stocks["Code"].astype(str)
                      .str.replace(".0", "", regex=False).str.zfill(6))
assert len(stocks) == len(csv_stocks), "종목 목록 행 수가 다릅니다"
assert list(stocks["Code"]) == list(csv_stocks["Code"]), "종목코드가 다릅니다"
assert stocks["Code"].dtype == object, "Code 가 문자열이 아닙니다"
print("종목 목록    : CSV 와 동일")

print("\n=== 통과 ===")
sys.exit(0)
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_bundle_read.py`
Expected: FAIL — `load_bundle` 을 찾지 못했다는 assertion

- [ ] **Step 4: `data_fingerprint` 를 번들 기준으로 바꾼다**

`app.py` 의 `data_fingerprint` 본문에서 CSV 순회를 다음으로 교체한다.

```python
def data_fingerprint():
    """
    주가 번들의 상태를 짧은 글자로 요약한다.

    파일이 바뀌지 않으면 같은 값이 나온다.
    이 값을 캐시 키로 쓰면 데이터가 그대로일 때 캐시가 유지된다.
    """

    parts = []

    for file in (BUNDLE_FILE, LIST_FILE):
        if not file.exists():
            parts.append(f"{file.name}:없음")
            continue

        info = file.stat()
        parts.append(f"{file.name}:{info.st_size}:{info.st_mtime_ns}")

    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]
```

- [ ] **Step 5: `load_bundle` 을 추가하고 `load_market` / `load_stocks` 를 바꾼다**

8절을 다음으로 교체한다.

```python
@st.cache_data(show_spinner=False)
def load_bundle(data_version):
    """
    주가 번들을 읽어 종목코드별 표로 나눠 돌려준다.

    돌려주는 표의 모양은 예전에 종목별 CSV 를 읽었을 때와 같다.
    Date 를 인덱스로 하고 Open/High/Low/Close/Volume/Change 컬럼을 가진다.
    """

    # data_version 은 데이터가 갱신되었을 때 캐시를 무효화하기 위한 값
    _ = data_version

    bundle = pd.read_parquet(BUNDLE_FILE)

    groups = {}

    for code, part in bundle.groupby("Code", observed=True):
        groups[str(code)] = (
            part.drop(columns="Code")
            .set_index("Date")
            .sort_index()
        )

    return groups


@st.cache_data(show_spinner=False)
def load_market(data_version):
    """KOSPI 지수 읽기"""

    groups = load_bundle(data_version)

    if "KS11" not in groups:
        raise RuntimeError("번들에 KOSPI 지수(KS11)가 없습니다.")

    return groups["KS11"]


@st.cache_data(show_spinner=False)
def load_stocks(data_version):
    """KOSPI 종목 목록 읽기"""

    _ = data_version

    df = pd.read_parquet(LIST_FILE)

    # 종목코드를 6자리 문자열로 통일
    # 예: 5930 → 005930
    df["Code"] = (
        df["Code"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(6)
    )

    return df
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_bundle_read.py`
Expected: `=== 통과 ===`

- [ ] **Step 7: 커밋**

`tests/run_all.py` 의 `TESTS` 에 `"test_bundle_read.py"` 를 추가한다. 이 시점에는 `prepare_stock_data` 가 아직 CSV 기반이라 `test_apptest.py` 가 실패할 수 있다. **실패하면 Task 6까지 보류하고, run_all 에서 해당 항목을 일시적으로 건너뛰지 말고 실패를 그대로 둔 채 다음 Task 로 간다.** Task 6 끝에 전부 초록이 되어야 한다.

```bash
git add work/_ko_stock/app.py work/_ko_stock/tests work/_ko_stock/stock_data.parquet work/_ko_stock/kospi_list.parquet
git commit -m "$(cat <<'EOF'
읽기 경로를 parquet 번들로 전환

load_bundle 을 추가하고 data_fingerprint / load_market / load_stocks 가
번들을 보도록 바꾼다. load_bundle 은 예전 CSV 경로와 같은 모양의
표를 돌려주므로 소비 함수의 계산 로직은 그대로 둔다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 4: `compute_metrics` 를 번들 기반으로 바꾼다

**Files:**
- Modify: `app.py` — 9절 `compute_metrics` 의 파일 읽기 부분만
- Modify: `tests/test_metrics_equiv.py` — 번들 경로를 주입하도록 갱신

**Interfaces:**
- Consumes: `load_bundle(data_version)` (Task 3)
- Produces: `compute_metrics(data_version)` — 시그니처와 반환값 `(pd.DataFrame, dict)` 모두 그대로

- [ ] **Step 1: 반복 순서를 유지하며 읽기만 교체한다**

`compute_metrics` 안에서 다음 부분을

```python
        stock_file = DATA_FOLDER / f"{code}.csv"

        # 주가 파일이 없으면 제외
        if not stock_file.exists():
            continue

        try:
            # 주가 데이터 읽기
            df = pd.read_csv(
                stock_file, index_col="Date", parse_dates=["Date"]
            ).sort_index()
```

다음으로 바꾼다.

```python
        # 번들에 없는 종목은 제외
        df = groups.get(code)

        if df is None:
            continue

        try:
```

그리고 함수 도입부의 `stocks = load_stocks(data_version)` 아래에 다음을 추가한다.

```python
    groups = load_bundle(data_version)
```

**`stocks.iterrows()` 순회는 그대로 둔다.** `groupby` 순서로 바꾸면 결과 표의 행 순서가 달라져 동치 검증이 깨진다.

- [ ] **Step 2: 동치 테스트를 실행한다**

`tests/test_metrics_equiv.py` 의 네임스페이스에 `BUNDLE_FILE` 과 `load_bundle` 이 필요하다. `load_funcs` 로 꺼내는 함수 목록에 `load_bundle` 을 추가하고, 주입 사전에 `BUNDLE_FILE`, `LIST_FILE` 을 넣는다. 기준선(`app_baseline.py`)은 CSV 를 그대로 읽으므로 `DATA_FOLDER` 도 계속 넣어 둔다.

Run: `/Users/back/miniforge3/bin/python3 tests/test_metrics_equiv.py`
Expected: 거래대금 6구간 전부 `OK`, `결과: 전 구간 동일`

행 순서나 dtype 때문에 실패하면 **테스트를 느슨하게 고치지 말고** 구현을 맞춘다. 이 테스트가 이번 전환의 핵심 안전장치다.

- [ ] **Step 3: 커밋**

```bash
git add work/_ko_stock/app.py work/_ko_stock/tests/test_metrics_equiv.py
git commit -m "$(cat <<'EOF'
compute_metrics 를 번들 기반으로 전환

파일별 read_csv 를 번들 슬라이스로 바꾼다.
종목 목록 순회 순서를 유지해 결과 표의 행 순서를 보존한다.
거래대금 6구간에서 전환 전과 동일함을 확인했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 5: `render_chart` 를 번들 기반으로 바꾼다

**Files:**
- Modify: `app.py` — `render_chart` 의 첫 부분
- Modify: `tests/capture_charts.py` (Task 1에서 옮긴 것) — 새 경로 대응

**Interfaces:**
- Consumes: `load_bundle(data_version)` (Task 3)
- Produces: `render_chart(code, chart_days, title, buy, stop, r1, r2, data_version) -> tuple[bytes, int]` — 시그니처와 반환값 그대로

- [ ] **Step 1: 전환 전 PNG 를 기준선으로 남긴다**

```bash
cd work/_ko_stock
/Users/back/miniforge3/bin/python3 tests/capture_charts.py app.py tests/_scratch/charts_before new
```

Expected: `005930.png` `000660.png` `005380.png` 생성

- [ ] **Step 2: 읽기만 교체한다**

`render_chart` 안에서

```python
    chart_df = pd.read_csv(
        DATA_FOLDER / f"{code}.csv", index_col="Date", parse_dates=["Date"]
    ).sort_index()
```

를 다음으로 바꾼다.

```python
    groups = load_bundle(data_version)

    chart_df = groups.get(code)

    if chart_df is None:
        raise KeyError(f"번들에 {code} 주가가 없습니다.")
```

함수 도입부의 `_ = data_version` 줄은 이제 실제로 쓰이므로 지운다.

- [ ] **Step 3: PNG 가 바이트 단위로 같은지 확인한다**

```bash
/Users/back/miniforge3/bin/python3 tests/capture_charts.py app.py tests/_scratch/charts_after new

for f in 005930 000660 005380; do
  if cmp -s tests/_scratch/charts_before/$f.png tests/_scratch/charts_after/$f.png; then
    echo "  $f.png : 완전 동일"
  else
    echo "  $f.png : 다름"
  fi
done
```

Expected: 세 종목 모두 `완전 동일`

다르면 원인을 규명한다. dtype 이나 컬럼 순서가 흔한 원인이다. 설계 문서 8절에 따라, 픽셀 차이가 불가피하다고 판단되면 **사유를 설계 문서에 적은 뒤에만** 육안 동등성으로 기준을 낮춘다.

- [ ] **Step 4: 커밋**

```bash
git add work/_ko_stock/app.py work/_ko_stock/tests
git commit -m "$(cat <<'EOF'
render_chart 를 번들 기반으로 전환

차트 데이터도 번들에서 읽는다.
대표 3종목의 PNG 가 전환 전과 바이트 단위로 같음을 확인했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 6: `prepare_stock_data` 를 번들 기반으로 바꾼다

가장 큰 함수다. 다운로드·병합·저장을 모두 번들 위에서 한다.

**Files:**
- Modify: `app.py` — 8절 `prepare_stock_data` 전체
- Create: `tests/test_prepare_bundle.py`

**Interfaces:**
- Consumes: `BUNDLE_FILE`, `LIST_FILE`, `BUNDLE_COLUMNS`, `save_bundle`, `build_bundle_from_csv` (Task 2)
- Produces: `prepare_stock_data()` — 반환 사전의 키는 그대로: `market_date`, `stock_count`, `stats`, `error_codes`, `data_version`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_prepare_bundle.py`:

```python
"""
번들이 없을 때 CSV 에서 자동으로 만들어지는지,
데이터가 그대로면 파일을 다시 쓰지 않는지 확인한다.

네트워크를 쓰지 않도록 fdr 을 가짜로 바꿔치기한다.
"""

import ast
import logging
import shutil
import sys
import time
from pathlib import Path
from threading import RLock

import pandas as pd

from conftest_paths import APP, DATA_FOLDER, PROJECT, SCRATCH

COLS = ["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change"]


class FakeFdr:
    """네트워크 대신 로컬 CSV 를 돌려준다."""

    def StockListing(self, market):
        df = pd.read_csv(DATA_FOLDER / "KOSPI_list.csv", dtype={"Code": str})
        return df

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
             "data_fingerprint")
    wanted = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(wanted) == len(names), [n.name for n in wanted]
    for n in wanted:
        n.decorator_list = []

    import datetime as _dt
    import hashlib as _hashlib

    ns = {
        "pd": pd,
        "fdr": FakeFdr(),
        "hashlib": _hashlib,
        "datetime": _dt.datetime,
        "logger": logging.getLogger("test"),
        "DATA_LOCK": RLock(),
        "DATA_FOLDER": work_dir / "stock_data",
        "BUNDLE_FILE": work_dir / "stock_data.parquet",
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
assert (work / "stock_data.parquet").exists(), "번들이 만들어지지 않았습니다"
print("① 번들 자동 생성 : 확인")
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

shutil.rmtree(work, ignore_errors=True)
print("\n=== 통과 ===")
sys.exit(0)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_prepare_bundle.py`
Expected: FAIL — 번들이 만들어지지 않음

- [ ] **Step 3: `prepare_stock_data` 를 다시 쓴다**

기존 함수 전체를 다음으로 교체한다.

```python
@st.cache_data(ttl=DATA_REFRESH_SECONDS, show_spinner=False)
def prepare_stock_data():
    """
    주가 번들을 확인하고 필요한 만큼만 갱신한다.

    - 번들이 없으면 예전 CSV 에서 만들거나 새로 내려받는다
    - KOSPI 지수와 개별 종목이 오래되었으면 부족한 날짜만 갱신
    - 이미 최신이면 다운로드 생략
    """

    stats = {
        "신규 다운로드": 0,
        "기존 파일 갱신": 0,
        "이미 최신": 0,
        "새 데이터 없음": 0,
        "오류": 0,
    }

    # 오류가 난 종목코드 예시 (사이드바 표시용)
    error_codes = []

    with DATA_LOCK:
        # ----------------------------------------------
        # ① KOSPI 종목 목록
        # ----------------------------------------------
        try:
            stocks = fdr.StockListing("KOSPI")

        except Exception as e:
            # 인터넷 오류 시 기존 목록 사용
            logger.warning("KOSPI 종목 목록 조회 실패, 저장된 목록을 사용합니다: %s", e)

            if not LIST_FILE.exists():
                raise RuntimeError(
                    "KOSPI 종목 목록을 받지 못했고 저장된 목록도 없습니다."
                )

            stocks = pd.read_parquet(LIST_FILE)

        # 종목코드를 6자리 문자열로 통일
        stocks["Code"] = (
            stocks["Code"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.zfill(6)
        )

        # 일반 종목만 사용
        stocks = stocks[stocks["Code"].str.endswith("0")].copy()

        # 목록이 달라졌을 때만 저장
        if LIST_FILE.exists():
            try:
                old = pd.read_parquet(LIST_FILE)
                list_changed = not old.equals(stocks)

            except Exception as e:
                logger.warning("종목 목록 비교 실패, 새로 저장합니다: %s", e)
                list_changed = True

        else:
            list_changed = True

        if list_changed:
            save_bundle(stocks, LIST_FILE)

        # ----------------------------------------------
        # ② 번들 적재
        # ----------------------------------------------
        if BUNDLE_FILE.exists():
            try:
                bundle = pd.read_parquet(BUNDLE_FILE)

            except Exception as e:
                # 번들이 깨졌으면 CSV 에서 복구를 시도한다
                logger.warning("번들을 읽지 못했습니다, 다시 만듭니다: %s", e)
                bundle = build_bundle_from_csv()

        else:
            # 예전 방식으로 받아 둔 CSV 가 있으면 거기서 만든다
            bundle = build_bundle_from_csv()

        if bundle is None:
            bundle = pd.DataFrame(columns=BUNDLE_COLUMNS)

        # 종목코드별로 나눠 둔다
        frames = {
            str(code): part.drop(columns="Code").set_index("Date").sort_index()
            for code, part in bundle.groupby("Code", observed=True)
        }

        # 번들을 새로 만들었으면 저장이 필요하다
        changed = not BUNDLE_FILE.exists()

        # ----------------------------------------------
        # ③ KOSPI 지수
        # ----------------------------------------------
        kospi = frames.get("KS11")

        if kospi is None or kospi.empty:
            kospi = fdr.DataReader("KS11", START)

            if kospi.empty:
                raise RuntimeError("KOSPI 데이터를 가져오지 못했습니다.")

            kospi.index = pd.to_datetime(kospi.index)
            kospi = kospi.sort_index()
            changed = True

        else:
            try:
                # 마지막 날짜보다 5일 앞부터 다시 받는다.
                start = (kospi.index[-1] - pd.Timedelta(days=5)).strftime("%Y-%m-%d")

                new = fdr.DataReader("KS11", start)

                if not new.empty:
                    new.index = pd.to_datetime(new.index)
                    new = new.sort_index()

                    merged = pd.concat([kospi, new])
                    merged = merged[
                        ~merged.index.duplicated(keep="last")
                    ].sort_index()

                    if not merged.equals(kospi):
                        kospi = merged
                        changed = True

            except Exception as e:
                # 갱신 실패 시 기존 데이터를 계속 사용
                logger.warning("KOSPI 지수 갱신 실패, 기존 데이터를 사용합니다: %s", e)

        # 최근 600일만 유지
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=600)
        trimmed = kospi[kospi.index >= cutoff]

        if not trimmed.equals(kospi):
            changed = True

        kospi = trimmed

        if kospi.empty:
            raise RuntimeError("KOSPI 데이터가 없습니다.")

        frames["KS11"] = kospi

        # 전체 시장의 최신 거래일
        market_date = kospi.index[-1].date()

        # ----------------------------------------------
        # ④ 개별 종목 주가
        # ----------------------------------------------
        for _, stock in stocks.iterrows():
            code = stock["Code"]

            try:
                df = frames.get(code)

                # 번들에 없으면 최근 600일 전체 다운로드
                if df is None or df.empty:
                    df = fdr.DataReader(code, START)

                    if df.empty:
                        stats["새 데이터 없음"] += 1
                        continue

                    df.index = pd.to_datetime(df.index)
                    frames[code] = df.sort_index()

                    changed = True
                    stats["신규 다운로드"] += 1
                    continue

                # 이미 최신 거래일까지 있으면 다운로드 생략
                if df.index[-1].date() >= market_date:
                    stats["이미 최신"] += 1
                    continue

                # 부족한 최근 날짜만 다운로드
                start = (df.index[-1] - pd.Timedelta(days=5)).strftime("%Y-%m-%d")

                new = fdr.DataReader(code, start)

                if new.empty:
                    stats["새 데이터 없음"] += 1
                    continue

                new.index = pd.to_datetime(new.index)
                new = new.sort_index()

                # 기존 데이터 + 새 데이터
                merged = pd.concat([df, new])
                merged = merged[
                    ~merged.index.duplicated(keep="last")
                ].sort_index()

                # 최근 600일만 유지
                merged = merged[merged.index >= cutoff]

                if merged.equals(df):
                    stats["이미 최신"] += 1
                    continue

                frames[code] = merged

                changed = True
                stats["기존 파일 갱신"] += 1

            except Exception as e:
                # 한 종목 오류가 전체 앱 실행을 막지 않도록 한다.
                logger.warning("%s 주가 갱신 실패: %s", code, e)

                stats["오류"] += 1

                # 사이드바에 보여 줄 예시 종목코드
                if len(error_codes) < 5:
                    error_codes.append(code)

                continue

        # ----------------------------------------------
        # ⑤ 실제로 바뀐 것이 있을 때만 저장
        # ----------------------------------------------
        if changed:
            rebuilt = []

            for code, part in frames.items():
                piece = part.reset_index()
                piece["Code"] = code
                rebuilt.append(piece)

            new_bundle = (
                pd.concat(rebuilt, ignore_index=True)[BUNDLE_COLUMNS]
                .sort_values(["Code", "Date"])
                .reset_index(drop=True)
            )

            save_bundle(new_bundle, BUNDLE_FILE)

    # 파일이 바뀌지 않으면 이 값도 그대로다.
    data_version = f"{market_date}-{data_fingerprint()}"

    return {
        "market_date": str(market_date),
        "stock_count": len(stocks),
        "stats": stats,
        "error_codes": error_codes,
        "data_version": data_version,
    }
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_prepare_bundle.py`
Expected: `① 번들 자동 생성 : 확인`, `지문 유지 : 확인`, `=== 통과 ===`

`②` 가 실패하면 데이터가 같은데도 `changed` 가 True 가 되는 경로가 있다는 뜻이다. 위 코드는 `merged.equals(df)` 로 비교해 그 경우를 막는다. 실패하면 어느 단계에서 `changed = True` 가 되는지 로그를 넣어 찾는다.

- [ ] **Step 5: 전체 테스트를 돌린다**

`tests/run_all.py` 의 `TESTS` 에 `"test_prepare_bundle.py"` 를 추가한다.

Run: `/Users/back/miniforge3/bin/python3 tests/run_all.py`
Expected: `전체 10종 통과` — Task 3에서 보류했던 `test_apptest.py` 도 여기서 초록이 되어야 한다

- [ ] **Step 6: 커밋**

```bash
git add work/_ko_stock/app.py work/_ko_stock/tests
git commit -m "$(cat <<'EOF'
prepare_stock_data 를 번들 기반으로 전환

다운로드·병합·저장을 모두 번들 위에서 한다.
데이터가 실제로 바뀐 경우에만 파일을 다시 써서
data_fingerprint 가 안정적으로 유지되도록 한다.
번들이 없으면 예전 CSV 에서 자동으로 만든다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 7: 정리와 저장소 추적 해제

**Files:**
- Modify: `app.py` — `save_if_changed` 제거
- Modify: `.gitignore`
- Modify: `requirements.txt`
- Create: `tests/test_cold_start.py`

**Interfaces:**
- Consumes: 앞선 모든 Task
- Produces: 없음 (정리 작업)

- [ ] **Step 1: `save_if_changed` 가 더 이상 쓰이지 않는지 확인하고 지운다**

```bash
grep -n "save_if_changed" work/_ko_stock/app.py
```

Expected: 정의부 외에 호출이 없어야 한다. 있으면 그 호출부터 번들 방식으로 바꾼다.

정의부(7절)를 통째로 삭제한다.

- [ ] **Step 2: 콜드 스타트 테스트를 쓴다**

`tests/test_cold_start.py`:

```python
"""
stock_data/ 폴더 없이 번들만으로 앱이 뜨는지 확인한다.
Streamlit Cloud 는 CSV 를 받지 않으므로 이 상태가 실제 배포 환경이다.
"""

import shutil
import sys
from pathlib import Path

from conftest_paths import BUNDLE_FILE, DATA_FOLDER, LIST_FILE, PROJECT, SCRATCH

assert BUNDLE_FILE.exists(), "번들이 없습니다. Task 3 을 먼저 끝내세요."
assert LIST_FILE.exists(), "종목 목록 번들이 없습니다."

# CSV 폴더를 잠시 치운다
moved = None
if DATA_FOLDER.exists():
    moved = SCRATCH / "stock_data_hidden"
    shutil.rmtree(moved, ignore_errors=True)
    shutil.move(str(DATA_FOLDER), str(moved))

try:
    import os
    os.chdir(PROJECT)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PROJECT / "app.py"), default_timeout=1800).run()

    if at.exception:
        for e in at.exception:
            print(e.value)
        raise AssertionError("CSV 없이 앱이 뜨지 않습니다")

    print("예외 없음")
    print("subheader :", [x.value for x in at.subheader])
    print("metric    :", [(x.label, x.value) for x in at.metric])
    assert at.subheader, "화면이 비어 있습니다"

finally:
    if moved is not None:
        shutil.rmtree(DATA_FOLDER, ignore_errors=True)
        shutil.move(str(moved), str(DATA_FOLDER))
        print("stock_data/ 복구 완료")

print("\n=== 통과 ===")
sys.exit(0)
```

- [ ] **Step 3: 콜드 스타트 테스트를 실행한다**

Run: `/Users/back/miniforge3/bin/python3 tests/test_cold_start.py`
Expected: `예외 없음`, `=== 통과 ===`, `stock_data/ 복구 완료`

**주의:** 이 테스트는 `stock_data/` 를 잠시 옮긴다. 중단되면 `tests/_scratch/stock_data_hidden` 에서 직접 되돌린다.

- [ ] **Step 4: `.gitignore` 와 `requirements.txt` 를 고친다**

`.gitignore` 에 추가:

```
stock_data/
```

`requirements.txt` 에 추가 (streamlit 이 이미 끌고 오지만 직접 쓰므로 명시한다):

```
pyarrow==24.0.0
```

- [ ] **Step 5: CSV 추적을 해제한다**

로컬 파일은 지우지 않는다. git 인덱스에서만 뺀다.

```bash
cd "$(git rev-parse --show-toplevel)"
git rm -r --cached work/_ko_stock/stock_data
ls work/_ko_stock/stock_data | wc -l
```

Expected: 마지막 명령이 835 를 출력한다 (로컬 파일은 그대로)

- [ ] **Step 6: 전체 테스트를 돌린다**

`tests/run_all.py` 의 `TESTS` 에 `"test_cold_start.py"` 를 추가한다.

Run: `/Users/back/miniforge3/bin/python3 tests/run_all.py`
Expected: `전체 11종 통과`

- [ ] **Step 7: 커밋**

```bash
git add -A work/_ko_stock
git commit -m "$(cat <<'EOF'
주가 CSV 추적 해제, save_if_changed 제거

stock_data/ 를 gitignore 로 옮기고 번들 3개만 커밋한다.
로컬 CSV 는 노트북 실습용으로 그대로 남는다.
CSV 경로가 사라져 save_if_changed 는 더 이상 쓰이지 않는다.
pyarrow 를 requirements 에 명시한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

### Task 8: 노트북에 번들 만들기 셀 추가와 최종 검증

**Files:**
- Modify: `01_stock_download.ipynb` — 마지막 `# end` 셀 앞에 코드 셀 1개 추가
- Modify: `docs/2026-09-13-parquet-bundle-design.md` — 완료 표시

**Interfaces:**
- Consumes: 앞선 모든 Task

- [ ] **Step 1: 노트북에 셀을 추가한다**

`01_stock_download.ipynb` 의 `# end` 셀 **앞**에 다음 코드 셀을 넣는다. 기존 셀은 수정하지 않는다.

```python
# ==================================================
# 번들 만들기
#
# 위에서 받은 종목별 CSV 를 파일 하나로 모은다.
# 앱(app.py)은 이 번들만 읽는다.
# ==================================================

import pandas as pd
from pathlib import Path

CACHE = Path("stock_data")

BUNDLE_COLUMNS = [
    "Code", "Date", "Open", "High", "Low", "Close", "Volume", "Change",
]

frames = []

for file in sorted(CACHE.glob("*.csv")):
    # 종목 목록은 주가가 아니므로 제외
    if file.stem == "KOSPI_list":
        continue

    df = pd.read_csv(file, index_col="Date", parse_dates=["Date"]).sort_index()

    if df.empty:
        continue

    df = df.reset_index()

    # 파일 이름이 곧 종목코드
    df["Code"] = file.stem

    frames.append(df)

bundle = (
    pd.concat(frames, ignore_index=True)[BUNDLE_COLUMNS]
    .sort_values(["Code", "Date"])
    .reset_index(drop=True)
)

bundle.to_parquet("stock_data.parquet", compression="zstd", index=False)

# 종목 목록도 번들로
stocks = pd.read_csv(CACHE / "KOSPI_list.csv", dtype={"Code": str})
stocks["Code"] = (
    stocks["Code"].astype(str).str.replace(".0", "", regex=False).str.zfill(6)
)
stocks.to_parquet("kospi_list.parquet", compression="zstd", index=False)

print("종목 수   :", bundle["Code"].nunique())
print("총 행 수  :", f"{len(bundle):,}")
print("번들 크기 :", f"{Path('stock_data.parquet').stat().st_size / 1024 / 1024:.1f} MB")
```

- [ ] **Step 2: 노트북 셀이 실제로 도는지 확인한다**

```bash
cd work/_ko_stock
/Users/back/miniforge3/bin/python3 - <<'PYEOF'
import json
nb = json.load(open("01_stock_download.ipynb"))
cells = [c for c in nb["cells"] if "번들 만들기" in "".join(c["source"])]
assert len(cells) == 1, f"번들 셀이 {len(cells)}개입니다"
exec("".join(cells[0]["source"]))
PYEOF
```

Expected: 종목 수·행 수·번들 크기가 출력되고 오류가 없다

- [ ] **Step 3: Python 3.13 에서 전체 검증**

```bash
cd work/_ko_stock

# venv 가 없으면 Global Constraints 의 명령으로 먼저 만든다.
# pyarrow 를 requirements 에 추가했으므로 다시 설치한다.
/Users/back/.local/bin/uv pip install \
    --python tests/_scratch/venv313/bin/python -r requirements.txt

tests/_scratch/venv313/bin/python -c "import sys; print(sys.version.split()[0])"
tests/_scratch/venv313/bin/python tests/run_all.py
```

Expected: 파이썬 버전이 `3.13.x`, 그리고 `전체 11종 통과`

지난번 `koreanize-matplotlib` 사고가 이 단계에서 잡혔을 문제다. 로컬 파이썬에만 있는 패키지가 가려 주는 일을 막기 위해, **로컬이 아니라 이 깨끗한 venv 에서 통과해야 한다.**

- [ ] **Step 4: 저장소 효과를 측정해 기록한다**

```bash
cd "$(git rev-parse --show-toplevel)"
git rev-list --objects --all > /tmp/objs.txt
grep "stock_data/" /tmp/objs.txt | awk '{print $1}' | sort -u \
  | git cat-file --batch-check='%(objecttype) %(objectsize:disk)' \
  | awk '$1=="blob"{n++;s+=$2} END{printf "과거 CSV blob: %d개 %.1f MB (변하지 않음)\n", n, s/1024/1024}'
ls -la work/_ko_stock/stock_data.parquet work/_ko_stock/kospi_list.parquet
```

설계 문서 2절에 적힌 대로 과거 172.5MB 는 줄지 않는다. 앞으로의 갱신이 4.8MB 단위가 되는 것이 이번 작업의 성과다.

- [ ] **Step 5: 설계 문서에 완료 사실을 적는다**

`docs/2026-09-13-parquet-bundle-design.md` 끝에 다음을 추가한다.

아래 틀에 **실제 값을 채워서** 쓴다. 괄호 안내문을 그대로 남기지 않는다.

```markdown
## 11. 구현 결과

구현일: YYYY-MM-DD
구현 계획: `docs/2026-09-13-parquet-bundle-plan.md`

| 검증 항목 | 결과 |
|---|---|
| 1. 지표 동치 | 거래대금 6구간 전부 일치 / 불일치 |
| 2. 차트 동일성 | 3종목 바이트 동일 / 차이 있음 (사유 아래) |
| 3. 콜드 스타트 | 통과 / 실패 |
| 4. 지문 안정성 | 재실행 시 지문 유지 확인 / 실패 |
| 5. Python 3.13 | 통과 / 실패 |
| 6. 기존 회귀 | 11종 중 N종 통과 |

번들 크기: stock_data.parquet N.N MB, kospi_list.parquet N KB
전환 전 CSV: 835개 18.5 MB
```

2번이 "차이 있음"이면 원인과 판단 근거를 바로 아래 문단에 적는다.
기준을 낮춘 사실을 표에만 남기고 넘어가지 않는다.

- [ ] **Step 6: 커밋**

```bash
git add work/_ko_stock/01_stock_download.ipynb work/_ko_stock/docs
git commit -m "$(cat <<'EOF'
노트북에 번들 만들기 셀 추가, 설계 문서에 결과 기록

학생은 지금처럼 CSV 를 받아 엑셀로 열어보고,
마지막에 번들을 만들어 앱에 넘긴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7YfGm9WqxeMKj7jS8314p
EOF
)"
```

---

## 실행 순서와 되돌리기

Task 1 → 8 을 순서대로 진행한다. Task 3 이후 Task 6 까지는 `test_apptest.py` 가 실패할 수 있으며, Task 6 끝에서 초록이 되어야 한다. 그 밖의 시점에 테스트가 빨간 채로 다음 Task 로 넘어가지 않는다.

되돌려야 하면 설계 문서 10절을 따른다. CSV 는 로컬에 그대로 남아 있으므로 데이터 손실 없이 복구할 수 있다.
