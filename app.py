# ---------------------------------------------------------
# 메뉴 3: 품목 관리 (개별 등록, 수정, 엑셀 일괄 등록 및 표준양식 제공)
# ---------------------------------------------------------
elif menu == "🏷️ 품목 관리":
    st.subheader("🏷️ 품목 등록 및 수정 관리")
    tab1, tab2, tab3 = st.tabs(["✍️ 개별 직접 등록", "✏️ 기존 품목 수정", "📂 엑셀 일괄 등록"])

    # ... [tab1, tab2 코드는 기존과 동일] ...

    with tab3:
        st.markdown("#### 📂 엑셀 대량 등록 및 양식 다운로드")
        st.caption("아래 표준 양식을 다운로드하여 작성한 후 업로드해 주세요. (초기 수량이 있는 경우 자동으로 재고 Lot이 생성됩니다)")

        # 1. 엑셀 표준 양식 생성 (initial_quantity 컬럼 추가)
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
            "initial_quantity": 10,  # 초기 수량 항목 추가
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
                    in_d = safe_str(r.get("in_date"), str(datetime.date.today()))

                    # 1) items 마스터 등록
                    db.supabase.table("items").upsert({
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
                    }).execute()
                    success_count += 1

                    # 2) 초기 수량이 1개 이상이면 stock_lots 및 stock_transactions(재고 Lot) 자동 등록
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

                st.success(f"🎉 총 {success_count}개 품목 등록 완료! (초기 재고 생성: {stock_count}건)")
                st.rerun()
            except Exception as e:
                st.error(f"엑셀 업로드 중 오류 발생: {e}")
