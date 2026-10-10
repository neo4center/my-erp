import datetime
import html
import io
import math
import re
import pandas as pd
import streamlit as st
import db_helper as db

# Streamlit 기본 설정
st.set_page_config(page_title="광주오포센터 자동화 ERP", layout="wide")

# ---------------------------------------------------------
# 1. 헬퍼 함수
# ---------------------------------------------------------
POSITIONS = ["팀장", "부팀장", "마스터", "과장", "대리", "주임", "사원"]

def safe_float(val, default=0.0):
    if pd.isna(val) or val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int_clean(val, default=0):
    if pd.isna(val) or val is None:
        return default
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default

def safe_str_clean(val, default="-"):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip()
    if s.lower() in ["nan", "null", "none", "", "none"]:
        return default
    return s.replace('"', '″').replace("'", "′")

def clean_date(val):
    if pd.isna(val) or val is None:
        return str(datetime.date.today())
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip().split("T")[0].split(" ")[0]
    return s if len(s) >= 8 else str(datetime.date.today())

def clean_val(val, default="-"):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip().replace('"', "")
    return html.escape(s) if s and s.lower() not in ["nan", "none", ""] else default

def generate_next_item_code():
    try:
        resp = db.supabase.table("items").select("item_code").order("item_code", desc=True).limit(1).execute()
        items = resp.data or []
        if not items:
            return "ITEM_00001"
        latest_code = str(items[0].get("item_code", ""))
        nums = re.findall(r'\d+', latest_code)
        if nums:
            max_num = int(nums[-1])
            return f"ITEM_{max_num + 1:05d}"
        else:
            return "ITEM_00001"
    except Exception:
        return f"ITEM_{int(datetime.datetime.now().timestamp())}"

def get_year_from_date(date_str):
    if not date_str:
        return datetime.date.today().year
    s = str(date_str).strip()
    nums = re.findall(r'\d+', s)
    if not nums:
        return datetime.date.today().year
    candidate = nums[0]
    if len(candidate) == 4:
        return int(candidate)
    elif len(candidate) == 2:
        yy = int(candidate)
        return 2000 + yy if yy < 50 else 1900 + yy
    return datetime.date.today().year

@st.cache_data(ttl=600)
def get_cached_exchange_rates():
    try:
        resp = db.supabase.table("exchange_rates").select("year, currency, rate").execute()
        rates_map = {}
        for r in (resp.data or []):
            rates_map[(r["year"], r["currency"].upper())] = safe_float(r["rate"], 1.0)
        return rates_map
    except Exception:
        return {}

def get_exchange_rate_by_year(currency, year):
    curr = str(currency).upper().strip()
    if curr == "KRW" or not curr:
        return 1.0
    rates_map = get_cached_exchange_rates()
    if (year, curr) in rates_map:
        return rates_map[(year, curr)]
    currency_rates = [v for k, v in rates_map.items() if k[1] == curr]
    if currency_rates:
        return currency_rates[0]
    return 1.0

