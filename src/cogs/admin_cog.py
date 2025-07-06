# src/cogs/admin_cog.py
import disnake
from disnake.ext import commands
from typing import Optional
import logging

from sqlalchemy import func, select, delete, update

from src.services.player_service import PlayerService
from src.services.currency_service import CurrencyService
from src.services.cache_service import CacheService
from src.services.base_service import ServiceResult
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import ratelimit
from src.utils.config_manager import ConfigManager
from src.utils.emoji_manager import EmojiStorageManager
from src.utils.database_service import DatabaseService

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    """🔧 Admin commands for bot management and testing"""
    
    def __init__(self, bot):
        self.bot = bot
        self.emoji_manager = None
        logger.info("AdminCog initialized successfully")
    
    async def cog_check(self, inter: disnake.ApplicationCommandInteraction) -> bool:
        """Global check - only bot owner can use admin commands"""
        app_info = await self.bot.application_info()
        return inter.author.id == app_info.owner.id
    
    @commands.slash_command(name="admin", description="🔧 Admin commands for bot management")
    async def admin(self, inter: disnake.ApplicationCommandInteraction):
        """Base admin command group"""
        pass

    # =====================================
    # PLAYER MANAGEMENT
    # =====================================
    
    @admin.sub_command_group(name="player", description="👤 Player management commands")
    async def player_group(self, inter: disnake.ApplicationCommandInteraction):
        """Player management commands"""
        pass
    
    @player_group.sub_command(name="reset", description="🗑️ Reset a player's data completely")
    @ratelimit(uses=1, per_seconds=10, command_name="admin_player_reset")
    async def reset_player(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="User to reset (defaults to you)", default=None),
        confirm: bool = commands.Param(default=False, description="Type True to confirm deletion")
    ):
        """Reset a player's data completely"""
        # ✅ FIX: @ratelimit decorator already handles defer() - don't call it again!
        
        target_user = user or inter.author
        
        # Require confirmation for this destructive action
        if not confirm:
            embed = disnake.Embed(
                title="⚠️ Confirmation Required",
                description=(
                    f"This will **PERMANENTLY DELETE** all data for {target_user.mention}:\n\n"
                    f"**Will Delete:**\n"
                    f"• Player profile and class\n"
                    f"• All Esprits and collections\n"
                    f"• All currencies (revies/erythl)\n"
                    f"• Quest progress and achievements\n"
                    f"• All items and fragments\n\n"
                    f"Use `/admin player reset user:{target_user.mention} confirm:True` to proceed."
                ),
                color=EmbedColors.WARNING
            )
            return await inter.edit_original_response(embed=embed)
        
        try:
            # Import what we need
            from src.database.models.player import Player
            from src.database.models.esprit import Esprit
            from src.database.models.player_class import PlayerClass
            from src.utils.transaction_logger import transaction_logger, TransactionType
            
            async with DatabaseService.get_transaction() as session:
                # Get the player
                stmt = select(Player).where(Player.discord_id == target_user.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="❌ Player Not Found",
                        description=f"{target_user.mention} isn't registered yet!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                player_id = player.id
                
                # Log the reset before deletion
                if player_id:
                    transaction_logger.log_transaction(
                        player_id=player_id,
                        transaction_type=TransactionType.ADMIN_DELETION,
                        details={
                            "action": "full_player_reset",
                            "discord_id": target_user.id,
                            "username": target_user.display_name,
                            "old_level": player.level,
                            "old_revies": player.revies,
                            "old_erythl": player.erythl
                        },
                        metadata={
                            "admin_command": "reset_player",
                            "admin_id": inter.author.id,
                            "admin_name": inter.author.display_name
                        }
                    )
                
                # Count what we're deleting for reporting
                esprit_count_stmt = select(func.count(Esprit.id)).where(Esprit.owner_id == player_id)  # type: ignore
                esprit_count = (await session.execute(esprit_count_stmt)).scalar() or 0
                
                # Step 1: Clear player's leader reference
                player.leader_esprit_stack_id = None
                
                # Step 2: Clear any other players' leader references to this player's Esprits
                # ✅ FIX: Use proper subquery construction
                player_esprit_ids = select(Esprit.id).where(Esprit.owner_id == player_id)  # type: ignore
                clear_leader_refs = update(Player).where(
                    Player.leader_esprit_stack_id.in_(player_esprit_ids)  # type: ignore
                ).values(leader_esprit_stack_id=None)
                await session.execute(clear_leader_refs)
                
                # Step 3: Delete player class record
                class_delete_stmt = delete(PlayerClass).where(PlayerClass.player_id == player_id)  # type: ignore
                await session.execute(class_delete_stmt)
                
                # Step 4: Delete all Esprits
                esprit_delete_stmt = delete(Esprit).where(Esprit.owner_id == player_id)  # type: ignore
                await session.execute(esprit_delete_stmt)
                
                # Step 5: Delete the player
                await session.delete(player)
                
                # Step 6: Clear cache - Only if player_id is not None
                if player_id is not None:
                    await CacheService.invalidate_player_cache(player_id)
                
                await session.commit()
                
                embed = disnake.Embed(
                    title="✅ Reset Complete",
                    description=(
                        f"Successfully wiped all data for {target_user.mention}\n\n"
                        f"**Deleted:**\n"
                        f"• Player profile (Level {player.level})\n"
                        f"• Player class record\n"
                        f"• {esprit_count} Esprit stacks\n"
                        f"• {player.revies:,} revies, {player.erythl:,} erythl\n"
                        f"• All leader references cleared\n"
                        f"• Cache data cleared\n\n"
                        f"They can use `/awaken` to begin fresh!"
                    ),
                    color=EmbedColors.SUCCESS
                )
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            logger.error(f"Admin reset error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Reset Failed",
                description="An unexpected error occurred during reset. Check logs for details.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    @player_group.sub_command(name="info", description="📊 Get detailed player information")
    async def player_info(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="User to inspect")
    ):
        """Get comprehensive player information"""
        await inter.response.defer()  # ✅ Required: no @ratelimit decorator
        
        try:
            player_result = await PlayerService.get_or_create_player(user.id, user.display_name)
            
            if not player_result.success:
                embed = disnake.Embed(
                    title="❌ Player Error",
                    description=player_result.error,
                    color=EmbedColors.WARNING
                )
                return await inter.edit_original_response(embed=embed)
            
            # Get player object
            player = player_result.data
            if not player or not hasattr(player, 'id'):
                embed = disnake.Embed(
                    title="❌ Invalid Player",
                    description="Failed to get valid player data.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            embed = disnake.Embed(
                title=f"📊 Player Info: {player.username}",
                color=EmbedColors.INFO
            )
            
            # Basic Info
            embed.add_field(
                name="👤 Basic Info",
                value=(
                    f"**Level:** {player.level}\n"
                    f"**Experience:** {player.experience:,}\n"
                    f"**Discord ID:** {user.id}\n"
                    f"**Registered:** <t:{int(player.created_at.timestamp())}:R>"
                ),
                inline=False
            )
            
            # Resources
            embed.add_field(
                name="💰 Resources",
                value=(
                    f"**Revies:** {player.revies:,}\n"
                    f"**Erythl:** {player.erythl:,}\n"
                    f"**Energy:** {player.energy}/{player.max_energy}\n"
                    f"**Stamina:** {player.stamina}/{player.max_stamina}"
                ),
                inline=False
            )
            
            # Power Stats
            embed.add_field(
                name="⚔️ Combat Power",
                value=(
                    f"**Attack:** {player.total_attack_power:,}\n"
                    f"**Defense:** {player.total_defense_power:,}\n"
                    f"**HP:** {player.total_hp:,}"
                ),
                inline=False
            )
            
            embed.set_thumbnail(url=user.display_avatar.url)
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Player info error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ System Error",
                description="Failed to retrieve player information.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    # =====================================
    # GIVING ITEMS/CURRENCY
    # =====================================
    
    @admin.sub_command_group(name="give", description="🎁 Give items and resources to players")
    async def give_group(self, inter: disnake.ApplicationCommandInteraction):
        """Give commands"""
        pass
    
    @give_group.sub_command(name="currency", description="💰 Give currency to a player")
    @ratelimit(uses=5, per_seconds=60, command_name="admin_give_currency")
    async def give_currency(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="Target player"),
        currency: str = commands.Param(
            choices=["revies", "erythl"], 
            description="Currency type"
        ),
        amount: int = commands.Param(
            min_value=1, 
            max_value=1000000,
            description="Amount to give"
        ),
        reason: str = commands.Param(default="admin_gift", description="Reason for giving")
    ):
        """Give currency to a player"""
        # ✅ FIX: @ratelimit decorator already handles defer() - don't call it again!
        
        try:
            # Get player first
            player_result = await PlayerService.get_or_create_player(user.id, user.display_name)
            
            if not player_result.success:
                embed = disnake.Embed(
                    title="❌ Player Error",
                    description=player_result.error,
                    color=EmbedColors.WARNING
                )
                return await inter.edit_original_response(embed=embed)
            
            # Get player ID from result (Player object)
            player = player_result.data
            if not player or not hasattr(player, 'id') or player.id is None:
                embed = disnake.Embed(
                    title="❌ Invalid Player",
                    description="Failed to get valid player data.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ FIX: Only call add_currency if player.id is not None
            currency_result = await CurrencyService.add_currency(
                player_id=player.id,
                currency=currency,
                amount=amount,
                reason=f"admin_gift: {reason}"
            )
            
            if not currency_result.success:
                embed = disnake.Embed(
                    title="❌ Gift Failed",
                    description=currency_result.error,
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # Format currency display  
            currency_emoji = "💰" if currency == "revies" else "💎"
            
            # CurrencyResult.data is a CurrencyTransaction object
            transaction = currency_result.data
            new_balance = transaction.new_balance if transaction else 0
            
            embed = disnake.Embed(
                title="✅ Currency Given!",
                description=(
                    f"Gave {user.mention}:\n\n"
                    f"{currency_emoji} **{amount:,} {currency.title()}**\n\n"
                    f"**New Balance:** {new_balance:,}\n"
                    f"**Reason:** {reason}"
                ),
                color=EmbedColors.SUCCESS
            )
            
            embed.set_footer(text=f"Given by {inter.author.display_name}")
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Give currency error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ System Error",
                description="Failed to give currency. Please try again.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @give_group.sub_command(name="esprit", description="👹 Give an Esprit to a player (Not Yet Implemented)")
    async def give_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="Target player"),
        esprit_name: str = commands.Param(description="Esprit name"),
        quantity: int = commands.Param(default=1, min_value=1, max_value=1000, description="Quantity"),
        awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level")
    ):
        """Give an Esprit to a player (placeholder)"""
        await inter.response.defer()  # ✅ Required: no @ratelimit decorator
        
        embed = disnake.Embed(
            title="⚠️ Feature Not Available",
            description=(
                f"Esprit giving is not yet implemented.\n\n"
                f"**Would give {user.mention}:**\n"
                f"• {quantity}x {esprit_name}\n"
                f"• Awakening: {'⭐' * awakening if awakening > 0 else 'None'}\n\n"
                f"*Requires EspritService.add_esprit_by_name() implementation*"
            ),
            color=EmbedColors.WARNING
        )
        
        await inter.edit_original_response(embed=embed)

    # =====================================
    # SYSTEM MANAGEMENT
    # =====================================
    
    @admin.sub_command_group(name="system", description="⚙️ System management commands")
    async def system_group(self, inter: disnake.ApplicationCommandInteraction):
        """System commands"""
        pass
    
    @system_group.sub_command(name="sync", description="🔄 Sync slash commands with Discord")
    @ratelimit(uses=1, per_seconds=30, command_name="admin_system_sync")
    async def sync_commands(self, inter: disnake.ApplicationCommandInteraction):
        """Force sync slash commands with Discord"""
        # ✅ FIX: @ratelimit decorator already handles defer() - don't call it again!
        
        try:
            synced = await self.bot.sync_application_commands()
            
            embed = disnake.Embed(
                title="✅ Commands Synced",
                description=f"Successfully synced {len(synced)} slash commands with Discord.",
                color=EmbedColors.SUCCESS
            )
            
            embed.set_footer(text="Commands may take a few minutes to appear globally")
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Command sync error: {e}")
            embed = disnake.Embed(
                title="❌ Sync Failed",
                description="Failed to sync commands with Discord.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @system_group.sub_command(name="reload", description="🔄 Reload configuration files")
    @ratelimit(uses=1, per_seconds=5, command_name="admin_system_reload")
    async def reload_config(
        self,
        inter: disnake.ApplicationCommandInteraction,
        config: str = commands.Param(
            default="ALL",
            description="Specific config to reload or 'ALL'"
        )
    ):
        """Reload configuration files"""
        # ✅ FIX: @ratelimit decorator already handles defer() - don't call it again!
        
        try:
            if config.upper() == "ALL":
                old_count = len(ConfigManager._configs) if hasattr(ConfigManager, '_configs') else 0
                ConfigManager.reload()
                new_count = len(ConfigManager._configs)
                
                embed = disnake.Embed(
                    title="🔄 All Configs Reloaded",
                    description=(
                        f"Successfully reloaded all configuration files.\n\n"
                        f"**Before:** {old_count} configs\n"
                        f"**After:** {new_count} configs\n\n"
                        f"**Reloaded:** {', '.join(ConfigManager._configs.keys())}"
                    ),
                    color=EmbedColors.SUCCESS
                )
            else:
                # Reload specific config
                if config in ConfigManager._configs:
                    del ConfigManager._configs[config]
                    
                    # Attempt to reload
                    import json
                    from pathlib import Path
                    
                    config_path = Path("data/config") / f"{config}.json"
                    if config_path.exists():
                        with open(config_path, 'r', encoding='utf-8') as f:
                            ConfigManager._configs[config] = json.load(f)
                        
                        embed = disnake.Embed(
                            title="✅ Config Reloaded",
                            description=f"Successfully reloaded `{config}` configuration.",
                            color=EmbedColors.SUCCESS
                        )
                    else:
                        embed = disnake.Embed(
                            title="❌ Config Not Found",
                            description=f"Config file `{config}.json` doesn't exist.",
                            color=EmbedColors.ERROR
                        )
                else:
                    embed = disnake.Embed(
                        title="❌ Config Not Loaded",
                        description=f"Config `{config}` wasn't found in memory.",
                        color=EmbedColors.ERROR
                    )
            
            import datetime
            embed.set_footer(text=f"Reloaded at {datetime.datetime.now().strftime('%H:%M:%S')}")
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Config reload error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Reload Failed",
                description="Configuration reload failed. Check logs for details.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @system_group.sub_command(name="cache", description="🗄️ Manage Redis cache")
    async def manage_cache(
        self,
        inter: disnake.ApplicationCommandInteraction,
        action: str = commands.Param(
            choices=["clear", "stats", "warm"],
            description="Cache action to perform"
        ),
        player: Optional[disnake.User] = commands.Param(
            default=None,
            description="Specific player for targeted operations"
        )
    ):
        """Manage Redis cache system"""
        await inter.response.defer()  # ✅ Required: no @ratelimit decorator
        
        try:
            if action == "stats":
                # Get cache statistics
                stats_result = await CacheService.get_cache_metrics()
                
                if not stats_result.success or not stats_result.data:
                    embed = disnake.Embed(
                        title="❌ Cache Unavailable",
                        description="Redis cache is not available or returned no data.",
                        color=EmbedColors.WARNING
                    )
                    return await inter.edit_original_response(embed=embed)
                
                stats = stats_result.data
                
                embed = disnake.Embed(
                    title="📊 Cache Statistics",
                    color=EmbedColors.INFO
                )
                
                # Safe access with defaults
                hit_rate = stats.get('hit_rate', 0.0) if stats else 0.0
                hits = stats.get('hits', 0) if stats else 0
                misses = stats.get('misses', 0) if stats else 0
                sets = stats.get('sets', 0) if stats else 0
                deletes = stats.get('deletes', 0) if stats else 0
                invalidations = stats.get('invalidations', 0) if stats else 0
                
                embed.add_field(
                    name="📈 Performance",
                    value=(
                        f"**Hit Rate:** {hit_rate:.1%}\n"
                        f"**Hits:** {hits:,}\n"
                        f"**Misses:** {misses:,}"
                    ),
                    inline=True
                )
                
                embed.add_field(
                    name="⚡ Operations",
                    value=(
                        f"**Sets:** {sets:,}\n"
                        f"**Deletes:** {deletes:,}\n"
                        f"**Invalidations:** {invalidations:,}"
                    ),
                    inline=True
                )
                
            elif action == "clear":
                if player:
                    # Clear specific player cache
                    player_result = await PlayerService.get_or_create_player(player.id, player.display_name)
                    if not player_result.success or not player_result.data:
                        embed = disnake.Embed(
                            title="❌ Player Error",
                            description=f"Failed to get player data for {player.mention}",
                            color=EmbedColors.WARNING
                        )
                        return await inter.edit_original_response(embed=embed)
                    
                    player_obj = player_result.data
                    if not hasattr(player_obj, 'id') or not player_obj.id:
                        embed = disnake.Embed(
                            title="❌ Invalid Player",
                            description="Player data is invalid.",
                            color=EmbedColors.ERROR
                        )
                        return await inter.edit_original_response(embed=embed)
                    
                    clear_result = await CacheService.invalidate_player_cache(player_obj.id)
                    
                    embed = disnake.Embed(
                        title="✅ Player Cache Cleared",
                        description=f"Cleared cache for {player.mention}",
                        color=EmbedColors.SUCCESS
                    )
                else:
                    # Clear global caches
                    clear_result = await CacheService.invalidate_global_caches()
                    
                    embed = disnake.Embed(
                        title="✅ Global Cache Cleared",
                        description="Cleared all global cache entries",
                        color=EmbedColors.SUCCESS
                    )
            
            elif action == "warm":
                if player:
                    player_result = await PlayerService.get_or_create_player(player.id, player.display_name)
                    if not player_result.success or not player_result.data:
                        embed = disnake.Embed(
                            title="❌ Player Error",
                            description=f"Failed to get player data for {player.mention}",
                            color=EmbedColors.WARNING
                        )
                        return await inter.edit_original_response(embed=embed)
                    
                    player_obj = player_result.data
                    if not hasattr(player_obj, 'id') or not player_obj.id:
                        embed = disnake.Embed(
                            title="❌ Invalid Player",
                            description="Player data is invalid.",
                            color=EmbedColors.ERROR
                        )
                        return await inter.edit_original_response(embed=embed)
                    
                    warm_result = await CacheService.warm_player_caches(player_obj.id)
                    
                    embed = disnake.Embed(
                        title="✅ Player Cache Warmed",
                        description=f"Pre-loaded cache for {player.mention}",
                        color=EmbedColors.SUCCESS
                    )
                else:
                    embed = disnake.Embed(
                        title="❌ Invalid Action",
                        description="Cache warming requires a specific player.",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Cache management error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Cache Operation Failed",
                description="Cache operation encountered an error.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    @system_group.sub_command(name="emoji", description="😀 Sync emoji mappings from Discord servers")
    @ratelimit(uses=1, per_seconds=30, command_name="admin_system_emoji")
    async def sync_emojis(self, inter: disnake.ApplicationCommandInteraction):
        """Sync emojis from configured Discord servers"""
        # ✅ FIX: @ratelimit decorator already handles defer() - don't call it again!
        
        try:
            # Initialize emoji manager if not already done
            if not self.emoji_manager:
                try:
                    import os
                    config_path = os.path.join("data", "config", "emoji_mapping.json")
                    self.emoji_manager = EmojiStorageManager(self.bot, config_path)
                    # Configure known emoji servers (you may need to adjust these IDs)
                    self.emoji_manager.set_emoji_servers([1369489835860955329])  # Your emoji server ID
                except Exception as init_error:
                    logger.error(f"Failed to initialize emoji manager: {init_error}")
                    embed = disnake.Embed(
                        title="❌ Emoji Manager Error",
                        description="Failed to initialize emoji manager.",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
            
            if not self.emoji_manager.emoji_servers:
                embed = disnake.Embed(
                    title="❌ No Emoji Servers",
                    description="No emoji servers configured. Please configure emoji servers first.",
                    color=EmbedColors.WARNING
                )
                return await inter.edit_original_response(embed=embed)
            
            synced_count = 0
            failed_count = 0
            
            for server_id in self.emoji_manager.emoji_servers:
                guild = self.bot.get_guild(server_id)
                if not guild:
                    logger.warning(f"Cannot access guild {server_id}")
                    failed_count += 1
                    continue
                
                for emoji in guild.emojis:
                    try:
                        name = emoji.name.lower()
                        
                        # Handle tier-prefixed emojis (t1blazeblob -> blazeblob)
                        if name.startswith("t") and len(name) > 2 and name[1].isdigit():
                            # Extract actual name after tier prefix
                            if len(name) > 3 and name[2].isdigit():  # t10+ handling
                                actual_name = name[3:]
                            else:
                                actual_name = name[2:]
                            
                            emoji_string = f"<:{emoji.name}:{emoji.id}>"
                            self.emoji_manager.add_emoji_to_cache(actual_name, emoji_string)
                            synced_count += 1
                        else:
                            # Regular emoji without tier prefix
                            emoji_string = f"<:{emoji.name}:{emoji.id}>"
                            self.emoji_manager.add_emoji_to_cache(name, emoji_string)
                            synced_count += 1
                            
                    except Exception as emoji_error:
                        logger.error(f"Failed to sync emoji {emoji.name}: {emoji_error}")
                        failed_count += 1
            
            # Save the updated config
            self.emoji_manager.save_config()
            
            embed = disnake.Embed(
                title="✅ Emoji Sync Complete",
                description=(
                    f"**Synced:** {synced_count} emojis\n"
                    f"**Failed:** {failed_count} emojis\n"
                    f"**Servers:** {len(self.emoji_manager.emoji_servers)}\n\n"
                    f"Emoji mappings saved to configuration."
                ),
                color=EmbedColors.SUCCESS
            )
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Emoji sync error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Emoji Sync Failed",
                description="Failed to sync emoji mappings. Check logs for details.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    # =====================================
    # DEBUG COMMANDS
    # =====================================
    
    @admin.sub_command_group(name="debug", description="🐛 Debug and testing commands")
    async def debug_group(self, inter: disnake.ApplicationCommandInteraction):
        """Debug commands"""
        pass
    
    @debug_group.sub_command(name="emoji", description="😀 Test emoji manager functionality")
    async def debug_emoji(self, inter: disnake.ApplicationCommandInteraction):
        """Test and debug emoji manager"""
        await inter.response.defer()  # ✅ Required: no @ratelimit decorator
        
        try:
            # Initialize emoji manager if needed
            if not self.emoji_manager:
                try:
                    import os
                    config_path = os.path.join("data", "config", "emoji_mapping.json")
                    self.emoji_manager = EmojiStorageManager(self.bot, config_path)
                except Exception as init_error:
                    embed = disnake.Embed(
                        title="❌ Emoji Manager Error",
                        description=f"Failed to initialize emoji manager: {init_error}",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
            
            # Test various emoji lookups
            test_emojis = ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]
            found_emojis = []
            missing_emojis = []
            
            for emoji_name in test_emojis:
                emoji = self.emoji_manager.get_emoji(emoji_name, "🔮")
                if emoji and emoji != "🔮":
                    found_emojis.append(f"{emoji} `{emoji_name}`")
                else:
                    missing_emojis.append(f"`{emoji_name}`")
            
            embed = disnake.Embed(
                title="🐛 Emoji Manager Debug",
                color=EmbedColors.INFO
            )
            
            embed.add_field(
                name="📊 Statistics",
                value=(
                    f"**Total Cached:** {len(self.emoji_manager.emoji_cache)}\n"
                    f"**Servers:** {len(self.emoji_manager.emoji_servers)}\n"
                    f"**Found:** {len(found_emojis)}/6 elements"
                ),
                inline=False
            )
            
            if found_emojis:
                embed.add_field(
                    name="✅ Found Emojis",
                    value="\n".join(found_emojis[:10]),  # Limit to 10 to avoid embed limits
                    inline=False
                )
            
            if missing_emojis:
                embed.add_field(
                    name="❌ Missing Emojis",
                    value="\n".join(missing_emojis),
                    inline=False
                )
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Debug emoji error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Debug Failed",
                description="Emoji debug encountered an error.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @debug_group.sub_command(name="services", description="🔧 Test all services functionality")
    async def debug_services(self, inter: disnake.ApplicationCommandInteraction):
        """Test all core services"""
        await inter.response.defer()  # ✅ Required: no @ratelimit decorator
        
        try:
            embed = disnake.Embed(
                title="🔧 Service Health Check",
                color=EmbedColors.INFO
            )
            
            # Test PlayerService
            try:
                test_result = await PlayerService.get_or_create_player(inter.author.id, inter.author.display_name)
                player_status = "✅ Working" if test_result.success else f"❌ Failed: {test_result.error}"
            except Exception as e:
                player_status = f"❌ Error: {str(e)[:50]}"
            
            # Test CacheService
            try:
                cache_result = await CacheService.get_cache_metrics()
                cache_status = "✅ Working" if cache_result.success else f"❌ Failed: {cache_result.error}"
            except Exception as e:
                cache_status = f"❌ Error: {str(e)[:50]}"
            
            # Test CurrencyService
            try:
                # Test currency service exists and has basic validation
                from src.services.currency_service import CurrencyService
                currency_status = "✅ Available"
            except ImportError:
                currency_status = "❌ Not Found"
            except Exception as e:
                currency_status = f"❌ Error: {str(e)[:50]}"
            
            # Test ConfigManager
            try:
                config_count = len(ConfigManager._configs) if hasattr(ConfigManager, '_configs') else 0
                config_status = f"✅ Working ({config_count} configs)"
            except Exception as e:
                config_status = f"❌ Error: {str(e)[:50]}"
            
            embed.add_field(
                name="🔍 Service Status",
                value=(
                    f"**PlayerService:** {player_status}\n"
                    f"**CurrencyService:** {currency_status}\n"
                    f"**CacheService:** {cache_status}\n"
                    f"**ConfigManager:** {config_status}"
                ),
                inline=False
            )
            
            embed.set_footer(text="All services follow REVE architecture principles")
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Debug services error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Service Check Failed",
                description="Service health check encountered an error.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    # =====================================
    # IMAGE GENERATION TESTING
    # =====================================
    
    @admin.sub_command_group(name="view", description="🎨 Test image generation systems")
    async def view_group(self, inter: disnake.ApplicationCommandInteraction):
        """Image generation test commands"""
        pass
    
    @view_group.sub_command(name="boss", description="🦹 Test boss card generation")
    async def view_boss(
        self,
        inter: disnake.ApplicationCommandInteraction,
        boss_name: str = commands.Param(default="Blazeblob", description="Boss esprit name to generate"),
        background: str = commands.Param(
            default="forest_nebula.png",
            choices=["forest_nebula.png", "space_forest.png", "crystal_cave.png", "volcanic_ridge.png"],
            description="Background theme"
        )
    ):
        """Generate a test boss card image"""
        await inter.response.defer()
        
        try:
            # Search for the esprit in database
            from src.database.models.esprit_base import EspritBase
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(EspritBase.name.ilike(f"%{boss_name}%"))
                esprit_base = (await session.execute(stmt)).scalar_one_or_none()
                
                if not esprit_base:
                    embed = disnake.Embed(
                        title="❌ Boss Not Found",
                        description=f"No esprit found matching '{boss_name}'. Try 'Blazeblob', 'Droozle', or 'Muddroot'.",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Create boss card data
                boss_max_hp = esprit_base.base_hp * 3  # Boss HP multiplier
                boss_current_hp = int(boss_max_hp * 0.75)  # 75% HP for dramatic effect
                
                boss_card_data = {
                    "name": esprit_base.name,
                    "element": esprit_base.element,
                    "current_hp": boss_current_hp,
                    "max_hp": boss_max_hp,
                    "background": background,
                    "image_url": esprit_base.image_url,
                    "sprite_path": esprit_base.image_url
                }
                
                # Generate boss card
                try:
                    from src.utils.boss_generator import generate_boss_card
                    boss_file = await generate_boss_card(boss_card_data, f"admin_boss_test_{esprit_base.name}.png")
                    
                    if boss_file:
                        embed = disnake.Embed(
                            title="🦹 Boss Card Generated!",
                            description=(
                                f"**Boss:** {esprit_base.name}\n"
                                f"**Element:** {esprit_base.element}\n"
                                f"**HP:** {boss_current_hp:,} / {boss_max_hp:,}\n"
                                f"**Background:** {background}\n"
                                f"**Base Stats:** ATK {esprit_base.base_atk}, DEF {esprit_base.base_def}"
                            ),
                            color=EmbedColors.SUCCESS
                        )
                        embed.set_image(url=f"attachment://{boss_file.filename}")
                        
                        await inter.edit_original_response(embed=embed, files=[boss_file])
                    else:
                        embed = disnake.Embed(
                            title="❌ Image Generation Failed",
                            description="Boss card generation returned None. Check image generation service.",
                            color=EmbedColors.ERROR
                        )
                        await inter.edit_original_response(embed=embed)
                        
                except ImportError:
                    embed = disnake.Embed(
                        title="❌ Boss Generator Not Available",
                        description="Boss generation module not found. Ensure `src.utils.boss_generator` exists.",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                except Exception as img_error:
                    logger.error(f"Boss card generation error: {img_error}", exc_info=True)
                    embed = disnake.Embed(
                        title="❌ Image Generation Error",
                        description=f"Failed to generate boss card: {str(img_error)[:100]}",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            logger.error(f"View boss error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Command Failed",
                description="Failed to process boss view command.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @view_group.sub_command(name="esprit", description="👹 Test esprit card generation")
    async def view_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        esprit_name: str = commands.Param(default="Blazeblob", description="Esprit name to generate"),
        awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level (stars)"),
        quantity: int = commands.Param(default=1, min_value=1, max_value=999, description="Stack quantity")
    ):
        """Generate a test esprit card image"""
        await inter.response.defer()
        
        try:
            # Search for the esprit in database
            from src.database.models.esprit_base import EspritBase
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(EspritBase.name.ilike(f"%{esprit_name}%"))
                esprit_base = (await session.execute(stmt)).scalar_one_or_none()
                
                if not esprit_base:
                    embed = disnake.Embed(
                        title="❌ Esprit Not Found",
                        description=f"No esprit found matching '{esprit_name}'. Try 'Blazeblob', 'Droozle', or 'Muddroot'.",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Create esprit card data
                esprit_card_data = {
                    "name": esprit_base.name,
                    "element": esprit_base.element,
                    "tier": esprit_base.base_tier,
                    "awakening": awakening,
                    "quantity": quantity,
                    "image_url": esprit_base.image_url,
                    "sprite_path": esprit_base.image_url,
                    "attack": esprit_base.base_atk,
                    "defense": esprit_base.base_def,
                    "hp": esprit_base.base_hp
                }
                
                # Generate esprit card
                try:
                    from src.utils.esprit_generator import generate_esprit_card
                    esprit_file = await generate_esprit_card(esprit_card_data, f"admin_esprit_test_{esprit_base.name}.png")
                    
                    if esprit_file:
                        embed = disnake.Embed(
                            title="👹 Esprit Card Generated!",
                            description=(
                                f"**Name:** {esprit_base.name}\n"
                                f"**Element:** {esprit_base.element}\n"
                                f"**Tier:** {esprit_base.base_tier}\n"
                                f"**Awakening:** {'⭐' * awakening if awakening > 0 else 'None'}\n"
                                f"**Quantity:** {quantity:,}\n"
                                f"**Stats:** ATK {esprit_base.base_atk}, DEF {esprit_base.base_def}, HP {esprit_base.base_hp}"
                            ),
                            color=EmbedColors.SUCCESS
                        )
                        embed.set_image(url=f"attachment://{esprit_file.filename}")
                        
                        await inter.edit_original_response(embed=embed, files=[esprit_file])
                    else:
                        embed = disnake.Embed(
                            title="❌ Image Generation Failed",
                            description="Esprit card generation returned None. Check image generation service.",
                            color=EmbedColors.ERROR
                        )
                        await inter.edit_original_response(embed=embed)
                        
                except ImportError:
                    embed = disnake.Embed(
                        title="❌ Esprit Generator Not Available",
                        description="Esprit generation module not found. Ensure `src.utils.esprit_generator` exists.",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                except Exception as img_error:
                    logger.error(f"Esprit card generation error: {img_error}", exc_info=True)
                    embed = disnake.Embed(
                        title="❌ Image Generation Error",
                        description=f"Failed to generate esprit card: {str(img_error)[:100]}",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            logger.error(f"View esprit error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Command Failed",
                description="Failed to process esprit view command.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @view_group.sub_command(name="stats", description="📊 Test stats/profile card generation")
    async def view_stats(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(default=None, description="User to generate stats for (defaults to you)")
    ):
        """Generate a test player stats card image"""
        await inter.response.defer()
        
        target_user = user or inter.author
        
        try:
            # Get player data
            player_result = await PlayerService.get_or_create_player(target_user.id, target_user.display_name)
            
            if not player_result.success:
                embed = disnake.Embed(
                    title="❌ Player Error",
                    description=player_result.error,
                    color=EmbedColors.WARNING
                )
                return await inter.edit_original_response(embed=embed)
            
            player = player_result.data
            if not player:
                embed = disnake.Embed(
                    title="❌ Invalid Player",
                    description="Failed to get valid player data.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # Create stats card data
            stats_card_data = {
                "username": player.username,
                "level": player.level,
                "experience": player.experience,
                "revies": player.revies,
                "erythl": player.erythl,
                "total_attack": player.total_attack_power,
                "total_defense": player.total_defense_power,
                "total_hp": player.total_hp,
                "energy": player.energy,
                "max_energy": player.max_energy,
                "stamina": player.stamina,
                "max_stamina": player.max_stamina,
                "discord_avatar": str(target_user.display_avatar.url),
                "class_type": "Unknown",  # Will be filled if class service exists
                "achievements_count": len(player.achievements_earned),
                "quests_completed": player.total_quests_completed
            }
            
            # Try to get class info
            try:
                from src.services.player_class_service import PlayerClassService
                class_result = await PlayerClassService.get_class_info(player.id) # type: ignore
                if class_result.success and class_result.data:
                    stats_card_data["class_type"] = class_result.data.get("class_type", "Unknown")
            except ImportError:
                pass
            
            # Generate stats card
            try:
                from src.utils.stats_generator import generate_stats_card
                stats_file = await generate_stats_card(stats_card_data, f"admin_stats_test_{player.username}.png")
                
                if stats_file:
                    embed = disnake.Embed(
                        title="📊 Stats Card Generated!",
                        description=(
                            f"**Player:** {player.username}\n"
                            f"**Level:** {player.level}\n"
                            f"**Class:** {stats_card_data['class_type']}\n"
                            f"**Power:** ATK {player.total_attack_power:,}, DEF {player.total_defense_power:,}, HP {player.total_hp:,}\n"
                            f"**Resources:** {player.revies:,} revies, {player.erythl:,} erythl\n"
                            f"**Progress:** {player.total_quests_completed} quests, {len(player.achievements_earned)} achievements"
                        ),
                        color=EmbedColors.SUCCESS
                    )
                    embed.set_image(url=f"attachment://{stats_file.filename}")
                    
                    await inter.edit_original_response(embed=embed, files=[stats_file])
                else:
                    embed = disnake.Embed(
                        title="❌ Image Generation Failed",
                        description="Stats card generation returned None. Check image generation service.",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    
            except ImportError:
                embed = disnake.Embed(
                    title="❌ Stats Generator Not Available",
                    description="Stats generation module not found. Ensure `src.utils.stats_generator` exists.",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_response(embed=embed)
            except Exception as img_error:
                logger.error(f"Stats card generation error: {img_error}", exc_info=True)
                embed = disnake.Embed(
                    title="❌ Image Generation Error",
                    description=f"Failed to generate stats card: {str(img_error)[:100]}",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            logger.error(f"View stats error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Command Failed",
                description="Failed to process stats view command.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

def setup(bot):
    bot.add_cog(AdminCog(bot))