import redis.asyncio as redis
from redis.exceptions import RedisError
import asyncio
from typing import Optional
from .logger import get_logger
from dotenv import load_dotenv
import os

load_dotenv()
logger = get_logger(__name__)


class RedisService:
    _client: Optional[redis.Redis] = None

    @classmethod
    def init(cls, redis_url: Optional[str] = None):
        redis_url = redis_url or os.getenv("REDIS_URL")
        if not redis_url:
            logger.error("REDIS_URL not found in environment.")
            raise ValueError("Missing REDIS_URL")

        cls._client = redis.from_url(redis_url, decode_responses=True)
        logger.info("RedisService initialized.")

    @classmethod
    def get_client(cls) -> redis.Redis:
        if cls._client is None:
            raise RuntimeError("RedisService not initialized. Call RedisService.init() first.")
        return cls._client

    @classmethod
    async def ping(cls) -> bool:
        try:
            pong = await cls.get_client().ping()
            return pong is True
        except RedisError as e:
            logger.error(f"Redis ping failed: {e}")
            return False

    @classmethod
    async def set(cls, key: str, value: str, expire_seconds: Optional[int] = None):
        try:
            await cls.get_client().set(key, value, ex=expire_seconds)
        except RedisError as e:
            logger.error(f"Redis set failed: {e}")

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        try:
            return await cls.get_client().get(key)
        except RedisError as e:
            logger.error(f"Redis get failed: {e}")
            return None
