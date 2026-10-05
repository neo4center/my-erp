import os
import streamlit as st
from supabase import create_client, Client
from PIL import Image
import io

SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_stock_by_lots():
    """
    호환성을 위해 유지하되, 현재고는 stock_transactions를 기준으로 계산되므로
    이 함수는 단순 참조용 Lot 목록(또는 빈 리스트)을 반환합니다.
    """
    try:
        resp = supabase.table("stock_lots").select("*").execute()
        return resp.data or []
    except Exception:
        return []

def register_inbound_lot(item_code, item_name, category, inbound_date, unit_price, quantity, manager, requester, remark):
    """
    입고 발생 시 stock_transactions에 기록을 남깁니다.
    (stock_lots 의존성을 낮추고 트랜잭션 장부 중심 운영)
    """
    try:
        # 트랜잭션 장부에 입고 기록 추가
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

        # 선택적으로 stock_lots에도 보조 기록 (없어도 트랜잭션으로 현재고 산정됨)
        try:
            supabase.table("stock_lots").insert({
                "item_code": item_code,
                "current_qty": quantity,
                "unit_price": unit_price,
                "inbound_date": inbound_date
            }).execute()
        except Exception:
            pass

    except Exception as e:
        st.error(f"입고 등록 중 오류 발생: {e}")

def process_fifo_outbound(item_code, outbound_qty, trans_date, requester, manager, remark):
    """
    출고 발생 시 stock_transactions에 OUT 기록을 남깁니다.
    """
    try:
        # 단가 조회용 (최근 입고 단가 또는 기본 품목 단가 참조)
        last_in = supabase.table("stock_transactions").select("unit_price").eq("item_code", item_code).eq("trans_type", "IN").order("trans_date", desc=True).limit(1).execute().data
        unit_p = last_in[0]["unit_price"] if last_in else 0

        # 트랜잭션 장부에 출고 기록 추가
        supabase.table("stock_transactions").insert({
            "item_code": item_code,
            "trans_type": "OUT",
            "quantity": outbound_qty,
            "unit_price": unit_p,
            "trans_date": trans_date,
            "requester": requester if requester else "출고담당자",
            "manager": manager if manager else "최광호",
            "remark": remark if remark else "출고 처리"
        }).execute()

    except Exception as e:
        st.error(f"출고 처리 중 오류 발생: {e}")

def update_transaction(trans_id, item_code, trans_type, trans_date, quantity, unit_price, manager, requester, remark):
    try:
        supabase.table("stock_transactions").update({
            "trans_type": trans_type,
            "trans_date": trans_date,
            "quantity": quantity,
            "unit_price": unit_price,
            "manager": manager,
            "requester": requester,
            "remark": remark
        }).eq("id", trans_id).execute()
    except Exception as e:
        st.error(f"입출고 내역 수정 중 오류 발생: {e}")

def delete_transaction(trans_id):
    try:
        supabase.table("stock_transactions").delete().eq("id", trans_id).execute()
    except Exception as e:
        st.error(f"입출고 내역 삭제 중 오류 발생: {e}")

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
