import datetime
import io
import pandas as pd
import streamlit as st
import db_helper as db  # 어제 만든 db_helper 모듈 연동

# Streamlit 기본 설정
st.set_page_config(page_title="자동화 ERP - Supabase Cloud", layout="wide")

# ---------------------------------------------------------
# 로그인 세션 관리
# ---------------------------------------------------------
if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None

if st.session_state.logged_in_user is None:
    st.title("🔐 자동화 ERP - 로그인")
    with st.form("login_form"):
        emp_no = st.text_input("사번 (ID)")
        pw = st.text_input("비밀번호 (PW)", type="password")
        submitted = st.form_submit_button("로그인")
        
        if submitted:
            # 관리자 및 사용자 기본 로그인 처리
            if emp_no.strip() and pw.strip():
                st.session_state.logged_in_user = {
                    "emp_no": emp_no,
                    "name": "관리자" if emp_no == "admin" else emp_no,
                    "position": "팀장"
                }
                st.success("로그인 성공!")
                st.rerun()
            else:
                st.error("사번과 비밀번호를 입력해 주세요.")
    st.stop()

# ---------------------------------------------------------
# 메인 ERP 레이아웃 및 사이드바
# ---------------------------------------------------------
user = st.session_state.logged_in_user
st.title("☁️ Supabase 기반 자동화 ERP")

st.sidebar.markdown(f"👤 접속자: **{user['name']} {user['position']}**")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in_user = None
    st.rerun()

st.sidebar.markdown("---")
menu = st.sidebar.radio("메뉴 선택", ["📊 Lot별 재고 현황", "📝 입출고 등록(FIFO)", "🏷️ 품목 등록"])

# ---------------------------------------------------------
# 메뉴 1: Lot별 재고 현황 (단가별/입고일별 명세)
# ---------------------------------------------------------
if menu == "📊 Lot별 재고 현황":
    st.subheader("📊 Lot별 재고 및 단가 명세 (Supabase Live)")
    
    lots_data = db.get_stock_by_lots()
    
    if lots_data:
        table_rows = []
        for lot in lots_data:
            item_info = lot.get("items", {}) or {}
            table_rows.append({
                "Lot ID": lot.get("lot_id"),
                "품목코드": lot.get("item_code"),
                "품명": item_info.get("item_name", "-"),
                "카테고리": item_info.get("category", "-"),
                "입고일자": lot.get("inbound_date"),
                "단가": lot.get("unit_price"),
                "현재재고": lot.get("current_qty"),
                "재고금액": lot.get("unit_price", 0) * lot.get("current_qty", 0),
                "사진": item_info.get("photo_url")
            })
            
        df = pd.DataFrame(table_rows)
        
        # 메트릭 표시
        col1, col2 = st.columns(2)
        col1.metric("총 잔여 Lot 수", f"{len(df)} 개")
        col2.metric("총 재고 자산", f"{df['재고금액'].sum():,} 원")
        
        st.dataframe(
            df,
            column_config={
                "사진": st.column_config.ImageColumn("상품 사진"),
                "단가": st.column_config.NumberColumn(format="%d 원"),
                "재고금액": st.column_config.NumberColumn(format="%d 원")
            },
            use_container_width=True
        )
    else:
        st.info("현재 등록된 Lot 재고가 없습니다.")

# ---------------------------------------------------------
# 메뉴 2: 입출고 등록 (FIFO 선입선출 자동적용)
# ---------------------------------------------------------
elif menu == "📝 입출고 등록(FIFO)":
    st.subheader("📝 입출고 등록 (단가 분리 및 FIFO 선입선출)")
    
    trans_type = st.radio("구분", ["입고", "출고"], horizontal=True)
    
    # Supabase에서 품목 목록 가져오기
    items_resp = db.supabase.table("items").select("item_code, item_name, category").execute()
    items_list = items_resp.data
    
    if not items_list and trans_type == "출고":
        st.warning("등록된 품목이 없습니다. 품목을 먼저 등록하세요.")
    else:
        item_options = {f"[{i['item_code']}] {i['item_name']}": i for i in items_list} if items_list else {}
        
        with st.form("trans_form"):
            if trans_type == "입고":
                st.markdown("#### 📥 신규 Lot 입고 등록")
                col1, col2 = st.columns(2)
                item_code = col1.text_input("품목코드", value="N4_0001")
                item_name = col2.text_input("품명", value="예시 자재")
                
                col3, col4, col5 = st.columns(3)
                category = col3.text_input("카테고리", value="소모품")
                unit_price = col4.number_input("입고 단가", min_value=0, value=800000, step=10000)
                quantity = col5.number_input("입고 수량", min_value=1, value=1, step=1)
                
                inbound_date = st.date_input("입고 일자", datetime.date.today())
                image_file = st.file_uploader("상품 사진 (선택 / 자동 썸네일 압축)", type=["jpg", "png", "jpeg"])
                
                submitted = st.form_submit_button("입고 저장")
                if submitted:
                    lot_id = db.register_inbound_lot(
                        item_code=item_code,
                        item_name=item_name,
                        category=category,
                        inbound_date=str(inbound_date),
                        unit_price=unit_price,
                        quantity=quantity,
                        image_file=image_file
                    )
                    st.success(f"✅ 입고 완료! (새 Lot ID: {lot_id})")
                    st.rerun()
                    
            else:  # 출고
                st.markdown("#### 📤 선입선출(FIFO) 출고 등록")
                selected_label = st.selectbox("대상 품목 선택", list(item_options.keys()))
                target_item = item_options[selected_label]
                
                col1, col2 = st.columns(2)
                out_qty = col1.number_input("출고 요청 수량", min_value=1, value=1, step=1)
                out_date = col2.date_input("출고 일자", datetime.date.today())
                
                submitted = st.form_submit_button("FIFO 출고 실행")
                if submitted:
                    success = db.process_fifo_outbound(
                        item_code=target_item["item_code"],
                        outbound_qty=out_qty,
                        trans_date=str(out_date)
                    )
                    if success:
                        st.rerun()

# ---------------------------------------------------------
# 메뉴 3: 품목 등록
# ---------------------------------------------------------
elif menu == "🏷️ 품목 등록":
    st.subheader("🏷️ 신규 품목 등록")
    st.info("입고 메뉴에서 직접 등록하거나 이 메뉴에서 사전 등록할 수 있습니다.")