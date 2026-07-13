import asyncio
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import MediaRequest
from app.utils import now_utc_naive
from datetime import timedelta

async def main():
    async with AsyncSessionLocal() as db:
        # Get total requests
        total = (await db.execute(select(func.count(MediaRequest.id)))).scalar()
        print(f"Total MediaRequest: {total}")
        
        # Get requests in the last 30 days
        start = now_utc_naive() - timedelta(days=30)
        recent = (await db.execute(select(func.count(MediaRequest.id)).filter(MediaRequest.requested_at >= start))).scalar()
        print(f"Recent (last 30 days) MediaRequest: {recent}")
        
        # Print actual dates
        rows = (await db.execute(select(MediaRequest.title, MediaRequest.requested_at).limit(10))).all()
        print("Sample requests:")
        for r in rows:
            print(f"  - {r.title}: {r.requested_at}")

if __name__ == "__main__":
    asyncio.run(main())
