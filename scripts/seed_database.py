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

# Define the initial list of Esprits you want in the game.
# You can expand this list whenever you want to add new content.
ESPRIT_DEFINITIONS = [
    {
        "slug": "faeling",
        "name": "Faeling",
        "description": "A mischievous spirit of the whispering glades.",
        "element": "Nature",
        "base_tier": 1
    },
    {
        "slug": "treant_sapling",
        "name": "Treant Sapling",
        "description": "An ancient tree in its infancy, radiating with life.",
        "element": "Nature",
        "base_tier": 1
    },
    {
        "slug": "flame_imp",
        "name": "Flame Imp",
        "description": "A small, fiery creature born from volcanic embers.",
        "element": "Fire",
        "base_tier": 1
    },
    {
        "slug": "sylph",
        "name": "Sylph",
        "description": "A graceful air elemental that dances on the wind.",
        "element": "Air",
        "base_tier": 2
    },
    {
        "slug": "aqua_serpent",
        "name": "Aqua Serpent",
        "description": "A slick, powerful serpent that commands the grotto waters.",
        "element": "Water",
        "base_tier": 2
    }
]

async def seed_esprits():
    """
    Initializes the database service and seeds the esprit_base table.
    Checks if an esprit already exists by its slug before inserting.
    """
    load_dotenv()
    logger.info("Initializing DatabaseService for seeding...")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not found.")
        return
        
    DatabaseService.init() # Use the synchronous init method
    session_factory = DatabaseService.get_session_factory()

    logger.info(f"Preparing to seed {len(ESPRIT_DEFINITIONS)} Esprits...")
    async with session_factory() as session:
        for esprit_data in ESPRIT_DEFINITIONS:
            # Check if the Esprit already exists
            statement = select(EspritBase).where(EspritBase.slug == esprit_data["slug"])
            result = await session.execute(statement)
            existing_esprit = result.scalar_one_or_none()
            
            if not existing_esprit:
                # If it doesn't exist, create and add it
                new_esprit = EspritBase(**esprit_data)
                session.add(new_esprit)
                logger.info(f"Added new Esprit: {new_esprit.name}")
            else:
                logger.info(f"Skipping existing Esprit: {existing_esprit.name}")
        
        await session.commit()
    logger.info("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(seed_esprits())