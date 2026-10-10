import os
import streamlit as st
from supabase import create_client, Client
from PIL import Image, ImageOps
import io
import time
import pandas as pd

SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def safe_float(val, default=0.0):
    if pd.isna(val) or val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def get_stock_by_lots():
    try:
        resp = supabase.table("stock_lots").select("*").execute()
        return resp.data or []
    except Exception:
        return []

def register_inbound_lot(item_code, item_name, category, inbound_date, unit_price, quantity, manager, requester, remark):
    try:
        # 1. 입출고 트랜잭션 기록
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

        # 2. 랏(Lot) 테이블 기록
        try:
            supabase.table("stock_lots").insert({
                "item_code": item_code,
                "current_qty": quantity,
                "unit_price": unit_price,
                "inbound_date": inbound_date
            }).execute()
        except Exception:
            pass

        # 3. 💡 품목 마스터(items) 테이블의 대표 단가와 입고일도 최신 입고가로 자동 갱신
        try:
            supabase.table("items").update({
                "unit_price": unit_price,
                "in_date": inbound_date
            }).eq("item_code", item_code).execute()
        except Exception:
            pass

    except Exception as e:
        st.error(f"입고 등록 중 오류 발생: {e}")

def process_fifo_outbound(item_code, outbound_qty, trans_date, requester, manager, remark, unit_price=0):
    try:
        final_unit_price = float(unit_price) if unit_price is not None and float(unit_price) > 0 else 0
        if final_unit_price == 0:
            last_in = supabase.table("stock_transactions").select("unit_price").eq("item_code", item_code).eq("trans_type", "IN").order("trans_date", desc=True).limit(1).execute().data
            final_unit_price = safe_float(last_in[0]["unit_price"]) if last_in else 0

        supabase.table("stock_transactions").insert({
            "item_code": item_code,
            "trans_type": "OUT",
            "quantity": outbound_qty,
            "unit_price": final_unit_price,
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
        img = ImageOps.exif_transpose(img)
        
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
            
        width, height = img.size
        min_side = min(width, height)
        left = (width - min_side) / 2
        top = (height - min_side) / 2
        right = (width + min_side) / 2
        bottom = (height + min_side) / 2
        
        img = img.crop((left, top, right, bottom))
        img = img.resize((500, 500), Image.Resampling.LANCZOS)
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        img_byte_arr.seek(0)
        
        timestamp = int(time.time())
        file_path = f"items/{item_code}_{timestamp}.jpg"
        
        try:
            existing_files = supabase.storage.from_("item_images").list("items", {"search": item_code})
            if existing_files:
                files_to_remove = [f"items/{f['name']}" for f in existing_files if f['name'].startswith(f"{item_code}_")]
                if files_to_remove:
                    supabase.storage.from_("item_images").remove(files_to_remove)
        except Exception:
            pass

        supabase.storage.from_("item_images").upload(
            file_path, 
            img_byte_arr.getvalue(), 
            file_options={"upsert": "true", "content-type": "image/jpeg"}
        )
        
        res = supabase.storage.from_("item_images").get_public_url(file_path)
        if isinstance(res, dict):
            public_url = res.get("publicUrl") or res.get("data", {}).get("publicUrl")
        else:
            public_url = str(res)
            
        return public_url
    except Exception as e:
        st.error(f"이미지 업로드 중 오류 발생: {e}")
        return None
