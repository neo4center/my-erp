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
    """
    try:
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
        last_in = supabase.table("stock_transactions").select("unit_price").eq("item_code", item_code).eq("trans_type", "IN").order("trans_date", desc=True).limit(1).execute().data
        unit_p = last_in[0]["unit_price"] if last_in else 0

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
        if image_file is None:
            return None
            
        img = Image.open(image_file)
        
        # 투명 채널(RGBA, P, LA 등)이 포함된 경우 JPEG 변환을 위해 RGB로 변환
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
            
        img.thumbnail((500, 500))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        img_byte_arr.seek(0)
        
        file_path = f"items/{item_code}.jpg"
        
        # 스토리지 업로드 (upsert 허용)
        supabase.storage.from_("item_images").upload(
            file_path, 
            img_byte_arr.getvalue(), 
            file_options={"upsert": "true", "content-type": "image/jpeg"}
        )
        
        # 공개 URL 획득 (버전별 반환 형태 대응)
        res = supabase.storage.from_("item_images").get_public_url(file_path)
        
        if isinstance(res, dict):
            public_url = res.get("publicUrl") or res.get("data", {}).get("publicUrl")
        else:
            public_url = str(res)
            
        return public_url
    except Exception as e:
        st.error(f"이미지 업로드 중 오류 발생: {e}")
        return None
