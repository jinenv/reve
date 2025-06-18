# run.py
import asyncio
from src.main import main

async def async_main():
    await main()

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Bot shutdown gracefully.")