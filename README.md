"# DS01"

## 개발 환경 구성하기

### miniconda 다운로드, 운영체제별 설치 파일 다운로드 후 Next, yes 클릭하여 설치 진행
==> https://repo.anaconda.com/miniconda/

### miniconda 프롬프트 띄우기
- 시작 > 모두 > Anaconda (miniconda3) > Anaconda Prompt

### conda update
- conda update -n base -c defaults conda

### 기본 레포지토리를 conda-forge로 변경하기
- conda config --add channels conda-forge
- conda config --set channel_priority strict

### 가상환경 생성 명령
- conda create -n ds python=3.11 -y
- conda activate ds

### 라이브러리 설치
- conda install -c conda-forge numpy pandas scipy matplotlib seaborn plotly jupyter scikit-learn statsmodels openpyxl xlrd beautifulsoup4 lxml requests tqdm xgboost lightgbm optuna catboost

### Visual Studio Code 다운로드 주소, 운영체제별 설치 파일 다운로드 후 Next, yes 클릭하여 설치 진행
- https://code.visualstudio.com/download

### 인공지능 제조 플랫폼 주소
- https://www.kamp-ai.kr/main

### 캐글 주소
- https://www.kaggle.com/

### streamlit 주소
- https://streamlit.io/

### streamlit 공부1 : wikidocs, 데이터 과학자의 쉬운 웹 제작 도구
- https://wikidocs.net/226653

### streamlit 공부2 : 설명이 잘된 블로그 주소
- https://blog.zarathu.com/posts/2023-02-01-streamlit/

### streamlit 공부3 : 설명이 잘된 github tutorial
- https://github.com/teddylee777/streamlit-tutorial

### streamlit 공부4 : 설명이 잘된 youtube 영상
- https://www.youtube.com/watch?v=F8a-0JFHfOo

### 데이터 사이트 주소들

공공 데이터 포털
==> https://www.data.go.kr/

국가 통계 포털
==> https://kosis.kr/index/index.do

서울 열린 데이터 광장
==> https://data.seoul.go.kr/

AI hub
==> https://aihub.or.kr/

Google Dataset Search
==> https://datasetsearch.research.google.com/

한국은행 경제통계 시스템
==> https://ecos.bok.or.kr

UC Irvine Machine Learning Repository
==> https://archive.ics.uci.edu/

OpenML
==> https://www.openml.org/

EU Open Research Repository
==> https://zenodo.org/

huggingface datasets
==> https://huggingface.co/datasets

Registry of Open Data on AWS
==> https://registry.opendata.aws/


### kaggle 제조 데이터 추천

Predictive Maintenance Dataset (AI4I 2020)
==> https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020

Predictive Maintenance for Industrial Machines
==> https://www.kaggle.com/code/sayidmufaqih/predictive-maintenance-for-industrial-machines

SECOM (Semiconductor Manufacturing) Dataset
==> https://www.kaggle.com/datasets/paresh2047/uci-semcom

Faulty Steel Plates
https://www.kaggle.com/datasets/uciml/faulty-steel-plates

Predicting Manufacturing Defects Dataset
==> https://www.kaggle.com/datasets/rabieelkharoua/predicting-manufacturing-defects-dataset


### [ kaggle 번역 크롬 확장 프로그램 설치 및 사용법 ]
1. 크롬 확장 프로그램 설치
1-1. https://github.com/sungback/DS01 에서
   kaggle-notebook-translation-helper-main.zip 를 다운로드
1-2. 편한 위치에 압축 해제. 다운로드 폴더는 자주 삭제하니까 지워지지 않게 문서 폴더 선택하겠음.
   예 : 문서\kaggle-notebook-translation-helper-main
1-3. 크롬 확장 프로그램 설치 방법 : 
   크롬 실행 > 우측 상단의 세로로 된 "..." 클릭
   > 확장 프로그램 >  확장 프로그램 관리 > 개발자 모드 체크(on)
   > [압축 해제된 확장 프로그램 로드] 클릭 > 문서\kaggle-notebook-translation-helper-main 아래 src 선택
   > Kaggle Notebook Translation Helper 1.4.0 설치 완료.
2. 사용 방법
2-1. 캐글에서 사용하는 방법
   kaggle.com 접속 > 예 : competitions 클릭 > 스크롤 > Getting Started 의 Titanic 클릭
   > Code 클릭 > 예를 들어 두번째인 "Titanic competition w/ TensorFlow Decision Forests" 클릭
   > 좌측 상단에 [Display iframe] 클릭 > 우클릭 > 한국어로 번역
