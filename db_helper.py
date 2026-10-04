import os
import datetime
from supabase import create_client, Client
import streamlit as st

SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase 연결 정보가 설정되지 않았습니다. st.secrets 또는 환경 변수를 확인해주세요.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_stock_by_lots():
    try:
        resp = supabase.table("stock_lots").select("*").gt("current_qty", 0).execute()
        return resp.data or []
    except Exception as e:
        st.error(f"재고 Lot 조회 오류: {e}")
        return []

def register_inbound_lot(item_code, item_name, category, inbound_date, unit_price, quantity, manager="시스템관리자", requester="시스템입고", remark="자재 입고 등록"):
    try:
        lot_payload = {
            "item_code": item_code,
            "current_qty": int(quantity),
            "unit_price": float(unit_price),
            "inbound_date": str(inbound_date),
        }
        supabase.table("stock_lots").insert(lot_payload).execute()

        trans_payload = {
            "item_code": item_code,
            "trans_type": "IN",
            "quantity": int(quantity),
            "unit_price": float(unit_price),
            "trans_date": str(inbound_date),
            "requester": requester,
            "manager": manager,
            "remark": remark if remark else "자재 입고 등록",
        }
        supabase.table("stock_transactions").insert(trans_payload).execute()
        return True
    except Exception as e:
        st.error(f"입고 등록 처리 중 오류 발생: {e}")
        return False

def process_fifo_outbound(item_code, outbound_qty, trans_date, requester="출고담당자", manager="관리자", remark=""):
    try:
        lots_resp = (
            supabase.table("stock_lots")
            .select("*")
            .eq("item_code", item_code)
            .gt("current_qty", 0)
            .order("inbound_date")
            .execute()
        )

        lots = lots_resp.data or []
        total_available = sum(int(l.get("current_qty", 0)) for l in lots)

        if total_available < outbound_qty:
            st.error(f"❌ 출고 가능 재고가 부족합니다. (현재 재고: {total_available}개, 요청 수량: {outbound_qty}개)")
            return False

        remaining_to_out = int(outbound_qty)
        avg_unit_price = 0.0

        for lot in lots:
            if remaining_to_out <= 0:
                break

            lot_id = lot["lot_id"]
            current_qty = int(lot["current_qty"])
            u_price = float(lot["unit_price"])

            if current_qty <= remaining_to_out:
                deduct_qty = current_qty
                remaining_to_out -= current_qty
                supabase.table("stock_lots").update({"current_qty": 0}).eq("lot_id", lot_id).execute()
            else:
                deduct_qty = remaining_to_out
                new_qty = current_qty - remaining_to_out
                remaining_to_out = 0
                supabase.table("stock_lots").update({"current_qty": new_qty}).eq("lot_id", lot_id).execute()

            avg_unit_price = u_price

        trans_payload = {
            "item_code": item_code,
            "trans_type": "OUT",
            "quantity": int(outbound_qty),
            "unit_price": avg_unit_price,
            "trans_date": str(trans_date),
            "requester": requester,
            "manager": manager,
            "remark": remark if remark else "FIFO 선입선출 출고",
        }
        supabase.table("stock_transactions").insert(trans_payload).execute()

        st.success(f"✅ 선입선출(FIFO) 출고 처리 완료 ({outbound_qty}개 차감)")
        return True

    except Exception as e:
        st.error(f"FIFO 출고 처리 중 오류 발생: {e}")
        return False

def upload_item_image(img_file, item_code):
    if not img_file:
        return None
    try:
        file_ext = img_file.name.split(".")[-1]
        file_path = f"items/{item_code}.{file_ext}"
        bytes_data = img_file.getvalue()

        supabase.storage.from_("item-images").upload(
            file_path,
            bytes_data,
            file_options={"upsert": "true", "content-type": img_file.type},
        )
        public_url = supabase.storage.from_("item-images").get_public_url(file_path)
        return public_url
    except Exception as e:
        return None
