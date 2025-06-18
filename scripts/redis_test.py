import asyncio
from src.utils.redis_service import RedisService

async def main():
    RedisService.init()  # ✅ DO NOT await this
    await RedisService.set("test-key", "hello")
    value = await RedisService.get("test-key")
    print(f"Value from Redis: {value}")

asyncio.run(main())


