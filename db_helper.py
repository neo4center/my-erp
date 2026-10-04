import os
import streamlit as st
from supabase import create_client, Client
from PIL import Image
import io

SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_stock_by_lots():
    try:
        resp = supabase.table("stock_lots").select("*").execute()
        return resp.data or []
    except Exception:
        return []

def register_inbound_lot(item_code, item_name, category, inbound_date, unit_price, quantity, manager, requester, remark):
    try:
        # Lot 테이블 등록
        supabase.table("stock_lots").insert({
            "item_code": item_code,
            "current_qty": quantity,
            "unit_price": unit_price,
            "inbound_date": inbound_date
        }).execute()

        # 트랜잭션 테이블 등록 (담당자, 요청자, 비고 정확히 저장)
        supabase.table("stock_transactions").insert({
            "item_code": item_code,
            "trans_type": "IN",
            "quantity": quantity,
            "unit_price": unit_price,
            "trans_date": inbound_date,
            "requester": requester if requester and requester != "-" else "-",
            "manager": manager if manager else "최광호",
            "remark": remark if remark else "-"
        }).execute()
    except Exception as e:
        st.error(f"입고 등록 중 오류 발생: {e}")

def process_fifo_outbound(item_code, outbound_qty, trans_date, requester, manager, remark):
    try:
        lots = supabase.table("stock_lots").select("*").eq("item_code", item_code).gt("current_qty", 0).order("inbound_date", desc=False).execute().data or []
        
        remaining_qty = outbound_qty
        for lot in lots:
            if remaining_qty <= 0:
                break
            lot_id = lot["lot_id"]
            current_qty = lot["current_qty"]
            
            if current_qty <= remaining_qty:
                deduct = current_qty
                remaining_qty -= deduct
                supabase.table("stock_lots").update({"current_qty": 0}).eq("lot_id", lot_id).execute()
            else:
                deduct = remaining_qty
                new_qty = current_qty - remaining_qty
                remaining_qty = 0
                supabase.table("stock_lots").update({"current_qty": new_qty}).eq("lot_id", lot_id).execute()

        # 출고 트랜잭션 기록 (요청자, 담당자, 비고 정확히 저장)
        supabase.table("stock_transactions").insert({
            "item_code": item_code,
            "trans_type": "OUT",
            "quantity": outbound_qty,
            "unit_price": lots[0]["unit_price"] if lots else 0,
            "trans_date": trans_date,
            "requester": requester if requester else "출고담당자",
            "manager": manager if manager else "최광호",
            "remark": remark if remark else "FIFO 선입선출 출고"
        }).execute()
    except Exception as e:
        st.error(f"출고 처리 중 오류 발생: {e}")

def upload_item_image(image_file, item_code):
    try:
        img = Image.open(image_file)
        img.thumbnail((500, 500))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        img_byte_arr.seek(0)
        
        file_path = f"items/{item_code}.jpg"
        supabase.storage.from_("item_images").upload(file_path, img_byte_arr.getvalue(), file_options={"upsert": "true"})
        public_url = supabase.storage.from_("item_images").get_public_url(file_path)
        return public_url
    except Exception:
        return None
