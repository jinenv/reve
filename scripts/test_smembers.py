import asyncio
import pathlib
import sys
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from src.utils.redis_service import RedisService

async def probe():
    client = RedisService.get_client()
    if client is None:
        print("Redis client is None → Redis not running / not configured")
        return

    raw = client.smembers("nonexistent:test:set")
    print("Raw smembers return type:", type(raw))

    if asyncio.iscoroutine(raw):
        awaited = await raw
        print("After await →", type(awaited), awaited)

asyncio.run(probe())
