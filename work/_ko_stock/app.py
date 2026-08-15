# ============================================================
# app.py
# KOSPI 상승추세 종목 분석 Streamlit
# ============================================================

import logging
logging.getLogger(
    'matplotlib.font_manager'
).setLevel(logging.ERROR)

from pathlib import Path
from threading import RLock
import platform

import numpy as np
import pandas as pd

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import mplfinance as mpf

import streamlit as st


# ============================================================
# 1. Streamlit 기본 설정
# ============================================================

st.set_page_config(
    page_title='KOSPI 추세 투자',
    page_icon='📈',
    layout='wide'
)

st.title('📈 KOSPI 추세 투자 분석')


# ============================================================
# 2. 기본 설정
# ============================================================

CACHE = Path('stock_cache')

# 실제 매수 후 직접 기록
BUY_PRICE = {
    # '021240': 98200,
}

BUY_STOP = {
    # '021240': 92100,
}


# ============================================================
# 3. 종목 유형
#
# 중요:
# 데이터에 특정 유형이 존재하는지와 관계없이
# 사이드바에는 항상 아래 메뉴가 표시됩니다.
# ============================================================

TYPE_ORDER = [
    '균형형',
    '강한추세',
    '급등주의',
    '과열주의',
    '저과열',
    '일반'
]

TYPE_OPTIONS = [
    '전체',
    '균형형',
    '강한추세',
    '급등주의',
    '과열주의',
    '저과열',
    '일반'
]


# ============================================================
# 4. 한글 폰트
# ============================================================

os_name = platform.system()

if os_name == 'Windows':
    font = 'Malgun Gothic'

elif os_name == 'Darwin':
    font = 'AppleGothic'

else:
    font = 'NanumGothic'


available_fonts = {
    f.name
    for f in fm.fontManager.ttflist
}

if font not in available_fonts:
    font = 'DejaVu Sans'


plt.rcParams.update({
    'font.family': font,
    'figure.titleweight': 'normal',
    'axes.unicode_minus': False
})


# Matplotlib 멀티스레드 충돌 방지
PLOT_LOCK = RLock()


# ============================================================
# 5. 사이드바
# ============================================================

with st.sidebar:

    st.header('분석 설정')

    # --------------------------------------------------------
    # 중요
    #
    # result['유형'].unique() 사용 금지
    # TYPE_OPTIONS 고정 목록 사용
    # --------------------------------------------------------

    opt = st.selectbox(
        '종목 유형',
        options=TYPE_OPTIONS,
        index=0,
        key='stock_type_select_v10'
    )

    TOP_N = st.slider(
        '전체 매수 후보 수',
        min_value=5,
        max_value=100,
        value=20,
        step=5
    )

    CHART_N = st.slider(
        '매매계획 / 차트 종목 수',
        min_value=1,
        max_value=30,
        value=10
    )

    min_value_eok = st.number_input(
        '최소 평균 거래대금(억원)',
        min_value=1,
        value=10,
        step=1
    )

    MIN_VALUE = (
        min_value_eok
        * 100_000_000
    )

    stop_percent = st.slider(
        '최대 손실률(%)',
        min_value=1,
        max_value=20,
        value=8
    )

    STOP_RATE = (
        stop_percent / 100
    )

    if st.button(
        '🔄 캐시 새로고침',
        width='stretch'
    ):

        st.cache_data.clear()

        st.rerun()


# ============================================================
# 6. 주가 CSV 읽기
# ============================================================

@st.cache_data(ttl=3600)
def read_price(path):

    df = pd.read_csv(
        path,
        index_col='Date',
        parse_dates=['Date']
    )

    return df


# ============================================================
# 7. 전체 KOSPI 종목 분석
# ============================================================

