# test_database.py - Run this to check your database setup
import asyncio
from src.utils.database_service import DatabaseService
from src.database.models.player import Player
from sqlalchemy import select

async def test_database():
    try:
        async with DatabaseService.get_session() as session:
            # Test if Player table exists
            stmt = select(Player).limit(1)
            result = await session.execute(stmt)
            print("✅ Database connection works")
            print("✅ Player table exists")
            
            # Test creating a player directly
            from src.services.player_service import PlayerService
            result = await PlayerService.get_or_create_player(
                discord_id=12345,
                username="TestUser"
            )
            
            if result.success:
                print("✅ PlayerService.get_or_create_player works")
            else:
                print(f"❌ PlayerService failed: {result.message}")
                
    except Exception as e:
        print(f"❌ Database error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_database())