=======
"# DS01"

## 개발 환경 구성하기

### miniconda 다운로드, 운영체제별 설치 파일 다운로드 후 Next, yes 클릭하여 설치 진행
==> https://repo.anaconda.com/miniconda/

### miniconda 프롬프트 띄우기
- 시작 > 모두 > Anaconda (miniconda3) > Anaconda Prompt

### conda update
- conda update -n base -c defaults conda

### 기본 레포지토리를 conda-forge로 변경하기
- conda config --add channels conda-forge
- conda config --set channel_priority strict

### 가상환경 생성 명령
- conda create -n ds python=3.11 -y
- conda activate ds

### 라이브러리 설치
- conda install -c conda-forge numpy pandas scipy matplotlib seaborn plotly jupyter scikit-learn statsmodels openpyxl xlrd beautifulsoup4 lxml requests tqdm xgboost lightgbm optuna catboost

### Visual Studio Code 다운로드 주소, 운영체제별 설치 파일 다운로드 후 Next, yes 클릭하여 설치 진행
- https://code.visualstudio.com/download

### 인공지능 제조 플랫폼 주소
- https://www.kamp-ai.kr/main

### 캐글 주소
- https://www.kaggle.com/

### streamlit 주소
- https://streamlit.io/

### streamlit 공부1 : wikidocs, 데이터 과학자의 쉬운 웹 제작 도구
- https://wikidocs.net/226653

### streamlit 공부2 : 설명이 잘된 블로그 주소
- https://blog.zarathu.com/posts/2023-02-01-streamlit/

### streamlit 공부3 : 설명이 잘된 github tutorial
- https://github.com/teddylee777/streamlit-tutorial

### streamlit 공부4 : 설명이 잘된 youtube 영상
- https://www.youtube.com/watch?v=F8a-0JFHfOo

### 데이터 사이트 주소들

공공 데이터 포털
==> https://www.data.go.kr/

국가 통계 포털
==> https://kosis.kr/index/index.do

서울 열린 데이터 광장
==> https://data.seoul.go.kr/

AI hub
==> https://aihub.or.kr/

Google Dataset Search
==> https://datasetsearch.research.google.com/

한국은행 경제통계 시스템
==> https://ecos.bok.or.kr

UC Irvine Machine Learning Repository
==> https://archive.ics.uci.edu/

OpenML
==> https://www.openml.org/

EU Open Research Repository
==> https://zenodo.org/

huggingface datasets
==> https://huggingface.co/datasets

Registry of Open Data on AWS
==> https://registry.opendata.aws/


### kaggle 제조 데이터 추천

Predictive Maintenance Dataset (AI4I 2020)
==> https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020

Predictive Maintenance for Industrial Machines
==> https://www.kaggle.com/code/sayidmufaqih/predictive-maintenance-for-industrial-machines

SECOM (Semiconductor Manufacturing) Dataset
==> https://www.kaggle.com/datasets/paresh2047/uci-semcom

Faulty Steel Plates
https://www.kaggle.com/datasets/uciml/faulty-steel-plates

Predicting Manufacturing Defects Dataset
==> https://www.kaggle.com/datasets/rabieelkharoua/predicting-manufacturing-defects-dataset


### [ kaggle 번역 크롬 확장 프로그램 설치 및 사용법 ]
1. 크롬 확장 프로그램 설치
1-1. https://github.com/sungback/DS01 에서
   kaggle-notebook-translation-helper-main.zip 를 다운로드
1-2. 편한 위치에 압축 해제. 다운로드 폴더는 자주 삭제하니까 지워지지 않게 문서 폴더 선택하겠음.
   예 : 문서\kaggle-notebook-translation-helper-main
1-3. 크롬 확장 프로그램 설치 방법 : 
   크롬 실행 > 우측 상단의 세로로 된 "..." 클릭
   > 확장 프로그램 >  확장 프로그램 관리 > 개발자 모드 체크(on)
   > [압축 해제된 확장 프로그램 로드] 클릭 > 문서\kaggle-notebook-translation-helper-main 아래 src 선택
   > Kaggle Notebook Translation Helper 1.4.0 설치 완료.
2. 사용 방법
2-1. 캐글에서 사용하는 방법
   kaggle.com 접속 > 예 : competitions 클릭 > 스크롤 > Getting Started 의 Titanic 클릭
   > Code 클릭 > 예를 들어 두번째인 "Titanic competition w/ TensorFlow Decision Forests" 클릭
   > 좌측 상단에 [Display iframe] 클릭 > 우클릭 > 한국어로 번역
