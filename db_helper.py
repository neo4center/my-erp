import os
import datetime
from supabase import create_client, Client
import streamlit as st

# Supabase 연결 설정 (Streamlit secrets 또는 환경 변수 활용)
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get(
    "SUPABASE_KEY", os.environ.get("SUPABASE_KEY", "")
)

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error(
        "Supabase 연결 정보가 설정되지 않았습니다. st.secrets 또는 환경 변수를 확인해주세요."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_stock_by_lots():
    """모든 재고 Lot 데이터를 가져옵니다."""
    try:
        resp = (
            supabase.table("stock_lots")
            .select("*")
            .gt("current_qty", 0)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        st.error(f"재고 Lot 조회 오류: {e}")
        return []


def register_inbound_lot(
    item_code, item_name, category, inbound_date, unit_price, quantity
):
    """신규 입고 시 stock_lots와 stock_transactions에 기록을 남깁니다."""
    try:
        # 1. stock_lots에 새로운 로트 추가 (기본적으로 오름차순 정렬 및 FIFO 대상이 됨)
        lot_payload = {
            "item_code": item_code,
            "current_qty": int(quantity),
            "unit_price": float(unit_price),
            "inbound_date": str(inbound_date),
        }
        supabase.table("stock_lots").insert(lot_payload).execute()

        # 2. stock_transactions에 입고 거래 내역 추가
        trans_payload = {
            "item_code": item_code,
            "trans_type": "IN",
            "quantity": int(quantity),
            "unit_price": float(unit_price),
            "trans_date": str(inbound_date),
            "requester": "시스템입고",
            "manager": "관리자",
            "remark": "자재 입고 등록",
        }
        supabase.table("stock_transactions").insert(trans_payload).execute()
        return True
    except Exception as e:
        st.error(f"입고 등록 처리 중 오류 발생: {e}")
        return False


def process_fifo_outbound(
    item_code,
    outbound_qty,
    trans_date,
    requester="출고담당자",
    manager="관리자",
    remark="",
):
    """
    선입선출(FIFO) 방식으로 출고를 처리합니다.
    입고일(inbound_date)이 빠른 순서대로 로트에서 수량을 차감합니다.
    (TypeError를 유발하던 asc=True 인자를 제거하고 기본 오름차순 정렬 적용)
    """
    try:
        # 1. 재고가 남아있는 로트들을 입고일 기준 오름차순 조회
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
            st.error(
                f"❌ 출고 가능 재고가 부족합니다. (현재 재고: {total_available}개, 요청 수량: {outbound_qty}개)"
            )
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
                # 해당 로트의 수량이 소모되거나 딱 맞아떨어지는 경우
                deduct_qty = current_qty
                remaining_to_out -= current_qty

                # 로트 잔고를 0으로 업데이트
                supabase.table("stock_lots").update(
                    {"current_qty": 0}
                ).eq("lot_id", lot_id).execute()
            else:
                # 해당 로트의 수량이 충분한 경우 (부분 차감)
                deduct_qty = remaining_to_out
                new_qty = current_qty - remaining_to_out
                remaining_to_out = 0

                supabase.table("stock_lots").update(
                    {"current_qty": new_qty}
                ).eq("lot_id", lot_id).execute()

            avg_unit_price = u_price

        # 2. stock_transactions에 출고 거래 내역 기록
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
    """품목 이미지를 Supabase Storage에 업로드하고 공인 URL을 반환합니다."""
    if not img_file:
        return None
    try:
        file_ext = img_file.name.split(".")[-1]
        file_path = f"items/{item_code}.{file_ext}"
        bytes_data = img_file.getvalue()

        # 기존 파일이 있다면 업로드 오버라이드
        supabase.storage.from_("item-images").upload(
            file_path,
            bytes_data,
            file_options={"upsert": "true", "content-type": img_file.type},
        )
        public_url = supabase.storage.from_("item-images").get_public_url(
            file_path
        )
        return public_url
    except Exception as e:
        # 버킷이 없거나 권한 문제 발생 시 None 반환
        return None
