import asyncio
from app.database import AsyncSessionLocal
from app.models import Settings
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        s = (await db.execute(select(Settings))).scalars().first()
        print(f"email_enabled: {s.email_enabled}")
        print(f"email_on_request: {s.email_on_request}")
        print(f"smtp_host: {s.smtp_host}")
        print(f"smtp_from: {s.smtp_from}")

if __name__ == "__main__":
    asyncio.run(main())