@st.cache_data(ttl=3600)
def analyze_stocks(
    cache_path,
    min_value
):

    cache_path = Path(
        cache_path
    )

    stocks = pd.read_csv(
        cache_path
        / 'KOSPI_list.csv'
    )


    # --------------------------------------------------------
    # 종목 코드 컬럼
    # --------------------------------------------------------

    if 'Code' in stocks.columns:

        code_col = 'Code'

    elif 'Symbol' in stocks.columns:

        code_col = 'Symbol'

    else:

        raise ValueError(
            'KOSPI_list.csv에 '
            'Code 또는 Symbol 컬럼이 없습니다.'
        )


    # --------------------------------------------------------
    # 종목코드 6자리
    # --------------------------------------------------------

    stocks[code_col] = (
        stocks[code_col]
        .astype(str)
        .str.replace(
            '.0',
            '',
            regex=False
        )
        .str.zfill(6)
    )


    # --------------------------------------------------------
    # 우선주 제외
    # --------------------------------------------------------

    stocks = stocks[
        ~stocks['Name']
        .str.contains(
            r'\d*우[A-Z]?$',
            regex=True,
            na=False
        )
    ].copy()


    rows = []
    errors = []


    # --------------------------------------------------------
    # 종목별 분석
    # --------------------------------------------------------

    for _, stock in stocks.iterrows():

        code = stock[code_col]

        name = stock['Name']

        stock_file = (
            cache_path
            / f'{code}.csv'
        )


        # 파일 없는 종목 제외
        if not stock_file.exists():
            continue


        try:

            df = pd.read_csv(
                stock_file,
                index_col='Date',
                parse_dates=['Date']
            )


            # ------------------------------------------------
            # 필수 컬럼
            # ------------------------------------------------

            required_cols = {
                'Close',
                'Volume'
            }

            if not required_cols.issubset(
                df.columns
            ):
                continue


            # ------------------------------------------------
            # 숫자 변환
            # ------------------------------------------------

            temp = pd.DataFrame(
                {
                    'Close':
                        pd.to_numeric(
                            df['Close'],
                            errors='coerce'
                        ),

                    'Volume':
                        pd.to_numeric(
                            df['Volume'],
                            errors='coerce'
                        )
                }
            ).dropna()


            # 최소 130 거래일
            if len(temp) < 130:
                continue


            c = temp['Close']

            volume = temp['Volume']


            # ------------------------------------------------
            # 이동평균선
            # ------------------------------------------------

            ma20 = (
                c
                .rolling(20)
                .mean()
            )

            ma60 = (
                c
                .rolling(60)
                .mean()
            )

            ma120 = (
                c
                .rolling(120)
                .mean()
            )


            # ------------------------------------------------
            # NaN 확인
            # ------------------------------------------------

            if (
                pd.isna(
                    ma20.iloc[-1]
                )
                or
                pd.isna(
                    ma60.iloc[-1]
                )
                or
                pd.isna(
                    ma120.iloc[-1]
                )
            ):
                continue


            # ------------------------------------------------
            # 정배열
            #
            # 현재가 > MA20 > MA60 > MA120
            # ------------------------------------------------

            trend = (
                c.iloc[-1]
                > ma20.iloc[-1]
                > ma60.iloc[-1]
                > ma120.iloc[-1]
            )


            # ------------------------------------------------
            # MA20 / 60 / 120 모두 상승
            # ------------------------------------------------

            rising = (

                ma20.iloc[-1]
                > ma20.iloc[-6]

                and

                ma60.iloc[-1]
                > ma60.iloc[-6]

                and

                ma120.iloc[-1]
                > ma120.iloc[-6]
            )


            if not (
                trend
                and rising
            ):
                continue


            # ------------------------------------------------
            # 수익률
            # ------------------------------------------------

            ret = (
                c
                .pct_change()
            )


            # 최근 20일 수익률
            r20 = (
                c.iloc[-1]
                / c.iloc[-21]
                - 1
            )


            # 6개월 - 최근 1개월 모멘텀
            momentum = (
                c.iloc[-22]
                / c.iloc[-126]
                - 1
            )


            # MA20 이격도
            distance = (
                c.iloc[-1]
                / ma20.iloc[-1]
                - 1
            )


            # 최근 20일 평균 거래대금
            value = (
                c
                * volume
            ).tail(
                20
            ).mean()


            # 최근 20일 변동성
            volatility = (
                ret
                .tail(20)
                .std()
            )


            # 최근 5일 최대 하루 상승률
            max_up = (
                ret
                .tail(5)
                .max()
            )


            # ------------------------------------------------
            # 기본 필터
            # ------------------------------------------------

            condition = (

                value
                >= min_value

                and

                momentum
                > 0

                and

                r20
                <= 0.30

                and

                distance
                <= 0.15

                and

                max_up
                <= 0.20
            )


            if not condition:
                continue


            # ------------------------------------------------
            # 결과 저장
            # ------------------------------------------------

            rows.append(
                [
                    code,
                    name,

                    c.iloc[-1],

                    ma20.iloc[-1],
                    ma60.iloc[-1],
                    ma120.iloc[-1],

                    r20,
                    momentum,
                    distance,

                    value,
                    volatility
                ]
            )


        except Exception as e:

            errors.append(
                f'{code} {name}: {e}'
            )


    columns = [
        'Code',
        'Name',

        'Close',

        'MA20',
        'MA60',
        'MA120',

        'Return20',
        'Momentum',
        'Distance',

        'Value',
        'Volatility'
    ]


    result = pd.DataFrame(
        rows,
        columns=columns
    )


    return result, errors


