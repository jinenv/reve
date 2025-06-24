# src/cogs/onboarding.py
import disnake
from disnake.ext import commands
from typing import Optional, List
from datetime import datetime
import random

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.redis_service import RedisService
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select


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
                starter_config = ConfigManager.get("global_config")
                starter_rewards = starter_config.get("starter_rewards", {}) if starter_config else {}
                
                # Create new player
                new_player = Player(
                    discord_id=inter.author.id,
                    username=inter.author.name,
                    created_at=datetime.utcnow(),
                    level=1,
                    experience=0,
                    energy=starter_rewards.get("energy", 100),
                    max_energy=100,
                    stamina=50,
                    max_stamina=50,
                    jijies=starter_rewards.get("jijies", 5000),
                    erythl=starter_rewards.get("erythl", 10),
                    skill_points=0,
                    total_jijies_earned=starter_rewards.get("jijies", 5000),
                    total_erythl_earned=starter_rewards.get("erythl", 10),
                    last_energy_update=datetime.utcnow(),
                    last_stamina_update=datetime.utcnow(),
                    last_active=datetime.utcnow()
                )
                
                # Add starter fragments if configured
                if "tier_1_fragments" in starter_rewards:
                    new_player.tier_fragments = {"1": starter_rewards["tier_1_fragments"]}
                
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
                            "starter_rewards": starter_rewards
                        }
                    )
                
                # Get starter Esprits
                starter_esprits = await self._get_starter_esprits(session)
                
                if not starter_esprits:
                    # Fallback if no starter Esprits configured
                    # Get any tier 1 Esprit
                    stmt = select(EspritBase).where(EspritBase.base_tier == 1).limit(1)  # type: ignore
                    fallback_esprit = (await session.execute(stmt)).scalar_one_or_none()
                    if fallback_esprit:
                        starter_esprits = [fallback_esprit]
                
                # Give starter Esprits
                given_esprits = []
                for esprit_base in starter_esprits:
                    if new_player.id is not None:
                        stack = await Esprit.add_to_collection(
                            session=session,
                            owner_id=new_player.id,
                            base=esprit_base,
                            quantity=1
                        )
                        given_esprits.append(esprit_base)
                        
                        # Log the capture
                        transaction_logger.log_esprit_captured(
                            new_player.id,
                            esprit_base.name,
                            esprit_base.base_tier,
                            esprit_base.element,
                            "starter_reward"
                        )
                
                # Set first Esprit as leader if we gave any
                if given_esprits and new_player.id is not None:
                    first_esprit_stmt = select(Esprit).where(Esprit.owner_id == new_player.id).limit(1)  # type: ignore
                    first_esprit = (await session.execute(first_esprit_stmt)).scalar_one_or_none()
                    if first_esprit:
                        new_player.leader_esprit_stack_id = first_esprit.id
                
                # Give starter items if configured
                if "items" in starter_rewards:
                    new_player.inventory = starter_rewards["items"].copy()
                
                # Give starter echo if configured
                if "faded_echo" in starter_rewards:
                    if new_player.inventory is None:
                        new_player.inventory = {}
                    new_player.inventory["faded_echo"] = starter_rewards.get("faded_echo", 1)
                
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
                rewards_text = f"💰 **{starter_rewards.get('jijies', 5000):,}** Jijies\n"
                rewards_text += f"💎 **{starter_rewards.get('erythl', 10)}** Erythl\n"
                rewards_text += f"⚡ **{starter_rewards.get('energy', 100)}** Energy\n"
                
                if given_esprits:
                    rewards_text += f"\n**Starter Esprits:**\n"
                    for esprit in given_esprits[:3]:  # Show max 3
                        rewards_text += f"{esprit.get_element_emoji()} **{esprit.name}** (Tier {esprit.base_tier})\n"
                
                if "faded_echo" in starter_rewards:
                    rewards_text += f"\n📦 **{starter_rewards.get('faded_echo', 1)}x** Faded Echo"
                
                if "items" in starter_rewards:
                    rewards_text += f"\n\n**Starter Items:**\n"
                    for item, qty in list(starter_rewards["items"].items())[:3]:
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
    
    async def _get_starter_esprits(self, session) -> List[EspritBase]:
        """Get configured starter Esprits"""
        # Default starter Esprits - one of each element at tier 1
        starter_names = [
            "Blazeblob",    # Inferno
            "Muddroot",     # Verdant  
            "Droozle",      # Abyssal
            "Jelune",       # Tempest
            "Gloomb",       # Umbral
            "Shynix"        # Radiant
        ]
        
        # Pick 2 random starters
        chosen_starters = random.sample(starter_names, 2)
        
        # Query for the chosen starters
        stmt = select(EspritBase).where(EspritBase.name.in_(chosen_starters))  # type: ignore
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    



def setup(bot):
    bot.add_cog(Onboarding(bot))