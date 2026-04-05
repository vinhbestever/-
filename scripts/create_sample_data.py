"""Submit sample call audio URLs for ingest processing."""

import httpx
import asyncio

API_URL = "http://localhost:8000/api/v1"

SAMPLE_CALLS = [
    {
        "audio_url": "https://storage.example.com/calls/complaint-001.wav",
        "direction": "inbound",
        "speaker_a": {"name": "Agent Lan", "phone_number": "19001234", "role": "agent"},
        "speaker_b": {"name": "Nguyễn Văn A", "phone_number": "0912345678", "role": "customer"},
        "language": "vi",
        "tags": ["complaint", "damaged-product"],
        "duration_seconds": 245,
    },
    {
        "audio_url": "https://storage.example.com/calls/warranty-002.wav",
        "direction": "outbound",
        "speaker_a": {"name": "Agent Bình", "phone_number": "19001234", "role": "agent"},
        "speaker_b": {"name": "Trần Thị B", "phone_number": "0987654321", "role": "customer"},
        "language": "vi",
        "tags": ["warranty", "appointment"],
        "duration_seconds": 120,
    },
    {
        "audio_url": "https://storage.example.com/calls/consultation-003.wav",
        "direction": "inbound",
        "speaker_a": {"name": "Agent Mai", "phone_number": "19009999", "role": "agent"},
        "speaker_b": {"name": "Lê Văn C", "phone_number": "0901234567", "role": "customer"},
        "language": "vi",
        "tags": ["sales", "consultation"],
        "duration_seconds": 300,
    },
    {
        "audio_url": "https://storage.example.com/calls/payment-004.wav",
        "direction": "inbound",
        "speaker_a": {"name": "Agent Hoa", "phone_number": "19005678", "role": "agent"},
        "speaker_b": {"name": "Vũ Văn D", "phone_number": "0933456789", "role": "customer"},
        "language": "vi",
        "tags": ["payment", "billing"],
        "duration_seconds": 150,
    },
]


async def main():
    async with httpx.AsyncClient() as client:
        for i, call in enumerate(SAMPLE_CALLS):
            resp = await client.post(f"{API_URL}/ingest", json=call)
            if resp.status_code == 202:
                data = resp.json()
                print(f"[{i+1}] Submitted: job_id={data['job_id']} status={data['status']}")
            else:
                print(f"[{i+1}] Error {resp.status_code}: {resp.text}")


if __name__ == "__main__":
    asyncio.run(main())
