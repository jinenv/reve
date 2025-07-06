import asyncio
import logging
from src.services.player_class_service import PlayerClassService
from src.database.models.player_class import PlayerClassType
from src.utils.database_service import DatabaseService

logging.basicConfig(level=logging.INFO)

async def test_class_selection():
    """Quick test of class selection service"""
    
    # Find a test player
    async with DatabaseService.get_session() as session:
        from sqlalchemy import select
        from src.database.models.player import Player
        
        stmt = select(Player).limit(1)
        result = await session.execute(stmt)
        test_player = result.scalar_one_or_none()
        
        if not test_player:
            print("❌ No players found for testing")
            return
            
        print(f"✅ Testing with player: {test_player.username} (ID: {test_player.id})")
        
        # Test class selection
        result = await PlayerClassService.select_class(
            player_id=test_player.id, # type: ignore
            class_type=PlayerClassType.ENLIGHTENED,
            cost=0
        )
        
        print(f"🎯 Result: success={result.success}")
        if result.success:
            print(f"📊 Data: {result.data}")
        else:
            print(f"❌ Error: {result.error}")

if __name__ == "__main__":
    DatabaseService.init()
    asyncio.run(test_class_selection())