# ============================================================
# 8. 매수점수 + 유형 분류
# ============================================================

def add_scores_and_types(
    result
):

    result = (
        result
        .copy()
    )


    # --------------------------------------------------------
    # 매수 점수
    # --------------------------------------------------------

    # 모멘텀 40점
    result['모멘텀점수'] = (
        result['Momentum']
        .rank(
            pct=True
        )
        * 40
    )


    # 이격도 30점
    # MA20 +5% 근처가 최고점
    result['이격점수'] = (

        30
        * (
            1
            - abs(
                result['Distance']
                - 0.05
            )
            / 0.10
        )

    ).clip(
        0,
        30
    )


    # 유동성 15점
    result['유동성점수'] = (
        result['Value']
        .rank(
            pct=True
        )
        * 15
    )


    # 안정성 15점
    result['안정성점수'] = (

        1
        - result[
            'Volatility'
        ].rank(
            pct=True
        )

    ) * 15


    # 총점
    result['BuyScore'] = (

        result['모멘텀점수']

        + result['이격점수']

        + result['유동성점수']

        + result['안정성점수']
    )


    result = (
        result
        .sort_values(
            'BuyScore',
            ascending=False
        )
        .reset_index(
            drop=True
        )
    )


    # --------------------------------------------------------
    # 유형 분류
    # --------------------------------------------------------

    m = (
        result['Momentum']
        * 100
    )

    r20 = (
        result['Return20']
        * 100
    )

    dist = (
        result['Distance']
        * 100
    )


    # --------------------------------------------------------
    # np.select는 위 조건이 우선
    #
    # 균형형과 저과열이 동시에 만족할 경우
    # 균형형을 우선합니다.
    # --------------------------------------------------------

    conditions = [

        # 강한추세
        m >= 80,

        # 급등주의
        r20 >= 20,

        # 과열주의
        dist >= 10,

        # 균형형
        (
            (m >= 15)
            &
            (m <= 50)
            &
            (r20 <= 5)
            &
            (dist <= 6)
        ),

        # 저과열
        dist <= 3
    ]


    result['유형'] = (
        np.select(
            conditions,

            [
                '강한추세',
                '급등주의',
                '과열주의',
                '균형형',
                '저과열'
            ],

            default='일반'
        )
    )


    # --------------------------------------------------------
    # 위험도
    # --------------------------------------------------------

    result['위험도'] = (
        result['유형']
        .map(
            {
                '강한추세': '높음',
                '급등주의': '높음',
                '과열주의': '높음',

                '균형형': '낮음',
                '저과열': '낮음',

                '일반': '보통'
            }
        )
    )


    # --------------------------------------------------------
    # 해석
    # --------------------------------------------------------

    result['해석'] = (
        result['유형']
        .map(
            {
                '강한추세':
                    '추세는 매우 강하지만 이미 많이 오른 종목',

                '급등주의':
                    '최근 급등하여 추격매수 주의',

                '과열주의':
                    '상승 추세지만 MA20에서 다소 멀어진 상태',

                '균형형':
                    '추세와 과열 정도의 균형이 좋은 종목',

                '저과열':
                    '과열은 적지만 상승 힘을 더 확인할 종목',

                '일반':
                    '무난한 상승 추세 종목'
            }
        )
    )


    # --------------------------------------------------------
    # 표시용 단위
    # --------------------------------------------------------

    result['20일(%)'] = (
        result['Return20']
        * 100
    )

    result['6-1M(%)'] = (
        result['Momentum']
        * 100
    )

    result['MA20이격(%)'] = (
        result['Distance']
        * 100
    )

    result['거래대금(억)'] = (
        result['Value']
        / 100_000_000
    )


    return result


