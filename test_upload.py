import httpx
import json
import asyncio

async def test_api():
    async with httpx.AsyncClient() as client:
        # First check the demo call worked
        res = await client.get("http://localhost:8000/api/accounts/unknown_company")
        print("GET unknown_company:", res.status_code)
        
        # Now test onboarding
        req = {
            "transcript": "ONBOARDING CALL TRANSCRIPT - Test Auto Repair Shop\n[00:00] Clara Rep: Following up on our setup. Any changes?\n[00:10] Shop Owner: Yes, we now also do transmission repairs, and our hours changed to 8 AM to 5 PM.",
            "call_type": "onboarding",
            "account_id": "unknown_company"
        }
        res = await client.post("http://localhost:8000/api/process", json=req, timeout=30.0)
        print("POST onboarding Status:", res.status_code)
        print("POST onboarding Body:", res.text)

if __name__ == "__main__":
    asyncio.run(test_api())
