"# DS01

## 💻 개발 환경 구성하기

### 1. Miniconda 설치
- **다운로드**: [Miniconda 홈페이지](https://repo.anaconda.com/miniconda/)
- 운영체제별 설치 파일을 다운로드한 후, **Next** 와 **Yes** 를 클릭하여 설치를 진행합니다.

### 2. Miniconda 프롬프트 실행
- `시작` > `모든 앱` > `Anaconda (miniconda3)` > `Anaconda Prompt`

### 3. conda 업데이트
```bash
conda update -n base -c defaults conda
```

### 4. 기본 레포지토리 변경 (conda-forge)
```bash
conda config --add channels conda-forge
conda config --set channel_priority strict
```

### 5. 가상환경 생성 및 활성화
```bash
conda create -n ds python=3.11 -y
conda activate ds
```

### 6. 라이브러리 설치
```bash
conda install -c conda-forge numpy pandas scipy matplotlib seaborn plotly jupyter scikit-learn statsmodels openpyxl beautifulsoup4 lxml requests tqdm xgboost lightgbm optuna catboost
```

### 7. Visual Studio Code 설치
- **다운로드**: [VS Code 홈페이지](https://code.visualstudio.com/download)
- 운영체제별 설치 파일을 다운로드한 후, **Next** 와 **Yes** 를 클릭하여 설치를 진행합니다.


### 8. D2Coding 글꼴 설치

1. 구글이나 네이버에서 **D2Coding**을 검색하거나, [D2Coding GitHub 레포지토리](https://github.com/naver/d2codingfont)에 접속합니다.
2. `D2Coding-Ver1.3.2-20180524.zip` 파일을 클릭합니다.
3. 측면의 **Download raw file** (아래 화살표 아이콘)을 클릭하여 다운로드합니다.
4. 다운로드한 파일의 압축을 해제합니다.
5. 파일 탐색기를 통해 `D2Coding-Ver1.3.2-20180524\D2CodingAll` 폴더로 이동합니다.
6. `D2Coding-Ver1.3.2-20180524-all.ttc` 파일을 우클릭합니다.
7. **추가 옵션 표시** > **모든 사용자용으로 설치**를 클릭하여 설치를 완료합니다.
   - *Mac 사용자: 압축 해제 후 `D2Coding` 폴더 내의 `*.ttf` 파일들을 더블 클릭하여 서체를 설치합니다.*

### 9. 윈도우 명령 프롬프트 기능 향상 (Clink 설치)

명령 프롬프트(cmd)의 기능을 향상시켜 명령어 색상 강조 및 이전 명령어 불러오기 등의 편의 기능을 제공하는 Clink 설치 방법입니다.

1. **Windows PowerShell 실행**
   - 작업 표시줄의 돋보기(검색) 클릭 > `power` 검색 > **Windows PowerShell** 클릭
2. **Clink 설치**
   - PowerShell 창에 아래 명령어를 입력하여 설치를 완료합니다.
     ```powershell
     winget install clink
     ```
3. **명령 프롬프트(cmd) 확인**
   - 작업 표시줄의 돋보기(검색) 클릭 > `cmd` 검색 > **명령 프롬프트** 클릭
   - 명령어가 색깔별로 표시되며, 위쪽 화살표 키(`↑`)로 이전 명령어를 쉽게 불러올 수 있습니다.

### 10. Jupyter 설정하기 (글꼴 및 자동완성)

#### 1. 코드 자동완성 설정
- **Home** 탭 > **Settings** > **Settings Editor** 메뉴로 이동합니다.
- 좌측 메뉴에서 **Code Completion**을 클릭합니다.
- **Enable autocompletion** 항목을 체크(활성화)합니다.

#### 2. Jupyter 노트북 설정
- **Home** 탭 > **Settings** > **Settings Editor** 메뉴로 이동합니다.
- 좌측 메뉴에서 **Notebook**을 클릭합니다.
- 다음 항목들을 체크합니다:
  - **Auto Closing Brackets** 체크
  - **Code Folding** 체크
- 화면을 아래로 스크롤하여 폰트 관련 설정을 다음과 같이 변경합니다:
  - **Font Family**: `D2Coding`
  - **Font Size**: `22`
  - **Line Height**: `140`

---

## 🔗 유용한 사이트 링크

### 주요 플랫폼
- [인공지능 제조 플랫폼 (KAMP)](https://www.kamp-ai.kr/main)
- [Kaggle (캐글)](https://www.kaggle.com/)
- [Streamlit](https://streamlit.io/)

### Streamlit 학습 자료
- [wikidocs: 데이터 과학자의 쉬운 웹 제작 도구](https://wikidocs.net/226653)
- [블로그: Streamlit 설명이 잘된 블로그](https://blog.zarathu.com/posts/2023-02-01-streamlit/)
- [GitHub: Streamlit 튜토리얼](https://github.com/teddylee777/streamlit-tutorial)
- [YouTube: Streamlit 설명 영상](https://www.youtube.com/watch?v=F8a-0JFHfOo)

### 데이터 제공 사이트
- [공공데이터포털](https://www.data.go.kr/)
- [국가통계포털 (KOSIS)](https://kosis.kr/index/index.do)
- [서울열린데이터광장](https://data.seoul.go.kr/)
- [AI Hub](https://aihub.or.kr/)
- [Google Dataset Search](https://datasetsearch.research.google.com/)
- [한국은행 경제통계시스템](https://ecos.bok.or.kr)
- [UC Irvine Machine Learning Repository](https://archive.ics.uci.edu/)
- [OpenML](https://www.openml.org/)
- [EU Open Research Repository (Zenodo)](https://zenodo.org/)
- [Hugging Face Datasets](https://huggingface.co/datasets)
- [Registry of Open Data on AWS](https://registry.opendata.aws/)

---

## 🏭 Kaggle 제조 데이터 추천
- [Predictive Maintenance Dataset (AI4I 2020)](https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020)
- [Predictive Maintenance for Industrial Machines](https://www.kaggle.com/code/sayidmufaqih/predictive-maintenance-for-industrial-machines)
- [SECOM (Semiconductor Manufacturing) Dataset](https://www.kaggle.com/datasets/paresh2047/uci-semcom)
- [Faulty Steel Plates](https://www.kaggle.com/datasets/uciml/faulty-steel-plates)
- [Predicting Manufacturing Defects Dataset](https://www.kaggle.com/datasets/rabieelkharoua/predicting-manufacturing-defects-dataset)

---

## 🌐 Kaggle 번역 크롬 확장 프로그램 설치 및 사용법

### 1. 확장 프로그램 설치
1. [DS01 GitHub 레포지토리](https://github.com/sungback/DS01)에서 `kaggle-notebook-translation-helper-main.zip` 파일을 다운로드합니다.
2. 다운로드한 파일의 압축을 편한 위치에 해제합니다. (예: `문서\kaggle-notebook-translation-helper-main`)
3. 크롬 브라우저를 실행하고 다음 순서로 이동합니다:
   - 우측 상단의 세로로 된 `...` 클릭 > `확장 프로그램` > `확장 프로그램 관리`
   - 우측 상단의 **개발자 모드** 켜기 (ON)
   - 좌측 상단의 **[압축해제된 확장 프로그램을 로드합니다.]** 클릭
   - 압축을 해제한 폴더 내의 `src` 폴더를 선택 (예: `문서\kaggle-notebook-translation-helper-main\src`)
4. 설치가 완료되면 확장 프로그램 목록에 **Kaggle Notebook Translation Helper 1.4.0**이 표시됩니다.

### 2. 사용 방법 (Kaggle에서)
1. [Kaggle 홈페이지](https://www.kaggle.com/)에 접속합니다.
2. `Competitions` 메뉴 등을 클릭하여 코드를 보고 싶은 대회를 선택합니다. (예: `Getting Started`의 `Titanic`)
3. `Code` 탭을 클릭하고 원하는 노트북 코드를 선택합니다. (예: `Titanic competition w/ TensorFlow Decision Forests`)
4. 노트북 화면 **좌측 상단에 표시되는 [Display iframe]** 버튼을 클릭합니다.
5. 표시된 iframe 내부에서 마우스 우클릭 후 **한국어로 번역**을 선택하여 사용합니다.
