import base64
import datetime
import html
import io
import os
import re
import sqlite3
import pandas as pd
import streamlit as st

# ---------------------------------------------------------
# 1. 디렉토리 및 DB 설정
# ---------------------------------------------------------
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

conn = sqlite3.connect("inventory.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1-1. items 테이블 생성 및 마이그레이션
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS items (
    item_code TEXT PRIMARY KEY,
    item_name TEXT NOT NULL
)
"""
)

item_cols = [
    ("item_detail_no", "TEXT"),
    ("model_spec", "TEXT"),
    ("category_type", "TEXT"),
    ("category_main", "TEXT"),
    ("category_sub", "TEXT"),
    ("shelf_no", "TEXT"),
    ("in_date", "TEXT"),
    ("zone", "TEXT"),
    ("device_name", "TEXT"),
    ("maker", "TEXT"),
    ("useful_life", "TEXT"),
    ("currency", "TEXT DEFAULT 'KRW'"),
    ("unit_price", "REAL DEFAULT 0"),
    ("remark", "TEXT"),
    ("initial_quantity", "INTEGER DEFAULT 0"),
    ("image_path", "TEXT"),
]
for col_name, col_type in item_cols:
    try:
        cursor.execute(f"ALTER TABLE items ADD COLUMN {col_name} {col_type}")
    except sqlite3.OperationalError:
        pass

# 1-2. transactions 테이블 생성 및 마이그레이션
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trans_date DATE DEFAULT CURRENT_DATE,
    type TEXT CHECK(type IN ('입고', '출고')),
    item_code TEXT
)
"""
)

trans_cols = [
    ("quantity", "INTEGER DEFAULT 0"),
    ("unit_price", "REAL DEFAULT 0"),
    ("currency", "TEXT DEFAULT 'KRW'"),
    ("total_price", "REAL DEFAULT 0"),
    ("manager", "TEXT"),
    ("requester", "TEXT"),
    ("remark", "TEXT"),
]
for col_name, col_type in trans_cols:
    try:
        cursor.execute(
            f"ALTER TABLE transactions ADD COLUMN {col_name} {col_type}"
        )
    except sqlite3.OperationalError:
        pass

