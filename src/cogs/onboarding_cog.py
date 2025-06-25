# src/cogs/onboarding.py
import disnake
from disnake.ext import commands
from typing import Any, Optional, List
from datetime import datetime
import random

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.redis_service import RedisService
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import cast
import sqlalchemy as sa


class Onboarding(commands.Cog):
    """Handles new player registration and onboarding"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.slash_command(name="start", description="Begin your journey as an Esprit Master!")
    async def start(self, inter: disnake.ApplicationCommandInteraction):
        """Register a new player and provide starter rewards"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Check if player already exists
                stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
                existing_player = (await session.execute(stmt)).scalar_one_or_none()
                
                if existing_player:
                    # Player already registered
                    embed = disnake.Embed(
                        title="Already Registered!",
                        description=(
                            f"Welcome back, **{existing_player.username}**!\n\n"
                            f"You're already registered as an Esprit Master.\n"
                            f"**Level**: {existing_player.level}\n"
                            f"**Jijies**: {existing_player.jijies:,}\n"
                            f"**Erythl**: {existing_player.erythl}\n\n"
                            f"Use `/profile` to view your stats or `/quest` to continue your adventure!"
                        ),
                        color=EmbedColors.INFO
                    )
                    embed.set_thumbnail(url=inter.author.display_avatar.url)
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Get starter rewards from config
                global_config = ConfigManager.get("global_config") or {}
                
                # Your config has these at root level
                starter_bonuses = global_config.get("starter_bonuses", {})
                starter_pool = global_config.get("starter_pool", {})
                
                # Fallback values if not in config
                if not starter_bonuses:
                    starter_bonuses = {
                        "jijies": 5000,
                        "erythl": 10,
                        "energy": 100,
                        "stamina": 50
                    }
                
                # Create new player
                new_player = Player(
                    discord_id=inter.author.id,
                    username=inter.author.name,
                    created_at=datetime.utcnow(),
                    level=1,
                    experience=0,
                    energy=starter_bonuses.get("energy", 100),
                    max_energy=100,
                    stamina=starter_bonuses.get("stamina", 50),
                    max_stamina=50,
                    jijies=starter_bonuses.get("jijies", 5000),
                    erythl=starter_bonuses.get("erythl", 10),
                    skill_points=0,
                    total_jijies_earned=starter_bonuses.get("jijies", 5000),
                    total_erythl_earned=starter_bonuses.get("erythl", 10),
                    last_energy_update=datetime.utcnow(),
                    last_stamina_update=datetime.utcnow(),
                    last_active=datetime.utcnow()
                )
                
                # Add starter fragments if configured
                if "tier_fragments" in starter_bonuses:
                    new_player.tier_fragments = starter_bonuses["tier_fragments"].copy()  # type: ignore
                
                session.add(new_player)
                await session.flush()  # Get the player ID
                
                # Log registration
                if new_player.id is not None:
                    transaction_logger.log_transaction(
                        new_player.id,
                        TransactionType.REGISTRATION,
                        {
                            "discord_id": str(inter.author.id),
                            "username": inter.author.name,
                            "starter_rewards": starter_bonuses
                        }
                    )
                
                # Get starter Esprits - pass the starter_pool config
                starter_esprits = await self._get_starter_esprits(session, {"starter_pool": starter_pool})
                
                if not starter_esprits:
                    # Emergency fallback if no starter Esprits configured
                    stmt = select(EspritBase).where(EspritBase.base_tier == 1).limit(1)  # type: ignore
                    fallback_esprit = (await session.execute(stmt)).scalar_one_or_none()
                    if fallback_esprit:
                        starter_esprits = [fallback_esprit]
                
                # Give starter Esprits
                given_esprits = []
                first_esprit_id = None
                
                for esprit_base in starter_esprits:
                    if new_player.id is not None:
                        stack = await Esprit.add_to_collection(
                            session=session,
                            owner_id=new_player.id,
                            base=esprit_base,
                            quantity=1
                        )
                        given_esprits.append(esprit_base)
                        
                        # Store first esprit ID for leader
                        if first_esprit_id is None and stack.id is not None:
                            first_esprit_id = stack.id
                        
                        # Log the capture
                        transaction_logger.log_esprit_captured(
                            new_player.id,
                            esprit_base.name,
                            esprit_base.base_tier,
                            esprit_base.element,
                            "starter_reward"
                        )
                
                # Set first Esprit as leader
                if first_esprit_id:
                    new_player.leader_esprit_stack_id = first_esprit_id
                
                # Give starter items if configured
                if "items" in starter_bonuses:
                    items = starter_bonuses["items"]
                    if isinstance(items, dict):
                        new_player.inventory = items.copy()
                    else:
                        new_player.inventory = {}
                
                # Calculate initial power
                await new_player.recalculate_total_power(session)
                
                # Commit everything
                await session.commit()
                
                # Create welcome embed
                embed = disnake.Embed(
                    title="🎉 Welcome to Jiji!",
                    description=(
                        f"Welcome, **{inter.author.name}**! Your journey as an Esprit Master begins now!\n\n"
                        f"You've received your starter kit:"
                    ),
                    color=EmbedColors.SUCCESS
                )
                
                # Add starter rewards field
                rewards_text = f"💰 **{starter_bonuses.get('jijies', 5000):,}** Jijies\n"
                rewards_text += f"💎 **{starter_bonuses.get('erythl', 10)}** Erythl\n"
                rewards_text += f"⚡ **{starter_bonuses.get('energy', 100)}** Energy\n"
                
                if given_esprits:
                    rewards_text += f"\n**Starter Esprits:**\n"
                    for esprit in given_esprits[:3]:  # Show max 3
                        rewards_text += f"{esprit.get_element_emoji()} **{esprit.name}** (Tier {esprit.base_tier})\n"
                
                if "items" in starter_bonuses and isinstance(starter_bonuses["items"], dict):
                    rewards_text += f"\n**Starter Items:**\n"
                    for item, qty in list(starter_bonuses["items"].items())[:3]: # type: ignore
                        rewards_text += f"• **{qty}x** {item.replace('_', ' ').title()}\n"
                
                embed.add_field(
                    name="Starter Rewards",
                    value=rewards_text,
                    inline=False
                )
                
                # Add getting started guide
                embed.add_field(
                    name="Getting Started",
                    value=(
                        "**Essential Commands:**\n"
                        "`/quest` - Explore areas and capture Esprits\n"
                        "`/profile` - View your stats and progress\n"
                        "`/collection` - See your Esprit collection\n"
                        "`/fusion` - Combine Esprits to create stronger ones\n"
                        "`/help` - Learn more about the game\n\n"
                        "**Tips:**\n"
                        "• Complete quests to gain XP and capture Esprits\n"
                        "• Set a leader Esprit for special bonuses\n"
                        "• Fuse duplicate Esprits to reach higher tiers\n"
                        "• Energy regenerates over time (1 per 6 minutes)"
                    ),
                    inline=False
                )
                
                embed.set_thumbnail(url=inter.author.display_avatar.url)
                embed.set_footer(text="Mreow! Let's begin your adventure!")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Registration Failed",
                description="An error occurred during registration. Please try again or contact support.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    async def _get_starter_esprits(self, session, starter_config: Optional[dict] = None) -> List[EspritBase]:
        """Get configured starter Esprits from config"""
        if not starter_config:
            global_config = ConfigManager.get("global_config") or {}
            starter_pool = global_config.get("starter_pool", {})
        else:
            starter_pool = starter_config.get("starter_pool", {})
        
        available_starters = starter_pool.get("available_starters", [])
        selection_count = starter_pool.get("selection_count", 2)
        
        print(f"DEBUG: Found {len(available_starters)} available starters in config")
        
        if not available_starters:
            # Fallback to any tier 1 Esprits
            print("DEBUG: No starters configured, falling back to tier 1 esprits")
            stmt = select(EspritBase).where(EspritBase.base_tier == 1).limit(selection_count) # type: ignore
            result = await session.execute(stmt)
            return list(result.scalars().all())
        
        # Get weighted random selection
        starter_names = []
        weights = []
        
        for starter in available_starters:
            starter_names.append(starter["name"])
            weights.append(starter.get("weight", 1.0))
        
        print(f"DEBUG: Starter names: {starter_names}")
        
        # Select with weights
        chosen_names = []
        if len(starter_names) <= selection_count:
            chosen_names = starter_names
        else:
            # Weighted random selection without replacement
            chosen_names = []
            available_names = starter_names.copy()
            available_weights = weights.copy()
            
            for _ in range(selection_count):
                if not available_names:
                    break
                    
                # Normalize weights
                total_weight = sum(available_weights)
                normalized_weights = [w/total_weight for w in available_weights]
                
                # Choose one
                chosen_index = random.choices(range(len(available_names)), weights=normalized_weights, k=1)[0]
                chosen_names.append(available_names[chosen_index])
                
                # Remove chosen from pools
                available_names.pop(chosen_index)
                available_weights.pop(chosen_index)
        
        print(f"DEBUG: Chosen starters: {chosen_names}")
        
        # Query for the chosen starters by NAME
        stmt = select(EspritBase).where(EspritBase.name.in_(chosen_names))  # type: ignore
        result = await session.execute(stmt)
        starters = list(result.scalars().all())
        
        print(f"DEBUG: Found {len(starters)} starters in database")
        for s in starters:
            print(f"DEBUG: - {s.name} (Tier {s.base_tier}, {s.element})")
        
        return starters
    
    @commands.slash_command(name="debug_starters", description="Debug: Check tier 1 esprits")
    async def debug_starters(self, inter: disnake.ApplicationCommandInteraction):
        """Debug command to check what tier 1 esprits exist"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get ALL tier 1 esprits
                stmt = select(EspritBase).where(EspritBase.base_tier == 1) # type: ignore
                result = await session.execute(stmt)
                tier1_esprits = list(result.scalars().all())
                
                response = "**Tier 1 Esprits in Database:**\n"
                response += f"Total found: {len(tier1_esprits)}\n\n"
                
                if tier1_esprits:
                    for esprit in tier1_esprits:
                        response += f"• {esprit.name} ({esprit.element})\n"
                else:
                    response += "❌ **NO TIER 1 ESPRITS FOUND!**\n"
                
                # Check starter names
                response += f"\n**Checking Config Starters:**\n"
                starter_names = ['Blazeblob', 'Muddroot', 'Droozle', 'Jelune', 'Gloomb', 'Shynix']
                
                for name in starter_names:
                    stmt = select(EspritBase).where(EspritBase.name == name) # type: ignore
                    result = await session.execute(stmt)
                    exists = result.scalar_one_or_none()
                    if exists:
                        response += f"✅ {name} - Found (Tier {exists.base_tier})\n"
                    else:
                        response += f"❌ {name} - Not in database\n"
                
                # Send response
                embed = disnake.Embed(
                    title="Debug: Starter Esprits",
                    description=response[:4000],
                    color=EmbedColors.INFO
                )
                await inter.edit_original_response(embed=embed)
        except Exception as e:
            embed = disnake.Embed(
                title="Debug Error",
                description=f"Error: {str(e)}",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)


def setup(bot):
    bot.add_cog(Onboarding(bot))