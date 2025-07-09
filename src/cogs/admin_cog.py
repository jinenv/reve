# src/cogs/admin_cog.py - FULLY REFACTORED WITH TYPE SAFETY
import disnake
from disnake.ext import commands
from typing import Optional
import logging

from src.services.admin_service import AdminService
from src.services.player_service import PlayerService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import ratelimit
from src.utils.emoji_manager import EmojiStorageManager

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
        # ✅ @ratelimit decorator handles defer() automatically
        
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
            # ✅ Use AdminService with proper type checking
            reset_result = await AdminService.reset_player_data(
                discord_id=target_user.id,
                admin_id=inter.author.id,
                admin_name=inter.author.display_name,
                reason="admin_command_reset"
            )
            
            if not reset_result.success:
                embed = disnake.Embed(
                    title="❌ Reset Failed",
                    description=reset_result.error or "Unknown error occurred",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            operation_result = reset_result.data
            if not operation_result:
                embed = disnake.Embed(
                    title="❌ Reset Failed",
                    description="No result data returned from reset operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            details = operation_result.details
            
            embed = disnake.Embed(
                title="✅ Reset Complete",
                description=(
                    f"Successfully wiped all data for {target_user.mention}\n\n"
                    f"**Deleted:**\n"
                    f"• Player profile (Level {details.get('old_level', 'Unknown')})\n"
                    f"• Player class record\n"
                    f"• {details.get('deleted_esprits', 0)} Esprit stacks\n"
                    f"• {details.get('old_revies', 0):,} revies, {details.get('old_erythl', 0):,} erythl\n"
                    f"• All leader references cleared\n"
                    f"• Cache data cleared\n\n"
                    f"**Execution Time:** {operation_result.execution_time:.2f}s\n"
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
                    description=player_result.error or "Failed to get player data",
                    color=EmbedColors.WARNING
                )
                return await inter.edit_original_response(embed=embed)
            
            # Get player object with null checking
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
        # ✅ @ratelimit decorator handles defer() automatically
        
        try:
            # ✅ Use AdminService with proper type checking
            give_result = await AdminService.give_currency(
                admin_id=inter.author.id,
                admin_name=inter.author.display_name,
                target_discord_id=user.id,
                currency_type=currency,
                amount=amount,
                reason=reason
            )
            
            if not give_result.success:
                embed = disnake.Embed(
                    title="❌ Gift Failed",
                    description=give_result.error or "Unknown error occurred",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            result = give_result.data
            if not result:
                embed = disnake.Embed(
                    title="❌ Gift Failed",
                    description="No result data returned from give operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            currency_emoji = "💰" if currency == "revies" else "💎"
            
            embed = disnake.Embed(
                title="✅ Currency Given!",
                description=(
                    f"Gave {user.mention}:\n\n"
                    f"{currency_emoji} **{result.amount_given:,} {result.resource_name.title()}**\n\n"
                    f"**New Balance:** {result.new_balance or 0:,}\n"
                    f"**Reason:** {reason}"
                ),
                color=EmbedColors.SUCCESS
            )
            
            embed.set_footer(text=f"Given by {result.admin_who_gave}")
            
            await inter.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Give currency error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ System Error",
                description="Failed to give currency. Please try again.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @give_group.sub_command(name="esprit", description="👹 Give an Esprit to a player")
    async def give_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(description="Target player"),
        esprit_name: str = commands.Param(description="Esprit name"),
        quantity: int = commands.Param(default=1, min_value=1, max_value=1000, description="Quantity"),
        awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level")
    ):
        """Give an Esprit to a player"""
        await inter.response.defer()  # ✅ Required: no @ratelimit decorator
        
        try:
            # ✅ Use AdminService with proper type checking
            give_result = await AdminService.give_esprit(
                admin_id=inter.author.id,
                admin_name=inter.author.display_name,
                target_discord_id=user.id,
                esprit_name=esprit_name,
                quantity=quantity,
                awakening_level=awakening
            )
            
            if not give_result.success:
                # ✅ Safe error message handling
                error_message = give_result.error or "Unknown error occurred"
                
                # Handle specific errors from AdminService
                if "not yet supported" in error_message:
                    embed = disnake.Embed(
                        title="⚠️ Feature Limitation",
                        description=(
                            f"**Esprit Given:** {quantity}x {esprit_name}\n"
                            f"**Awakening:** Manual awakening required\n\n"
                            f"Auto-awakening to level {awakening} is not yet implemented. "
                            f"The Esprit has been given at base level. Use awakening commands manually."
                        ),
                        color=EmbedColors.WARNING
                    )
                else:
                    embed = disnake.Embed(
                        title="❌ Gift Failed",
                        description=error_message,
                        color=EmbedColors.ERROR
                    )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            result = give_result.data
            if not result:
                embed = disnake.Embed(
                    title="❌ Gift Failed",
                    description="No result data returned from give operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            embed = disnake.Embed(
                title="✅ Esprit Given!",
                description=(
                    f"Gave {user.mention}:\n\n"
                    f"👹 **{result.amount_given}x {result.resource_name}**\n"
                    f"**Awakening:** {'⭐' * awakening if awakening > 0 else 'Base Level'}\n\n"
                    f"*Check collection with `/collection` command*"
                ),
                color=EmbedColors.SUCCESS
            )
            
            embed.set_footer(text=f"Given by {result.admin_who_gave}")
            
            await inter.edit_original_response(embed=embed)
            
        except NotImplementedError as nie:
            # Handle fail-loud awakening error
            embed = disnake.Embed(
                title="⚠️ Feature Not Available", 
                description=str(nie),
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"Give esprit error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ System Error",
                description="Failed to give esprit. Please try again.",
                color=EmbedColors.ERROR
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
        # ✅ @ratelimit decorator handles defer() automatically
        
        try:
            # ✅ Use AdminService with proper type checking
            sync_result = await AdminService.sync_discord_commands(
                bot=self.bot,
                admin_id=inter.author.id
            )
            
            if not sync_result.success:
                embed = disnake.Embed(
                    title="❌ Sync Failed",
                    description=sync_result.error or "Unknown error occurred",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            operation_result = sync_result.data
            if not operation_result:
                embed = disnake.Embed(
                    title="❌ Sync Failed",
                    description="No result data returned from sync operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            embed = disnake.Embed(
                title="✅ Commands Synced",
                description=f"Successfully synced {operation_result.affected_count} slash commands with Discord.",
                color=EmbedColors.SUCCESS
            )
            
            embed.add_field(
                name="📊 Details",
                value=f"**Execution Time:** {operation_result.execution_time:.2f}s",
                inline=False
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
        # ✅ @ratelimit decorator handles defer() automatically
        
        try:
            # ✅ Use AdminService with proper type checking and fixed parameter order
            reload_result = await AdminService.reload_configuration(
                admin_id=inter.author.id,
                config_name=config
            )
            
            if not reload_result.success:
                embed = disnake.Embed(
                    title="❌ Reload Failed",
                    description=reload_result.error or "Unknown error occurred",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            operation_result = reload_result.data
            if not operation_result:
                embed = disnake.Embed(
                    title="❌ Reload Failed",
                    description="No result data returned from reload operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            details = operation_result.details
            
            if config.upper() == "ALL":
                embed = disnake.Embed(
                    title="🔄 All Configs Reloaded",
                    description=(
                        f"Successfully reloaded all configuration files.\n\n"
                        f"**Before:** {details.get('old_count', 0)} configs\n"
                        f"**After:** {details.get('new_count', 0)} configs\n"
                        f"**Execution Time:** {operation_result.execution_time:.2f}s"
                    ),
                    color=EmbedColors.SUCCESS
                )
                
                configs_loaded = details.get('configs_loaded', [])
                if configs_loaded:
                    configs_list = ", ".join(configs_loaded[:10])  # Limit display
                    if len(configs_loaded) > 10:
                        configs_list += f" (+{len(configs_loaded) - 10} more)"
                    embed.add_field(
                        name="📁 Loaded Configs",
                        value=configs_list,
                        inline=False
                    )
            else:
                embed = disnake.Embed(
                    title="✅ Config Reloaded",
                    description=(
                        f"Successfully reloaded `{details.get('config_name', config)}` configuration.\n\n"
                        f"**Execution Time:** {operation_result.execution_time:.2f}s"
                    ),
                    color=EmbedColors.SUCCESS
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
            # Get target player ID if provided
            target_player_id = None
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
                
                target_player_id = player_obj.id
            
            # ✅ Use AdminService with proper type checking and fixed parameter order
            cache_result = await AdminService.manage_cache(
                action=action,
                admin_id=inter.author.id,
                target_player_id=target_player_id
            )
            
            if not cache_result.success:
                embed = disnake.Embed(
                    title="❌ Cache Operation Failed",
                    description=cache_result.error or "Unknown error occurred",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            operation_result = cache_result.data
            if not operation_result:
                embed = disnake.Embed(
                    title="❌ Cache Operation Failed",
                    description="No result data returned from cache operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            details = operation_result.details
            
            if action == "stats":
                embed = disnake.Embed(
                    title="📊 Cache Statistics",
                    color=EmbedColors.INFO
                )
                
                # Safe access with defaults
                hit_rate = details.get('hit_rate', 0.0)
                hits = details.get('hits', 0)
                misses = details.get('misses', 0)
                sets = details.get('sets', 0)
                deletes = details.get('deletes', 0)
                invalidations = details.get('invalidations', 0)
                
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
                if target_player_id:
                    player_display = player.mention if player is not None else f"Player ID {target_player_id}"
                    embed = disnake.Embed(
                        title="✅ Player Cache Cleared",
                        description=f"Cleared cache for {player_display}",
                        color=EmbedColors.SUCCESS
                    )
                else:
                    embed = disnake.Embed(
                        title="✅ Global Cache Cleared",
                        description="Cleared all global cache entries",
                        color=EmbedColors.SUCCESS
                    )
            
            elif action == "warm":
                player_display = player.mention if player is not None else f"Player ID {target_player_id}"
                embed = disnake.Embed(
                    title="✅ Player Cache Warmed",
                    description=f"Pre-loaded cache for {player_display}",
                    color=EmbedColors.SUCCESS
                )
            
            # Add execution time for all operations
            embed.add_field(
                name="⏱️ Execution Time",
                value=f"{operation_result.execution_time:.3f}s",
                inline=True
            )
            
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
        # ✅ @ratelimit decorator handles defer() automatically
        
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
            
            # ✅ Use AdminService for emoji sync
            emoji_result = await AdminService.sync_emoji_mappings(
                bot=self.bot,
                emoji_servers=self.emoji_manager.emoji_servers,
                admin_id=inter.author.id
            )
            
            if not emoji_result.success:
                embed = disnake.Embed(
                    title="❌ Emoji Sync Failed",
                    description=emoji_result.error or "Unknown error occurred",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to result data with null checking
            operation_result = emoji_result.data
            if not operation_result:
                embed = disnake.Embed(
                    title="❌ Emoji Sync Failed",
                    description="No result data returned from emoji sync operation",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            details = operation_result.details
            
            embed = disnake.Embed(
                title="✅ Emoji Sync Complete",
                description=(
                    f"**Synced:** {details.get('synced_count', 0)} emojis\n"
                    f"**Failed:** {details.get('failed_count', 0)} emojis\n"
                    f"**Servers:** {details.get('servers_processed', 0)}\n"
                    f"**Total Cache Size:** {details.get('total_cache_size', 0)}\n\n"
                    f"**Execution Time:** {operation_result.execution_time:.2f}s\n"
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
            # ✅ Use AdminService for system health check
            health_result = await AdminService.get_system_health()
            
            if not health_result.success:
                embed = disnake.Embed(
                    title="❌ Health Check Failed",
                    description=health_result.error or "Failed to get system health",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # ✅ Safe access to health data
            health_data = health_result.data
            if not health_data:
                embed = disnake.Embed(
                    title="❌ Health Check Failed",
                    description="No health data returned",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # Determine overall status color
            overall_status = health_data.get("overall_status", "unknown")
            if overall_status == "healthy":
                color = EmbedColors.SUCCESS
            elif overall_status == "degraded":
                color = EmbedColors.WARNING
            else:
                color = EmbedColors.ERROR
            
            embed = disnake.Embed(
                title="🔧 Service Health Check",
                color=color
            )
            
            # Overall health
            health_score = health_data.get("health_score", 0)
            embed.add_field(
                name="📊 Overall Health",
                value=(
                    f"**Status:** {overall_status.title()}\n"
                    f"**Score:** {health_score}%\n"
                    f"**Database:** {health_data.get('database', 'unknown')}\n"
                    f"**Cache:** {health_data.get('cache', 'unknown')}\n"
                    f"**Config:** {health_data.get('config', 'unknown')}"
                ),
                inline=False
            )
            
            # Service status
            services = health_data.get("services", {})
            if services:
                service_status_lines = []
                for service_name, status in services.items():
                    emoji = "✅" if "healthy" in status else "❌"
                    service_status_lines.append(f"{emoji} **{service_name}:** {status}")
                
                embed.add_field(
                    name="🔍 Service Details",
                    value="\n".join(service_status_lines[:10]),  # Limit to prevent embed overflow
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
            from src.utils.database_service import DatabaseService
            from sqlalchemy import select
            
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
        """Generate a test esprit card image using the new EspritGenerator"""
        await inter.response.defer()
        
        try:
            # Search for the esprit in database
            from src.database.models.esprit_base import EspritBase
            from src.utils.database_service import DatabaseService
            from sqlalchemy import select
            
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
                
                # Create esprit card data matching the new generator's expected format
                esprit_card_data = {
                    "name": esprit_base.name,
                    "element": esprit_base.element,
                    "tier": esprit_base.base_tier,
                    "base_tier": esprit_base.base_tier,
                    "rarity": esprit_base.tier_name,  # tier name (common, rare, etc.)
                    "awakening_level": awakening,
                    "quantity": quantity,
                    "base_atk": esprit_base.base_atk,
                    "base_def": esprit_base.base_def,
                    "base_hp": esprit_base.base_hp
                }
                
                # Generate esprit card using the new EspritGenerator
                try:
                    from src.utils.esprit_generator import EspritGenerator
                    
                    # Initialize the generator
                    generator = EspritGenerator()
                    
                    # Generate the card image
                    card_image = await generator.render_esprit_card(esprit_card_data)
                    
                    # Convert to Discord file
                    filename = f"admin_test_{esprit_base.name.lower().replace(' ', '_')}.png"
                    esprit_file = await generator.to_discord_file(card_image, filename)
                    
                    if esprit_file:
                        embed = disnake.Embed(
                            title="👹 Esprit Card Generated!",
                            description=(
                                f"**Name:** {esprit_base.name}\n"
                                f"**Element:** {esprit_base.element}\n"
                                f"**Tier:** {esprit_base.base_tier} ({esprit_base.tier_name})\n"
                                f"**Awakening:** {'⭐' * awakening if awakening > 0 else 'Base Level'}\n"
                                f"**Quantity:** {quantity:,}\n"
                                f"**Stats:** ATK {esprit_base.base_atk:,}, DEF {esprit_base.base_def:,}, HP {esprit_base.base_hp:,}\n\n"
                                f"✨ **New Generator Features:**\n"
                                f"• 400x600 card size\n"
                                f"• Element frames from assets\n"
                                f"• A/B background variants\n"
                                f"• Portrait sprite support"
                            ),
                            color=EmbedColors.SUCCESS
                        )
                        embed.set_image(url=f"attachment://{esprit_file.filename}")
                        
                        await inter.edit_original_response(embed=embed, files=[esprit_file])
                    else:
                        embed = disnake.Embed(
                            title="❌ Image Generation Failed",
                            description="Esprit card generation returned None. Check logs for details.",
                            color=EmbedColors.ERROR
                        )
                        await inter.edit_original_response(embed=embed)
                        
                except ImportError as ie:
                    embed = disnake.Embed(
                        title="❌ Esprit Generator Not Available",
                        description=f"Failed to import EspritGenerator: {str(ie)}",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                except Exception as img_error:
                    logger.error(f"Esprit card generation error: {img_error}", exc_info=True)
                    embed = disnake.Embed(
                        title="❌ Image Generation Error",
                        description=f"Failed to generate esprit card: {str(img_error)[:200]}",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            logger.error(f"View esprit error: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Command Failed",
                description=f"Failed to process esprit view command: {str(e)[:100]}",
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
                    description=player_result.error or "Failed to get player data",
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
                if player.id:
                    class_result = await PlayerClassService.get_class_info(player.id)
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