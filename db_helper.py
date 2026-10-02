import io
import streamlit as st
from PIL import Image
from supabase import create_client, Client

# 1. Supabase 연결 초기화 (st.secrets 사용)
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# 2. 이미지 자동 압축(Thumbnail) 및 Supabase Storage 업로드
def upload_item_image(image_file, item_code: str) -> str:
    """
    업로드한 이미지를 400x400 이하 썸네일(JPEG, ~100KB)로 자동 압축 후
    Supabase Storage('item-images')에 저장하고 Public URL을 반환합니다.
    """
    try:
        img = Image.open(image_file)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        img.thumbnail((400, 400))
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        buffer.seek(0)
        
        file_path = f"{item_code}_thumb.jpg"
        bucket_name = "item-images"
        
        supabase.storage.from_(bucket_name).upload(
            file_path, 
            buffer.getvalue(), 
            file_options={"content-type": "image/jpeg", "upsert": "true"}
        )
        
        public_url = supabase.storage.from_(bucket_name).get_public_url(file_path)
        return public_url
    except Exception as e:
        st.error(f"이미지 업로드 중 오류 발생: {e}")
        return None

# 3. Lot/배치 기반 단가별 입고 등록 함수
def register_inbound_lot(item_code, item_name, category, inbound_date, unit_price, quantity, image_file=None):
    """
    동일 품목이라도 단가나 입고일이 다르면 새로운 Lot 레코드로 분리하여 저장합니다.
    """
    photo_url = None
    if image_file:
        photo_url = upload_item_image(image_file, item_code)
        
    # 1) items (품목 마스터) 등록/업데이트
    item_data = {
        "item_code": item_code,
        "item_name": item_name,
        "category": category
    }
    if photo_url:
        item_data["photo_url"] = photo_url
        
    supabase.table("items").upsert(item_data).execute()
    
    # 2) stock_lots (Lot별 재고) 추가
    lot_data = {
        "item_code": item_code,
        "inbound_date": inbound_date,
        "unit_price": unit_price,
        "current_qty": quantity
    }
    lot_result = supabase.table("stock_lots").insert(lot_data).execute()
    new_lot_id = lot_result.data[0]["lot_id"]
    
    # 3) stock_transactions (입출고 이력) 남기기
    trans_data = {
        "trans_date": inbound_date,
        "trans_type": "IN",
        "lot_id": new_lot_id,
        "item_code": item_code,
        "quantity": quantity,
        "unit_price": unit_price
    }
    supabase.table("stock_transactions").insert(trans_data).execute()
    
    return new_lot_id

# 4. 재고 현황 조회 (stock_lots와 items 조인)
def get_stock_by_lots():
    """
    stock_lots와 items를 조인하여 Lot별 재고 및 상세 품목 정보, 사진 URL을 조회합니다.
    """
    try:
        response = supabase.table("stock_lots") \
            .select("lot_id, item_code, inbound_date, unit_price, current_qty, items(item_name, item_detail_no, model_spec, category_type, category_main, category_sub, shelf_no, zone, device_name, maker, photo_url)") \
            .gt("current_qty", 0) \
            .order("inbound_date", desc=False) \
            .execute()
        return response.data or []
    except Exception as e:
        st.error(f"재고 데이터 조회 중 오류 발생: {e}")
        return []

# 5. FIFO(선입선출) 출고 처리 함수
def process_fifo_outbound(item_code: str, outbound_qty: int, trans_date: str):
    """
    해당 품목의 잔여 재고가 있는 Lot들을 입고일자 순(FIFO)으로 불러와 
    요청 수량만큼 순차적으로 차감하고 출고 이력을 남깁니다.
    """
    lots_response = supabase.table("stock_lots") \
        .select("*") \
        .eq("item_code", item_code) \
        .gt("current_qty", 0) \
        .order("inbound_date", asc=True) \
        .execute()
        
    lots = lots_response.data
    total_available = sum(lot["current_qty"] for lot in lots)
    
    if total_available < outbound_qty:
        st.error(f"재고 부족! (현재 남은 재고: {total_available}개 / 요청 수량: {outbound_qty}개)")
        return False
        
    remaining_to_deduct = outbound_qty
    
    for lot in lots:
        if remaining_to_deduct <= 0:
            break
            
        lot_id = lot["lot_id"]
        current_qty = lot["current_qty"]
        unit_price = lot["unit_price"]
        
        if current_qty <= remaining_to_deduct:
            deduct_qty = current_qty
            remaining_to_deduct -= deduct_qty
            new_qty = 0
        else:
            deduct_qty = remaining_to_deduct
            new_qty = current_qty - remaining_to_deduct
            remaining_to_deduct = 0
            
        supabase.table("stock_lots") \
            .update({"current_qty": new_qty}) \
            .eq("lot_id", lot_id) \
            .execute()
            
        trans_data = {
            "trans_date": trans_date,
            "trans_type": "OUT",
            "lot_id": lot_id,
            "item_code": item_code,
            "quantity": deduct_qty,
            "unit_price": unit_price
        }
        supabase.table("stock_transactions").insert(trans_data).execute()
        
    st.success(f"[{item_code}] 총 {outbound_qty}개 선입선출(FIFO) 출고 처리 완료!")
    return True