# ============================================================
# 9. 차트 종목 선택
#
# "전체" 선택 시
# 존재하는 모든 유형을 최소 1개씩 포함
# ============================================================

def select_chart_stocks(
    selected,
    opt,
    chart_n
):

    selected = (
        selected
        .sort_values(
            'BuyScore',
            ascending=False
        )
        .copy()
    )


    # --------------------------------------------------------
    # 특정 유형
    # --------------------------------------------------------

    if opt != '전체':

        return (
            selected
            .head(
                chart_n
            )
            .reset_index(
                drop=True
            )
        )


    # --------------------------------------------------------
    # 전체
    #
    # 각 유형에서 최고점 종목 1개 먼저 선택
    # --------------------------------------------------------

    representatives = []


    for stock_type in TYPE_ORDER:

        temp = (
            selected[
                selected['유형']
                == stock_type
            ]
            .head(1)
        )


        if not temp.empty:

            representatives.append(
                temp
            )


    # 방어 코드
    if not representatives:

        return (
            selected
            .head(
                chart_n
            )
            .reset_index(
                drop=True
            )
        )


    first_stocks = (
        pd.concat(
            representatives,
            ignore_index=True
        )
    )


    # --------------------------------------------------------
    # CHART_N이 유형 수보다 작으면
    # 모든 유형을 보여주기 위해 자동 증가
    # --------------------------------------------------------

    target_count = max(
        chart_n,
        len(
            first_stocks
        )
    )


    first_codes = set(
        first_stocks[
            'Code'
        ]
    )


    # --------------------------------------------------------
    # 이미 뽑은 대표 종목 제거
    # --------------------------------------------------------

    remaining = (
        selected[
            ~selected['Code']
            .isin(
                first_codes
            )
        ]
    )


    remain_count = (
        target_count
        - len(
            first_stocks
        )
    )


    # --------------------------------------------------------
    # 각 유형 대표주 + 남은 BuyScore 상위
    # --------------------------------------------------------

    chart_selected = (
        pd.concat(
            [
                first_stocks,

                remaining.head(
                    remain_count
                )
            ],

            ignore_index=True
        )
    )


    # --------------------------------------------------------
    # 최종 점수순 정렬
    # --------------------------------------------------------

    chart_selected = (
        chart_selected
        .sort_values(
            'BuyScore',
            ascending=False
        )
        .reset_index(
            drop=True
        )
    )


    return chart_selected


# ============================================================
# 10. 필수 파일 검사
# ============================================================

if not CACHE.exists():

    st.error(
        'stock_cache 폴더를 찾을 수 없습니다.'
    )

    st.stop()


KOSPI_FILE = (
    CACHE
    / 'KS11.csv'
)

LIST_FILE = (
    CACHE
    / 'KOSPI_list.csv'
)


if not KOSPI_FILE.exists():

    st.error(
        'stock_cache/KS11.csv 파일이 없습니다.'
    )

    st.stop()


if not LIST_FILE.exists():

    st.error(
        'stock_cache/KOSPI_list.csv 파일이 없습니다.'
    )

    st.stop()


# ============================================================
# 11. KOSPI 시장 상태
# ============================================================

kospi = read_price(
    str(
        KOSPI_FILE
    )
)


kospi_close = (
    pd.to_numeric(
        kospi['Close'],
        errors='coerce'
    )
    .dropna()
)


if len(
    kospi_close
) < 200:

    st.error(
        'KS11.csv의 데이터가 '
        '200일 미만입니다.'
    )

    st.stop()


kospi_now = (
    kospi_close
    .iloc[-1]
)


ma200 = (
    kospi_close
    .rolling(200)
    .mean()
    .iloc[-1]
)


market_up = (
    kospi_now
    > ma200
)


market_date = (
    kospi_close
    .index[-1]
    .date()
)


# ============================================================
# 12. 시장 상태 출력
# ============================================================

st.subheader(
    '시장 상태'
)


col1, col2, col3, col4 = (
    st.columns(4)
)


col1.metric(
    '데이터 기준일',
    str(
        market_date
    )
)


col2.metric(
    'KOSPI',
    f'{kospi_now:,.2f}'
)


col3.metric(
    'MA200',
    f'{ma200:,.2f}'
)


