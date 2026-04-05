"""Script to create sample call log data for testing."""

import httpx
import asyncio
import json

API_URL = "http://localhost:8000/api/v1"

SAMPLE_CALLS = [
    {
        "transcript_text": (
            "Xin chào, tôi là Nguyễn Văn A, số điện thoại 0912345678. "
            "Tôi muốn khiếu nại về đơn hàng ngày 15/03/2026. "
            "Tổng số tiền là 500.000 đồng nhưng hàng bị hỏng. "
            "Tôi rất thất vọng với dịch vụ. Bạn cần kiểm tra lại và gọi lại cho tôi."
        ),
        "direction": "inbound",
        "status": "completed",
        "caller": {"name": "Nguyễn Văn A", "phone_number": "0912345678", "role": "customer"},
        "callee": {"name": "CSKH Hotline", "phone_number": "19001234", "role": "agent"},
        "language": "vi",
        "tags": ["complaint", "damaged-product"],
        "duration_seconds": 245,
    },
    {
        "transcript_text": (
            "Chào anh, em gọi để xác nhận lịch hẹn bảo hành ngày 20/03/2026. "
            "Anh có thể mang sản phẩm đến trung tâm lúc 9h sáng không ạ? "
            "Phí bảo hành là 200.000 đồng. Cảm ơn anh đã sử dụng dịch vụ."
        ),
        "direction": "outbound",
        "status": "completed",
        "caller": {"name": "Trần Thị B", "phone_number": "0987654321", "role": "agent"},
        "callee": {"name": "Lê Văn C", "phone_number": "0901234567", "role": "customer"},
        "language": "vi",
        "tags": ["warranty", "appointment"],
        "duration_seconds": 120,
    },
    {
        "transcript_text": (
            "Hello, I need to check on my order status. My order number is ORD-2026-1234. "
            "I placed it on 10/03/2026 and paid $150 USD. "
            "The delivery was supposed to arrive yesterday. "
            "Can you please follow up and send me a tracking number?"
        ),
        "direction": "inbound",
        "status": "completed",
        "caller": {"name": "John Smith", "phone_number": "+84901111222", "role": "customer"},
        "callee": {"name": "Support Agent", "phone_number": "19009999", "role": "agent"},
        "language": "en",
        "tags": ["order-tracking", "delivery"],
        "duration_seconds": 180,
    },
    {
        "transcript_text": (
            "Dạ em chào chị. Em gọi để tư vấn gói dịch vụ mới cho chị ạ. "
            "Gói Premium có giá 1.5 triệu mỗi tháng, bao gồm hỗ trợ 24/7. "
            "Chị có muốn đăng ký không ạ? Em sẽ gửi hợp đồng qua email cho chị."
        ),
        "direction": "outbound",
        "status": "completed",
        "caller": {"name": "Phạm Thị D", "phone_number": "0909876543", "role": "agent"},
        "callee": {"name": "Hoàng Thị E", "phone_number": "0918765432", "role": "customer"},
        "language": "vi",
        "tags": ["sales", "consultation"],
        "duration_seconds": 300,
    },
    {
        "transcript_text": (
            "Tôi gọi để thanh toán hóa đơn tháng này. Số tài khoản của tôi là TK-5678. "
            "Tổng số tiền cần thanh toán là 3.5 triệu đồng. "
            "Tôi muốn chuyển khoản qua ngân hàng. Cảm ơn, dịch vụ rất tốt."
        ),
        "direction": "inbound",
        "status": "completed",
        "caller": {"name": "Vũ Văn F", "phone_number": "0933456789", "role": "customer"},
        "callee": {"name": "Bộ phận thanh toán", "phone_number": "19005678", "role": "agent"},
        "language": "vi",
        "tags": ["payment", "billing"],
        "duration_seconds": 150,
    },
]


async def main():
    async with httpx.AsyncClient() as client:
        for i, call in enumerate(SAMPLE_CALLS):
            resp = await client.post(f"{API_URL}/call-logs", json=call)
            if resp.status_code == 201:
                data = resp.json()
                print(f"[{i+1}] Created call log: {data['call_id']} "
                      f"(sentiment: {data.get('enriched', {}).get('sentiment', 'N/A')})")
            else:
                print(f"[{i+1}] Error: {resp.status_code} — {resp.text}")


if __name__ == "__main__":
    asyncio.run(main())
