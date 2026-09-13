"""테스트가 공유하는 경로 상수와 도우미."""

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


def has_real_csv():
    """예전 방식의 CSV 가 로컬에 남아 있는지."""

    if not DATA_FOLDER.exists():
        return False

    return any(DATA_FOLDER.glob("[0-9]*.csv"))


def csv_source():
    """
    비교 기준으로 쓸 CSV 폴더를 돌려준다.

    stock_data/ 는 이제 git 추적 대상이 아니라서
    새로 clone 한 환경에는 존재하지 않는다.
    그럴 때는 번들에서 CSV 를 만들어 낸다.

    덕분에 어느 환경에서든 검증을 건너뛰지 않는다.
    """

    if has_real_csv():
        return DATA_FOLDER

    import pandas as pd

    out = SCRATCH / "csv_from_bundle"

    # 이미 만들어 두었으면 다시 만들지 않는다
    if out.exists() and any(out.glob("[0-9]*.csv")):
        return out

    out.mkdir(parents=True, exist_ok=True)

    bundle = pd.read_parquet(BUNDLE_FILE)

    for code, part in bundle.groupby("Code", observed=True):
        (part.drop(columns="Code")
             .set_index("Date")
             .sort_index()
             .to_csv(out / f"{code}.csv", index_label="Date"))

    # KOSPI 지수
    (pd.read_parquet(INDEX_FILE)
       .set_index("Date")
       .sort_index()
       .to_csv(out / "KS11.csv", index_label="Date"))

    # 종목 목록
    pd.read_parquet(LIST_FILE).to_csv(out / "KOSPI_list.csv", index=False)

    return out