col4.metric(
    '시장 상태',
    (
        '상승장'
        if market_up
        else '하락장'
    )
)


if not market_up:

    st.warning(
        '현재 KOSPI가 MA200 아래입니다. '
        '신규 매수는 보수적으로 접근하는 것이 좋습니다.'
    )


# ============================================================
# 13. 전체 종목 분석
# ============================================================

with st.spinner(
    'KOSPI 종목 분석 중...'
):

    result, errors = (
        analyze_stocks(
            str(CACHE),
            MIN_VALUE
        )
    )


if result.empty:

    st.warning(
        '조건을 만족하는 종목이 없습니다.'
    )

    st.stop()


# ============================================================
# 14. 점수 / 유형 추가
# ============================================================

result = (
    add_scores_and_types(
        result
    )
)


# ============================================================
# 15. 표시 컬럼
# ============================================================

SHOW_COLS = [
    'Code',
    'Name',
    'Close',

    'BuyScore',

    '20일(%)',
    '6-1M(%)',
    'MA20이격(%)',

    '거래대금(억)',

    '유형',
    '위험도',
    '해석'
]


# ============================================================
# 16. 전체 매수 후보
# ============================================================

st.divider()


if market_up:

    st.subheader(
        f'매수 후보 TOP {TOP_N}'
    )

else:

    st.subheader(
        f'관심 종목 TOP {TOP_N}'
    )


st.dataframe(
    result[
        SHOW_COLS
    ]
    .head(
        TOP_N
    )
    .round(2),

    hide_index=True,

    width='stretch'
)


# ============================================================
# 17. 유형별 종목 수
# ============================================================

st.subheader(
    '유형별 종목 수'
)


type_count = (
    result['유형']
    .value_counts()
    .reindex(
        TYPE_ORDER,
        fill_value=0
    )
)


type_cols = (
    st.columns(
        len(TYPE_ORDER)
    )
)


for col, stock_type in zip(
    type_cols,
    TYPE_ORDER
):

    col.metric(
        stock_type,
        f'{int(type_count[stock_type])}개'
    )


# ============================================================
# 18. 균형형 확인
# ============================================================

balanced_count = int(
    type_count[
        '균형형'
    ]
)


if balanced_count == 0:

    st.warning(
        '현재 조건에서는 균형형 종목이 0개입니다. '
        '사이드바의 균형형 메뉴는 계속 표시됩니다.'
    )


# ============================================================
# 19. 선택한 유형 필터
# ============================================================

st.divider()


if opt == '전체':

    # 전체 종목
    selected = (
        result
        .copy()
    )

else:

    # 선택 유형만
    selected = (
        result[
            result['유형']
            == opt
        ]
        .copy()
    )


# ============================================================
# 20. 선택 유형 제목
# ============================================================

st.subheader(
    f'{opt} 종목 : '
    f'{len(selected)}개'
)


if selected.empty:

    st.info(
        f'{opt} 유형에 해당하는 '
        '종목이 없습니다.'
    )

    st.stop()


# ============================================================
# 21. 선택한 유형 전체 표
#
# 전체 선택 시 유형별로 묶어서 출력
# ============================================================

if opt == '전체':

    type_order_map = {
        name: index
        for index, name
        in enumerate(
            TYPE_ORDER
        )
    }


    selected_view = (
        selected
        .assign(
            유형순서=
                selected[
                    '유형'
                ].map(
                    type_order_map
                )
        )
        .sort_values(
            [
                '유형순서',
                'BuyScore'
            ],

            ascending=[
                True,
                False
            ]
        )
    )

else:

    selected_view = (
        selected
        .sort_values(
            'BuyScore',
            ascending=False
        )
    )


st.dataframe(
    selected_view[
        SHOW_COLS
    ]
    .round(2),

    hide_index=True,

    width='stretch'
)


# ============================================================
# 22. 매매계획 / 차트 대상 선정
# ============================================================

chart_selected = (
    select_chart_stocks(
        selected,
        opt,
        CHART_N
    )
)


# ============================================================
# 23. 차트 대상 확인
# ============================================================

st.subheader(
    '매매계획 / 차트 대상 '
    f': {len(chart_selected)}개'
)


CHART_SUMMARY_COLS = [
    'Code',
    'Name',

    'BuyScore',

    '20일(%)',
    '6-1M(%)',
    'MA20이격(%)',

    '유형',
    '위험도'
]


