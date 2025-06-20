# scripts/seed_database.py
import asyncio
import os
import logging
from dotenv import load_dotenv
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import EspritBase
from src.utils.database_service import DatabaseService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Empty list - add your own Esprits here
ESPRIT_DEFINITIONS = [
    # Example template:
    # {
    #     "name": "Your Esprit Name",
    #     "element": "Inferno",  # Choose from: Inferno, Verdant, Abyssal, Tempest, Umbral, Radiant
    #     "type": "warrior",     # Choose from: warrior, guardian, scout, mystic, titan
    #     "base_tier": 1,        # 1-18
    #     "base_atk": 15,        # Base attack stat
    #     "base_def": 10,        # Base defense stat
    #     "base_hp": 100,        # Base HP stat
    #     "description": "Description of your Esprit",
    #     "image_url": "https://example.com/your_esprit.png"  # Optional
    # },
]

async def seed_esprits():
    """
    Initializes the database service and seeds the esprit_base table.
    Checks if an esprit already exists by its name before inserting.
    """
    load_dotenv()
    logger.info("Initializing DatabaseService for seeding...")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not found.")
        return
        
    DatabaseService.init()
    session_factory = DatabaseService.get_session_factory()

    if not ESPRIT_DEFINITIONS:
        logger.warning("No Esprits defined to seed. Add them to ESPRIT_DEFINITIONS list.")
        return

    logger.info(f"Preparing to seed {len(ESPRIT_DEFINITIONS)} Esprits...")
    async with session_factory() as session:
        for esprit_data in ESPRIT_DEFINITIONS:
            # Check if the Esprit already exists
            statement = select(EspritBase).where(EspritBase.name == esprit_data["name"])
            result = await session.execute(statement)
            existing_esprit = result.scalar_one_or_none()
            
            if not existing_esprit:
                # If it doesn't exist, create and add it
                new_esprit = EspritBase(**esprit_data)
                session.add(new_esprit)
                logger.info(f"Added new Esprit: {new_esprit.name} ({new_esprit.element} {new_esprit.type})")
            else:
                # Update existing if needed
                for key, value in esprit_data.items():
                    setattr(existing_esprit, key, value)
                logger.info(f"Updated existing Esprit: {existing_esprit.name}")
        
        await session.commit()
    logger.info("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(seed_esprits())