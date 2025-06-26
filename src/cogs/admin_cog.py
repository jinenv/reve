# src/cogs/admin.py
import disnake
from disnake.ext import commands

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService
from src.database.models import Player, Esprit
from sqlalchemy import select, delete


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
        
        # Default to self if no user specified
        target_user = user or inter.author
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Find the player
                stmt = select(Player).where(Player.discord_id == target_user.id)  # type: ignore
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
                
                # Delete all their Esprits first (foreign key constraints)
                delete_esprits = delete(Esprit).where(Esprit.owner_id == player_id)  # type: ignore
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

    @commands.slash_command(name="sync_emojis")
    @commands.is_owner()
    async def sync_emojis(self, inter):
        await inter.response.defer()
        
        from src.utils.emoji_manager import get_emoji_manager
        manager = get_emoji_manager()
        
        # ADD THIS CHECK
        if not manager:
            await inter.edit_original_response(content="❌ Emoji manager not initialized! Did you add it to on_ready?")
            return
        
        count = 0
        for server_id in manager.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                for emoji in guild.emojis:
                    # Handle t1name, t2name, etc format
                    name = emoji.name
                    if name.startswith("t") and len(name) > 2 and name[1:].split(name[2:])[0].isdigit():
                        # Extract: t1blazeblob → blazeblob
                        parts = name.split(name[2:], 1)
                        actual_name = name[2:] if len(parts) > 1 else name
                        manager.emoji_cache[actual_name.lower()] = f"<:{emoji.name}:{emoji.id}>"
                        count += 1
        
        manager.save_config()
        await inter.edit_original_response(content=f"✅ Synced {count} emojis!")

def setup(bot):
    bot.add_cog(Admin(bot))