import asyncio
from database import engine, Base
from sqlalchemy import inspect, text

async def check():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))
        columns = result.fetchall()
        print('Columns in users table:')
        for col in columns:
            print(f'  - {col[0]}')

asyncio.run(check())