# 1-3. 품목 수정 이력 테이블
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS item_edit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edit_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    item_code TEXT,
    editor TEXT,
    reason TEXT,
    details TEXT
)
"""
)

# 1-4. 사용자(로그인) 테이블 생성
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    emp_no TEXT PRIMARY KEY,
    password TEXT NOT NULL,
    name TEXT NOT NULL,
    position TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)

try:
    cursor.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT 'admin'")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass

cursor.execute(
    """
    INSERT OR IGNORE INTO users (emp_no, password, name, position, is_admin)
    VALUES ('admin', 'admin', '시스템관리자', '팀장', 1)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS exchange_rates (
    year INTEGER,
    currency TEXT,
    rate REAL,
    PRIMARY KEY (year, currency)
)
"""
)

default_rates = [
    (2023, "KRW", 1.0),
    (2023, "USD", 1300.0),
    (2023, "EUR", 1400.0),
    (2023, "JPY", 11.14),
    (2024, "KRW", 1.0),
    (2024, "USD", 1350.0),
    (2024, "EUR", 1450.0),
    (2024, "JPY", 9.0),
    (2025, "KRW", 1.0),
    (2025, "USD", 1380.0),
    (2025, "EUR", 1480.0),
    (2025, "JPY", 9.2),
    (2026, "KRW", 1.0),
    (2026, "USD", 1400.0),
    (2026, "EUR", 1500.0),
    (2026, "JPY", 9.5),
]
for y, c, r in default_rates:
    cursor.execute(
        "INSERT OR IGNORE INTO exchange_rates (year, currency, rate) VALUES (?, ?, ?)",
        (y, c, r),
    )

conn.commit()


# ---------------------------------------------------------
# 2. 헬퍼 함수
# ---------------------------------------------------------
POSITIONS = ["팀장", "부팀장", "마스터", "과장", "대리", "주임", "사원"]


def generate_next_item_code():
    cursor.execute("SELECT item_code FROM items WHERE item_code LIKE 'N4_%'")
    codes = cursor.fetchall()
    max_num = 0
    for row in codes:
        try:
            num_part = int(row["item_code"].split("_")[1])
            if num_part > max_num:
                max_num = num_part
        except (IndexError, ValueError, KeyError):
            continue
    return f"N4_{max_num + 1:04d}"


def parse_year_from_in_date(date_str):
    if not date_str or pd.isna(date_str):
        return None
    clean_str = str(date_str).strip()
    digits = re.findall(r"\d+", clean_str)
    if not digits:
        return None
    first_num = digits[0]
    if len(first_num) == 2:
        return 2000 + int(first_num)
    elif len(first_num) == 4:
        yr_sub = first_num[-2:]
        return 2000 + int(yr_sub)
    return None


def get_exchange_rate(currency, date_str=None):
    if currency == "KRW" or not currency:
        return 1.0, True

    parsed_year = parse_year_from_in_date(date_str)
    if parsed_year is None:
        cursor.execute(
            "SELECT rate FROM exchange_rates WHERE currency = ? ORDER BY year DESC LIMIT 1",
            (currency,),
        )
        row = cursor.fetchone()
        return (row["rate"] if row else 1.0), False

    cursor.execute(
        "SELECT rate FROM exchange_rates WHERE year = ? AND currency = ?",
        (parsed_year, currency),
    )
    row = cursor.fetchone()
    if row:
        return row["rate"], True

    cursor.execute(
        "SELECT rate FROM exchange_rates WHERE currency = ? ORDER BY year DESC LIMIT 1",
        (currency,),
    )
    row = cursor.fetchone()
    return (row["rate"] if row else 1.0), True


def safe_float(val, default=0.0):
    if pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    if pd.isna(val):
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_str(val, default=""):
    if pd.isna(val):
        return default
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def clean_category_type(val, default="-"):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return default
    try:
        f_val = float(s)
        if f_val.is_integer():
            return str(int(f_val))
    except (ValueError, TypeError):
        pass
    return s.replace('"', "")


def get_image_base64(image_path):
    if not image_path or pd.isna(image_path) or not isinstance(image_path, str):
        return None
    if os.path.exists(image_path):
        try:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            ext = image_path.split(".")[-1].lower()
            mime = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
            return f"data:{mime};base64,{encoded}"
        except Exception:
            return None
    return None


def clean_val(val, default="-"):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip().replace('"', "")
    return html.escape(s) if s and s.lower() != "nan" else default


def render_a4_spec_card(item_code):
    query_item = """
    SELECT 
        i.image_path AS image_path,
        i.item_code AS 품목코드,
        i.item_name AS 품명,
        i.item_detail_no AS 아이템상세번호,
        i.model_spec AS 모델번호_규격,
        i.category_type AS 구분,
        i.category_main AS 대분류,
        i.category_sub AS 소분류,
        i.shelf_no AS 선반번호,
        i.zone AS 해당구역,
        i.device_name AS 기기명,
        i.maker AS Maker,
        i.in_date AS 입고일,
        i.currency AS 입력화폐,
        i.unit_price AS 기초단가,
        COALESCE(i.initial_quantity, 0) AS 초기수량,
        COALESCE(i.initial_quantity, 0) + COALESCE(SUM(CASE WHEN t.type = '입고' THEN t.quantity ELSE 0 END), 0) - COALESCE(SUM(CASE WHEN t.type = '출고' THEN t.quantity ELSE 0 END), 0) AS 현재재고,
        i.remark AS 비고
    FROM items i
    LEFT JOIN transactions t ON i.item_code = t.item_code
    WHERE i.item_code = ?
    GROUP BY i.item_code
    """
    df_target = pd.read_sql_query(query_item, conn, params=[item_code])
    if df_target.empty:
        return

    item_data = df_target.iloc[0]

    # 가장 최근 입고 단가 조회 (없으면 기초단가 사용)
    cursor.execute(
        """
        SELECT unit_price, currency, trans_date FROM transactions 
        WHERE item_code = ? AND type = '입고' 
        ORDER BY trans_date DESC, id DESC LIMIT 1
    """,
        (item_code,),
    )
    latest_in = cursor.fetchone()

    if latest_in and latest_in["unit_price"] is not None:
        price = safe_float(latest_in["unit_price"])
        curr = latest_in["currency"] or item_data["입력화폐"]
        in_d = latest_in["trans_date"]
    else:
        price = safe_float(item_data["기초단가"])
        curr = item_data["입력화폐"]
        in_d = item_data["입고일"]

    stock = safe_int(item_data["현재재고"])

    rate, is_valid_date = get_exchange_rate(curr, in_d)
    unit_krw = int(price * rate)
    val_krw = int(unit_krw * stock)
    img_b64 = get_image_base64(item_data["image_path"])

    query_in = """
    SELECT trans_date AS 일자, quantity AS 입고수량, unit_price AS 단가, currency AS 화폐, manager AS 담당자, requester AS 요청자, remark AS 비고
    FROM transactions
    WHERE item_code = ? AND type = '입고'
    ORDER BY trans_date DESC, id DESC
    """
    df_in_trans = pd.read_sql_query(query_in, conn, params=[item_code])

    query_out = """
    SELECT trans_date AS 일자, quantity AS 출고수량, unit_price AS 단가, currency AS 화폐, manager AS 담당자, requester AS 요청자, remark AS 비고
    FROM transactions
    WHERE item_code = ? AND type = '출고'
    ORDER BY trans_date DESC, id DESC
    """
    df_out_trans = pd.read_sql_query(query_out, conn, params=[item_code])

    st.markdown(
        """
    <style>
    .a4-card {
        background-color: #ffffff;
        border: 2px solid #333333;
        border-radius: 8px;
        padding: 25px;
        margin-top: 10px;
        color: #111111;
        font-family: 'Malgun Gothic', sans-serif;
    }
    .a4-header {
        text-align: center;
        border-bottom: 3px double #333333;
        padding-bottom: 10px;
        margin-bottom: 20px;
    }
    .info-table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 15px;
    }
    .info-table th, .info-table td {
        border: 1px solid #cccccc;
        padding: 8px 12px;
        font-size: 14px;
    }
    .info-table th {
        background-color: #f4f4f4;
        font-weight: bold;
        width: 15%;
        text-align: center;
    }
    .info-table td {
        width: 35%;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    if curr == "KRW" or not curr:
        rate_info_str = f"{price:,.0f} KRW"
    else:
        if is_valid_date:
            rate_info_str = f"{price:,.2f} {curr} (환산: {unit_krw:,}원 | 적용환율: {rate:,.2f} 원/{curr})"
        else:
            rate_info_str = f"{price:,.2f} {curr} (환산: {unit_krw:,}원 | <span style='color:red; font-weight:bold;'>⚠️ 입고일 정보를 입력해 주세요</span>)"

    with st.container():
        st.markdown("<div class='a4-card'>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='a4-header'><h2>자 재 품 목 명 세 서</h2><p>발행일자: {datetime.date.today()}</p></div>",
            unsafe_allow_html=True,
        )

        col_img, col_info = st.columns([1, 3])

        with col_img:
            if img_b64:
                st.image(
                    img_b64,
                    caption=str(item_data["품명"]),
                    use_container_width=True,
                )
            else:
                st.info("등록된 사진 없음")

        with col_info:
            html_table = f"""
            <table class="info-table">
                <tr>
                    <th>품목코드</th>
                    <td><code>{clean_val(item_data['품목코드'])}</code></td>
                    <th>품명</th>
                    <td><b>{clean_val(item_data['품명'])}</b></td>
                </tr>
                <tr>
                    <th>상세번호</th>
                    <td>{clean_val(item_data['아이템상세번호'])}</td>
                    <th>규격/모델</th>
                    <td>{clean_val(item_data['모델번호_규격'])}</td>
                </tr>
                <tr>
                    <th>구분/대분류</th>
                    <td>{clean_category_type(item_data['구분'])} / {clean_val(item_data['대분류'])}</td>
                    <th>소분류/선반</th>
                    <td>{clean_val(item_data['소분류'])} / {clean_val(item_data['선반번호'])}</td>
                </tr>
                <tr>
                    <th>구역/기기명</th>
                    <td>{clean_val(item_data['해당구역'])} / {clean_val(item_data['기기명'])}</td>
                    <th>Maker</th>
                    <td>{clean_val(item_data['Maker'])}</td>
                </tr>
                <tr>
                    <th>단가</th>
                    <td>{rate_info_str}</td>
                    <th>입고일</th>
                    <td>{clean_val(item_data['입고일'])}</td>
                </tr>
                <tr>
                    <th>현재재고</th>
                    <td><b>{stock:,} 개</b></td>
                    <th>총 재고금액</th>
                    <td><b>{val_krw:,} 원</b></td>
                </tr>
                <tr>
                    <th>비고</th>
                    <td colspan="3">{clean_val(item_data['비고'])}</td>
                </tr>
            </table>
            """
            st.markdown(html_table, unsafe_allow_html=True)

        st.markdown("<hr style='border:1px solid #ddd;'>", unsafe_allow_html=True)
        st.markdown("### 📥 1. 입고 내역 (History)")
        if not df_in_trans.empty:
            st.dataframe(df_in_trans, use_container_width=True)
        else:
            st.caption("※ 등록된 추가 입고 내역이 없습니다.")

        st.markdown("### 📤 2. 출고 내역 (History)")
        if not df_out_trans.empty:
            st.dataframe(df_out_trans, use_container_width=True)
        else:
            st.caption("※ 등록된 출고 내역이 없습니다.")

        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------
# 3. 로그인 세션 및 UI 제어
# ---------------------------------------------------------
st.set_page_config(page_title="자동화erp - 자재 관리 시스템", layout="wide")

if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None

if st.session_state.logged_in_user is None:
    st.title("🔐 자동화erp - 사용자 로그인")
    st.markdown("사번(ID)과 비밀번호(PW)를 입력하여 접속해 주세요.")

    with st.form("login_form"):
        col1, col2 = st.columns(2)
        login_emp_no = col1.text_input("사번 (ID) (*필수)")
        login_pw = col2.text_input("비밀번호 (PW) (*필수)", type="password")

        submitted_login = st.form_submit_button("로그인")

        if submitted_login:
            emp = login_emp_no.strip()
            pw = login_pw.strip()
            if not emp or not pw:
                st.error("사번과 비밀번호를 모두 입력해 주세요.")
            else:
                cursor.execute(
                    "SELECT * FROM users WHERE emp_no = ? AND password = ?",
                    (emp, pw),
                )
                user_row = cursor.fetchone()

                if user_row:
                    st.session_state.logged_in_user = {
                        "emp_no": user_row["emp_no"],
                        "name": user_row["name"],
                        "position": user_row["position"],
                        "is_admin": user_row["is_admin"],
                    }
                    st.success(
                        f"환영합니다, {user_row['name']} {user_row['position']}님!"
                    )
                    st.rerun()
                else:
                    st.error(
                        "❌ 사번 또는 비밀번호가 일치하지 않거나 등록되지 않은 계정입니다."
                    )
    st.stop()

# ---------------------------------------------------------
# 4. 메인 ERP 시스템 (로그인 완료 상태)
# ---------------------------------------------------------
user = st.session_state.logged_in_user
st.title("📦 자동화erp - 자재 입출고 및 재고관리")

st.sidebar.markdown(f"👤 **접속 사용자:**")
st.sidebar.info(
    f"**{user['name']} {user['position']}**\n\n(사번: `{user['emp_no']}`)"
)
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in_user = None
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 📌 메뉴 목록")

menu_list = [
    "📊 재고 현황판",
    "📝 입출고 등록",
    "🏷 품목 관리",
    "🔍 입출고 내역 조회",
    "⚙️ 환율 설정",
]

if user["is_admin"] == 1:
    menu_list.append("👥 사용자 관리 (관리자)")

menu = st.sidebar.radio("이동할 메뉴를 선택하세요:", menu_list)

# ---------------------------------------------------------
# 메뉴 1: 재고 현황판
# ---------------------------------------------------------
if menu == "📊 재고 현황판":
    st.subheader("📊 현재 품목별 재고 현황 (KRW 환산 기준)")
    st.caption(
        "💡 표에서 원하는 품목의 행을 클릭하시면 하단에 A4 상세 내역서가 자동으로 생성됩니다."
    )

    search_kw = st.text_input(
        "🔍 통합 검색 (품명, 코드, 상세번호, 규격, 구분, 대/소분류, 구역, 기기명, Maker, 입고일, 비고 내용 포함)",
        "",
    )

    query = """
    SELECT 
        i.image_path AS image_path,
        i.item_code AS 품목코드,
        i.item_name AS 품명,
        i.item_detail_no AS 아이템상세번호,
        i.model_spec AS 모델번호_규격,
        i.category_type AS 구분,
        i.category_main AS 대분류,
        i.category_sub AS 소분류,
        i.shelf_no AS 선반번호,
        i.zone AS 해당구역,
        i.device_name AS 기기명,
        i.maker AS Maker,
        i.in_date AS 입고일,
        i.currency AS 입력화폐,
        i.unit_price AS 기초단가,
        COALESCE(i.initial_quantity, 0) AS 초기수량,
        COALESCE(i.initial_quantity, 0) + COALESCE(SUM(CASE WHEN t.type = '입고' THEN t.quantity ELSE 0 END), 0) - COALESCE(SUM(CASE WHEN t.type = '출고' THEN t.quantity ELSE 0 END), 0) AS 현재재고,
        i.remark AS 비고
    FROM items i
    LEFT JOIN transactions t ON i.item_code = t.item_code
    GROUP BY i.item_code
    ORDER BY i.item_code ASC
    """
    df_stock = pd.read_sql_query(query, conn)

    if not df_stock.empty:
        krw_prices = []
        stock_values_krw = []
        img_urls = []
        clean_types = []

        for _, row in df_stock.iterrows():
            item_code_val = row["품목코드"]

            # 최근 입고 단가가 있으면 우선 적용
            cursor.execute(
                """
                SELECT unit_price, currency, trans_date FROM transactions 
                WHERE item_code = ? AND type = '입고' 
                ORDER BY trans_date DESC, id DESC LIMIT 1
            """,
                (item_code_val,),
            )
            latest_in = cursor.fetchone()

            if latest_in and latest_in["unit_price"] is not None:
                price = safe_float(latest_in["unit_price"])
                curr = latest_in["currency"] or row["입력화폐"]
                in_d = latest_in["trans_date"]
            else:
                price = safe_float(row["기초단가"])
                curr = row["입력화폐"]
                in_d = row["입고일"]

            stock = safe_int(row["현재재고"])

            rate, _ = get_exchange_rate(curr, in_d)
            unit_krw = int(price * rate)
            val_krw = int(unit_krw * stock)

            krw_prices.append(unit_krw)
            stock_values_krw.append(val_krw)
            img_urls.append(get_image_base64(row["image_path"]))
            clean_types.append(clean_category_type(row["구분"]))

        df_stock["사진"] = img_urls
        df_stock["구분"] = clean_types
        df_stock["단가(KRW)"] = krw_prices
        df_stock["재고금액(KRW)"] = stock_values_krw

        if search_kw:
            kw = search_kw.lower()
            mask = (
                df_stock["품명"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["품목코드"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["아이템상세번호"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["모델번호_규격"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["구분"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["대분류"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["소분류"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["선반번호"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["해당구역"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["기기명"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["Maker"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["입고일"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_stock["비고"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
            )
            df_stock = df_stock[mask]

        col1, col2, col3 = st.columns([2, 2, 2])
        col1.metric("조회된 품목 수", f"{len(df_stock)} 개")
        col2.metric(
            "총 재고 자산 (KRW 기준)",
            f"{df_stock['재고금액(KRW)'].sum():,} 원",
        )

        excel_export_df = df_stock.drop(
            columns=["사진", "image_path"], errors="ignore"
        )
        output_stock = io.BytesIO()
        with pd.ExcelWriter(output_stock, engine="openpyxl") as writer:
            excel_export_df.to_excel(writer, index=False, sheet_name="재고현황")
        col3.write("")
        col3.download_button(
            label="📥 재고현황 엑셀 다운로드 (.xlsx)",
            data=output_stock.getvalue(),
            file_name=f"자동화erp_자재재고현황_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        display_cols = [
            "사진",
            "품목코드",
            "품명",
            "아이템상세번호",
            "모델번호_규격",
            "구분",
            "대분류",
            "소분류",
            "선반번호",
            "해당구역",
            "기기명",
            "Maker",
            "입고일",
            "입력화폐",
            "단가(KRW)",
            "현재재고",
            "재고금액(KRW)",
            "비고",
        ]

        selection_event = st.dataframe(
            df_stock[display_cols],
            column_config={
                "사진": st.column_config.ImageColumn(
                    "사진", help="품목 사진 썸네일"
                ),
                "단가(KRW)": st.column_config.NumberColumn(format="%d 원"),
                "재고금액(KRW)": st.column_config.NumberColumn(format="%d 원"),
            },
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
        )

        st.markdown("---")
        st.subheader("📄 A4 품목 상세 내역서 출력 및 조회")

        item_select_list = {
            f"[{row['품목코드']}] {row['품명']} (상세번호: {row['아이템상세번호'] or '없음'}, Maker: {row['Maker'] or '없음'})": row[
                "품목코드"
            ]
            for _, row in df_stock.iterrows()
        }

        selected_code = None
        selected_index = 0

        selected_rows = (
            selection_event.selection.rows
            if selection_event and hasattr(selection_event, "selection")
            else []
        )
        if selected_rows:
            click_idx = selected_rows[0]
            if click_idx < len(df_stock):
                selected_code = df_stock.iloc[click_idx]["품목코드"]
                for i, (_, code) in enumerate(item_select_list.items()):
                    if code == selected_code:
                        selected_index = i
                        break

        if item_select_list:
            selected_item_label = st.selectbox(
                "📋 내역서를 조회할 품목을 선택하세요:",
                list(item_select_list.keys()),
                index=selected_index,
            )
            selected_code = item_select_list[selected_item_label]
            render_a4_spec_card(selected_code)

    else:
        st.info("등록된 품목이 없습니다.")

# ---------------------------------------------------------
# 메뉴 2: 입출고 등록
# ---------------------------------------------------------
elif menu == "📝 입출고 등록":
    st.subheader("📝 자재 입출고 등록")

    df_items = pd.read_sql_query(
        "SELECT item_code, item_name, item_detail_no, maker, unit_price, currency FROM items ORDER BY item_code ASC",
        conn,
    )

    if df_items.empty:
        st.warning(
            "등록된 품목이 없습니다. '품목 관리'에서 품목을 먼저 등록하세요."
        )
    else:
        search_item_kw = st.text_input(
            "🔍 품목 실시간 검색 (품명, 코드, 상세번호, Maker 등)", ""
        )

        filtered_items = df_items.copy()
        if search_item_kw:
            kw = search_item_kw.lower()
            filtered_items = filtered_items[
                filtered_items["item_name"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | filtered_items["item_code"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | filtered_items["item_detail_no"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | filtered_items["maker"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
            ]

        item_options = {}
        for _, row in filtered_items.iterrows():
            i_code = row["item_code"]

            # 최근 입고 단가가 있으면 우선 가져오기
            cursor.execute(
                """
                SELECT unit_price, currency FROM transactions 
                WHERE item_code = ? AND type = '입고' 
                ORDER BY trans_date DESC, id DESC LIMIT 1
            """,
                (i_code,),
            )
            latest_in = cursor.fetchone()

            if latest_in and latest_in["unit_price"] is not None:
                p_val = safe_float(latest_in["unit_price"])
                c_val = latest_in["currency"] or row["currency"]
            else:
                p_val = safe_float(row["unit_price"])
                c_val = row["currency"]

            label = f"[{i_code}] {row['item_name']} | 상세번호: {row['item_detail_no'] or '없음'} | Maker: {row['maker'] or '없음'}"
            item_options[label] = (i_code, p_val, c_val)

        if not item_options:
            st.error("검색 조건에 맞는 품목이 없습니다.")
        else:
            # 선택박스를 Form 외부로 배치하거나 고유 key 설정으로 하단 연동 문제 해결
            selected_item_label = st.selectbox(
                "🎯 대상 품목 선택",
                list(item_options.keys()),
                key="trans_item_select",
            )
            item_code, default_price, curr = item_options[selected_item_label]

            with st.form("trans_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                trans_type = col1.radio(
                    "입출고 구분", ["입고", "출고"], horizontal=True
                )
                trans_date = col2.date_input("입출고 일자", datetime.date.today())

                col3, col4 = st.columns(2)
                quantity = col3.number_input(
                    "수량", min_value=1, value=1, step=1
                )
                unit_price = col4.number_input(
                    f"적용 단가 ({curr})",
                    min_value=0.0,
                    value=float(default_price or 0.0),
                    step=100.0,
                )

                col6, col7 = st.columns(2)
                default_manager = f"{user['name']} {user['position']} (사번: {user['emp_no']})"
                manager = col6.text_input(
                    "담당자 (작성자)", value=default_manager
                )
                requester = col7.text_input("출고/입고 요청자 (*필수)")

                remark = st.text_input("비고 (용도, 출처 등)")
                submitted = st.form_submit_button("입출고 저장")

                if submitted:
                    if not requester:
                        st.error("요청자는 필수 입력 항목입니다.")
                    else:
                        total_price = quantity * unit_price
                        cursor.execute(
                            """
                            INSERT INTO transactions (trans_date, type, item_code, quantity, unit_price, currency, total_price, manager, requester, remark)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                str(trans_date),
                                trans_type,
                                item_code,
                                quantity,
                                unit_price,
                                curr,
                                total_price,
                                manager,
                                requester,
                                remark,
                            ),
                        )
                        conn.commit()
                        st.success(
                            f"✅ [{trans_type}] [{item_code}] - {quantity}개 입출고 등록이 완료되었습니다!"
                        )
                        st.toast(
                            f"[{trans_type}] {item_code} - {quantity}개 저장 완료!",
                            icon="🎉",
                        )
                        st.rerun()

            st.markdown("---")
            st.subheader(
                f"📄 선택 품목 [{item_code}] 상세 내역서 (실시간 연동)"
            )
            render_a4_spec_card(item_code)

# ---------------------------------------------------------
# 메뉴 3: 품목 관리
# ---------------------------------------------------------
elif menu == "🏷️ 품목 관리":
    st.subheader("🏷️ 품목 등록 및 수정 관리")

    tab1, tab2, tab3 = st.tabs(
        ["✍️ 개별 직접 등록", "✏️ 기존 품목 수정", "📂 엑셀 일괄 등록"]
    )

    with tab1:
        next_code = generate_next_item_code()
        st.info(f"💡 새로 부여될 자동 품목코드: **{next_code}**")

        with st.form("item_form_new", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            item_name = col1.text_input("품명 (*필수)")
            item_detail_no = col2.text_input("아이템상세번호")
            model_spec = col3.text_input("모델번호_규격")

            col4, col5, col6 = st.columns(3)
            category_type = col4.text_input("구분")
            category_main = col5.text_input("대분류")
            category_sub = col6.text_input("소분류")

            col7, col8, col9 = st.columns(3)
            shelf_no = col7.text_input("선반번호")
            zone = col8.text_input("해당구역")
            device_name = col9.text_input("기기명")

            col10, col11, col12 = st.columns(3)
            maker = col10.text_input("Maker")
            useful_life = col11.text_input("내구연한")
            in_date = col12.text_input(
                "입고일 (예: 2023-10-20 또는 23.10.20)",
                value=str(datetime.date.today()),
            )

            col13, col14, col15 = st.columns(3)
            currency = col13.selectbox("화폐", ["KRW", "USD", "EUR", "JPY"])
            unit_price = col14.number_input(
                "단가", min_value=0.0, value=0.0, step=100.0
            )
            initial_quantity = col15.number_input(
                "초기 수량", min_value=0, value=0, step=1
            )

            remark = st.text_input("비고")
            img_file = st.file_uploader(
                "품목 사진 첨부 (모바일 접속 시 카메라 촬영 가능)",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=False,
            )

            submitted = st.form_submit_button("신규 품목 저장")

            if submitted:
                if not item_name:
                    st.error("품명은 필수 입력 항목입니다.")
                else:
                    item_code = generate_next_item_code()
                    image_path = None
                    if img_file is not None:
                        file_ext = img_file.name.split(".")[-1]
                        file_name = f"{item_code}.{file_ext}"
                        image_path = os.path.join(UPLOAD_DIR, file_name)
                        with open(image_path, "wb") as f:
                            f.write(img_file.getbuffer())

                    clean_c_type = clean_category_type(
                        category_type, default=""
                    )

                    try:
                        cursor.execute(
                            """
                            INSERT INTO items (
                                item_code, item_name, item_detail_no, model_spec,
                                category_type, category_main, category_sub, shelf_no,
                                in_date, zone, device_name, maker, useful_life,
                                currency, unit_price, remark, initial_quantity, image_path
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                item_code,
                                item_name,
                                item_detail_no,
                                model_spec,
                                clean_c_type,
                                category_main,
                                category_sub,
                                shelf_no,
                                str(in_date),
                                zone,
                                device_name,
                                maker,
                                useful_life,
                                currency,
                                unit_price,
                                remark,
                                initial_quantity,
                                image_path,
                            ),
                        )
                        conn.commit()
                        st.success(
                            f"🎉 신규 품목 [{item_code}] {item_name} 이(가) 성공적으로 저장되었습니다!"
                        )
                        st.toast(f"품목 [{item_code}] 등록 완료", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"저장 중 오류 발생: {e}")

    with tab2:
        df_all_items = pd.read_sql_query(
            "SELECT * FROM items ORDER BY item_code ASC", conn
        )
        if df_all_items.empty:
            st.info("수정할 품목이 존재하지 않습니다.")
        else:
            edit_item_list = {
                f"[{row['item_code']}] {row['item_name']} (상세: {row['item_detail_no'] or '-'})": row[
                    "item_code"
                ]
                for _, row in df_all_items.iterrows()
            }
            selected_edit_label = st.selectbox(
                "✏️ 수정할 품목 선택", list(edit_item_list.keys())
            )
            target_code = edit_item_list[selected_edit_label]

            target_row = df_all_items[
                df_all_items["item_code"] == target_code
            ].iloc[0]

            with st.form("edit_item_form"):
                st.markdown(f"#### 📌 품목 수정 - [{target_code}]")
                col1, col2, col3 = st.columns(3)
                e_name = col1.text_input(
                    "품명", value=safe_str(target_row["item_name"])
                )
                e_detail = col2.text_input(
                    "아이템상세번호", value=safe_str(target_row["item_detail_no"])
                )
                e_spec = col3.text_input(
                    "모델번호_규격", value=safe_str(target_row["model_spec"])
                )

                col4, col5, col6 = st.columns(3)
                e_type = col4.text_input(
                    "구분", value=safe_str(target_row["category_type"])
                )
                e_main = col5.text_input(
                    "대분류", value=safe_str(target_row["category_main"])
                )
                e_sub = col6.text_input(
                    "소분류", value=safe_str(target_row["category_sub"])
                )

                col7, col8, col9 = st.columns(3)
                e_shelf = col7.text_input(
                    "선반번호", value=safe_str(target_row["shelf_no"])
                )
                e_zone = col8.text_input(
                    "해당구역", value=safe_str(target_row["zone"])
                )
                e_device = col9.text_input(
                    "기기명", value=safe_str(target_row["device_name"])
                )

                col10, col11, col12 = st.columns(3)
                e_maker = col10.text_input(
                    "Maker", value=safe_str(target_row["maker"])
                )
                e_life = col11.text_input(
                    "내구연한", value=safe_str(target_row["useful_life"])
                )
                e_indate = col12.text_input(
                    "입고일", value=safe_str(target_row["in_date"])
                )

                col13, col14, col15 = st.columns(3)
                e_curr = col13.selectbox(
                    "화폐",
                    ["KRW", "USD", "EUR", "JPY"],
                    index=(
                        ["KRW", "USD", "EUR", "JPY"].index(
                            target_row["currency"]
                        )
                        if target_row["currency"] in ["KRW", "USD", "EUR", "JPY"]
                        else 0
                    ),
                )
                e_price = col14.number_input(
                    "단가",
                    min_value=0.0,
                    value=safe_float(target_row["unit_price"]),
                )
                e_init_qty = col15.number_input(
                    "초기수량",
                    min_value=0,
                    value=safe_int(target_row["initial_quantity"]),
                )

                e_remark = st.text_input(
                    "비고", value=safe_str(target_row["remark"])
                )
                edit_reason = st.text_input(
                    "수정 사유 (*이력 관리를 위해 입력 권장)"
                )

                new_img = st.file_uploader(
                    "사진 교체 (선택)", type=["png", "jpg", "jpeg"]
                )

                btn_update = st.form_submit_button("정보 수정 완료")

                if btn_update:
                    image_path = target_row["image_path"]
                    if new_img is not None:
                        file_ext = new_img.name.split(".")[-1]
                        file_name = f"{target_code}.{file_ext}"
                        image_path = os.path.join(UPLOAD_DIR, file_name)
                        with open(image_path, "wb") as f:
                            f.write(new_img.getbuffer())

                    cursor.execute(
                        """
                        UPDATE items SET
                            item_name=?, item_detail_no=?, model_spec=?, category_type=?, category_main=?,
                            category_sub=?, shelf_no=?, in_date=?, zone=?, device_name=?, maker=?,
                            useful_life=?, currency=?, unit_price=?, remark=?, initial_quantity=?, image_path=?
                        WHERE item_code=?
                    """,
                        (
                            e_name,
                            e_detail,
                            e_spec,
                            clean_category_type(e_type, default=""),
                            e_main,
                            e_sub,
                            e_shelf,
                            e_indate,
                            e_zone,
                            e_device,
                            e_maker,
                            e_life,
                            e_curr,
                            e_price,
                            e_remark,
                            e_init_qty,
                            image_path,
                            target_code,
                        ),
                    )

                    editor_info = f"{user['name']} {user['position']}"
                    cursor.execute(
                        """
                        INSERT INTO item_edit_history (item_code, editor, reason, details)
                        VALUES (?, ?, ?, ?)
                    """,
                        (
                            target_code,
                            editor_info,
                            edit_reason or "기본 정보 수정",
                            f"품명: {e_name}, 단가: {e_price} {e_curr}",
                        ),
                    )

                    conn.commit()
                    st.success(
                        f"✅ [{target_code}] 품목 정보가 성공적으로 수정되었습니다."
                    )
                    st.rerun()

    with tab3:
        st.markdown("#### 📂 엑셀 데이터 일괄 업로드")
        st.caption(
            "Excel 파일(.xlsx)의 컬럼 헤더가 DB 항목명과 일치하는지 확인해 주세요."
        )

        uploaded_excel = st.file_uploader(
            "엑셀 파일 선택", type=["xlsx", "xls"]
        )
        if uploaded_excel:
            try:
                df_upload = pd.read_excel(uploaded_excel)
                st.write("📋 업로드 데이터 미리보기:", df_upload.head())

                if st.button("🚀 DB에 데이터 등록 실행"):
                    success_cnt = 0
                    for _, r in df_upload.iterrows():
                        i_code = (
                            safe_str(r.get("item_code"))
                            or generate_next_item_code()
                        )
                        i_name = safe_str(r.get("item_name"))
                        if not i_name:
                            continue

                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO items (
                                item_code, item_name, item_detail_no, model_spec, category_type,
                                category_main, category_sub, shelf_no, in_date, zone, device_name,
                                maker, useful_life, currency, unit_price, remark, initial_quantity
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                i_code,
                                i_name,
                                safe_str(r.get("item_detail_no")),
                                safe_str(r.get("model_spec")),
                                clean_category_type(
                                    r.get("category_type"), default=""
                                ),
                                safe_str(r.get("category_main")),
                                safe_str(r.get("category_sub")),
                                safe_str(r.get("shelf_no")),
                                safe_str(r.get("in_date")),
                                safe_str(r.get("zone")),
                                safe_str(r.get("device_name")),
                                safe_str(r.get("maker")),
                                safe_str(r.get("useful_life")),
                                safe_str(r.get("currency"), default="KRW"),
                                safe_float(r.get("unit_price")),
                                safe_str(r.get("remark")),
                                safe_int(r.get("initial_quantity")),
                            ),
                        )
                        success_cnt += 1
                    conn.commit()
                    st.success(
                        f"🎉 총 {success_cnt}건의 품목 데이터가 업로드/업데이트되었습니다."
                    )
            except Exception as ex:
                st.error(f"엑셀 파일 처리 실패: {ex}")

# ---------------------------------------------------------
# 메뉴 4: 입출고 내역 조회
# ---------------------------------------------------------
elif menu == "🔍 입출고 내역 조회":
    st.subheader("🔍 입출고 통합 내역 조회")

    q_trans = """
    SELECT 
        t.id AS 번호,
        t.trans_date AS 일자,
        t.type AS 구분,
        t.item_code AS 품목코드,
        i.item_name AS 품명,
        t.quantity AS 수량,
        t.unit_price AS 단가,
        t.currency AS 화폐,
        t.total_price AS 총금액,
        t.manager AS 담당자,
        t.requester AS 요청자,
        t.remark AS 비고
    FROM transactions t
    LEFT JOIN items i ON t.item_code = i.item_code
    ORDER BY t.trans_date DESC, t.id DESC
    """
    df_all_trans = pd.read_sql_query(q_trans, conn)

    if df_all_trans.empty:
        st.info("등록된 입출고 내역이 없습니다.")
    else:
        filter_kw = st.text_input(
            "🔍 내역 검색 (품명, 담당자, 요청자, 비고 등)", ""
        )
        if filter_kw:
            kw = filter_kw.lower()
            df_all_trans = df_all_trans[
                df_all_trans["품명"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_all_trans["품목코드"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_all_trans["담당자"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_all_trans["요청자"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
                | df_all_trans["비고"].astype(str).str.lower().str.contains(kw, na=False, regex=False)
            ]

        st.dataframe(df_all_trans, use_container_width=True)

        out_trans = io.BytesIO()
        with pd.ExcelWriter(out_trans, engine="openpyxl") as writer:
            df_all_trans.to_excel(writer, index=False, sheet_name="입출고내역")
        st.download_button(
            label="📥 입출고 내역 엑셀 다운로드",
            data=out_trans.getvalue(),
            file_name=f"자동화erp_입출고내역_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ---------------------------------------------------------
# 메뉴 5: 환율 설정
# ---------------------------------------------------------
elif menu == "⚙️ 환율 설정":
    st.subheader("⚙️️ 연도별 기준 환율 관리")
    st.caption(
        "해외 구매 자재의 원화(KRW) 자산 가치 환산 시 기준이 되는 환율 테이블입니다."
    )

    df_rates = pd.read_sql_query(
        "SELECT year AS 연도, currency AS 화폐, rate AS 환율 FROM exchange_rates ORDER BY year DESC, currency ASC",
        conn,
    )
    st.dataframe(df_rates, use_container_width=True)

    with st.form("rate_form"):
        st.markdown("#### ➕ 환율 추가 및 수정")
        col1, col2, col3 = st.columns(3)
        r_year = col1.number_input(
            "연도",
            min_value=2020,
            max_value=2030,
            value=datetime.date.today().year,
        )
        r_curr = col2.selectbox("화폐", ["USD", "EUR", "JPY", "KRW"])
        r_rate = col3.number_input(
            "환율 (원)", min_value=0.0, value=1350.0, step=10.0
        )

        btn_rate = st.form_submit_button("환율 설정 저장")
        if btn_rate:
            cursor.execute(
                """
                INSERT OR REPLACE INTO exchange_rates (year, currency, rate)
                VALUES (?, ?, ?)
            """,
                (r_year, r_curr, r_rate),
            )
            conn.commit()
            st.success(
                f"✅ {r_year}년 {r_curr} 환율이 {r_rate:,}원으로 저장되었습니다."
            )
            st.rerun()

# ---------------------------------------------------------
# 메뉴 6: 사용자 관리 (관리자 전용)
# ---------------------------------------------------------
elif menu == "👥 사용자 관리 (관리자)":
    st.subheader("👥 시스템 사용자 계정 관리")

    df_users = pd.read_sql_query(
        "SELECT emp_no AS 사번, name AS 이름, position AS 직급, is_admin AS 관리자여부, created_at AS 생성일시 FROM users",
        conn,
    )
    st.dataframe(df_users, use_container_width=True)

    with st.form("add_user_form"):
        st.markdown("#### ➕ 신규 사용자 추가")
        col1, col2, col3 = st.columns(3)
        u_emp = col1.text_input("사번 (ID) (*필수)")
        u_pw = col2.text_input("비밀번호 (*필수)", type="password")
        u_name = col3.text_input("이름 (*필수)")

        col4, col5 = st.columns(2)
        u_pos = col4.selectbox("직급", POSITIONS)
        u_admin = col5.checkbox("관리자 권한 부여 (is_admin)")

        btn_add_user = st.form_submit_button("계정 생성")
        if btn_add_user:
            if not u_emp or not u_pw or not u_name:
                st.error("사번, 비밀번호, 이름은 필수 항목입니다.")
            else:
                try:
                    cursor.execute(
                        """
                        INSERT INTO users (emp_no, password, name, position, is_admin)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            u_emp.strip(),
                            u_pw.strip(),
                            u_name.strip(),
                            u_pos,
                            1 if u_admin else 0,
                        ),
                    )
                    conn.commit()
                    st.success(f"✅ 사용자 [{u_name}] 계정이 생성되었습니다.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("이미 존재하는 사번입니다.")