def render_a4_spec_card(item_code):
    item_resp = db.supabase.table("items").select("*").eq("item_code", item_code).execute()
    if not item_resp.data:
        return
    item = item_resp.data[0]

    trans_resp = db.supabase.table("stock_transactions").select("*").eq("item_code", item_code).order("trans_date", desc=False).execute()
    trans_data = trans_resp.data or []
    
    calc_stock = 0
    in_rows, out_rows = [], []
    in_idx, out_idx = 1, 1
    total_in_qty, total_in_amt = 0, 0
    total_out_qty, total_out_amt = 0, 0
    
    curr = safe_str_clean(item.get("currency"), "KRW")
    base_price = safe_float(item.get("unit_price"), 0.0)
    base_in_date = clean_date(item.get("in_date", str(datetime.date.today())))
    
    # 💡 최신(마지막) 입고일 및 입고 단가 산정 로직 (날짜 정규화 적용)
    latest_in_price = base_price
    latest_in_date = base_in_date
    
    for t in trans_data:
        t_type = str(t.get("trans_type", "")).strip().upper()
        if t_type in ["IN", "입고"]:
            t_date = clean_date(t.get("trans_date", ""))
            t_price = safe_float(t.get("unit_price"), 0.0)
            if t_date and t_price > 0:
                if t_date >= latest_in_date:
                    latest_in_date = t_date
                    latest_in_price = t_price

    representative_price = latest_in_price
    representative_year = get_year_from_date(latest_in_date)
    representative_rate = get_exchange_rate_by_year(curr, representative_year)

    for t in trans_data:
        t_type = str(t.get("trans_type", "")).strip().upper()
        qty = safe_int_clean(t.get("quantity"), 0)
        price = safe_float(t.get("unit_price"), base_price)
        t_date = clean_date(t.get("trans_date", ""))
        t_year = get_year_from_date(t_date)
        t_rate = get_exchange_rate_by_year(curr, t_year)
        t_krw_unit = price * t_rate
        total_row_amt = round(qty * t_krw_unit)
        
        raw_mgr = safe_str_clean(t.get("manager"), "")
        if not raw_mgr or raw_mgr in ["-", "None", ""]:
            raw_mgr = "최광호"
        else:
            for pos in POSITIONS:
                raw_mgr = raw_mgr.replace(pos, "").strip()
        
        raw_req = safe_str_clean(t.get("requester"), "-")
        if raw_req in ["-", "초기재고일괄등록", "시스템입고", "None", ""]:
            raw_req = "-" if t_type in ["IN", "입고"] else "출고담당자"

        t_remark = safe_str_clean(t.get("remark"), "")
        if not t_remark or t_remark in ["-", "None", ""]:
            t_remark = safe_str_clean(item.get("remark"), "-")

        row_dict = {
            "No": in_idx if t_type in ["IN", "입고"] else out_idx,
            "일자": t_date,
            "구분": "입고 (IN)" if t_type in ["IN", "입고"] else "출고 (OUT)",
            "수량": f"{qty:,} 개",
            "원화환산액": f"{round(t_krw_unit):,} 원",
            "총금액": f"{total_row_amt:,} 원",
            "담당자": raw_mgr,
            "요청자": raw_req,
            "비고": t_remark
        }

        if t_type in ["IN", "입고"]:
            in_rows.append(row_dict)
            total_in_qty += qty
            total_in_amt += total_row_amt
            calc_stock += qty
            in_idx += 1
        elif t_type in ["OUT", "출고"]:
            out_rows.append(row_dict)
            total_out_qty += qty
            total_out_amt += total_row_amt
            calc_stock -= qty
            out_idx += 1

    current_stock = max(0, calc_stock)
    total_val_krw = round(current_stock * (representative_price * representative_rate))
    unit_krw_display = int(round(representative_price * representative_rate))

    df_in = pd.DataFrame(in_rows)
    df_out = pd.DataFrame(out_rows)
    category_full = f"{safe_str_clean(item.get('category_main'))} - {safe_str_clean(item.get('category_sub'))} - 선반:{safe_str_clean(item.get('shelf_no'))}"

    st.markdown("""
    <style>
    .a4-card { background-color: #ffffff; border: 2px solid #333; border-radius: 8px; padding: 25px; margin-top: 10px; color: #111; }
    .a4-header { text-align: center; border-bottom: 3px double #333; padding-bottom: 10px; margin-bottom: 20px; }
    .info-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; }
    .info-table th, .info-table td { border: 1px solid #ccc; padding: 8px 12px; font-size: 14px; }
    .info-table th { background-color: #f4f4f4; font-weight: bold; width: 18%; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='a4-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='a4-header'><h2>자재품목명세서</h2><p>발행일자: {datetime.date.today()}</p></div>", unsafe_allow_html=True)
        col_img, col_info = st.columns([1, 3])

        with col_img:
            photo_url = item.get("photo_url")
            if photo_url:
                st.image(photo_url, caption=str(item.get("item_name")), use_container_width=True)
            else:
                st.info("등록된 사진 없음")

        with col_info:
            html_table = f"""
            <table class="info-table">
                <tr><th>품목코드</th><td><code>{clean_val(item.get('item_code'))}</code></td><th>품명</th><td><b>{clean_val(item.get('item_name'))}</b></td></tr>
                <tr><th>상세번호</th><td>{clean_val(item.get('item_detail_no'))}</td><th>규격/모델</th><td>{clean_val(item.get('model_spec'))}</td></tr>
                <tr><th>구분</th><td>{clean_val(item.get('category_type'))}</td><th>분류체계</th><td>{category_full}</td></tr>
                <tr><th>설치구역/기기</th><td>{clean_val(item.get('zone'))} / {clean_val(item.get('device_name'))}</td><th>Maker</th><td>{clean_val(item.get('maker'))}</td></tr>
                <tr><th>화폐단위/단가</th><td>{curr} / {representative_price:,.2f}</td><th>적용 환율({representative_year}년)</th><td>{representative_rate:,.2f} 원</td></tr>
                <tr><th>원화환산액</th><td>{unit_krw_display:,} 원</td><th>현재재고 / 재고금액</th><td><b>{current_stock:,} 개 / {total_val_krw:,} 원</b></td></tr>
                <tr><th>비고</th><td colspan="3">{clean_val(item.get('remark'))}</td></tr>
            </table>
            """
            st.markdown(html_table, unsafe_allow_html=True)

        st.markdown("---")
        
        col_t1, col_t1_sum = st.columns([2, 3])
        col_t1.markdown("### 📥 1. 입고 내역")
        col_t1_sum.markdown(f"<div style='text-align: right; padding-top: 10px; font-weight: bold; color: #1B5E20;'>합계 수량: {total_in_qty:,} 개 &nbsp;|&nbsp; 총 금액: {total_in_amt:,} 원</div>", unsafe_allow_html=True)
        
        if not df_in.empty:
            st.dataframe(df_in, column_config={"No": st.column_config.NumberColumn("No", width="small", format="%d")}, use_container_width=True, hide_index=True)
        else:
            st.caption("※ 입고 내역이 없습니다.")

        st.markdown("---")

        col_t2, col_t2_sum = st.columns([2, 3])
        col_t2.markdown("### 📤 2. 출고 내역")
        col_t2_sum.markdown(f"<div style='text-align: right; padding-top: 10px; font-weight: bold; color: #B71C1C;'>합계 수량: {total_out_qty:,} 개 &nbsp;|&nbsp; 총 금액: {total_out_amt:,} 원</div>", unsafe_allow_html=True)

        if not df_out.empty:
            st.dataframe(df_out, column_config={"No": st.column_config.NumberColumn("No", width="small", format="%d")}, use_container_width=True, hide_index=True)
        else:
            st.caption("※ 출고 내역이 없습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. 로그인 세션 관리
# ---------------------------------------------------------
if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None

if st.session_state.logged_in_user is None:
    st.title("🔐 광주오포센터 자동화 ERP - 로그인")
    with st.form("login_form"):
        emp_no = st.text_input("사번 (ID) (*필수)")
        pw = st.text_input("비밀번호 (PW) (*필수)", type="password")
        submitted = st.form_submit_button("로그인")
        
        if submitted:
            with st.spinner("⏳ 사용자 인증 중입니다..."):
                if emp_no.strip() and pw.strip():
                    resp = db.supabase.table("users").select("*").eq("emp_no", emp_no.strip()).eq("password", pw.strip()).execute()
                    if resp.data:
                        u = resp.data[0]
                        st.session_state.logged_in_user = {
                            "emp_no": u["emp_no"], "name": u["name"], "position": u["position"], "is_admin": u.get("is_admin", 0)
                        }
                        st.success(f"환영합니다, {u['name']} {u['position']}님!")
                        st.rerun()
                    elif emp_no == "admin" and pw == "admin":
                        st.session_state.logged_in_user = {"emp_no": "admin", "name": "시스템관리자", "position": "팀장", "is_admin": 1}
                        st.rerun()
                    else:
                        st.error("❌ 사번 또는 비밀번호가 올바르지 않습니다.")
                else:
                    st.error("사번과 비밀번호를 입력하세요.")
    st.stop()

# ---------------------------------------------------------
# 3. 메인 ERP 사이드바 및 메뉴 정의
# ---------------------------------------------------------
user = st.session_state.logged_in_user
st.title("🏭 광주오포센터 자동화 ERP")

st.sidebar.markdown(f"👤 접속자: **{user['name']} {user['position']}**<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(사번: `{user['emp_no']}`)", unsafe_allow_html=True)

if st.sidebar.button("로그아웃"):
    st.session_state.logged_in_user = None
    st.rerun()

st.sidebar.markdown("---")
MENU_STOCK = "📊 재고 현황판"
MENU_TRANS = "📝 입출고 등록"
MENU_ITEMS = "🏷️ 품목 관리"
MENU_HISTORY = "🔍 입출고 내역 조회"
MENU_RATES = "⚙️ 환율 설정"

menu_list = [MENU_STOCK, MENU_TRANS, MENU_ITEMS, MENU_HISTORY, MENU_RATES]
if user.get("is_admin") == 1:
    menu_list.append("👥 사용자 관리 (관리자)")

menu = st.sidebar.radio("메뉴 이동:", menu_list)

# ---------------------------------------------------------
# 메뉴 1: 재고 현황판
# ---------------------------------------------------------
if menu == MENU_STOCK:
    st.subheader("📊 현재 품목별/Lot별 재고 현황판 (초기재고 0개 포함)")
    st.caption("💡 검색어를 입력하시면 데이터베이스 전체에서 일치하는 품목을 즉시 찾아줍니다.")

    search_kw = st.text_input("🔍 통합 검색 (품목코드, 품명, 상세번호, 규격/모델, 비고 통합 검색)", "")

    all_meta_resp = []
    try:
        chunk_size = 1000
        start = 0
        while True:
            resp = db.supabase.table("items").select("in_date, device_name, maker, category_main").range(start, start + chunk_size - 1).execute()
            chunk_data = resp.data or []
            all_meta_resp.extend(chunk_data)
            if len(chunk_data) < chunk_size:
                break
            start += chunk_size
    except Exception:
        all_meta_resp = []

    dates_opt = sorted(list(set(str(m.get("in_date", "")) for m in all_meta_resp if m.get("in_date"))))
    devices_opt = sorted(list(set(str(m.get("device_name", "")) for m in all_meta_resp if m.get("device_name") and m.get("device_name") != "-")))
    makers_opt = sorted(list(set(str(m.get("maker", "")) for m in all_meta_resp if m.get("maker") and m.get("maker") != "-")))
    categories_opt = sorted(list(set(str(m.get("category_main", "")) for m in all_meta_resp if m.get("category_main") and m.get("category_main") != "-")))

    with st.expander("🛠 엑셀 스타일 상세 필터 열기/닫기", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        sel_in_date = fc1.selectbox("입고일 필터", ["전체"] + dates_opt)
        sel_stock_range = fc2.selectbox("재고 수량 필터", ["전체", "0 (재고없음)", "1~10개", "11개 이상"])
        sel_device = fc3.selectbox("기기명 필터", ["전체"] + devices_opt)

        fc4, fc5 = st.columns(2)
        sel_maker = fc4.selectbox("Maker 필터", ["전체"] + makers_opt)
        sel_cat_main = fc5.selectbox("대분류 필터", ["전체"] + categories_opt)

    try:
        count_query = db.supabase.table("items").select("item_code", count="exact")
        count_resp = count_query.execute()
        total_count = count_resp.count if hasattr(count_resp, "count") and count_resp.count is not None else 1097
    except Exception:
        total_count = 1097

    try:
        all_items = []
        is_filtering = (
            sel_in_date != "전체" or 
            sel_stock_range != "전체" or 
            sel_device != "전체" or 
            sel_maker != "전체" or 
            sel_cat_main != "전체"
        )

        chunk_size = 1000
        start = 0
        while True:
            sub_query = db.supabase.table("items").select("*")
            if search_kw.strip():
                kw = search_kw.strip()
                sub_query = sub_query.or_(f"item_code.ilike.%{kw}%,item_name.ilike.%{kw}%,item_detail_no.ilike.%{kw}%,model_spec.ilike.%{kw}%,remark.ilike.%{kw}%")
            
            resp = sub_query.order("item_code", desc=False).range(start, start + chunk_size - 1).execute()
            chunk_data = resp.data or []
            all_items.extend(chunk_data)
            
            if search_kw.strip() or is_filtering:
                if len(chunk_data) < chunk_size:
                    break
                start += chunk_size
            else:
                PAGE_SIZE_STOCK = 100
                total_stock_pages = max(1, math.ceil(total_count / PAGE_SIZE_STOCK))
                
                col_p1, _ = st.columns([1, 4])
                with col_p1:
                    current_stock_page = st.selectbox("📄 페이지 선택 (100건씩)", list(range(1, total_stock_pages + 1)), format_func=lambda x: f"{x} 페이지 (총 {total_stock_pages}페이지)")

                start_idx = (current_stock_page - 1) * PAGE_SIZE_STOCK
                end_idx = start_idx + PAGE_SIZE_STOCK - 1
                
                items_resp = db.supabase.table("items").select("*").order("item_code", desc=False).range(start_idx, end_idx).execute()
                all_items = items_resp.data or []
                break
    except Exception:
        all_items = []

    all_trans_resp = []
    try:
        chunk_size = 1000
        start = 0
        while True:
            resp = db.supabase.table("stock_transactions").select("item_code, trans_type, quantity").range(start, start + chunk_size - 1).execute()
            chunk_data = resp.data or []
            all_trans_resp.extend(chunk_data)
            if len(chunk_data) < chunk_size:
                break
            start += chunk_size
    except Exception:
        all_trans_resp = []

    item_calc_stock_map = {}
    for t in all_trans_resp:
        ic = t.get("item_code")
        if not ic:
            continue
        q = safe_int_clean(t.get("quantity"), 0)
        ttype = str(t.get("trans_type", "")).strip().upper()
        if ic not in item_calc_stock_map:
            item_calc_stock_map[ic] = 0
        if ttype in ["IN", "입고"]:
            item_calc_stock_map[ic] += q
        elif ttype in ["OUT", "출고"]:
            item_calc_stock_map[ic] -= q

    table_rows = []
    for item in all_items:
        icode = item.get("item_code")
        curr = safe_str_clean(item.get("currency"), "KRW")
        base_price = safe_float(item.get("unit_price"), 0.0)
        base_in_date = clean_date(item.get("in_date", str(datetime.date.today())))
        
        category_type = safe_str_clean(item.get("category_type"))
        category_main = safe_str_clean(item.get("category_main"))
        category_full = f"{category_main} - {safe_str_clean(item.get('category_sub'))} - 선반:{safe_str_clean(item.get('shelf_no'))}"
        device_name = safe_str_clean(item.get("device_name"))
        maker = safe_str_clean(item.get("maker"))
        remark = safe_str_clean(item.get("remark"))
        model_spec = safe_str_clean(item.get("model_spec"))
        detail_no = safe_str_clean(item.get("item_detail_no"))
        iname = safe_str_clean(item.get("item_name"))

        calc_qty = max(0, item_calc_stock_map.get(icode, 0))
        
        year = get_year_from_date(base_in_date)
        rate = get_exchange_rate_by_year(curr, year)
        unit_krw = round(base_price * rate)
        stock_amt = round(unit_krw * calc_qty)

        table_rows.append({
            "사진": item.get("photo_url"),
            "Lot ID": "-",
            "품목코드": icode,
            "품명": iname,
            "상세번호": detail_no,
            "규격/모델": model_spec,
            "구분": category_type,
            "분류체계": category_full,
            "대분류": category_main,
            "구역": safe_str_clean(item.get("zone")),
            "기기명": device_name,
            "Maker": maker,
            "입고일": base_in_date,
            "현재재고": calc_qty,
            "화폐단위": curr,
            "단가": base_price,
            "원화환산액": unit_krw,
            "재고금액": stock_amt,
            "비고": remark
        })

    if table_rows:
        df_stock = pd.DataFrame(table_rows)

        if sel_in_date != "전체":
            df_stock = df_stock[df_stock["입고일"] == sel_in_date]
        if sel_stock_range == "0 (재고없음)":
            df_stock = df_stock[df_stock["현재재고"] == 0]
        elif sel_stock_range == "1~10개":
            df_stock = df_stock[(df_stock["현재재고"] >= 1) & (df_stock["현재재고"] <= 10)]
        elif sel_stock_range == "11개 이상":
            df_stock = df_stock[df_stock["현재재고"] >= 11]
        if sel_device != "전체":
            df_stock = df_stock[df_stock["기기명"] == sel_device]
        if sel_maker != "전체":
            df_stock = df_stock[df_stock["Maker"] == sel_maker]
        if sel_cat_main != "전체":
            df_stock = df_stock[df_stock["대분류"] == sel_cat_main]

        total_all_asset_amt = sum(df_stock["재고금액"])

        col1, col2, col3 = st.columns([2, 2, 2])
        col1.metric("전체 등록 품목 수", f"{total_count} 개")
        col2.metric("총 재고 자산 금액", f"{total_all_asset_amt:,.0f} 원")

        try:
            full_excel_items = []
            chunk_size = 1000
            start = 0
            while True:
                resp = db.supabase.table("items").select("*").order("item_code", desc=False).range(start, start + chunk_size - 1).execute()
                chunk_data = resp.data or []
                full_excel_items.extend(chunk_data)
                if len(chunk_data) < chunk_size:
                    break
                start += chunk_size
        except Exception:
            full_excel_items = all_items

        excel_rows = []
        for item in full_excel_items:
            icode = item.get("item_code")
            curr = safe_str_clean(item.get("currency"), "KRW")
            base_price = safe_float(item.get("unit_price"), 0.0)
            base_in_date = clean_date(item.get("in_date", str(datetime.date.today())))
            calc_qty = max(0, item_calc_stock_map.get(icode, 0))
            
            year = get_year_from_date(base_in_date)
            rate = get_exchange_rate_by_year(curr, year)
            unit_krw = round(base_price * rate)
            stock_amt = round(unit_krw * calc_qty)

            excel_rows.append({
                "Lot ID": "-",
                "품목코드": icode,
                "품명": safe_str_clean(item.get("item_name")),
                "상세번호": safe_str_clean(item.get("item_detail_no")),
                "규격/모델": safe_str_clean(item.get("model_spec")),
                "구분": safe_str_clean(item.get("category_type")),
                "분류체계": f"{safe_str_clean(item.get('category_main'))} - {safe_str_clean(item.get('category_sub'))} - 선반:{safe_str_clean(item.get('shelf_no'))}",
                "구역": safe_str_clean(item.get("zone")),
                "기기명": safe_str_clean(item.get("device_name")),
                "Maker": safe_str_clean(item.get("maker")),
                "입고일": base_in_date,
                "현재재고 / EA": calc_qty,
                "화폐단위": curr,
                "단가": base_price,
                "원화환산액 / 원": unit_krw,
                "재고금액 / 원": stock_amt,
                "비고": safe_str_clean(item.get("remark"))
            })

        df_all_excel = pd.DataFrame(excel_rows)

        out_excel = io.BytesIO()
        with pd.ExcelWriter(out_excel, engine="openpyxl") as writer:
            df_all_excel.to_excel(writer, index=False, sheet_name="전체재고현황")
            
        col3.write("")
        col3.download_button("📥 전체 품목 엑셀 다운로드 (.xlsx)", out_excel.getvalue(), file_name=f"ERP_전체재고현황_{datetime.date.today()}.xlsx")

        display_df = df_stock.drop(columns=["대분류"], errors="ignore").copy()
        if "현재재고" in display_df.columns:
            display_df["현재재고"] = display_df["현재재고"].apply(lambda x: f"{x} 개")
        if "원화환산액" in display_df.columns:
            display_df["원화환산액"] = display_df["원화환산액"].apply(lambda x: f"{x:,} 원")
        if "재고금액" in display_df.columns:
            display_df["재고금액"] = display_df["재고금액"].apply(lambda x: f"{x:,} 원")

        selection_event = st.dataframe(
            display_df,
            column_config={
                "사진": st.column_config.ImageColumn("사진"),
                "단가": st.column_config.NumberColumn(format="%,.2f")
            },
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row"
        )

        st.markdown("---")
        st.subheader("📄 자재품목명세서 출력 및 조회")
        selected_code = None
        selected_rows = selection_event.selection.rows if selection_event and hasattr(selection_event, "selection") else []
        
        if selected_rows and selected_rows[0] < len(df_stock):
            selected_code = df_stock.iloc[selected_rows[0]]["품목코드"]

        item_list = {f"[{i['item_code']}] {i['item_name']}": i["item_code"] for i in all_items}
        
        if item_list:
            default_idx = list(item_list.values()).index(selected_code) if selected_code in item_list.values() else 0
            sel_label = st.selectbox("📋 상세 명세서 조회 품목 선택:", list(item_list.keys()), index=default_idx)
            render_a4_spec_card(item_list[sel_label])
    else:
        st.info("조건에 일치하는 품목 데이터가 없습니다.")

# ---------------------------------------------------------
# 메뉴 2: 입출고 등록
# ---------------------------------------------------------
elif menu == MENU_TRANS:
    st.subheader("📝 자재 입출고 등록 및 이력 관리")

    tab_t1, tab_t2 = st.tabs(["✍️ 신규 입출고 등록", "✏️ 기존 입출고 내역 수정 및 삭제"])

    with tab_t1:
        search_kw_trans = st.text_input("🔍 대상 품목 통합 검색 (품명, 코드, 상세번호, 규격, 비고 등)", "", key="trans_search_box")
        
        try:
            t_query = db.supabase.table("items").select("*").order("item_code", desc=False)
            if search_kw_trans.strip():
                kw = search_kw_trans.strip()
                t_query = t_query.or_(f"item_code.ilike.%{kw}%,item_name.ilike.%{kw}%,item_detail_no.ilike.%{kw}%,model_spec.ilike.%{kw}%,remark.ilike.%{kw}%")
            items_list = t_query.limit(100).execute().data or []
        except Exception:
            items_list = []

        if not items_list:
            st.warning("조건에 일치하는 품목이 없습니다. 검색어를 다시 확인해 주세요.")
        else:
            if not search_kw_trans.strip():
                st.info("💡 데이터가 많아 기본적으로 상위 100개 품목을 표시합니다. 찾으시는 품목이 없다면 위 검색창에 품명이나 코드를 입력해 주세요.")

            item_opts = {f"[{i['item_code']}] {i['item_name']} (상세: {i.get('item_detail_no','-')}, 규격: {i.get('model_spec','-')})": i for i in items_list}
            
            selected_label = st.selectbox("🎯 대상 품목 선택", list(item_opts.keys()), key="trans_select")
            target_item = item_opts[selected_label]
            item_code = target_item["item_code"]

            if "trans_form_data" not in st.session_state:
                st.session_state.trans_form_data = {}

            with st.form("trans_form"):
                st.markdown("#### 📌 입출고 구분 선택")
                
                st.markdown("""
                <style>
                div.row-widget.stRadio > div { display: flex; gap: 20px; }
                div.row-widget.stRadio > div > label:nth-child(1) {
                    background-color: #E8F5E9 !important; border: 2px solid #66BB6A !important;
                    padding: 14px 25px !important; border-radius: 10px !important;
                    font-size: 17px !important; font-weight: bold !important; color: #1B5E20 !important;
                    flex: 1; text-align: center; cursor: pointer;
                }
                div.row-widget.stRadio > div > label:nth-child(2) {
                    background-color: #FFEBEE !important; border: 2px solid #EF5350 !important;
                    padding: 14px 25px !important; border-radius: 10px !important;
                    font-size: 17px !important; font-weight: bold !important; color: #B71C1C !important;
                    flex: 1; text-align: center; cursor: pointer;
                }
                </style>
                """, unsafe_allow_html=True)

                col1, col2 = st.columns(2)
                trans_type = col1.radio("입출고 구분", ["입고", "출고"], index=0, horizontal=True)
                trans_date = col2.date_input("일자", datetime.date.today())

                col3, col4 = st.columns(2)
                quantity = col3.number_input("수량", min_value=1, value=1, step=1)
                unit_price = col4.number_input(f"적용 단가 ({target_item.get('currency', 'KRW')})", min_value=0.0, value=safe_float(target_item.get("unit_price")), step=100.0)

                col5, col6 = st.columns(2)
                current_user_str = f"{user['name']}"
                manager = col5.text_input("담당자 (작성자)", value=current_user_str)
                requester = col6.text_input("출고/입고 요청자 (*필수)")

                remark = st.text_input("비고 (용도, 출처 등)")
                form_submitted = st.form_submit_button("입출고 저장 실행")

                if form_submitted:
                    if not requester:
                        st.error("요청자는 필수 입력 항목입니다.")
                    else:
                        parsed_type = "입고" if trans_type == "입고" else "출고"
                        st.session_state.trans_form_data = {
                            "item_code": item_code,
                            "item_name": target_item["item_name"],
                            "category": target_item.get("category_type", "일반"),
                            "trans_type": parsed_type,
                            "trans_date": str(trans_date),
                            "quantity": quantity,
                            "unit_price": unit_price,
                            "manager": manager,
                            "requester": requester,
                            "remark": remark,
                            "currency": target_item.get('currency', 'KRW')
                        }
                        st.session_state.show_confirm_dialog = True

            @st.dialog("⚠️ 최종 입출고 실행 확인")
            def confirm_trans_dialog():
                data = st.session_state.trans_form_data
                if not data:
                    st.rerun()
                
                t_type = data.get("trans_type")
                if t_type == "입고":
                    st.success("다음 내용으로 [입고] 처리를 최종 실행하시겠습니까?")
                else:
                    st.error("다음 내용으로 [출고] 처리를 최종 실행하시겠습니까?")

                st.markdown("---")
                st.write(f"- **품목코드:** `{data.get('item_code')}`")
                st.write(f"- **품명:** **{data.get('item_name')}**")
                st.write(f"- **구분:** **{t_type}**")
                st.write(f"- **수량:** {data.get('quantity'):,} 개")
                st.write(f"- **적용단가:** {data.get('unit_price'):,.2f} {data.get('currency')}")
                st.write(f"- **요청자:** {data.get('requester')}")
                st.write(f"- **비고:** {data.get('remark', '-')}")
                st.markdown("---")

                col_d1, col_d2 = st.columns(2)
                if col_d1.button("✅ 최종 확인 및 실행", type="primary", use_container_width=True):
                    with st.spinner("⏳ 입출고 데이터를 최종 처리 중입니다..."):
                        if t_type == "입고":
                            db.register_inbound_lot(
                                item_code=data.get("item_code"),
                                item_name=data.get("item_name"),
                                category=data.get("category"),
                                inbound_date=data.get("trans_date"),
                                unit_price=data.get("unit_price"),
                                quantity=data.get("quantity"),
                                manager=data.get("manager"),
                                requester=data.get("requester"),
                                remark=data.get("remark")
                            )
                            st.success(f"✅ [{data.get('item_code')}] {data.get('quantity')}개 입고 등록 완료!")
                        else:
                            db.process_fifo_outbound(
                                item_code=data.get("item_code"),
                                outbound_qty=data.get("quantity"),
                                trans_date=data.get("trans_date"),
                                requester=data.get("requester"),
                                manager=data.get("manager"),
                                remark=data.get("remark"),
                                unit_price=data.get("unit_price")
                            )
                            st.success(f"✅ [{data.get('item_code')}] {data.get('quantity')}개 출고 처리 완료!")
                        
                        st.session_state.show_confirm_dialog = False
                        st.session_state.trans_form_data = {}
                        st.rerun()

                if col_d2.button("❌ 취소", use_container_width=True):
                    st.session_state.show_confirm_dialog = False
                    st.rerun()

            if st.session_state.get("show_confirm_dialog", False):
                confirm_trans_dialog()

            st.markdown("---")
            st.subheader(f"📄 선택 품목 [{item_code}] 실시간 상세 명세서")
            render_a4_spec_card(item_code)

    with tab_t2:
        st.markdown("#### ✏️ 기존 입출고 트랜잭션 내역 수정 및 삭제")
        col_ed1, col_ed2, col_ed3 = st.columns([2, 1, 1])
        edit_trans_kw = col_ed1.text_input("🔍 내역 검색 (품목코드, 요청자, 담당자, 비고)", "", key="edit_trans_search")
        edit_start_date = col_ed2.date_input("조회 시작일", value=datetime.date.today() - datetime.timedelta(days=180), key="edit_start")
        edit_end_date = col_ed3.date_input("조회 종료일", value=datetime.date.today(), key="edit_end")

        try:
            et_query = db.supabase.table("stock_transactions").select("*").neq("requester", "초기재고일괄등록").neq("requester", "시스템입고").neq("requester", "-").order("trans_date", desc=False)
            all_trans_list = et_query.limit(500).execute().data or []
        except Exception:
            all_trans_list = []

        filtered_edit_list = []
        for t in all_trans_list:
            t_date_str = str(t.get("trans_date", "")).split(" ")[0]
            try:
                t_dt = datetime.datetime.strptime(t_date_str, "%Y-%m-%d").date()
            except:
                t_dt = datetime.date.today()

            if not (edit_start_date <= t_dt <= edit_end_date):
                continue

            if edit_trans_kw.strip():
                ekw = edit_trans_kw.strip().lower()
                matched = ekw in str(t.get("item_code","")).lower() or ekw in str(t.get("requester","")).lower() or ekw in str(t.get("manager","")).lower() or ekw in str(t.get("remark","")).lower()
                if not matched:
                    continue
            filtered_edit_list.append(t)

        if filtered_edit_list:
            trans_opts = {f"[ID:{t.get('id')}] {t.get('trans_date')} | 코드:{t.get('item_code')} | 구분:{t.get('trans_type')} | 수량:{t.get('quantity')}개 | 요청자:{t.get('requester')}": t for t in filtered_edit_list}
            sel_trans_label = st.selectbox("수정/삭제할 내역 선택:", list(trans_opts.keys()))
            target_t = trans_opts[sel_trans_label]

            with st.form("edit_trans_form"):
                col1, col2 = st.columns(2)
                current_t_type = target_t.get("trans_type", "IN")
                default_radio_idx = 0 if current_t_type in ["IN", "입고"] else 1
                
                e_type_radio = col1.radio("입출고 구분", ["입고", "출고"], index=default_radio_idx, horizontal=True)
                
                try:
                    default_d = datetime.datetime.strptime(str(target_t.get("trans_date", "")).split(" ")[0], "%Y-%m-%d").date()
                except:
                    default_d = datetime.date.today()
                e_date = col2.date_input("일자", value=default_d)

                col3, col4 = st.columns(2)
                e_qty = col3.number_input("수량", min_value=1, value=safe_int_clean(target_t.get("quantity"), 1), step=1)
                e_price = col4.number_input("적용 단가", min_value=0.0, value=safe_float(target_t.get("unit_price"), 0.0), step=100.0)

                col5, col6 = st.columns(2)
                e_mgr = col5.text_input("담당자", value=safe_str_clean(target_t.get("manager"), ""))
                e_req = col6.text_input("요청자", value=safe_str_clean(target_t.get("requester"), ""))

                e_rem = st.text_input("비고", value=safe_str_clean(target_t.get("remark"), ""))

                col_btn1, col_btn2 = st.columns(2)
                submitted_update = col_btn1.form_submit_button("💾 수정 내용 저장")
                submitted_delete = col_btn2.form_submit_button("🗑️ 해당 내역 삭제")

                if submitted_update:
                    save_type_code = "IN" if e_type_radio == "입고" else "OUT"
                    with st.spinner("⏳ 입출고 내역 수정 중..."):
                        db.update_transaction(
                            trans_id=target_t.get("id"),
                            item_code=target_t.get("item_code"),
                            trans_type=save_type_code,
                            trans_date=str(e_date),
                            quantity=e_qty,
                            unit_price=e_price,
                            manager=e_mgr,
                            requester=e_req,
                            remark=e_rem
                        )
                        st.success("✅ 선택한 입출고 내역이 성공적으로 수정되었습니다!")
                        st.rerun()

                if submitted_delete:
                    with st.spinner("⏳ 입출고 내역 삭제 중..."):
                        db.delete_transaction(target_t.get("id"))
                        st.success("✅ 선택한 입출고 내역이 삭제되었습니다!")
                        st.rerun()
        else:
            st.info("선택한 기간 또는 검색 조건에 일치하는 입출고 내역이 없습니다.")

# ---------------------------------------------------------
# 메뉴 3: 품목 관리
# ---------------------------------------------------------
elif menu == MENU_ITEMS:
    st.subheader("🏷️ 품목 등록 및 수정 관리")
    tab1, tab2, tab3 = st.tabs(["✍️ 개별 직접 등록", "✏️ 기존 품목 수정", "📂 기초 데이터 엑셀 일괄 등록"])

    with tab1:
        with st.form("new_item_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            item_code = col1.text_input("품목코드 (공란 시 자동 채번)", value="")
            item_name = col2.text_input("품명 * (*필수)")
            item_detail_no = col3.text_input("아이템상세번호")

            col4, col5, col6 = st.columns(3)
            model_spec = col4.text_input("모델번호_규격")
            category_type = col5.text_input("구분")
            category_main = col6.text_input("대분류")

            col7, col8, col9 = st.columns(3)
            category_sub = col7.text_input("소분류")
            shelf_no = col8.text_input("선반번호")
            zone = col9.text_input("해당구역")

            col10, col11, col12 = st.columns(3)
            device_name = col10.text_input("기기명")
            maker = col11.text_input("Maker")
            useful_life = col12.text_input("내구연한")

            col13, col14, col15, col16 = st.columns(4)
            in_date = col13.text_input("입고일", value=str(datetime.date.today()))
            currency = col14.selectbox("화폐", ["KRW", "USD", "EUR", "JPY"])
            unit_price = col15.number_input("기초 단가 *", min_value=0.0, value=0.0)
            initial_qty = col16.number_input("초기 수량 *", min_value=0, value=0, step=1, format="%d")

            remark = st.text_input("비고")
            img_file = st.file_uploader("품목 사진 첨부", type=["png", "jpg", "jpeg"])

            if st.form_submit_button("신규 품목 및 초기 수량 저장"):
                if not item_name.strip():
                    st.error("❌ 품명은 필수 입력 항목입니다.")
                else:
                    with st.spinner("⏳ 데이터 저장 중..."):
                        code_input = str(item_code).strip() if item_code else ""
                        if code_input and code_input.lower() not in ["nan", "null", "none", "", "-"]:
                            final_code = code_input
                        else:
                            final_code = generate_next_item_code()

                        photo_url = db.upload_item_image(img_file, final_code) if img_file else None
                        
                        item_data = {
                            "item_code": final_code,
                            "item_name": safe_str_clean(item_name),
                            "item_detail_no": safe_str_clean(item_detail_no),
                            "model_spec": safe_str_clean(model_spec),
                            "category_type": safe_str_clean(category_type),
                            "category_main": safe_str_clean(category_main),
                            "category_sub": safe_str_clean(category_sub),
                            "shelf_no": safe_str_clean(shelf_no),
                            "zone": safe_str_clean(zone),
                            "device_name": safe_str_clean(device_name),
                            "maker": safe_str_clean(maker),
                            "useful_life": safe_str_clean(useful_life),
                            "in_date": clean_date(in_date),
                            "currency": currency,
                            "unit_price": float(unit_price),
                            "remark": safe_str_clean(remark)
                        }
                        if photo_url: 
                            item_data["photo_url"] = photo_url
                        
                        try:
                            db.supabase.table("items").insert(item_data).execute()
                            if initial_qty >
