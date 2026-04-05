"""Create sample call log data for testing."""

import httpx
import asyncio

API_URL = "http://localhost:8000/api/v1"

SAMPLE_CALLS = [
    {
        "utterances": [
            {"speaker": "Agent", "text": "Xin chào anh, em là tư vấn viên của công ty ABC.", "start_time": 0.0, "end_time": 3.2},
            {"speaker": "Customer", "text": "Chào em. Anh muốn khiếu nại về đơn hàng đặt ngày 15 tháng 3.", "start_time": 3.5, "end_time": 7.1},
            {"speaker": "Agent", "text": "Dạ anh cho em xin mã đơn hàng ạ.", "start_time": 7.5, "end_time": 9.8},
            {"speaker": "Customer", "text": "Mã đơn là ORD-2026-1234. Hàng giao bị hỏng, anh rất thất vọng.", "start_time": 10.0, "end_time": 14.5},
            {"speaker": "Agent", "text": "Em xin lỗi anh ạ. Em sẽ chuyển sang bộ phận bảo hành xử lý ngay.", "start_time": 15.0, "end_time": 19.0},
        ],
        "direction": "inbound",
        "status": "completed",
        "speaker_a": {"name": "Agent Lan", "phone_number": "19001234", "role": "agent"},
        "speaker_b": {"name": "Nguyễn Văn A", "phone_number": "0912345678", "role": "customer"},
        "language": "vi",
        "tags": ["complaint", "damaged-product"],
        "duration_seconds": 19.0,
    },
    {
        "utterances": [
            {"speaker": "Agent", "text": "Chào chị, em gọi xác nhận lịch hẹn bảo hành ạ.", "start_time": 0.0, "end_time": 3.0},
            {"speaker": "Customer", "text": "Vâng em, chị nhận được tin nhắn rồi.", "start_time": 3.2, "end_time": 5.5},
            {"speaker": "Agent", "text": "Dạ chị mang sản phẩm đến trung tâm lúc 9h sáng ngày mai nhé.", "start_time": 5.8, "end_time": 9.5},
            {"speaker": "Customer", "text": "Được em, cảm ơn em nhiều nhé. Dịch vụ rất tốt.", "start_time": 9.8, "end_time": 12.5},
        ],
        "direction": "outbound",
        "status": "completed",
        "speaker_a": {"name": "Agent Bình", "phone_number": "19001234", "role": "agent"},
        "speaker_b": {"name": "Trần Thị B", "phone_number": "0987654321", "role": "customer"},
        "language": "vi",
        "tags": ["warranty", "appointment"],
        "duration_seconds": 12.5,
    },
    {
        "utterances": [
            {"speaker": "Customer", "text": "Tôi muốn hỏi về gói cước Internet mới.", "start_time": 0.0, "end_time": 2.5},
            {"speaker": "Agent", "text": "Dạ hiện tại bên em có gói Premium 300Mbps giá 250 nghìn một tháng ạ.", "start_time": 2.8, "end_time": 7.0},
            {"speaker": "Customer", "text": "Có gói nào rẻ hơn không em?", "start_time": 7.3, "end_time": 9.0},
            {"speaker": "Agent", "text": "Dạ có gói Basic 100Mbps giá 150 nghìn ạ. Anh muốn đăng ký gói nào?", "start_time": 9.2, "end_time": 13.0},
            {"speaker": "Customer", "text": "Để anh suy nghĩ thêm đã. Cảm ơn em.", "start_time": 13.3, "end_time": 15.5},
        ],
        "direction": "inbound",
        "status": "completed",
        "speaker_a": {"name": "Agent Mai", "phone_number": "19009999", "role": "agent"},
        "speaker_b": {"name": "Lê Văn C", "phone_number": "0901234567", "role": "customer"},
        "language": "vi",
        "tags": ["sales", "consultation"],
        "duration_seconds": 15.5,
    },
    {
        "utterances": [
            {"speaker": "Customer", "text": "Em ơi anh muốn thanh toán hóa đơn tháng này.", "start_time": 0.0, "end_time": 3.0},
            {"speaker": "Agent", "text": "Dạ anh cho em số tài khoản ạ.", "start_time": 3.2, "end_time": 5.0},
            {"speaker": "Customer", "text": "Số tài khoản TK-5678. Tổng bao nhiêu em?", "start_time": 5.3, "end_time": 8.0},
            {"speaker": "Agent", "text": "Dạ tổng là 3 triệu 500 nghìn đồng ạ. Anh thanh toán qua chuyển khoản hay thẻ ạ?", "start_time": 8.2, "end_time": 13.0},
            {"speaker": "Customer", "text": "Chuyển khoản nhé em. Cảm ơn em.", "start_time": 13.3, "end_time": 15.0},
        ],
        "direction": "inbound",
        "status": "completed",
        "speaker_a": {"name": "Agent Hoa", "phone_number": "19005678", "role": "agent"},
        "speaker_b": {"name": "Vũ Văn D", "phone_number": "0933456789", "role": "customer"},
        "language": "vi",
        "tags": ["payment", "billing"],
        "duration_seconds": 15.0,
    },
]


async def main():
    async with httpx.AsyncClient() as client:
        for i, call in enumerate(SAMPLE_CALLS):
            resp = await client.post(f"{API_URL}/call-logs", json=call)
            if resp.status_code == 201:
                data = resp.json()
                print(f"[{i+1}] Created: {data['call_id']}")
            else:
                print(f"[{i+1}] Error {resp.status_code}: {resp.text}")


if __name__ == "__main__":
    asyncio.run(main())
