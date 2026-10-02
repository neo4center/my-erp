import datetime
import html
import io
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

def safe_int(val, default=0):
    if pd.isna(val) or val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default

def safe_str(val, default=""):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip()
    return "" if s.lower() == "nan" else s

def clean_date(val):
    if pd.isna(val) or val is None:
        return str(datetime.date.today())
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip().split(" ")[0]
    return s if len(s) >= 8 else str(datetime.date.today())

def clean_val(val, default="-"):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip().replace('"', "")
    return html.escape(s) if s and s.lower() != "nan" else default

def get_exchange_rate(currency, year=None):
    if currency == "KRW" or not currency:
        return 1.0
    try:
        query = db.supabase.table("exchange_rates").select("rate").eq("currency", currency)
        if year:
            query = query.eq("year", year)
        resp = query.order("year", desc=True).limit(1).execute()
        if resp.data:
            return safe_float(resp.data[0]["rate"], 1.0)
    except Exception:
        pass
    return 1.0

def render_a4_spec_card(item_code):
    """Supabase 데이터를 활용해 A4 스타일 상세 명세서 카드 출력"""
    item_resp = db.supabase.table("items").select("*").eq("item_code", item_code).execute()
    if not item_resp.data:
        return
    item = item_resp.data[0]

    lots_resp = db.supabase.table("stock_lots").select("current_qty, unit_price").eq("item_code", item_code).gt("current_qty", 0).execute()
    lots = lots_resp.data or []
    current_stock = sum(l["current_qty"] for l in lots)
    
    latest_price = lots[0]["unit_price"] if lots else safe_float(item.get("unit_price"))
    curr = item.get("currency", "KRW")
    rate = get_exchange_rate(curr)
    unit_krw = int(latest_price * rate)
    val_krw = int(unit_krw * current_stock)

    trans_resp = db.supabase.table("stock_transactions").select("*").eq("item_code", item_code).order("trans_date", desc=True).execute()
    trans_data = trans_resp.data or []
    df_in = pd.DataFrame([t for t in trans_data if t["trans_type"] in ["IN", "입고"]])
    df_out = pd.DataFrame([t for t in trans_data if t["trans_type"] in ["OUT", "출고"]])

    st.markdown("""
    <style>
    .a4-card { background-color: #ffffff; border: 2px solid #333; border-radius: 8px; padding: 25px; margin-top: 10px; color: #111; }
    .a4-header { text-align: center; border-bottom: 3px double #333; padding-bottom: 10px; margin-bottom: 20px; }
    .info-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; }
    .info-table th, .info-table td { border: 1px solid #ccc; padding: 8px 12px; font-size: 14px; }
    .info-table th { background-color: #f4f4f4; font-weight: bold; width: 15%; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='a4-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='a4-header'><h2>자 재 품 목 명 세 서</h2><p>발행일자: {datetime.date.today()}</p></div>", unsafe_allow_html=True)
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
                <tr><th>구분/대분류</th><td>{clean_val(item.get('category_type'))} / {clean_val(item.get('category_main'))}</td><th>소분류/선반</th><td>{clean_val(item.get('category_sub'))} / {clean_val(item.get('shelf_no'))}</td></tr>
                <tr><th>구역/기기명</th><td>{clean_val(item.get('zone'))} / {clean_val(item.get('device_name'))}</td><th>Maker</th><td>{clean_val(item.get('maker'))}</td></tr>
                <tr><th>적용단가</th><td>{latest_price:,.0f} {curr} ({unit_krw:,.0f} 원)</td><th>입고일</th><td>{clean_val(item.get('in_date'))}</td></tr>
                <tr><th>현재재고</th><td><b>{current_stock:,} 개</b></td><th>총 재고금액</th><td><b>{val_krw:,} 원</b></td></tr>
                <tr><th>비고</th><td colspan="3">{clean_val(item.get('remark'))}</td></tr>
            </table>
            """
            st.markdown(html_table, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### 📥 1. 입고 내역 (History)")
        if not df_in.empty:
            cols_show = [c for c in ['trans_date', 'quantity', 'unit_price', 'manager', 'requester', 'remark'] if c in df_in.columns]
            st.dataframe(df_in[cols_show], use_container_width=True)
        else:
            st.caption("※ 입고 내역이 없습니다.")

        st.markdown("### 📤 2. 출고 내역 (History)")
        if not df_out.empty:
            cols_show = [c for c in ['trans_date', 'quantity', 'unit_price', 'manager', 'requester', 'remark'] if c in df_out.columns]
            st.dataframe(df_out[cols_show], use_container_width=True)
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
                            "emp_no": u["emp_no"],
                            "name": u["name"],
                            "position": u["position"],
                            "is_admin": u.get("is_admin", 0)
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
# 3. 메인 ERP 사이드바
# ---------------------------------------------------------
user = st.session_state.logged_in_user
st.title("🏭 광주오포센터 자동화 ERP")

st.sidebar.markdown(f"👤 접속자: **{user['name']} {user['position']}** (사번: `{user['emp_no']}`)")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in_user = None
    st.rerun()

st.sidebar.markdown("---")
menu_list = ["📊 재고 현황판", "📝 입출고 등록", "🏷️ 품목 관리", "🔍 입출고 내역 조회", "⚙️ 환율 설정"]
if user.get("is_admin") == 1:
    menu_list.append("👥 사용자 관리 (관리자)")

menu = st.sidebar.radio("메뉴 이동:", menu_list)

# ---------------------------------------------------------
# 메뉴 1: 재고 현황판
# ---------------------------------------------------------
if menu == "📊 재고 현황판":
    st.subheader("📊 현재 품목별/Lot별 재고 현황판")
    st.caption("💡 아래 표에서 행을 선택하면 하단에 A4 자재 품목 명세서가 자동으로 생성됩니다.")

    search_kw = st.text_input("🔍 통합 검색 (품명, 코드, 상세번호, 규격, 구분, 구역, Maker 등)", "")

    lots_data = db.get_stock_by_lots()
    
    if lots_data:
        table_rows = []
        for lot in lots_data:
            i = lot.get("items", {}) or {}
            table_rows.append({
                "사진": i.get("photo_url"),
                "Lot ID": lot.get("lot_id"),
                "품목코드": lot.get("item_code"),
                "품명": i.get("item_name", "-"),
                "상세번호": i.get("item_detail_no", "-"),
                "규격/모델": i.get("model_spec", "-"),
                "구분": i.get("category_type", "-"),
                "대분류": i.get("category_main", "-"),
                "소분류": i.get("category_sub", "-"),
                "구역": i.get("zone", "-"),
                "기기명": i.get("device_name", "-"),
                "Maker": i.get("maker", "-"),
                "입고일": lot.get("inbound_date"),
                "단가": lot.get("unit_price", 0),
                "현재재고": lot.get("current_qty", 0),
                "재고금액": lot.get("unit_price", 0) * lot.get("current_qty", 0)
            })
        
        df_stock = pd.DataFrame(table_rows)

        if search_kw:
            kw = search_kw.lower()
            mask = df_stock.astype(str).apply(lambda col: col.str.lower().str.contains(kw, na=False)).any(axis=1)
            df_stock = df_stock[mask]

        col1, col2, col3 = st.columns([2, 2, 2])
        col1.metric("조회된 Lot 수", f"{len(df_stock)} 개")
        col2.metric("총 재고 자산", f"{df_stock['재고금액'].sum():,} 원")

        out_excel = io.BytesIO()
        with pd.ExcelWriter(out_excel, engine="openpyxl") as writer:
            df_stock.drop(columns=["사진"], errors="ignore").to_excel(writer, index=False, sheet_name="재고현황")
        col3.write("")
        col3.download_button("📥 엑셀 다운로드 (.xlsx)", out_excel.getvalue(), file_name=f"ERP_재고현황_{datetime.date.today()}.xlsx")

        selection_event = st.dataframe(
            df_stock,
            column_config={
                "사진": st.column_config.ImageColumn("사진"),
                "단가": st.column_config.NumberColumn(format="%d 원"),
                "재고금액": st.column_config.NumberColumn(format="%d 원")
            },
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row"
        )

        st.markdown("---")
        st.subheader("📄 A4 품목 상세 내역서 출력 및 조회")
        selected_code = None
        selected_rows = selection_event.selection.rows if selection_event and hasattr(selection_event, "selection") else []
        
        if selected_rows and selected_rows[0] < len(df_stock):
            selected_code = df_stock.iloc[selected_rows[0]]["품목코드"]

        items_resp = db.supabase.table("items").select("item_code, item_name").execute()
        item_list = {f"[{i['item_code']}] {i['item_name']}": i["item_code"] for i in (items_resp.data or [])}
        
        if item_list:
            default_idx = list(item_list.values()).index(selected_code) if selected_code in item_list.values() else 0
            sel_label = st.selectbox("📋 상세 명세서 조회 품목 선택:", list(item_list.keys()), index=default_idx)
            render_a4_spec_card(item_list[sel_label])
    else:
        st.info("등록된 재고 데이터가 없습니다.")

# ---------------------------------------------------------
# 메뉴 2: 입출고 등록
# ---------------------------------------------------------
elif menu == "📝 입출고 등록":
    st.subheader("📝 자재 입출고 등록 (Lot 단가 분리 & FIFO 선입선출)")

    items_resp = db.supabase.table("items").select("item_code, item_name, item_detail_no, maker, unit_price, currency").execute()
    items_list = items_resp.data or []

    if not items_list:
        st.warning("등록된 품목이 없습니다. '품목 관리'에서 품목을 먼저 등록하세요.")
    else:
        search_kw = st.text_input("🔍 품목 실시간 검색 (품명, 코드, Maker 등)", "")
        filtered = [i for i in items_list if search_kw.lower() in f"{i['item_code']} {i['item_name']} {i.get('maker','')} {i.get('item_detail_no','')}".lower()] if search_kw else items_list

        item_opts = {f"[{i['item_code']}] {i['item_name']} (상세: {i.get('item_detail_no','-')})": i for i in filtered}
        
        selected_label = st.selectbox("🎯 대상 품목 선택", list(item_opts.keys()), key="trans_select")
        target_item = item_opts[selected_label]
        item_code = target_item["item_code"]

        with st.form("trans_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            trans_type = col1.radio("입출고 구분", ["입고", "출고"], horizontal=True)
            trans_date = col2.date_input("일자", datetime.date.today())

            col3, col4 = st.columns(2)
            quantity = col3.number_input("수량", min_value=1, value=1, step=1)
            unit_price = col4.number_input(f"적용 단가 ({target_item.get('currency', 'KRW')})", min_value=0.0, value=safe_float(target_item.get("unit_price")), step=100.0)

            col5, col6 = st.columns(2)
            manager = col5.text_input("담당자 (작성자)", value=f"{user['name']} {user['position']}")
            requester = col6.text_input("출고/입고 요청자 (*필수)")

            remark = st.text_input("비고 (용도, 출처 등)")
            submitted = st.form_submit_button("입출고 저장 실행")

            if submitted:
                if not requester:
                    st.error("요청자는 필수 입력 항목입니다.")
                else:
                    with st.spinner("⏳ 입출고 데이터를 처리 중입니다..."):
                        if trans_type == "입고":
                            db.register_inbound_lot(
                                item_code=item_code,
                                item_name=target_item["item_name"],
                                category=target_item.get("category_type", "일반"),
                                inbound_date=str(trans_date),
                                unit_price=unit_price,
                                quantity=quantity
                            )
                            st.success(f"✅ [{item_code}] {quantity}개 입고 등록이 완료되었습니다.")
                        else:
                            success = db.process_fifo_outbound(
                                item_code=item_code,
                                outbound_qty=quantity,
                                trans_date=str(trans_date)
                            )
                        st.rerun()

        st.markdown("---")
        st.subheader(f"📄 선택 품목 [{item_code}] 실시간 상세 명세서")
        render_a4_spec_card(item_code)

# ---------------------------------------------------------
# 메뉴 3: 품목 관리 (로딩 스피너 및 안전한 엑셀 일괄 등록)
# ---------------------------------------------------------
elif menu == "🏷️ 품목 관리":
    st.subheader("🏷️ 품목 등록 및 수정 관리")
    tab1, tab2, tab3 = st.tabs(["✍️ 개별 직접 등록", "✏️ 기존 품목 수정", "📂 엑셀 일괄 등록"])

    with tab1:
        with st.form("new_item_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            item_code = col1.text_input("품목코드 (*필수)", value="N4_0001")
            item_name = col2.text_input("품명 (*필수)")
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

            col13, col14, col15 = st.columns(3)
            in_date = col13.text_input("입고일", value=str(datetime.date.today()))
            currency = col14.selectbox("화폐", ["KRW", "USD", "EUR", "JPY"])
            unit_price = col15.number_input("기초 단가", min_value=0.0, value=0.0)

            remark = st.text_input("비고")
            img_file = st.file_uploader("품목 사진 첨부 (자동 썸네일 압축 업로드)", type=["png", "jpg", "jpeg"])

            if st.form_submit_button("신규 품목 저장"):
                if not item_name or not item_code:
                    st.error("품목코드와 품명은 필수입니다.")
                else:
                    with st.spinner("⏳ 이미지 압축 및 데이터 저장 중..."):
                        photo_url = db.upload_item_image(img_file, item_code) if img_file else None
                        item_data = {
                            "item_code": item_code, "item_name": item_name, "item_detail_no": item_detail_no,
                            "model_spec": model_spec, "category_type": category_type, "category_main": category_main,
                            "category_sub": category_sub, "shelf_no": shelf_no, "zone": zone, "device_name": device_name,
                            "maker": maker, "useful_life": useful_life, "in_date": in_date, "currency": currency,
                            "unit_price": unit_price, "remark": remark
                        }
                        if photo_url: item_data["photo_url"] = photo_url
                        db.supabase.table("items").upsert(item_data).execute()
                        st.success(f"🎉 신규 품목 [{item_code}] 저장 완료!")
                        st.rerun()

    with tab2:
        items_resp = db.supabase.table("items").select("*").execute()
        all_items = items_resp.data or []
        if all_items:
            edit_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in all_items}
            sel_edit = st.selectbox("✏️ 수정할 품목 선택:", list(edit_opts.keys()))
            t = edit_opts[sel_edit]

            with st.form("edit_item_form"):
                col1, col2 = st.columns(2)
                e_name = col1.text_input("품명", value=safe_str(t.get("item_name")))
                e_detail = col2.text_input("아이템상세번호", value=safe_str(t.get("item_detail_no")))

                col3, col4, col5 = st.columns(3)
                e_spec = col3.text_input("규격", value=safe_str(t.get("model_spec")))
                e_price = col4.number_input("단가", value=safe_float(t.get("unit_price")))
                e_curr = col5.selectbox("화폐", ["KRW", "USD", "EUR", "JPY"], index=["KRW", "USD", "EUR", "JPY"].index(t.get("currency", "KRW")))

                e_remark = st.text_input("비고", value=safe_str(t.get("remark")))
                if st.form_submit_button("품목 정보 수정 완료"):
                    with st.spinner("⏳ 품목 정보 수정 중..."):
                        db.supabase.table("items").update({
                            "item_name": e_name, "item_detail_no": e_detail, "model_spec": e_spec,
                            "unit_price": e_price, "currency": e_curr, "remark": e_remark
                        }).eq("item_code", t["item_code"]).execute()
                        st.success("✅ 수정 완료!")
                        st.rerun()

    with tab3:
        st.markdown("#### 📂 엑셀 대량 등록 및 양식 다운로드")
        st.caption("아래 표준 양식을 다운로드하여 작성한 후 업로드해 주세요. (초기 수량이 작성되면 자동으로 재고 Lot이 생성됩니다)")

        template_df = pd.DataFrame([{
            "item_code": "N4_0001",
            "item_name": "예시 자재명",
            "item_detail_no": "ABC-123",
            "model_spec": "SPEC-01",
            "category_type": "소모품",
            "category_main": "기계",
            "category_sub": "베어링",
            "shelf_no": "A-01",
            "zone": "1구역",
            "device_name": "컨베이어",
            "maker": "한국기공",
            "useful_life": "5년",
            "in_date": str(datetime.date.today()),
            "currency": "KRW",
            "unit_price": 50000,
            "initial_quantity": 10,
            "remark": "비고 내용 예시"
        }])
        
        tpl_buffer = io.BytesIO()
        with pd.ExcelWriter(tpl_buffer, engine="openpyxl") as writer:
            template_df.to_excel(writer, index=False, sheet_name="품목등록양식")
        
        st.download_button(
            label="📥 엑셀 표준 양식 다운로드 (.xlsx)",
            data=tpl_buffer.getvalue(),
            file_name="ERP_품목등록_표준양식.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.markdown("---")

        uploaded_excel = st.file_uploader("📂 작성된 엑셀 파일 선택 (.xlsx)", type=["xlsx"])
        if uploaded_excel and st.button("🚀 DB 일괄 등록 및 재고 생성 실행"):
            with st.spinner("⏳ 엑셀 파일 읽기 및 Supabase DB 등록 중입니다... 잠시만 기다려 주세요."):
                try:
                    df_up = pd.read_excel(uploaded_excel)
                    success_count = 0
                    stock_count = 0

                    for _, r in df_up.iterrows():
                        i_code = safe_str(r.get("item_code"))
                        i_name = safe_str(r.get("item_name"))
                        if not i_code or not i_name:
                            continue

                        u_price = safe_float(r.get("unit_price"))
                        init_qty = safe_int(r.get("initial_quantity"), 0)
                        in_d = clean_date(r.get("in_date"))

                        # 기존 이미지 URL 보존을 위해 기존 정보 확인
                        existing = db.supabase.table("items").select("photo_url").eq("item_code", i_code).execute()
                        existing_photo = existing.data[0]["photo_url"] if existing.data and existing.data[0].get("photo_url") else None

                        item_payload = {
                            "item_code": i_code,
                            "item_name": i_name,
                            "item_detail_no": safe_str(r.get("item_detail_no")),
                            "model_spec": safe_str(r.get("model_spec")),
                            "category_type": safe_str(r.get("category_type")),
                            "category_main": safe_str(r.get("category_main")),
                            "category_sub": safe_str(r.get("category_sub")),
                            "shelf_no": safe_str(r.get("shelf_no")),
                            "zone": safe_str(r.get("zone")),
                            "device_name": safe_str(r.get("device_name")),
                            "maker": safe_str(r.get("maker")),
                            "useful_life": safe_str(r.get("useful_life")),
                            "in_date": in_d,
                            "currency": safe_str(r.get("currency"), "KRW"),
                            "unit_price": u_price,
                            "remark": safe_str(r.get("remark"))
                        }
                        if existing_photo:
                            item_payload["photo_url"] = existing_photo

                        # 1) items 마스터 등록 (안전한 Upsert)
                        db.supabase.table("items").upsert(item_payload).execute()
                        success_count += 1

                        # 2) 초기 수량이 1개 이상인 경우 stock_lots 및 stock_transactions 생성
                        if init_qty > 0:
                            db.register_inbound_lot(
                                item_code=i_code,
                                item_name=i_name,
                                category=safe_str(r.get("category_type"), "일반"),
                                inbound_date=in_d,
                                unit_price=u_price,
                                quantity=init_qty
                            )
                            stock_count += 1

                    st.success(f"🎉 총 {success_count}개 품목 등록 완료! (초기 재고 Lot 생성: {stock_count}건)")
                    st.rerun()
                except Exception as e:
                    st.error(f"엑셀 업로드 중 오류 발생: {e}")

# ---------------------------------------------------------
# 메뉴 4: 입출고 내역 조회
# ---------------------------------------------------------
elif menu == "🔍 입출고 내역 조회":
    st.subheader("🔍 입출고 통합 이력 조회 (Supabase Transactions)")
    resp = db.supabase.table("stock_transactions").select("*").order("trans_date", desc=True).execute()
    df_trans = pd.DataFrame(resp.data or [])
    if not df_trans.empty:
        st.dataframe(df_trans, use_container_width=True)
    else:
        st.info("등록된 입출고 이력이 없습니다.")

# ---------------------------------------------------------
# 메뉴 5: 환율 설정
# ---------------------------------------------------------
elif menu == "⚙️ 환율 설정":
    st.subheader("⚙️ 연도별 기준 환율 관리")
    st.caption("🎨 통화별 구분: USD (연한 연두색), EUR (연한 하늘색), JPY (연한 핑크색)")
    
    resp = db.supabase.table("exchange_rates").select("year, currency, rate").order("year", desc=True).execute()
    df_rates = pd.DataFrame(resp.data or [])
    
    if not df_rates.empty:
        df_rates.rename(columns={"year": "연도", "currency": "화폐단위", "rate": "환율"}, inplace=True)
        
        def highlight_currency(row):
            curr = str(row.get("화폐단위", "")).upper()
            if curr == "USD":
                return ['background-color: #E8F5E9; color: #1B5E20; font-weight: bold;'] * len(row)
            elif curr == "EUR":
                return ['background-color: #E1F5FE; color: #01579B; font-weight: bold;'] * len(row)
            elif curr == "JPY":
                return ['background-color: #FCE4EC; color: #880E4F; font-weight: bold;'] * len(row)
            return [''] * len(row)

        styled_df = df_rates.style.apply(highlight_currency, axis=1)
        
        st.dataframe(
            styled_df,
            column_config={
                "연도": st.column_config.NumberColumn("연도", format="%d", alignment="center"),
                "화폐단위": st.column_config.TextColumn("화폐단위", alignment="center"),
                "환율": st.column_config.NumberColumn("환율 (KRW)", format="%.2f 원", alignment="center")
            },
            use_container_width=True
        )
    else:
        st.info("등록된 환율 데이터가 없습니다.")

    with st.form("rate_form"):
        col1, col2, col3 = st.columns(3)
        r_year = col1.number_input("연도", value=datetime.date.today().year)
        r_curr = col2.selectbox("화폐", ["USD", "EUR", "JPY"])
        r_rate = col3.number_input("환율 (KRW)", value=1350.00, step=10.0, format="%.2f")
        if st.form_submit_button("환율 저장"):
            with st.spinner("⏳ 환율 정보 업데이트 중..."):
                db.supabase.table("exchange_rates").upsert({"year": r_year, "currency": r_curr, "rate": r_rate}).execute()
                st.success(f"✅ {r_year}년 {r_curr} 환율 설정 저장 완료!")
                st.rerun()

# ---------------------------------------------------------
# 메뉴 6: 사용자 관리 (관리자 전용)
# ---------------------------------------------------------
elif menu == "👥 사용자 관리 (관리자)":
    st.subheader("👥 시스템 사용자 계정 관리")
    
    resp = db.supabase.table("users").select("emp_no, name, position, is_admin, created_at").execute()
    users_data = resp.data or []
    df_users = pd.DataFrame(users_data)
    
    if not df_users.empty:
        st.dataframe(df_users, use_container_width=True)
    
    tab_user1, tab_user2, tab_user3 = st.tabs(["➕ 신규 사용자 추가", "✏️ 계정 정보 수정", "🗑️ 계정 삭제"])

    with tab_user1:
        with st.form("add_user_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            u_emp = col1.text_input("사번 (ID) (*필수)")
            u_pw = col2.text_input("비밀번호 (*필수)", type="password")
            u_name = col3.text_input("이름 (*필수)")
            u_pos = st.selectbox("직급", POSITIONS)
            u_admin = st.checkbox("관리자 권한 부여")

            if st.form_submit_button("사용자 계정 생성"):
                if u_emp and u_pw and u_name:
                    with st.spinner("⏳ 계정 생성 중..."):
                        db.supabase.table("users").insert({
                            "emp_no": u_emp.strip(), "password": u_pw.strip(),
                            "name": u_name.strip(), "position": u_pos, "is_admin": 1 if u_admin else 0
                        }).execute()
                        st.success(f"✅ 사용자 [{u_name}] 계정 생성 완료!")
                        st.rerun()
                else:
                    st.error("필수 정보를 모두 입력하세요.")

    with tab_user2:
        if users_data:
            user_opts = {f"[{u['emp_no']}] {u['name']} ({u['position']})": u for u in users_data}
            sel_u_label = st.selectbox("수정할 사용자 선택:", list(user_opts.keys()))
            target_u = user_opts[sel_u_label]

            with st.form("edit_user_form"):
                st.markdown(f"#### 📌 [{target_u['emp_no']}] 계정 수정")
                col1, col2 = st.columns(2)
                edit_pw = col1.text_input("새 비밀번호 (변경 시만 입력)")
                edit_name = col2.text_input("이름", value=target_u["name"])
                
                col3, col4 = st.columns(2)
                edit_pos = col3.selectbox("직급", POSITIONS, index=POSITIONS.index(target_u["position"]) if target_u["position"] in POSITIONS else 0)
                edit_admin = col4.checkbox("관리자 권한", value=bool(target_u.get("is_admin")))

                if st.form_submit_button("사용자 정보 수정 저장"):
                    with st.spinner("⏳ 사용자 정보 수정 중..."):
                        update_payload = {
                            "name": edit_name.strip(),
                            "position": edit_pos,
                            "is_admin": 1 if edit_admin else 0
                        }
                        if edit_pw.strip():
                            update_payload["password"] = edit_pw.strip()

                        db.supabase.table("users").update(update_payload).eq("emp_no", target_u["emp_no"]).execute()
                        st.success(f"✅ [{target_u['emp_no']}] 사용자 정보가 성공적으로 수정되었습니다.")
                        st.rerun()

    with tab_user3:
        if users_data:
            del_opts = {f"[{u['emp_no']}] {u['name']} ({u['position']})": u['emp_no'] for u in users_data}
            sel_del_label = st.selectbox("삭제할 사용자 계정 선택:", list(del_opts.keys()))
            target_del_emp = del_opts[sel_del_label]

            st.warning(f"⚠️ 선택한 계정 (`{target_del_emp}`)을 삭제하시겠습니까? 삭제된 계정은 복구할 수 없습니다.")
            if st.button("❌ 선택 계정 즉시 삭제"):
                if target_del_emp == user["emp_no"]:
                    st.error("현재 로그인되어 있는 본인 계정은 삭제할 수 없습니다.")
                else:
                    with st.spinner("⏳ 계정 삭제 중..."):
                        db.supabase.table("users").delete().eq("emp_no", target_del_emp).execute()
                        st.success(f"✅ 사용자 계정 (`{target_del_emp}`)이 성공적으로 삭제되었습니다.")
                        st.rerun()