st.dataframe(
    chart_selected[
        CHART_SUMMARY_COLS
    ]
    .round(2),

    hide_index=True,

    width='stretch'
)


# ============================================================
# 24. 전체 선택 시 유형 누락 검사
# ============================================================

if opt == '전체':

    included_count = (
        chart_selected[
            '유형'
        ]
        .value_counts()
        .reindex(
            TYPE_ORDER,
            fill_value=0
        )
    )


    st.caption(
        '매매계획 / 차트 유형 구성'
    )


    included_cols = (
        st.columns(
            len(TYPE_ORDER)
        )
    )


    for col, stock_type in zip(
        included_cols,
        TYPE_ORDER
    ):

        col.metric(
            stock_type,
            f'{int(included_count[stock_type])}개'
        )


    # --------------------------------------------------------
    # 실제 결과에는 존재하는데
    # chart_selected에 빠진 유형 검사
    # --------------------------------------------------------

    missing_types = [

        stock_type

        for stock_type
        in TYPE_ORDER

        if (
            type_count[
                stock_type
            ] > 0

            and

            included_count[
                stock_type
            ] == 0
        )
    ]


    if missing_types:

        st.error(
            '차트 대상에서 누락된 유형: '
            + ', '.join(
                missing_types
            )
        )

    else:

        st.success(
            '존재하는 모든 유형이 '
            '매매계획/차트에 포함되었습니다.'
        )


# ============================================================
# 25. 매수가
# ============================================================

chart_selected[
    '매수가'
] = (
    chart_selected[
        'Code'
    ]
    .map(
        BUY_PRICE
    )
    .fillna(
        chart_selected[
            'Close'
        ]
    )
)


# ============================================================
# 26. 자동 손절가
#
# MA60
# 또는
# 매수가 - 최대손실률
#
# 두 가격 중 높은 가격 사용
# ============================================================

auto_stop = (
    pd.concat(
        [
            chart_selected[
                'MA60'
            ],

            chart_selected[
                '매수가'
            ]
            * (
                1
                - STOP_RATE
            )
        ],

        axis=1
    )
    .max(
        axis=1
    )
)


# ============================================================
# 27. 직접 입력 손절가 적용
# ============================================================

chart_selected[
    '손절가'
] = (
    chart_selected[
        'Code'
    ]
    .map(
        BUY_STOP
    )
    .fillna(
        auto_stop
    )
)


# ============================================================
# 28. R 계산
# ============================================================

chart_selected[
    'R'
] = (
    chart_selected[
        '매수가'
    ]
    -
    chart_selected[
        '손절가'
    ]
)


chart_selected[
    '1R(30%매도)'
] = (
    chart_selected[
        '매수가'
    ]
    +
    chart_selected[
        'R'
    ]
)


chart_selected[
    '2R(30%매도)'
] = (
    chart_selected[
        '매수가'
    ]
    +
    chart_selected[
        'R'
    ]
    * 2
)


# ============================================================
# 29. 현재 단계 / 매도 신호
# ============================================================

price = (
    chart_selected[
        'Close'
    ]
)


sell_conditions = [

    # 1. 손절가 이하
    price
    <= chart_selected[
        '손절가'
    ],

    # 2. MA60 이탈
    price
    < chart_selected[
        'MA60'
    ],

    # 3. MA20 이탈
    price
    < chart_selected[
        'MA20'
    ],

    # 4. 2R 이상
    price
    >= chart_selected[
        '2R(30%매도)'
    ],

    # 5. 1R 이상
    price
    >= chart_selected[
        '1R(30%매도)'
    ]
]


chart_selected[
    '현재단계'
] = np.select(

    sell_conditions,

    [
        '손절 구간',
        '추세 이탈',
        'MA20 이탈',
        '2R 이상',
        '1R 이상'
    ],

    default='1R 전'
)


chart_selected[
    '매도신호'
] = np.select(

    sell_conditions,

    [
        '전량 손절',
        '매도',
        '주의',
        '30% 매도 → 남은 40% MA20 추적',
        '30% 매도'
    ],

    default='보유'
)


# ============================================================
# 30. 매매 계획
# ============================================================

st.subheader(
    f'{opt} 매매 계획'
)


