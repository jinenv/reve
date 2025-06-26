# src/cogs/admin.py
import disnake
from disnake.ext import commands
from sqlalchemy import select, delete, func

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService
from src.utils.config_manager import ConfigManager
from src.database.models import Player, Esprit, EspritBase


class Admin(commands.Cog):
    """Admin commands for testing and maintenance"""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def cog_check(self, inter: disnake.ApplicationCommandInteraction) -> bool:
        """Global check - only bot owner can use these commands"""
        app_info = await self.bot.application_info()
        return inter.author.id == app_info.owner.id
    
    @commands.slash_command(name="admin", description="Admin commands for bot owner")
    async def admin(self, inter: disnake.ApplicationCommandInteraction):
        """Base admin command - never called directly"""
        pass
    
    @admin.sub_command(name="reset", description="Reset player data")
    async def admin_reset(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="User to reset (defaults to self)", default=None)
    ):
        """Reset a player's data"""
        await inter.response.defer(ephemeral=True)
        
        target_user = user or inter.author
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Fix: Use proper column comparison
                stmt = select(Player).where(Player.discord_id == target_user.id) # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Player Not Found",
                        description=f"{target_user.mention} isn't registered yet!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                player_id = player.id
                
                # Delete all their Esprits first
                delete_esprits = delete(Esprit).where(Esprit.owner_id == player_id) # type: ignore
                await session.execute(delete_esprits)
                
                # Delete the player
                await session.delete(player)
                
                # Clear any cached data
                if RedisService.is_available() and player_id:
                    await RedisService.invalidate_player_cache(player_id)
                
                await session.commit()
                
                embed = disnake.Embed(
                    title="✅ Reset Complete",
                    description=(
                        f"Successfully wiped all data for {target_user.mention}\n"
                        f"They can use `/start` to begin fresh!"
                    ),
                    color=EmbedColors.SUCCESS
                )
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            embed = disnake.Embed(
                title="❌ Reset Failed",
                description=f"Error: {str(e)}",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    @admin.sub_command_group(name="sync", description="Sync various game data")
    async def admin_sync(self, inter: disnake.ApplicationCommandInteraction):
        """Sync group - never called directly"""
        pass
    
    @admin_sync.sub_command(name="emojis", description="Sync emoji mappings from Discord")
    async def sync_emojis(self, inter: disnake.ApplicationCommandInteraction):
        """Sync emojis from configured servers"""
        await inter.response.defer()
        
        from src.utils.emoji_manager import get_emoji_manager
        manager = get_emoji_manager()
        
        if not manager:
            await inter.edit_original_response(content="❌ Emoji manager not initialized!")
            return
        
        count = 0
        for server_id in manager.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                for emoji in guild.emojis:
                    name = emoji.name
                    # Handle t1blazeblob, t2emberwolf format
                    if name.startswith("t") and len(name) > 2 and name[1].isdigit():
                        # Extract the actual name after tier prefix
                        if name[2:3].isdigit():  # t10+ handling
                            actual_name = name[3:]
                        else:
                            actual_name = name[2:]
                        
                        manager.emoji_cache[actual_name.lower()] = f"<:{emoji.name}:{emoji.id}>"
                        count += 1
        
        manager.save_config()
        await inter.edit_original_response(content=f"✅ Synced {count} emojis!")

    @admin.sub_command_group(name="give", description="Give items/esprits to players")
    async def admin_give(self, inter: disnake.ApplicationCommandInteraction):
        """Give group - never called directly"""
        pass
    
    @admin_give.sub_command(name="esprit", description="Give an esprit to a player")
    async def give_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="Target player"),
        esprit_name: str = commands.Param(description="Name of the esprit"),
        quantity: int = commands.Param(default=1, min_value=1, description="How many to give"),
        awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level (0-5 stars)")
    ):
        """Give an esprit to a player by name"""
        await inter.response.defer(ephemeral=True)
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == user.id) # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    await inter.edit_original_response(content=f"❌ {user.mention} isn't registered!")
                    return
                
                # Find esprit base by name
                stmt = select(EspritBase).where(
                    func.lower(EspritBase.name) == esprit_name.lower()
                )
                esprit_base = (await session.execute(stmt)).scalar_one_or_none()
                
                if not esprit_base:
                    # Try partial match
                    stmt = select(EspritBase).where(
                        func.lower(EspritBase.name).like(f"%{esprit_name.lower()}%")
                    )
                    results = (await session.execute(stmt)).scalars().all()
                    
                    if not results:
                        await inter.edit_original_response(content=f"❌ No esprit found matching '{esprit_name}'")
                        return
                    elif len(results) > 1:
                        names = ", ".join([e.name for e in results[:5]])
                        await inter.edit_original_response(
                            content=f"❌ Multiple matches found: {names}{'...' if len(results) > 5 else ''}"
                        )
                        return
                    else:
                        esprit_base = results[0]
                
                # Check player.id is not None before using
                if player.id is None:
                    await inter.edit_original_response(content="❌ Player ID error!")
                    return
                
                # Add to collection
                stack = await Esprit.add_to_collection(
                    session=session,
                    owner_id=player.id,
                    base=esprit_base,
                    quantity=quantity
                )
                
                # Set awakening if specified
                if awakening > 0:
                    stack.awakening_level = awakening
                
                await session.commit()
                
                # Invalidate cache
                if RedisService.is_available() and player.id:
                    await RedisService.invalidate_player_cache(player.id)
                
                embed = disnake.Embed(
                    title="✅ Esprit Given!",
                    description=(
                        f"Gave {user.mention}:\n"
                        f"{esprit_base.get_element_emoji()} **{quantity}x {esprit_base.name}**\n"
                        f"Tier {esprit_base.base_tier} ({esprit_base.tier_name})"
                    ),
                    color=EmbedColors.SUCCESS
                )
                
                if awakening > 0:
                    embed.add_field(name="Awakening", value=f"{'⭐' * awakening}")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            await inter.edit_original_response(content=f"❌ Error: {str(e)}")

    @admin_give.sub_command(name="all_esprits", description="Give ALL esprits (WARNING: This is insane)")
    async def give_all_esprits(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="Target player"),
        quantity: int = commands.Param(default=1, min_value=1, max_value=1000, description="How many of EACH"),
        awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level")
    ):
        """Give one of every esprit because testing"""
        await inter.response.defer(ephemeral=True)
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == user.id) # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player or player.id is None:
                    await inter.edit_original_response(content=f"❌ {user.mention} isn't registered!")
                    return
                
                # Get ALL esprits
                stmt = select(EspritBase).order_by(EspritBase.base_tier) # type: ignore
                all_esprits = (await session.execute(stmt)).scalars().all()
                
                count = 0
                for esprit_base in all_esprits:
                    # Add to collection
                    stack = await Esprit.add_to_collection(
                        session=session,
                        owner_id=player.id,
                        base=esprit_base,
                        quantity=quantity
                    )
                    
                    if awakening > 0:
                        stack.awakening_level = awakening
                    
                    count += 1
                
                await session.commit()
                
                # Invalidate cache
                if RedisService.is_available():
                    await RedisService.invalidate_player_cache(player.id)
                
                embed = disnake.Embed(
                    title="✅ ALL Esprits Given!",
                    description=(
                        f"Gave {user.mention}:\n"
                        f"**{quantity}x** of EVERY esprit ({count} types)\n"
                        f"Total: {count * quantity} esprits"
                    ),
                    color=EmbedColors.SUCCESS
                )
                
                if awakening > 0:
                    embed.add_field(name="Awakening", value=f"All at {'⭐' * awakening}")
                
                embed.set_footer(text="Their power level is probably illegal now")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            await inter.edit_original_response(content=f"❌ Error: {str(e)}")
    
    @give_esprit.autocomplete("esprit_name")
    async def esprit_autocomplete(self, inter: disnake.ApplicationCommandInteraction, query: str):
        """Autocomplete esprit names from config"""
        query = query.lower()
        
        # Get all esprit names from config
        esprits_config = ConfigManager.get("esprits")
        if not esprits_config:
            return []
        
        esprit_list = esprits_config.get("esprits", [])
        
        # Filter and format
        matches = []
        for esprit in esprit_list:
            name = esprit.get("name", "")
            if query in name.lower():
                tier = esprit.get("base_tier", 1)
                element = esprit.get("element", "")
                
                # Format: "Blazeblob (T1 Inferno)"
                display = f"{name} (T{tier} {element})"
                matches.append(disnake.OptionChoice(name=display[:100], value=name))
                
                if len(matches) >= 25:  # Discord limit
                    break
        
        # Sort by relevance (starts with > contains)
        matches.sort(key=lambda x: (not x.value.lower().startswith(query), x.value))
        
        return matches


def setup(bot):
    bot.add_cog(Admin(bot))