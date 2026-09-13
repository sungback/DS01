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