PLAN_COLS = [
    'Code',
    'Name',

    '유형',

    'Close',

    'MA20',
    'MA60',

    '매수가',
    '손절가',

    '1R(30%매도)',
    '2R(30%매도)',

    '현재단계',
    '매도신호'
]


st.dataframe(
    chart_selected[
        PLAN_COLS
    ]
    .round(0),

    hide_index=True,

    width='stretch'
)


# ============================================================
# 31. mplfinance 스타일
# ============================================================

market_colors = (
    mpf.make_marketcolors(
        up='red',
        down='blue',
        inherit=True
    )
)


chart_style = (
    mpf.make_mpf_style(

        base_mpf_style='yahoo',

        marketcolors=
            market_colors,

        rc={
            'font.family':
                font,

            'figure.titleweight':
                'normal'
        }
    )
)


# ============================================================
# 32. 캔들 차트
# ============================================================

st.divider()

st.subheader(
    '캔들 차트'
)


for _, row in (
    chart_selected
    .iterrows()
):

    code = (
        row['Code']
    )

    name = (
        row['Name']
    )

    stock_file = (
        CACHE
        / f'{code}.csv'
    )


    if not stock_file.exists():

        st.warning(
            f'{code} {name}: '
            'CSV 파일이 없습니다.'
        )

        continue


    try:

        df = read_price(
            str(
                stock_file
            )
        )


        # ----------------------------------------------------
        # mplfinance 필수 컬럼 검사
        # ----------------------------------------------------

        required_chart_cols = {
            'Open',
            'High',
            'Low',
            'Close'
        }


        if not required_chart_cols.issubset(
            df.columns
        ):

            st.warning(
                f'{code} {name}: '
                'Open/High/Low/Close 컬럼이 부족합니다.'
            )

            continue


        # ----------------------------------------------------
        # 숫자 변환
        # ----------------------------------------------------

        chart_df = (
            df.copy()
        )


        numeric_cols = [
            'Open',
            'High',
            'Low',
            'Close',
            'Volume'
        ]


        for column in numeric_cols:

            if column in (
                chart_df.columns
            ):

                chart_df[column] = (
                    pd.to_numeric(
                        chart_df[column],
                        errors='coerce'
                    )
                )


        chart_df = (
            chart_df
            .dropna(
                subset=[
                    'Open',
                    'High',
                    'Low',
                    'Close'
                ]
            )
        )


        if chart_df.empty:

            continue


        # ----------------------------------------------------
        # 종목 제목
        # ----------------------------------------------------

        st.markdown(
            f"### {name} ({code})"
        )


        # ----------------------------------------------------
        # 주요 정보
        # ----------------------------------------------------

        c1, c2, c3, c4 = (
            st.columns(4)
        )


        c1.metric(
            '현재가',
            f"{row['Close']:,.0f}원"
        )


        c2.metric(
            'BuyScore',
            f"{row['BuyScore']:.1f}"
        )


        c3.metric(
            '유형',
            row['유형']
        )


        c4.metric(
            '위험도',
            row['위험도']
        )


        st.caption(
            row['해석']
        )


        title = (
            f"{name} | "
            f"{row['유형']} | "
            f"위험도 {row['위험도']} | "
            f"{row['해석']}"
        )


        # ----------------------------------------------------
        # 차트
        # ----------------------------------------------------

        with PLOT_LOCK:

            fig, axes = (
                mpf.plot(

                    chart_df.tail(
                        180
                    ),

                    type='candle',

                    mav=(
                        20,
                        60,
                        120
                    ),

                    volume=(
                        'Volume'
                        in chart_df.columns
                    ),

                    style=
                        chart_style,

                    figsize=(
                        13,
                        7
                    ),

                    title=
                        title,

                    returnfig=True
                )
            )


            st.pyplot(
                fig,
                width='stretch'
            )


            plt.close(
                fig
            )


    except Exception as e:

        st.error(
            f'{code} {name} '
            f'차트 오류: {e}'
        )


# ============================================================
# 33. 분석 오류
# ============================================================

if errors:

    with st.expander(
        f'종목 분석 오류 '
        f'{len(errors)}건'
    ):

        for error in errors:

            st.text(
                error
            )


# ============================================================
# 34. 완료
# ============================================================

st.divider()

st.caption(
    f'데이터 기준일: {market_date} | '
    f'분석 후보: {len(result)}개 | '
    f'현재 선택: {opt}'
)