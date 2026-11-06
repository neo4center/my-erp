import datetime
import html
import io
import math
import os
import re
import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import db_helper as db

# Streamlit 기본 설정
st.set_page_config(page_title="광주오포센터 자동화 ERP", layout="wide")

# ---------------------------------------------------------
# 1. 헬퍼 함수
# ---------------------------------------------------------
POSITIONS = ["팀장", "부팀장", "마스터", "과장", "대리", "주임", "사원", "게스트"]

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

def parse_standard_date(date_str):
    if not date_str:
        return datetime.date.today()
    s = str(date_str).strip().split("T")[0].split(" ")[0]
    parts = re.split(r'[-./]', s)
    if len(parts) == 3:
        p1, p2, p3 = parts[0], parts[1], parts[2]
        try:
            year = 2000 + int(p1) if len(p1) == 2 and int(p1) < 50 else (1900 + int(p1) if len(p1) == 2 else int(p1))
            month = int(p2)
            day = int(p3)
            return datetime.date(year, month, day)
        except:
            pass
    return datetime.date.today()

def clean_val(val, default="-"):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip().replace('"', "")
    return html.escape(s) if s and s.lower() not in ["nan", "none", ""] else default

def get_image_base64(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode("utf-8")
    except Exception:
        return ""

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
    dt = parse_standard_date(date_str)
    return dt.year

@st.cache_data(ttl=600)
def get_cached_exchange_rates():
    try:
        resp = db.supabase.table("exchange_rates").select("*").execute()
        rates_map = {}
        for r in (resp.data or []):
            year_val = safe_int_clean(r.get("year"), 0)
            curr_val = str(r.get("currency", "")).upper().strip()
            rate_val = safe_float(r.get("rate"), 1.0)
            if year_val > 0 and curr_val:
                rates_map[(year_val, curr_val)] = rate_val
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

def render_a4_spec_card(item_code, is_guest_user=False):
    item_resp = db.supabase.table("items").select("*").eq("item_code", item_code).execute()
    if not item_resp.data:
        return
    item = item_resp.data[0]

    trans_resp = db.supabase.table("stock_transactions").select("*").eq("item_code", item_code).order("id", desc=False).execute()
    trans_data = trans_resp.data or []
    
    st.markdown("""
    <div style="background-color: #f1f8e9; border: 1px solid #c5e1a5; padding: 12px 18px; border-radius: 8px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 15px; font-weight: bold; color: #33691e;">📅 자재품목명세서 입출고 기간 필터 선택 및 인쇄</span>
    </div>
    """, unsafe_allow_html=True)

    col_pr1, col_pr2 = st.columns([3, 1])
    spec_period_opt = col_pr1.radio(
        "조회 기간 선택",
        ["전체", "3개월", "6개월", "1년", "기간설정"],
        index=0,
        horizontal=True,
        key=f"spec_period_radio_{item_code}"
    )

    with col_pr2:
        st.write("")
        print_clicked = st.button("🖨️ 명세서 프린트 (인쇄)", key=f"print_btn_{item_code}", use_container_width=True, type="primary")

    today_dt = datetime.date.today()
    if spec_period_opt == "3개월":
        filter_start_dt = today_dt - datetime.timedelta(days=90)
        filter_end_dt = today_dt
    elif spec_period_opt == "6개월":
        filter_start_dt = today_dt - datetime.timedelta(days=180)
        filter_end_dt = today_dt
    elif spec_period_opt == "1년":
        filter_start_dt = today_dt - datetime.timedelta(days=365)
        filter_end_dt = today_dt
    elif spec_period_opt == "기간설정":
        cc1, cc2 = st.columns(2)
        filter_start_dt = cc1.date_input("시작일", value=today_dt - datetime.timedelta(days=180), key=f"spec_start_{item_code}")
        filter_end_dt = cc2.date_input("종료일", value=today_dt, key=f"spec_end_{item_code}")
    else:
        filter_start_dt = datetime.date(2020, 1, 1)
        filter_end_dt = today_dt

    period_badge_text = f"전체 기간 (~{today_dt})" if spec_period_opt == "전체" else f"선택 기간: {filter_start_dt} ~ {filter_end_dt}"

    calc_stock = 0
    in_rows, out_rows = [], []
    in_idx, out_idx = 1, 1
    total_in_qty, total_in_amt = 0, 0
    total_out_qty, total_out_amt = 0, 0
    
    curr = safe_str_clean(item.get("currency"), "KRW")
    base_price = safe_float(item.get("unit_price"), 0.0)
    base_in_date = clean_date(item.get("in_date", str(datetime.date.today())))
    
    latest_in_price = base_price
    latest_in_date = base_in_date
    latest_dt_obj = parse_standard_date(base_in_date)
    
    for t in trans_data:
        t_type = str(t.get("trans_type", "")).strip().upper()
        if t_type in ["IN", "입고"]:
            t_price = safe_float(t.get("unit_price"), 0.0)
            t_date_str = clean_date(t.get("trans_date", ""))
            t_dt_obj = parse_standard_date(t_date_str)
            if t_price > 0:
                if t_dt_obj >= latest_dt_obj:
                    latest_dt_obj = t_dt_obj
                    latest_in_date = t_date_str
                    latest_in_price = t_price

    representative_price = latest_in_price
    representative_year = latest_dt_obj.year
    representative_rate = get_exchange_rate_by_year(curr, representative_year)

    active_lots = []

    for t in trans_data:
        t_type = str(t.get("trans_type", "")).strip().upper()
        qty = safe_int_clean(t.get("quantity"), 0)
        price = safe_float(t.get("unit_price"), base_price)
        t_date_str = clean_date(t.get("trans_date", ""))
        t_dt_parsed = parse_standard_date(t_date_str)
        t_year = t_dt_parsed.year
        t_rate = get_exchange_rate_by_year(curr, t_year)

        in_range = (filter_start_dt <= t_dt_parsed <= filter_end_dt)

        if t_type in ["IN", "입고"]:
            active_lots.append({"qty": qty, "price": price, "rate": t_rate, "year": t_year})
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
                raw_req = "-"

            t_remark = safe_str_clean(t.get("remark"), "")
            if not t_remark or t_remark in ["-", "None", ""]:
                t_remark = safe_str_clean(item.get("remark"), "-")

            if is_guest_user:
                row_dict = {
                    "No": in_idx, "일자": t_date_str, "구분": "입고 (IN)",
                    "수량": f"{qty:,} 개", "원화환산액": "🔒 (비공개)", "총금액": "🔒 (비공개)",
                    "담당자": raw_mgr, "요청자": raw_req, "비고": t_remark
                }
            else:
                row_dict = {
                    "No": in_idx, "일자": t_date_str, "구분": "입고 (IN)",
                    "수량": f"{qty:,} 개", "원화환산액": f"{round(t_krw_unit):,} 원", "총금액": f"{total_row_amt:,} 원",
                    "담당자": raw_mgr, "요청자": raw_req, "비고": t_remark
                }

            if in_range:
                in_rows.append(row_dict)
                total_in_qty += qty
                total_in_amt += total_row_amt
            calc_stock += qty
            in_idx += 1

        elif t_type in ["OUT", "출고"]:
            remaining_out = qty
            consumed_lots_info = []
            
            while remaining_out > 0 and active_lots:
                lot = active_lots[0]
                if lot["qty"] <= remaining_out:
                    consumed_qty = lot["qty"]
                    remaining_out -= consumed_qty
                    active_lots.pop(0)
                    consumed_lots_info.append((consumed_qty, lot["price"], lot["rate"]))
                else:
                    consumed_qty = remaining_out
                    lot["qty"] -= consumed_qty
                    remaining_out = 0
                    consumed_lots_info.append((consumed_qty, lot["price"], lot["rate"]))
            
            if remaining_out > 0:
                consumed_lots_info.append((remaining_out, representative_price, representative_rate))
            
            total_consumed_qty = sum(q for q, p, r in consumed_lots_info)
            if total_consumed_qty > 0:
                t_krw_unit = sum(q * p * r for q, p, r in consumed_lots_info) / total_consumed_qty
            else:
                t_krw_unit = representative_price * representative_rate

            total_row_amt = round(qty * t_krw_unit)

            raw_mgr = safe_str_clean(t.get("manager"), "")
            if not raw_mgr or raw_mgr in ["-", "None", ""]:
                raw_mgr = "최광호"
            else:
                for pos in POSITIONS:
                    raw_mgr = raw_mgr.replace(pos, "").strip()
            
            raw_req = safe_str_clean(t.get("requester"), "-")
            if raw_req in ["-", "초기재고일괄등록", "시스템입고", "None", ""]:
                raw_req = "출고담당자"

            t_remark = safe_str_clean(t.get("remark"), "")
            if not t_remark or t_remark in ["-", "None", ""]:
                t_remark = safe_str_clean(item.get("remark"), "-")

            if is_guest_user:
                row_dict = {
                    "No": out_idx, "일자": t_date_str, "구분": "출고 (OUT)",
                    "수량": f"{qty:,} 개", "원화환산액": "🔒 (비공개)", "총금액": "🔒 (비공개)",
                    "담당자": raw_mgr, "요청자": raw_req, "비고": t_remark
                }
            else:
                row_dict = {
                    "No": out_idx, "일자": t_date_str, "구분": "출고 (OUT)",
                    "수량": f"{qty:,} 개", "원화환산액": f"{round(t_krw_unit):,} 원", "총금액": f"{total_row_amt:,} 원",
                    "담당자": raw_mgr, "요청자": raw_req, "비고": t_remark
                }

            if in_range:
                out_rows.append(row_dict)
                total_out_qty += qty
                total_out_amt += total_row_amt
            calc_stock -= qty
            out_idx += 1

    current_stock = max(0, calc_stock)
    total_val_krw = round(current_stock * (representative_price * representative_rate))
    unit_krw_display = int(round(representative_price * representative_rate))

    category_full = f"{safe_str_clean(item.get('category_main'))} - {safe_str_clean(item.get('category_sub'))} - 선반:{safe_str_clean(item.get('shelf_no'))}"
    net_stock_valuation = total_in_amt - total_out_amt

    # 인쇄 전용 CSS 스타일 적용 (브라우저 직접 인쇄 지원)
    st.markdown("""
    <style>
    .a4-card { background-color: #ffffff; border: 2px solid #333; border-radius: 8px; padding: 25px; margin-top: 10px; color: #111; }
    .a4-header { text-align: center; border-bottom: 3px double #333; padding-bottom: 10px; margin-bottom: 20px; }
    .info-table, .trans-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; }
    .info-table th, .info-table td, .trans-table th, .trans-table td { border: 1px solid #ccc; padding: 8px 12px; font-size: 13px; text-align: center; }
    .info-table th { background-color: #f4f4f4; font-weight: bold; width: 18%; }
    .trans-table th { background-color: #f8f9fa; font-weight: bold; }
    .stock-calc-banner { background-color: #E3F2FD; border: 2px solid #2196F3; border-radius: 8px; padding: 15px; text-align: center; font-size: 16px; font-weight: bold; color: #0D47A1; margin: 20px 0; }
    .table-scroll-container { max-height: 380px; overflow-y: auto; border: 1px solid #ccc; margin-bottom: 15px; }

    @media print {
        body * {
            visibility: hidden !important;
        }
        .printable-spec-area, .printable-spec-area * {
            visibility: visible !important;
        }
        .printable-spec-area {
            position: absolute !important;
            left: 0 !important;
            top: 0 !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 10px !important;
            border: none !important;
            box-shadow: none !important;
            background-color: white !important;
        }
        header, footer, nav, .stSidebar, .stButton {
            display: none !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    photo_url = item.get("photo_url")

    if is_guest_user:
        info_table_html = f"""
        <table class="info-table">
            <tr><th>품목코드</th><td><code>{clean_val(item.get('item_code'))}</code></td><th>품명</th><td><b>{clean_val(item.get('item_name'))}</b></td></tr>
            <tr><th>상세번호</th><td>{clean_val(item.get('item_detail_no'))}</td><th>규격/모델</th><td>{clean_val(item.get('model_spec'))}</td></tr>
            <tr><th>구분</th><td>{clean_val(item.get('category_type'))}</td><th>분류체계</th><td>{category_full}</td></tr>
            <tr><th>설치구역/기기</th><td>{clean_val(item.get('zone'))} / {clean_val(item.get('device_name'))}</td><th>Maker</th><td>{clean_val(item.get('maker'))}</td></tr>
            <tr><th>화폐단위/단가</th><td>🔒 (비공개)</td><th>적용 환율({representative_year}년)</th><td>🔒 (비공개)</td></tr>
            <tr><th>원화환산액</th><td><b>🔒 (비공개)</b></td><th>현재재고 / 재고금액</th><td><b>{current_stock:,} 개 / 🔒 (비공개)</b></td></tr>
            <tr><th>비고</th><td colspan="3">{clean_val(item.get('remark'))}</td></tr>
        </table>
        """
        in_amt_str = "🔒 (비공개)"
        out_amt_str = "🔒 (비공개)"
    else:
        info_table_html = f"""
        <table class="info-table">
            <tr><th>품목코드</th><td><code>{clean_val(item.get('item_code'))}</code></td><th>품명</th><td><b>{clean_val(item.get('item_name'))}</b></td></tr>
            <tr><th>상세번호</th><td>{clean_val(item.get('item_detail_no'))}</td><th>규격/모델</th><td>{clean_val(item.get('model_spec'))}</td></tr>
            <tr><th>구분</th><td>{clean_val(item.get('category_type'))}</td><th>분류체계</th><td>{category_full}</td></tr>
            <tr><th>설치구역/기기</th><td>{clean_val(item.get('zone'))} / {clean_val(item.get('device_name'))}</td><th>Maker</th><td>{clean_val(item.get('maker'))}</td></tr>
            <tr><th>화폐단위/단가</th><td>{curr} / {representative_price:,.2f}</td><th>적용 환율({representative_year}년)</th><td>{representative_rate:,.2f} 원</td></tr>
            <tr><th>원화환산액</th><td><b>{unit_krw_display:,} 원</b> (최신단가적용)</td><th>현재재고 / 재고금액</th><td><b>{current_stock:,} 개 / {total_val_krw:,} 원</b></td></tr>
            <tr><th>비고</th><td colspan="3">{clean_val(item.get('remark'))}</td></tr>
        </table>
        """
        in_amt_str = f"{total_in_amt:,} 원"
        out_amt_str = f"{total_out_amt:,} 원"

    # 프린트 버튼 클릭 시 JavaScript window.print() 즉시 실행
    if print_clicked:
        components.html("""
            <script>
                window.parent.print();
            </script>
        """, height=0)

    with st.container():
        # 인쇄 대상 지정 래퍼 클래스 적용 (.printable-spec-area)
        st.markdown("<div class='a4-card printable-spec-area'>", unsafe_allow_html=True)
        st.markdown(f"<div class='a4-header'><h2>자재품목명세서</h2><p>발행일자: {datetime.date.today()} &nbsp;|&nbsp; <span style='color: #d81b60; font-weight: bold;'>({period_badge_text})</span></p></div>", unsafe_allow_html=True)
        col_img, col_info = st.columns([1, 3])

        with col_img:
            if photo_url:
                st.image(photo_url, caption=str(item.get("item_name")), use_container_width=True)
            else:
                st.info("등록된 사진 없음")

        with col_info:
            st.markdown(info_table_html, unsafe_allow_html=True)

        st.markdown("---")

        if not is_guest_user:
            st.markdown(f"""
            <div class="stock-calc-banner">
                📦 [재고금액 산출] : {total_in_amt:,} 원 (기간 내 입고 총금액) - {total_out_amt:,} 원 (기간 내 출고 총금액) = <span style="color: #D32F2F;">{net_stock_valuation:,} 원</span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("---")
        
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
            <h3 style="margin: 0; font-size: 18px;">📥 1. 입고 내역 <span style="font-size: 14px; color: #33691e; font-weight: bold;">({period_badge_text})</span></h3>
            <span style="font-weight: bold; color: #1B5E20; font-size: 14px;">합계 수량: {total_in_qty:,} 개 &nbsp;|&nbsp; 총 금액: {in_amt_str}</span>
        </div>
        """, unsafe_allow_html=True)

        if in_rows:
            in_table_html = "<div class='table-scroll-container'><table class='trans-table'><thead><tr style='background-color: #f8f9fa;'><th>No</th><th>일자</th><th>구분</th><th>수량</th><th>원화환산액</th><th>총금액</th><th>담당자</th><th>요청자</th><th>비고</th></tr></thead><tbody>"
            for r in in_rows:
                in_table_html += f"<tr><td>{r['No']}</td><td>{r['일자']}</td><td>{r['구분']}</td><td>{r['수량']}</td><td>{r['원화환산액']}</td><td>{r['총금액']}</td><td>{r['담당자']}</td><td>{r['요청자']}</td><td>{r['비고']}</td></tr>"
            in_table_html += "</tbody></table></div>"
            st.markdown(in_table_html, unsafe_allow_html=True)
        else:
            st.caption("※ 선택한 기간 내 입고 내역이 없습니다.")

        st.markdown("---")

        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
            <h3 style="margin: 0; font-size: 18px;">📤 2. 출고 내역 <span style="font-size: 14px; color: #33691e; font-weight: bold;">({period_badge_text})</span></h3>
            <span style="font-weight: bold; color: #B71C1C; font-size: 14px;">합계 수량: {total_out_qty:,} 개 &nbsp;|&nbsp; 총 금액: {out_amt_str}</span>
        </div>
        """, unsafe_allow_html=True)

        if out_rows:
            out_table_html = "<div class='table-scroll-container'><table class='trans-table'><thead><tr style='background-color: #f8f9fa;'><th>No</th><th>일자</th><th>구분</th><th>수량</th><th>원화환산액</th><th>총금액</th><th>담당자</th><th>요청자</th><th>비고</th></tr></thead><tbody>"
            for r in out_rows:
                out_table_html += f"<tr><td>{r['No']}</td><td>{r['일자']}</td><td>{r['구분']}</td><td>{r['수량']}</td><td>{r['원화환산액']}</td><td>{r['총금액']}</td><td>{r['담당자']}</td><td>{r['요청자']}</td><td>{r['비고']}</td></tr>"
            out_table_html += "</tbody></table></div>"
            st.markdown(out_table_html, unsafe_allow_html=True)
        else:
            st.caption("※ 선택한 기간 내 출고 내역이 없습니다.")

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

    st.markdown("---")
    st.markdown("### 📖 시스템 사용 매뉴얼 및 가이드")
    
    if os.path.exists("manual.pptx"):
        with open("manual.pptx", "rb") as file:
            st.download_button(
                label="📥 매뉴얼 PPT 파일 다운로드 (.pptx)",
                data=file,
                file_name="광주오포센터_ERP_사용매뉴얼.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True
            )
    else:
        st.info("💡 'manual.pptx' 파일이 루트 디렉터리에 업로드되면 다운로드 버튼이 활성화됩니다.")

    with st.expander("🖼️ 웹에서 카드형 매뉴얼 슬라이드 바로 보기"):
        slide_images = []
        for i in range(1, 25):
            img_path_lower = f"assets/slide_{i}.png"
            img_path_upper = f"assets/slide_{i}.PNG"
            
            if os.path.exists(img_path_lower):
                slide_images.append(img_path_lower)
            elif os.path.exists(img_path_upper):
                slide_images.append(img_path_upper)
            else:
                break
        
        if slide_images:
            if "slide_idx" not in st.session_state:
                st.session_state.slide_idx = 0

            col_prev, col_info, col_next = st.columns([1, 2, 1])
            
            if col_prev.button("◀ 이전 슬라이드") and st.session_state.slide_idx > 0:
                st.session_state.slide_idx -= 1
                st.rerun()
                
            col_info.markdown(f"<p style='text-align: center; font-weight: bold; margin-top: 10px;'>페이지 {st.session_state.slide_idx + 1} / {len(slide_images)}</p>", unsafe_allow_html=True)
            
            if col_next.button("다음 슬라이드 ▶") and st.session_state.slide_idx < len(slide_images) - 1:
                st.session_state.slide_idx += 1
                st.rerun()

            img_base64 = get_image_base64(slide_images[st.session_state.slide_idx])
            st.markdown(
                f"""
                <div style="display: flex; justify-content: center; margin-top: 15px; margin-bottom: 20px;">
                    <img src="data:image/png;base64,{img_base64}" style="max-width: 650px; width: 100%; border: 1px solid #ddd; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.caption("ℹ️ 'assets/' 폴더에 `slide_1.png` 또는 `slide_1.PNG` 형식으로 매뉴얼 이미지를 업로드하시면 카드형 슬라이드 뷰어가 활성화됩니다.")

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

is_guest = (str(user.get("position")).strip() == "게스트" or user.get("is_admin") == 2)

if is_guest:
    menu_list = [MENU_STOCK, MENU_HISTORY]
else:
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
            resp = db.supabase.table("items").select("*").order("item_code", desc=False).range(start, start + chunk_size - 1).execute()
            chunk_data = resp.data or []
            all_items.extend(chunk_data)
            if len(chunk_data) < chunk_size:
                break
            start += chunk_size
    except Exception:
        all_items = []

    if search_kw.strip():
        kw = search_kw.strip().lower()
        filtered_items = []
        for item in all_items:
            if (kw in str(item.get("item_code", "")).lower() or
                kw in str(item.get("item_name", "")).lower() or
                kw in str(item.get("item_detail_no", "")).lower() or
                kw in str(item.get("model_spec", "")).lower() or
                kw in str(item.get("remark", "")).lower() or
                kw in str(item.get("device_name", "")).lower() or
                kw in str(item.get("maker", "")).lower()):
                filtered_items.append(item)
        all_items = filtered_items
    elif not is_filtering:
        PAGE_SIZE_STOCK = 100
        total_stock_pages = max(1, math.ceil(len(all_items) / PAGE_SIZE_STOCK))
        
        col_p1, _, col_p_btn = st.columns([1, 2, 2])
        with col_p1:
            current_stock_page = st.selectbox("📄 페이지 선택 (100건씩)", list(range(1, total_stock_pages + 1)), format_func=lambda x: f"{x} 페이지 (총 {total_stock_pages}페이지)")

        start_idx = (current_stock_page - 1) * PAGE_SIZE_STOCK
        end_idx = start_idx + PAGE_SIZE_STOCK
        all_items = all_items[start_idx:end_idx]
    else:
        col_p_btn = st.columns([1, 2, 2])[2]

    all_trans_resp = []
    try:
        chunk_size = 1000
        start = 0
        while True:
            resp = db.supabase.table("stock_transactions").select("item_code, trans_type, quantity, unit_price, trans_date").order("id", desc=False).range(start, start + chunk_size - 1).execute()
            chunk_data = resp.data or []
            all_trans_resp.extend(chunk_data)
            if len(chunk_data) < chunk_size:
                break
            start += chunk_size
    except Exception:
        all_trans_resp = []

    item_calc_stock_map = {}
    item_latest_price_map = {}
    item_latest_date_map = {}
    item_latest_dt_obj_map = {}

    for t in all_trans_resp:
        ic = t.get("item_code")
        if not ic:
            continue
        q = safe_int_clean(t.get("quantity"), 0)
        ttype = str(t.get("trans_type", "")).strip().upper()
        t_date = clean_date(t.get("trans_date", ""))
        t_dt_obj = parse_standard_date(t_date)
        t_price = safe_float(t.get("unit_price"), 0.0)

        if ic not in item_calc_stock_map:
            item_calc_stock_map[ic] = 0
        if ttype in ["IN", "입고"]:
            item_calc_stock_map[ic] += q
            if t_price > 0:
                curr_dt_obj = item_latest_dt_obj_map.get(ic, datetime.date(1900, 1, 1))
                if t_dt_obj >= curr_dt_obj:
                    item_latest_dt_obj_map[ic] = t_dt_obj
                    item_latest_date_map[ic] = t_date
                    item_latest_price_map[ic] = t_price
        elif ttype in ["OUT", "출고"]:
            item_calc_stock_map[ic] -= q

    table_rows = []
    for item in all_items:
        icode = item.get("item_code")
        curr = safe_str_clean(item.get("currency"), "KRW")
        base_price = safe_float(item.get("unit_price"), 0.0)
        base_in_date = clean_date(item.get("in_date", str(datetime.date.today())))
        
        latest_price = item_latest_price_map.get(icode, base_price)
        latest_date = item_latest_date_map.get(icode, base_in_date)

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
        
        year = get_year_from_date(latest_date)
        rate = get_exchange_rate_by_year(curr, year)
        unit_krw = round(latest_price * rate)
        stock_amt = round(unit_krw * calc_qty)

        if is_guest:
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
                "입고일": latest_date,
                "현재재고": calc_qty,
                "화폐단위": "🔒",
                "단가": "🔒",
                "원화환산액": "🔒",
                "재고금액": "🔒",
                "비고": remark
            })
        else:
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
                "입고일": latest_date,
                "현재재고": calc_qty,
                "화폐단위": curr,
                "단가": latest_price,
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

        current_page_asset_amt = 0 if is_guest else sum(df_stock[df_stock["재고금액"] != "🔒"]["재고금액"])

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

        total_all_asset_amt = 0
        excel_rows = []
        for item in full_excel_items:
            icode = item.get("item_code")
            curr = safe_str_clean(item.get("currency"), "KRW")
            base_price = safe_float(item.get("unit_price"), 0.0)
            base_in_date = clean_date(item.get("in_date", str(datetime.date.today())))
            
            latest_price = item_latest_price_map.get(icode, base_price)
            latest_date = item_latest_date_map.get(icode, base_in_date)
            calc_qty = max(0, item_calc_stock_map.get(icode, 0))
            
            year = get_year_from_date(latest_date)
            rate = get_exchange_rate_by_year(curr, year)
            unit_krw = round(latest_price * rate)
            stock_amt = round(unit_krw * calc_qty)
            total_all_asset_amt += stock_amt

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
                "입고일": latest_date,
                "현재재고 / EA": calc_qty,
                "화폐단위": "🔒 비공개" if is_guest else curr,
                "단가": "🔒 비공개" if is_guest else latest_price,
                "원화환산액 / 원": "🔒 비공개" if is_guest else unit_krw,
                "재고금액 / 원": "🔒 비공개" if is_guest else stock_amt,
                "비고": safe_str_clean(item.get("remark"))
            })

        df_all_excel = pd.DataFrame(excel_rows)

        out_excel = io.BytesIO()
        with pd.ExcelWriter(out_excel, engine="openpyxl") as writer:
            df_all_excel.to_excel(writer, index=False, sheet_name="전체재고현황")

        if search_kw.strip() or is_filtering:
            col_p_btn = st.columns([1, 2, 2])[2]

        with col_p_btn:
            st.write("")
            if not is_guest:
                st.download_button("📥 전체 품목 엑셀 다운로드 (.xlsx)", out_excel.getvalue(), file_name=f"ERP_전체재고현황_{datetime.date.today()}.xlsx")

        if not is_guest:
            st.markdown(f"<p style='color: #666; font-size: 13px; margin-top: -10px; margin-bottom: 15px;'>📌 현재 페이지(또는 검색결과) 재고 자산 금액: <b>{current_page_asset_amt:,.0f} 원</b></p>", unsafe_allow_html=True)

        col1, col2, _ = st.columns([2, 2, 2])
        col1.metric("전체 등록 품목 수", f"{total_count} 개")
        if not is_guest:
            col2.metric("총 재고 자산 금액", f"{total_all_asset_amt:,.0f} 원")
        else:
            col2.metric("총 재고 자산 금액", "🔒 (비공개)")

        display_df = df_stock.drop(columns=["대분류"], errors="ignore").copy()
        if "현재재고" in display_df.columns:
            display_df["현재재고"] = display_df["현재재고"].apply(lambda x: f"{x} 개")
        if not is_guest:
            if "원화환산액" in display_df.columns:
                display_df["원화환산액"] = display_df["원화환산액"].apply(lambda x: f"{x:,} 원" if isinstance(x, (int, float)) else x)
            if "재고금액" in display_df.columns:
                display_df["재고금액"] = display_df["재고금액"].apply(lambda x: f"{x:,} 원" if isinstance(x, (int, float)) else x)

        selection_event = st.dataframe(
            display_df,
            column_config={
                "사진": st.column_config.ImageColumn("사진"),
                "단가": st.column_config.NumberColumn(format="%,.2f") if not is_guest else st.column_config.TextColumn("단가")
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
            render_a4_spec_card(item_list[sel_label], is_guest_user=is_guest)
    else:
        st.info("조건에 일치하는 품목 데이터가 없습니다.")

# ---------------------------------------------------------
# 메뉴 2: 입출고 등록
# ---------------------------------------------------------
elif menu == MENU_TRANS:
    if is_guest:
        st.error("❌ 게스트 계정은 접근할 수 없는 메뉴입니다.")
        st.stop()
    st.subheader("📝 자재 입출고 등록 및 이력 관리")

    tab_t1, tab_t2 = st.tabs(["✍️ 신규 입출고 등록", "✏️ 기존 입출고 내역 수정 및 삭제"])

    with tab_t1:
        search_kw_trans = st.text_input("🔍 대상 품목 통합 검색 (품명, 코드, 상세번호, 규격, 비고 등)", "", key="trans_search_box")
        
        try:
            all_trans_items = []
            chunk_size = 1000
            start = 0
            while True:
                resp = db.supabase.table("items").select("*").order("item_code", desc=False).range(start, start + chunk_size - 1).execute()
                c_data = resp.data or []
                all_trans_items.extend(c_data)
                if len(c_data) < chunk_size:
                    break
                start += chunk_size
        except Exception:
            all_trans_items = []

        if search_kw_trans.strip():
            kw = search_kw_trans.strip().lower()
            items_list = []
            for item in all_trans_items:
                if (kw in str(item.get("item_code", "")).lower() or
                    kw in str(item.get("item_name", "")).lower() or
                    kw in str(item.get("item_detail_no", "")).lower() or
                    kw in str(item.get("model_spec", "")).lower() or
                    kw in str(item.get("remark", "")).lower()):
                    items_list.append(item)
        else:
            PAGE_SIZE_TRANS = 100
            total_trans_pages = max(1, math.ceil(len(all_trans_items) / PAGE_SIZE_TRANS))
            selected_trans_page = 1
            if total_trans_pages > 1:
                col_tp1, _ = st.columns([1, 4])
                with col_tp1:
                    selected_trans_page = st.selectbox("📄 대상 품목 페이지 선택 (100건씩)", list(range(1, total_trans_pages + 1)), format_func=lambda x: f"{x} 페이지 (총 {total_trans_pages}페이지)", key="trans_page_select")
            start_t_idx = (selected_trans_page - 1) * PAGE_SIZE_TRANS
            end_t_idx = start_t_idx + PAGE_SIZE_TRANS
            items_list = all_trans_items[start_t_idx:end_t_idx]

        if not items_list:
            st.warning("조건에 일치하는 품목이 없습니다. 검색어를 다시 확인해 주세요.")
        else:
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
        edit_start_date = col_ed2.date_input("조회 시작일", value=datetime.date(2022, 1, 1), key="edit_start")
        edit_end_date = col_ed3.date_input("조회 종료일", value=datetime.date.today(), key="edit_end")

        try:
            et_query = db.supabase.table("stock_transactions").select("*").neq("requester", "초기재고일괄등록").neq("requester", "시스템입고").neq("requester", "-").order("trans_date", desc=False)
            all_trans_list = et_query.limit(500).execute().data or []
        except Exception:
            all_trans_list = []

        filtered_edit_list = []
        for t in all_trans_list:
            t_dt = parse_standard_date(t.get("trans_date", ""))
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
                e_date = col2.date_input("일자", value=parse_standard_date(target_t.get("trans_date", "")))

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
    if is_guest:
        st.error("❌ 게스트 계정은 접근할 수 없는 메뉴입니다.")
        st.stop()
        
    st.subheader("🏷️ 자재 품목 마스터 관리")
    st.caption("💡 새로운 자재 품목을 등록하거나 기존 품목 정보를 수정·삭제합니다.")
    
    tab_add, tab_edit = st.tabs(["➕ 신규 품목 등록", "✏️ 기존 품목 수정/삭제"])
    
    with tab_add:
        with st.form("new_item_form"):
            new_code = st.text_input("품목코드 (자동생성 추천)", value=generate_next_item_code())
            c_i1, c_i2 = st.columns(2)
            new_name = c_i1.text_input("품명 (*필수)")
            new_detail_no = c_i2.text_input("상세번호 (Part No 등)")
            
            c_i3, c_i4 = st.columns(2)
            new_model = c_i3.text_input("규격 / 모델")
            new_cat_type = c_i4.selectbox("구분", ["전기", "기계", "소방", "기타"])
            
            c_i5, c_i6, c_i7 = st.columns(3)
            new_cat_main = c_i5.text_input("대분류")
            new_cat_sub = c_i6.text_input("소분류")
            new_shelf = c_i7.text_input("선반 번호")
            
            c_i8, c_i9 = st.columns(2)
            new_zone = c_i8.text_input("설치 구역 (Zone)")
            new_device = c_i9.text_input("설치 기기명")
            
            c_i10, c_i11, c_i12 = st.columns(3)
            new_maker = c_i10.text_input("Maker (제조사)")
            new_curr = c_i11.selectbox("화폐 단위", ["KRW", "USD", "EUR", "JPY", "CNY"])
            new_price = c_i12.number_input("단가", min_value=0.0, value=0.0, step=100.0)
            
            c_i13, c_i14 = st.columns(2)
            new_indate = c_i13.date_input("최초 입고일", value=datetime.date.today())
            new_photo = c_i14.text_input("사진 URL (선택)")
            
            new_remark = st.text_input("비고")
            
            submitted_item = st.form_submit_button("신규 품목 등록하기")
            
            if submitted_item:
                if not new_name.strip():
                    st.error("품명은 필수 입력 항목입니다.")
                else:
                    payload = {
                        "item_code": new_code.strip(),
                        "item_name": new_name.strip(),
                        "item_detail_no": new_detail_no.strip(),
                        "model_spec": new_model.strip(),
                        "category_type": new_cat_type,
                        "category_main": new_cat_main.strip(),
                        "category_sub": new_cat_sub.strip(),
                        "shelf_no": new_shelf.strip(),
                        "zone": new_zone.strip(),
                        "device_name": new_device.strip(),
                        "maker": new_maker.strip(),
                        "currency": new_curr,
                        "unit_price": float(new_price),
                        "in_date": str(new_indate),
                        "photo_url": new_photo.strip() if new_photo.strip() else None,
                        "remark": new_remark.strip()
                    }
                    try:
                        db.supabase.table("items").insert(payload).execute()
                        st.success(f"✅ 신규 품목 [{new_code}]이 성공적으로 등록되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 등록 실패: {e}")

    with tab_edit:
        st.info("💡 수정 또는 삭제할 품목을 선택하세요.")
        try:
            items_resp = db.supabase.table("items").select("*").order("item_code").execute()
            all_items_master = items_resp.data or []
        except:
            all_items_master = []
            
        if all_items_master:
            master_opts = {f"[{i['item_code']}] {i['item_name']} (규격: {i.get('model_spec', '-')})": i for i in all_items_master}
            sel_master_label = st.selectbox("관리할 품목 선택", list(master_opts.keys()))
            target_item_obj = master_opts[sel_master_label]
            
            with st.form("edit_item_form"):
                e_name = st.text_input("품명", value=target_item_obj.get("item_name", ""))
                e_detail = st.text_input("상세번호", value=target_item_obj.get("item_detail_no", ""))
                e_model = st.text_input("규격/모델", value=target_item_obj.get("model_spec", ""))
                e_maker = st.text_input("Maker", value=target_item_obj.get("maker", ""))
                e_price = st.number_input("단가", value=safe_float(target_item_obj.get("unit_price"), 0.0))
                e_remark = st.text_input("비고", value=target_item_obj.get("remark", ""))
                
                col_btn1, col_btn2 = st.columns(2)
                update_btn = col_btn1.form_submit_button("정보 수정 저장")
                delete_btn = col_btn2.form_submit_button("품목 삭제")
                
                if update_btn:
                    try:
                        db.supabase.table("items").update({
                            "item_name": e_name,
                            "item_detail_no": e_detail,
                            "model_spec": e_model,
                            "maker": e_maker,
                            "unit_price": e_price,
                            "remark": e_remark
                        }).eq("item_code", target_item_obj["item_code"]).execute()
                        st.success("✅ 품목 정보가 수정되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 수정 실패: {e}")
                        
                if delete_btn:
                    try:
                        db.supabase.table("items").delete().eq("item_code", target_item_obj["item_code"]).execute()
                        st.success("🗑️ 품목이 삭제되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 삭제 실패: {e}")

# ---------------------------------------------------------
# 메뉴 4: 품목별 입출고 집계 및 이력 조회 (기존 유지)
# ---------------------------------------------------------
elif menu == MENU_HISTORY:
    st.subheader("🔍 품목별 입출고 집계 및 소진 추이 조회")
    st.caption("💡 조회 기간 동안 출고 수량이 1개 이상인 품목들의 입출고 집계 요약 및 상세 이력을 조회합니다.")

    today_date = datetime.date.today()
    period_option = st.radio(
        "⏱️ 빠른 기간 선택", 
        ["전체 (2022년~)", "1개월", "3개월", "6개월", "1년", "직접 설정"], 
        index=0, 
        horizontal=True
    )

    if period_option == "1개월":
        default_start = today_date - datetime.timedelta(days=30)
    elif period_option == "3개월":
        default_start = today_date - datetime.timedelta(days=90)
    elif period_option == "6개월":
        default_start = today_date - datetime.timedelta(days=180)
    elif period_option == "1년":
        default_start = today_date - datetime.timedelta(days=365)
    elif period_option == "전체 (2022년~)":
        default_start = datetime.date(2022, 1, 1)
    else:
        default_start = datetime.date(2022, 1, 1)

    col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
    hist_search = col_f1.text_input("🔍 품목 검색 (품목코드, 품명 등)", "")
    
    start_date_filter = col_f2.date_input("조회 시작일", value=default_start)
    end_date_filter = col_f3.date_input("조회 종료일", value=today_date)

    all_trans_resp = []
    try:
        chunk_size = 1000
        start = 0
        while True:
            resp = db.supabase.table("stock_transactions").select("*").range(start, start + chunk_size - 1).execute()
            chunk_data = resp.data or []
            all_trans_resp.extend(chunk_data)
            if len(chunk_data) < chunk_size:
                break
            start += chunk_size
    except Exception:
        all_trans_resp = []

    item_calc_stock_map = {}
    item_total_in_all_map = {}
    item_latest_price_map = {}
    item_latest_date_map = {}
    item_latest_dt_obj_map = {}

    for t in all_trans_resp:
        ic = t.get("item_code")
        if not ic:
            continue
        q = safe_int_clean(t.get("quantity"), 0)
        ttype = str(t.get("trans_type", "")).strip().upper()
        t_date = clean_date(t.get("trans_date", ""))
        t_dt_obj = parse_standard_date(t_date)
        t_price = safe_float(t.get("unit_price"), 0.0)

        if ic not in item_calc_stock_map:
            item_calc_stock_map[ic] = 0
        if ic not in item_total_in_all_map:
            item_total_in_all_map[ic] = 0

        if ttype in ["IN", "입고"]:
            item_calc_stock_map[ic] += q
            item_total_in_all_map[ic] += q
            if t_price > 0:
                curr_dt_obj = item_latest_dt_obj_map.get(ic, datetime.date(1900, 1, 1))
                if t_dt_obj >= curr_dt_obj:
                    item_latest_dt_obj_map[ic] = t_dt_obj
                    item_latest_date_map[ic] = t_date
                    item_latest_price_map[ic] = t_price
        elif ttype in ["OUT", "출고"]:
            item_calc_stock_map[ic] -= q

    item_info_map = {}
    try:
        chunk_size = 1000
        start = 0
        while True:
            items_resp = db.supabase.table("items").select("item_code, item_name, currency, model_spec, item_detail_no, unit_price, in_date, photo_url").order("item_code", desc=False).range(start, start + chunk_size - 1).execute()
            chunk_items = items_resp.data or []
            for i in chunk_items:
                icode_key = str(i.get("item_code", "")).strip().upper()
                item_info_map[icode_key] = {
                    "name": i.get("item_name", "-"),
                    "currency": safe_str_clean(i.get("currency"), "KRW"),
                    "model_spec": safe_str_clean(i.get("model_spec"), "-"),
                    "detail_no": safe_str_clean(i.get("item_detail_no"), "-"),
                    "unit_price": safe_float(i.get("unit_price"), 0.0),
                    "in_date": clean_date(i.get("in_date", str(datetime.date.today()))),
                    "photo_url": i.get("photo_url")
                }
            if len(chunk_items) < chunk_size:
                break
            start += chunk_size
    except Exception:
        pass

    filtered_trans_data = []
    for t in all_trans_resp:
        icode = str(t.get("item_code", "-")).strip().upper()
        
        t_dt = parse_standard_date(t.get("trans_date", ""))
        if not (start_date_filter <= t_dt <= end_date_filter):
            continue

        info = item_info_map.get(icode, {"name": "-", "currency": "KRW", "model_spec": "-", "detail_no": "-"})
        iname = info["name"]

        if hist_search.strip():
            kw = hist_search.strip().lower()
            matched = (
                kw in icode.lower() or 
                kw in iname.lower() or 
                kw in str(t.get("requester","")).lower() or 
                kw in str(t.get("manager","")).lower() or 
                kw in str(t.get("remark","")).lower()
            )
            if not matched:
                continue

        filtered_trans_data.append(t)

    if filtered_trans_data or hist_search.strip():
        item_summary_map = {}
        for t in filtered_trans_data:
            icode = str(t.get("item_code", "-")).strip().upper()
            if icode not in item_summary_map:
                info = item_info_map.get(icode, {"name": "-", "model_spec": "-", "detail_no": "-", "currency": "KRW", "unit_price": 0.0, "in_date": str(datetime.date.today())})
                current_stock = max(0, item_calc_stock_map.get(icode, 0))
                total_in_all = item_total_in_all_map.get(icode, 0)
                
                latest_price = item_latest_price_map.get(icode, info["unit_price"])
                latest_date = item_latest_date_map.get(icode, info["in_date"])
                year = get_year_from_date(latest_date)
                rate = get_exchange_rate_by_year(info["currency"], year)
                stock_amt = 0 if is_guest else round(current_stock * latest_price * rate)

                item_summary_map[icode] = {
                    "품목코드": t.get("item_code", "-"),
                    "품명": info["name"],
                    "규격_모델": info["model_spec"],
                    "총재고": total_in_all,
                    "총 입고수량": 0,
                    "총 출고수량": 0,
                    "현재재고": current_stock,
                    "재고금액": stock_amt,
                    "거래건수": 0,
                    "상세내역": []
                }
            
            t_type = str(t.get("trans_type", "")).strip().upper()
            qty = safe_int_clean(t.get("quantity"), 0)
            
            if t_type in ["IN", "입고"]:
                item_summary_map[icode]["총 입고수량"] += qty
            elif t_type in ["OUT", "출고"]:
                item_summary_map[icode]["총 출고수량"] += qty
            
            item_summary_map[icode]["거래건수"] += 1
            item_summary_map[icode]["상세내역"].append(t)

        summary_rows = []
        for icode, data in item_summary_map.items():
            if data["총 출고수량"] < 1:
                continue

            summary_rows.append({
                "품목코드": data["품목코드"],
                "품명": data["품명"],
                "규격_모델": data["규격_모델"],
                "총재고": data["총재고"],
                "총 입고수량": data["총 입고수량"],
                "총 출고수량": data["총 출고수량"],
                "현재재고": data["현재재고"],
                "재고금액": "🔒 (비공개)" if is_guest else data["재고금액"]
            })

        if summary_rows:
            df_summary = pd.DataFrame(summary_rows)

            st.markdown("### 📦 품목별 입출고 집계 요약 (출고 1개 이상 품목)")
            st.markdown("---")

            df_summary_display = df_summary.copy()
            df_summary_display["총재고"] = df_summary_display["총재고"].apply(lambda x: f"{x:,} 개")
            df_summary_display["총 입고수량"] = df_summary_display["총 입고수량"].apply(lambda x: f"{x:,} 개")
            df_summary_display["총 출고수량"] = df_summary_display["총 출고수량"].apply(lambda x: f"{x:,} 개")
            df_summary_display["현재재고_raw"] = df_summary_display["현재재고"]
            df_summary_display["현재재고"] = df_summary_display["현재재고"].apply(lambda x: f"{x:,} 개")
            if not is_guest:
                df_summary_display["재고금액"] = df_summary_display["재고금액"].apply(lambda x: f"{x:,.0f} 원")

            styled_df = df_summary_display.drop(columns=["현재재고_raw"]).style

            def color_zero_stock(val):
                if str(val).strip() == "0 개":
                    return 'color: #D32F2F; font-weight: bold;'
                return ''

            styled_df = styled_df.map(color_zero_stock, subset=["현재재고"])

            summary_selection = st.dataframe(
                styled_df,
                column_config={
                    "품목코드": st.column_config.TextColumn("품목코드", width="small"),
                    "품명": st.column_config.TextColumn("품명", width="medium"),
                    "규격_모델": st.column_config.TextColumn("규격_모델", width="medium"),
                    "총재고": st.column_config.TextColumn("총재고", width="small"),
                    "총 입고수량": st.column_config.TextColumn("총 입고수량", width="small"),
                    "총 출고수량": st.column_config.TextColumn("총 출고수량", width="small"),
                    "현재재고": st.column_config.TextColumn("현재재고", width="small"),
                    "재고금액": st.column_config.TextColumn("재고금액", width="medium")
                },
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row"
            )

            sel_rows = summary_selection.selection.rows if summary_selection and hasattr(summary_selection, "selection") else []

            selected_icodes = []
            if sel_rows:
                for r_idx in sel_rows:
                    if r_idx < len(df_summary):
                        selected_icodes.append(df_summary.iloc[r_idx]["품목코드"])
            else:
                if not df_summary.empty:
                    selected_icodes.append(df_summary.iloc[0]["품목코드"])

            if sel_rows:
                out_multi_excel = io.BytesIO()
                with pd.ExcelWriter(out_multi_excel, engine="openpyxl") as writer:
                    df_summary.to_excel(writer, index=False, sheet_name="입출고집계요약")
                    
                    for s_icode in selected_icodes:
                        s_summary = item_summary_map.get(str(s_icode).strip().upper(), None)
                        if s_summary and s_summary["상세내역"]:
                            s_sorted = sorted(s_summary["상세내역"], key=lambda x: str(x.get("trans_date", "")), reverse=False)
                            s_rows = []
                            for idx, t in enumerate(s_sorted, 1):
                                q = safe_int_clean(t.get("quantity"), 0)
                                t_date = clean_date(t.get("trans_date", ""))
                                t_type = str(t.get("trans_type", "")).strip().upper()
                                type_disp = "입고 (IN)" if t_type in ["IN", "입고"] else "출고 (OUT)"
                                
                                raw_mgr = safe_str_clean(t.get("manager"), "")
                                if not raw_mgr or raw_mgr == "-":
                                    raw_mgr = "최광호"
                                else:
                                    for pos in POSITIONS:
                                        raw_mgr = raw_mgr.replace(pos, "").strip()

                                raw_req = safe_str_clean(t.get("requester"), "-")
                                if raw_req in ["-", "초기재고일괄등록", "시스템입고", "None", ""]:
                                    raw_req = "기초재고등록" if t_type in ["IN", "입고"] else "-"

                                s_rows.append({
                                    "No": idx,
                                    "일자": t_date,
                                    "구분": type_disp,
                                    "수량": q,
                                    "담당자": raw_mgr,
                                    "요청자": raw_req,
                                    "비고": safe_str_clean(t.get("remark"), "-")
                                })
                            df_s_detail = pd.DataFrame(s_rows)
                            safe_sheet_name = re.sub(r'[:\\/?*\[\]]', '', str(s_icode))[:31]
                            df_s_detail.to_excel(writer, index=False, sheet_name=safe_sheet_name)

                st.write("")
                col_btn_dl, _ = st.columns([1, 3])
                with col_btn_dl:
                    st.download_button(
                        label="📥 선택한 품목별 상세이력 엑셀 다운로드 (개별 시트)",
                        data=out_multi_excel.getvalue(),
                        file_name=f"선택품목_입출고상세이력_{datetime.date.today()}.xlsx",
                        use_container_width=True
                    )

            st.markdown("---")
            st.markdown("### 📋 선택품목 상세 입출고 이력")

            for target_icode in selected_icodes:
                target_summary = item_summary_map.get(str(target_icode).strip().upper(), None)
                info = item_info_map.get(str(target_icode).strip().upper(), {})
                photo_url = info.get("photo_url")

                st.markdown(f"#### 🔍 품목코드: `{target_icode}`")
                
                c_img, c_desc = st.columns([1, 4])
                with c_img:
                    if photo_url:
                        st.image(photo_url, caption=target_summary['품명'] if target_summary else target_icode, use_container_width=True)
                    else:
                        st.info("등록된 사진 없음")

                with c_desc:
                    if target_summary and target_summary["상세내역"]:
                        sorted_details = sorted(target_summary["상세내역"], key=lambda x: str(x.get("trans_date", "")), reverse=False)

                        detail_rows = []

                        for idx, t in enumerate(sorted_details, 1):
                            qty = safe_int_clean(t.get("quantity"), 0)
                            t_date = clean_date(t.get("trans_date", ""))
                            t_type = str(t.get("trans_type", "")).strip().upper()
                            
                            type_display = "입고 (IN)" if t_type in ["IN", "입고"] else "출고 (OUT)"

                            raw_mgr = safe_str_clean(t.get("manager"), "")
                            if not raw_mgr or raw_mgr == "-":
                                raw_mgr = "최광호"
                            else:
                                for pos in POSITIONS:
                                    raw_mgr = raw_mgr.replace(pos, "").strip()

                            raw_req = safe_str_clean(t.get("requester"), "-")
                            if raw_req in ["-", "초기재고일괄등록", "시스템입고", "None", ""]:
                                raw_req = "기초재고등록" if t_type in ["IN", "입고"] else "-"

                            if is_guest:
                                detail_rows.append({
                                    "No": idx, "일자": t_date, "구분": type_display,
                                    "수량": f"{qty:,} 개", "원화환산액": "🔒 (비공개)", "총금액": "🔒 (비공개)",
                                    "담당자": raw_mgr, "요청자": raw_req, "비고": safe_str_clean(t.get("remark"), "-")
                                })
                            else:
                                detail_rows.append({
                                    "No": idx, "일자": t_date, "구분": type_display,
                                    "수량": f"{qty:,} 개", "원화환산액": "표시", "총금액": "표시",
                                    "담당자": raw_mgr, "요청자": raw_req, "비고": safe_str_clean(t.get("remark"), "-")
                                })

                        if is_guest:
                            summary_html = f"""
                            <div style="background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 6px; padding: 12px 20px; margin-bottom: 12px; font-size: 15px; color: #111;">
                                <div><b>품명:</b> <span style="color: #2e7d32; font-weight: bold;">{target_summary['품명']}</span> (규격: {target_summary['규격_모델']})</div>
                                <div style="margin-top: 8px;">
                                    📦 <b>현재재고:</b> <span style="color: #1976D2; font-weight: bold;">{target_summary['현재재고']:,} 개</span> &nbsp;|&nbsp; 💵 <b>재고금액:</b> <span style="color: #D32F2F; font-weight: bold;">🔒 (비공개)</span>
                                </div>
                            </div>
                            """
                        else:
                            summary_html = f"""
                            <div style="background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 6px; padding: 12px 20px; margin-bottom: 12px; font-size: 15px; color: #111;">
                                <div><b>품명:</b> <span style="color: #2e7d32; font-weight: bold;">{target_summary['품명']}</span> (규격: {target_summary['규격_모델']})</div>
                            </div>
                            """
                        st.markdown(summary_html, unsafe_allow_html=True)

                        df_detail = pd.DataFrame(detail_rows)

                        def highlight_trans_type(row):
                            val = str(row.get("구분", ""))
                            if "입고" in val or "IN" in val:
                                return ['background-color: #E8F5E9; color: #1B5E20; font-weight: bold;'] * len(row)
                            elif "출고" in val or "OUT" in val:
                                return ['background-color: #FFEBEE; color: #B71C1C; font-weight: bold;'] * len(row)
                            return [''] * len(row)

                        styled_detail_df = df_detail.style.apply(highlight_trans_type, axis=1)

                        st.dataframe(
                            styled_detail_df,
                            column_config={
                                "No": st.column_config.NumberColumn("No", width="small", format="%d"),
                                "일자": st.column_config.TextColumn("일자", width="small"),
                                "구분": st.column_config.TextColumn("구분", width="small"),
                                "수량": st.column_config.TextColumn("수량", width="small"),
                                "원화환산액": st.column_config.TextColumn("원화환산액", width="small"),
                                "총금액": st.column_config.TextColumn("총금액", width="small"),
                                "담당자": st.column_config.TextColumn("담당자", width="small"),
                                "요청자": st.column_config.TextColumn("요청자", width="small"),
                                "비고": st.column_config.TextColumn("비고", width="medium")
                            },
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info("선택한 품목에 대한 해당 기간 내 세부 입출고 이력이 없습니다.")
                
                st.markdown("---")
        else:
            st.info("선택한 기간 내 출고 수량이 1개 이상인 품목이 없습니다.")
    else:
        st.info("조건에 일치하는 내역이 없습니다.")

# ---------------------------------------------------------
# 메뉴 5: 환율 설정
# ---------------------------------------------------------
elif menu == MENU_RATES:
    if is_guest:
        st.error("❌ 게스트 계정은 접근할 수 없는 메뉴입니다.")
        st.stop()
        
    st.subheader("⚙️ 연도별/통화별 환율 설정")
    st.caption("💡 자재 단가 환산에 적용될 연도별 기준 환율을 관리합니다.")
    
    with st.form("rate_form"):
        r_col1, r_col2, r_col3 = st.columns(3)
        target_year = r_col1.number_input("적용 연도", min_value=2020, max_value=2030, value=datetime.date.today().year)
        target_curr = r_col2.selectbox("통화", ["USD", "EUR", "JPY", "CNY"])
        target_rate = r_col3.number_input("환율 (원)", min_value=0.0, value=1300.0, step=10.0)
        
        save_rate_btn = st.form_submit_button("환율 정보 저장/업데이트")
        
        if save_rate_btn:
            try:
                db.supabase.table("exchange_rates").upsert({
                    "year": int(target_year),
                    "currency": target_curr,
                    "rate": float(target_rate)
                }, on_conflict="year,currency").execute()
                st.success(f"✅ [{target_year}년] {target_curr} 환율이 {target_rate:,.2f}원으로 설정되었습니다.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 환율 저장 실패: {e}")

    try:
        rates_resp = db.supabase.table("exchange_rates").select("*").order("year", desc=True).execute()
        rates_data = rates_resp.data or []
        if rates_data:
            st.markdown("---")
            st.markdown("#### 📋 등록된 환율 현황")
            st.dataframe(pd.DataFrame(rates_data), use_container_width=True)
    except:
        pass

# ---------------------------------------------------------
# 메뉴 6: 사용자 관리 (관리자)
# ---------------------------------------------------------
elif menu == "👥 사용자 관리 (관리자)":
    if is_guest:
        st.error("❌ 게스트 계정은 접근할 수 없는 메뉴입니다.")
        st.stop()
        
    st.subheader("👥 사용자 계정 및 권한 관리")
    st.caption("💡 시스템에 접근할 수 있는 사용자 계정을 추가하고 권한(관리자/일반/게스트)을 설정합니다.")
    
    try:
        users_resp = db.supabase.table("users").select("*").execute()
        users_list = users_resp.data or []
    except:
        users_list = []
        
    if users_list:
        st.dataframe(pd.DataFrame(users_list)[["emp_no", "name", "position", "is_admin"]], use_container_width=True)
    
    st.markdown("---")
    with st.form("add_user_form"):
        st.markdown("#### ➕ 신규 사용자 추가")
        u_col1, u_col2 = st.columns(2)
        new_emp_no = u_col1.text_input("사번 (ID)")
        new_name = u_col2.text_input("성명")
        
        u_col3, u_col4 = st.columns(2)
        new_pw = u_col3.text_input("비밀번호", type="password")
        new_pos = u_col4.selectbox("직책", POSITIONS)
        
        new_is_admin = st.selectbox("권한 등급", [0, 1, 2], format_func=lambda x: "일반 사용자 (0)" if x==0 else ("시스템 관리자 (1)" if x==1 else "게스트 사용자 (2)"))
        
        add_user_btn = st.form_submit_button("사용자 등록")
        
        if add_user_btn:
            if not new_emp_no.strip() or not new_name.strip() or not new_pw.strip():
                st.error("모든 필수 정보를 입력해주세요.")
            else:
                try:
                    db.supabase.table("users").insert({
                        "emp_no": new_emp_no.strip(),
                        "name": new_name.strip(),
                        "password": new_pw.strip(),
                        "position": new_pos,
                        "is_admin": int(new_is_admin)
                    }).execute()
                    st.success(f"✅ 사용자 [{new_name}]님이 성공적으로 등록되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 사용자 등록 실패: {e}")
