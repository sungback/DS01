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
