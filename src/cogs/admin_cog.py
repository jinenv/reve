# src/cogs/admin.py
import disnake
from disnake.ext import commands
from sqlalchemy import select, delete, func, update

from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import ratelimit
from src.database.models import Player, Esprit, EspritBase

import logging
logger = logging.getLogger(__name__)


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
   @ratelimit(uses=1, per_seconds=10, command_name="admin_reset")
   async def admin_reset(
       self,
       inter: disnake.ApplicationCommandInteraction,
       user: disnake.User = commands.Param(description="User to reset (defaults to self)", default=None)
   ):
       """Reset a player's data"""
       
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
               
               # Log the reset before deletion
               if player_id:
                   transaction_logger.log_transaction(
                       player_id=player_id,
                       transaction_type=TransactionType.ADMIN_DELETION,
                       details={
                           "action": "full_player_reset",
                           "discord_id": target_user.id,
                           "username": target_user.name
                       },
                       metadata={
                           "admin_command": "reset",
                           "admin_id": inter.author.id,
                           "admin_name": inter.author.name
                       }
                   )
               
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
           logger.error(f"Admin command error in {inter.application_command.name}: {e}", exc_info=True)
           embed = disnake.Embed(
               title="❌ Reset Failed",
               description="An error occurred. Check logs for details.",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)

   @admin.sub_command_group(name="sync", description="Sync various game data")
   async def admin_sync(self, inter: disnake.ApplicationCommandInteraction):
       """Sync group - never called directly"""
       pass
   
   @admin_sync.sub_command(name="emojis", description="Sync emoji mappings from Discord")
   @ratelimit(uses=1, per_seconds=30, command_name="admin_sync_emojis")
   async def sync_emojis(self, inter: disnake.ApplicationCommandInteraction):
       """Sync emojis from configured servers"""
       
       try:
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
           
       except Exception as e:
           logger.error(f"Admin command error in {inter.application_command.name}: {e}", exc_info=True)
           await inter.edit_original_response(content="❌ Error syncing emojis. Check logs for details.")

   @admin.sub_command(name="sync_commands", description="Force sync slash commands with Discord")
   @ratelimit(uses=1, per_seconds=30, command_name="admin_sync_commands")
   async def sync_commands(self, inter: disnake.ApplicationCommandInteraction):
       """Force Discord to recognize new slash commands"""
       await inter.response.defer()
       
       try:
           # Sync commands globally
           synced = await self.bot.sync_application_commands()
           
           embed = disnake.Embed(
               title="✅ Commands Synced",
               description=f"Synced {len(synced)} slash commands with Discord.",
               color=EmbedColors.SUCCESS
           )
           
           embed.set_footer(text="Commands may take a few minutes to appear")
           await inter.edit_original_response(embed=embed)
           
       except Exception as e:
           logger.error(f"Command sync failed: {e}")
           embed = disnake.Embed(
               title="❌ Sync Failed",
               description=f"Error syncing commands: {str(e)}",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)
        
   @admin.sub_command_group(name="give", description="Give items/esprits to players")
   async def admin_give(self, inter: disnake.ApplicationCommandInteraction):
       """Give group - never called directly"""
       pass
   
   @admin_give.sub_command(name="esprit", description="Give an esprit to a player")
   @ratelimit(uses=5, per_seconds=60, command_name="admin_give_esprit")
   async def give_esprit(
       self,
       inter: disnake.ApplicationCommandInteraction,
       user: disnake.User = commands.Param(description="Target player"),
       esprit_name: str = commands.Param(description="Name of the esprit"),
       quantity: int = commands.Param(default=1, min_value=1, description="How many to give"),
       awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level (0-5 stars)")
   ):
       """Give an esprit to a player by name"""
       
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
               
               # Log the admin gift
               transaction_logger.log_transaction(
                   player_id=player.id,
                   transaction_type=TransactionType.ITEM_GAINED,
                   details={
                       "esprit_name": esprit_base.name,
                       "tier": esprit_base.base_tier,
                       "element": esprit_base.element,
                       "quantity": quantity,
                       "awakening": awakening,
                       "action": "admin_gift"
                   },
                   metadata={
                       "admin_command": "give_esprit",
                       "admin_id": inter.author.id,
                       "admin_name": inter.author.name
                   }
               )
               
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
           logger.error(f"Admin command error in {inter.application_command.name}: {e}", exc_info=True)
           embed = disnake.Embed(
               title="❌ Command Failed",
               description="An error occurred. Check logs for details.",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)

   @admin_give.sub_command(name="all_esprits", description="Give ALL esprits (WARNING: This is insane)")
   @ratelimit(uses=1, per_seconds=300, command_name="admin_give_all")
   async def give_all_esprits(
       self,
       inter: disnake.ApplicationCommandInteraction,
       user: disnake.User = commands.Param(description="Target player"),
       quantity: int = commands.Param(default=1, min_value=1, max_value=1000, description="How many of EACH"),
       awakening: int = commands.Param(default=0, min_value=0, max_value=5, description="Awakening level")
   ):
       """Give one of every esprit for testing purposes"""

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
               
               # Log the massive admin gift
               transaction_logger.log_transaction(
                   player_id=player.id,
                   transaction_type=TransactionType.ITEM_GAINED,
                   details={
                       "action": "admin_give_all_esprits",
                       "esprit_types_given": count,
                       "quantity_each": quantity,
                       "total_esprits": count * quantity,
                       "awakening": awakening
                   },
                   metadata={
                       "admin_command": "give_all_esprits",
                       "admin_id": inter.author.id,
                       "admin_name": inter.author.name
                   }
               )
               
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
           logger.error(f"Admin command error in {inter.application_command.name}: {e}", exc_info=True)
           embed = disnake.Embed(
               title="❌ Command Failed", 
               description="An error occurred. Check logs for details.",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)
   
   @give_esprit.autocomplete("esprit_name")
   async def esprit_autocomplete(self, inter: disnake.ApplicationCommandInteraction, query: str):
       """Autocomplete esprit names from config"""
       query = query.lower()
       
       try:
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
       except Exception as e:
           logger.error(f"Autocomplete error: {e}")
           return []
   
   @admin.sub_command_group(name="remove", description="Remove various game elements")
   async def admin_remove(self, inter: disnake.ApplicationCommandInteraction):
       """Remove group - never called directly"""
       pass

   @admin_remove.sub_command(name="esprit_base", description="DANGER: Remove an Esprit type from existence entirely")
   @ratelimit(uses=1, per_seconds=60, command_name="admin_remove_base")
   async def remove_esprit_base(
       self,
       inter: disnake.ApplicationCommandInteraction,
       esprit_name: str = commands.Param(description="Exact name of the Esprit to remove"),
       confirm_deletion: bool = commands.Param(default=False, description="Type True to confirm PERMANENT deletion")
   ):
       """Remove an EspritBase (Esprit type) entirely from the game"""

       if not confirm_deletion:
           embed = disnake.Embed(
               title="⚠️ DANGER: Complete Esprit Removal",
               description=(
                   f"This will **PERMANENTLY DELETE** the Esprit type `{esprit_name}` from existence.\n\n"
                   "**This means:**\n"
                   "• All players who own this Esprit will lose it\n"
                   "• The Esprit can never be captured again\n"
                   "• This cannot be undone\n\n"
                   f"Use `/admin remove esprit_base {esprit_name} confirm_deletion:True` if you're absolutely sure."
               ),
               color=EmbedColors.ERROR
           )
           return await inter.edit_original_response(embed=embed)
       
       try:
           async with DatabaseService.get_transaction() as session:
               # Find the EspritBase
               stmt = select(EspritBase).where(
                   func.lower(EspritBase.name) == esprit_name.lower()
               )
               esprit_base = (await session.execute(stmt)).scalar_one_or_none()
               
               if not esprit_base:
                   await inter.edit_original_response(content=f"❌ No Esprit named '{esprit_name}' found in the database.")
                   return
               
               # Count how many players own this Esprit
               count_stmt = select(func.count(Esprit.id)).where(  # type: ignore
                   Esprit.esprit_base_id == esprit_base.id # type: ignore
               )
               owned_count = (await session.execute(count_stmt)).scalar() or 0
               
               # Get total quantity owned
               qty_stmt = select(func.sum(Esprit.quantity)).where(
                   Esprit.esprit_base_id == esprit_base.id # type: ignore
               )
               total_quantity = (await session.execute(qty_stmt)).scalar() or 0
               
               # Check if it's anyone's leader
               leader_stmt = select(func.count(Player.id)).where(  # type: ignore
                   Player.leader_esprit_stack_id.in_( # type: ignore
                       select(Esprit.id).where(Esprit.esprit_base_id == esprit_base.id) # type: ignore
                   )
               )
               leader_count = (await session.execute(leader_stmt)).scalar() or 0
               
               # Store info for logging
               deletion_info = {
                   "esprit_base_id": esprit_base.id,
                   "name": esprit_base.name,
                   "element": esprit_base.element,
                   "base_tier": esprit_base.base_tier,
                   "players_affected": owned_count,
                   "total_quantity_destroyed": total_quantity,
                   "leader_references": leader_count
               }
               
               # Log the deletion
               transaction_logger.log_transaction(
                   player_id=0,  # System action
                   transaction_type=TransactionType.ESPRIT_BASE_DELETED,
                   details=deletion_info,
                   metadata={
                       "admin_command": "remove_esprit_base",
                       "admin_id": inter.author.id,
                       "admin_name": inter.author.name
                   }
               )
               
               # Clear leader references first
               if leader_count > 0: 
                   leader_clear_stmt = update(Player).where(   # type: ignore
                       Player.leader_esprit_stack_id.in_( # type: ignore
                           select(Esprit.id).where(Esprit.esprit_base_id == esprit_base.id) # type: ignore
                       )
                   ).values(leader_esprit_stack_id=None)
                   await session.execute(leader_clear_stmt)
               
               # Delete all player-owned instances of this Esprit
               delete_instances_stmt = delete(Esprit).where(
                   Esprit.esprit_base_id == esprit_base.id # type: ignore
               )
               await session.execute(delete_instances_stmt)
               
               # Delete the EspritBase itself
               await session.delete(esprit_base)
               
               embed = disnake.Embed(
                   title="💥 Esprit Type Completely Removed",
                   description=(
                       f"**{esprit_base.name}** has been completely removed from existence.\n\n"
                       f"**Destruction Summary:**\n"
                       f"• **Element:** {esprit_base.element}\n"
                       f"• **Tier:** {esprit_base.base_tier}\n"
                       f"• **Players Affected:** {owned_count}\n"
                       f"• **Total Copies Destroyed:** {total_quantity:,}\n"
                       f"• **Leader References Cleared:** {leader_count}\n\n"
                       f"This Esprit no longer exists and cannot be captured."
                   ),
                   color=EmbedColors.ERROR
               )
               
               await inter.edit_original_response(embed=embed)
               
       except Exception as e:
           logger.error(f"Admin command error in {inter.application_command.name}: {e}", exc_info=True)
           embed = disnake.Embed(
               title="❌ Command Failed",
               description="An error occurred. Check logs for details.",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)

   @admin_remove.sub_command(name="esprit_instance", description="Remove a specific Esprit from a player")
   @ratelimit(uses=3, per_seconds=60, command_name="admin_remove_instance")
   async def remove_esprit_instance(
       self,
       inter: disnake.ApplicationCommandInteraction,
       user: disnake.User = commands.Param(description="Target player"),
       esprit_id: int = commands.Param(description="Esprit stack ID to remove"),
       confirm: bool = commands.Param(default=False, description="Confirm deletion")
   ):
       """Remove a specific Esprit stack from a player"""
       
       if not confirm:
           embed = disnake.Embed(
               title="⚠️ Confirmation Required",
               description=f"This will permanently delete Esprit ID {esprit_id} from {user.mention}.\nUse confirm:True to proceed.",
               color=EmbedColors.WARNING
           )
           return await inter.edit_original_response(embed=embed)
       
       try:
           async with DatabaseService.get_transaction() as session:
               # Get player
               stmt = select(Player).where(Player.discord_id == user.id) # type: ignore
               player = (await session.execute(stmt)).scalar_one_or_none()
               
               if not player:
                   await inter.edit_original_response(content=f"❌ {user.mention} isn't registered!")
                   return
               
               # Get the Esprit with base info
               stmt = select(Esprit, EspritBase).where(
                   Esprit.id == esprit_id, # type: ignore
                   Esprit.owner_id == player.id,  # type: ignore
                   Esprit.esprit_base_id == EspritBase.id # type: ignore
               )
               result = (await session.execute(stmt)).first()
               
               if not result:
                   await inter.edit_original_response(content=f"❌ Esprit ID {esprit_id} not found or not owned by {user.mention}")
                   return
               
               esprit, base = result
               
               # Clear leader reference if this Esprit is set as leader
               if player.leader_esprit_stack_id == esprit_id:
                   player.leader_esprit_stack_id = None
               
               # Store info for response
               esprit_info = {
                   "name": base.name,
                   "element": base.element,
                   "tier": esprit.tier,
                   "quantity": esprit.quantity,
                   "awakening": esprit.awakening_level
               }
               
               # Log the removal
               if player.id is not None:
                   transaction_logger.log_transaction(
                       player_id=player.id,
                       transaction_type=TransactionType.ADMIN_DELETION,
                       details={
                           "esprit_id": esprit.id,
                           "esprit_name": base.name,
                           "tier": esprit.tier,
                           "quantity": esprit.quantity,
                           "element": esprit.element,
                           "action": "remove_esprit_instance"
                       },
                       metadata={
                           "admin_command": "remove_esprit_instance", 
                           "admin_id": inter.author.id,
                           "admin_name": inter.author.name
                       }
                   )
               
               # DELETE FROM DATABASE
               await session.delete(esprit)
               
               # Invalidate cache
               if RedisService.is_available() and player.id:
                   await RedisService.invalidate_player_cache(player.id)
               
               # Recalculate power
               await player.recalculate_total_power(session)
               
               embed = disnake.Embed(
                   title="🗑️ Esprit Instance Removed",
                   description=(
                       f"Successfully removed from {user.mention}:\n\n"
                       f"{base.get_element_emoji()} **{esprit_info['name']}**\n"
                       f"Tier {esprit_info['tier']} | Quantity: {esprit_info['quantity']}\n"
                       f"Awakening: {'⭐' * esprit_info['awakening'] if esprit_info['awakening'] > 0 else 'None'}"
                   ),
                   color=EmbedColors.SUCCESS
               )
               
               if player.leader_esprit_stack_id is None:
                   embed.add_field(name="⚠️ Leader Cleared", value="This Esprit was set as leader and has been cleared.", inline=False)
               
               await inter.edit_original_response(embed=embed)
               
       except Exception as e:
           logger.error(f"Admin command error in {inter.application_command.name}: {e}", exc_info=True)
           embed = disnake.Embed(
               title="❌ Command Failed",
               description="An error occurred. Check logs for details.",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)

   # Autocomplete for both commands
   @remove_esprit_base.autocomplete("esprit_name")
   async def esprit_base_autocomplete(self, inter: disnake.ApplicationCommandInteraction, query: str):
       """Autocomplete for EspritBase names"""
       query = query.lower()
       
       try:
           async with DatabaseService.get_session() as session:
               stmt = select(EspritBase.name, EspritBase.element, EspritBase.base_tier).where( # type: ignore
                   func.lower(EspritBase.name).like(f"%{query}%")
               ).limit(25)
               
               results = (await session.execute(stmt)).all()
               
               matches = []
               for name, element, tier in results:
                   display = f"{name} (T{tier} {element})"
                   matches.append(disnake.OptionChoice(name=display[:100], value=name))
               
               return matches
       except Exception as e:
           logger.error(f"Autocomplete error: {e}")
           return []

   @admin.sub_command(name="reload_config", description="NUCLEAR CONFIG RELOAD - Reloads EVERYTHING")
   @ratelimit(uses=1, per_seconds=5, command_name="admin_reload_config")
   async def universal_config_reload(
       self, 
       inter: disnake.ApplicationCommandInteraction,
       specific_config: str = commands.Param(default="ALL", description="Specific config to reload or 'ALL'")
   ):
       """UNIVERSAL CONFIG RELOADER for live config editing"""
       
       # Check if interaction was already responded to by rate limiter
       if not inter.response.is_done():
           await inter.response.defer()
       
       try:
           reloaded_configs = []
           
           if specific_config.upper() == "ALL":
               # NUCLEAR OPTION: Reload EVERYTHING
               old_count = len(ConfigManager._configs) if hasattr(ConfigManager, '_configs') else 0
               
               # Use the actual reload method
               ConfigManager.reload()
               
               new_count = len(ConfigManager._configs)
               reloaded_configs = list(ConfigManager._configs.keys())
               
               # Force ImageGenerator to reinitialize 
               from utils.stats_generator import _generator
               _generator.__init__()
               
               embed = disnake.Embed(
                   title="🔥 NUCLEAR CONFIG RELOAD COMPLETE",
                   description=f"Obliterated and reloaded ALL configs from disk.\n\n**Before:** {old_count} configs\n**After:** {new_count} configs",
                   color=EmbedColors.SUCCESS
               )
               
               if reloaded_configs:
                   embed.add_field(
                       name="💥 Configs Reloaded",
                       value=", ".join(reloaded_configs),
                       inline=False
                   )
               
               embed.add_field(
                   name="🎯 ImageGenerator",
                   value="Forced reinitialization with new config",
                   inline=False
               )
                
           else:
               # Reload specific config
               if specific_config in ConfigManager._configs:
                   # Remove from cache
                   del ConfigManager._configs[specific_config]
                   
                   # Try to reload it
                   import json
                   from pathlib import Path
                   
                   config_path = Path("data/config") / f"{specific_config}.json"
                   if config_path.exists():
                       with open(config_path, 'r', encoding='utf-8') as f:
                           ConfigManager._configs[specific_config] = json.load(f)
                       
                       reloaded_configs = [specific_config]
                       
                       # If it's stats_generation, reload StatsGenerator
                       if specific_config == "stats_generation":
                           from utils.stats_generator import _generator
                           _generator.__init__()
                       
                       embed = disnake.Embed(
                           title="✅ Specific Config Reloaded",
                           description=f"Successfully reloaded `{specific_config}` from disk.",
                           color=EmbedColors.SUCCESS
                       )
                       
                       if specific_config == "stats_generation":
                           embed.add_field(
                               name="🎯 ImageGenerator",
                               value="Forced reinitialization with new config",
                               inline=False
                           )
                   else:
                       embed = disnake.Embed(
                           title="❌ Config File Not Found",
                           description=f"Config file `{specific_config}.json` doesn't exist on disk.",
                           color=EmbedColors.ERROR
                       )
               else:
                   embed = disnake.Embed(
                       title="❌ Config Not Loaded",
                       description=f"Config `{specific_config}` wasn't loaded in memory.",
                       color=EmbedColors.ERROR
                   )
        
           # Add timestamp
           import datetime
           embed.set_footer(text=f"Reloaded at {datetime.datetime.now().strftime('%H:%M:%S')}")
           
           # Use edit_original_response whether we deferred or rate limiter handled it
           await inter.edit_original_response(embed=embed)
           
       except Exception as e:
           logger.error(f"Universal config reload failed: {e}", exc_info=True)
           embed = disnake.Embed(
               title="💥 RELOAD CATASTROPHICALLY FAILED",
               description=f"Error: {str(e)}\n\nYour configs might be in an undefined state. Restart the bot.",
               color=EmbedColors.ERROR
           )
           await inter.edit_original_response(embed=embed)
    
   @admin.sub_command(name="debug_image_config", description="🔥 Debug image generation configuration")
   async def debug_image_config(self, inter: disnake.ApplicationCommandInteraction):
       """Debug command to verify image config is working"""
       
       await inter.response.defer()
       
       try:
           # Test 1: Raw ConfigManager access
           raw_config = ConfigManager.get("stats_generation")
           
           # Test 2: ImageConfig methods
           from utils.stats_generator import ImageConfig
           
           # Test basic values
           bg_color = ImageConfig.get_background_color()
           text_color = ImageConfig.get_text_color()
           line_color = ImageConfig.get_line_color()
           
           # Test nested access
           tier_10_effects = ImageConfig.get_tier_effects(10)
           tier_1_effects = ImageConfig.get_tier_effects(1)
           tier_20_effects = ImageConfig.get_tier_effects(20)
           
           # Test fonts config
           fonts = ImageConfig.get("fonts", {})
           font_sizes = fonts.get("sizes", {}) if isinstance(fonts, dict) else {}
           
           # Test layout config
           layout = ImageConfig.get("layout", {})
           left_margin = layout.get("left_margin", "NOT FOUND") if isinstance(layout, dict) else "NOT FOUND"
           
           # Test content box
           content_box = ImageConfig.get("content_box", {})
           content_enabled = content_box.get("enabled", "NOT FOUND") if isinstance(content_box, dict) else "NOT FOUND"
           
           # Test tier thresholds specifically
           thresholds = ImageConfig.get_nested("tier_effects", "thresholds", default="NOT FOUND")
           
           embed = disnake.Embed(
               title="🔥 Image Config Debug Results",
               description="**Config Diagnostic Report**",
               color=0xFF4500
           )
           
           # Basic results
           embed.add_field(
               name="🎨 Colors",
               value=f"**Background:** {bg_color}\n**Text:** {text_color}\n**Lines:** {line_color}",
               inline=False
           )
           
           # Tier effects
           embed.add_field(
               name="⭐ Tier Effects",
               value=f"**Tier 1:** {tier_1_effects.get('glow_intensity', 'MISSING')}\n**Tier 10:** {tier_10_effects.get('glow_intensity', 'MISSING')}\n**Tier 20:** {tier_20_effects.get('glow_intensity', 'MISSING')}",
               inline=False
           )
           
           # Layout
           embed.add_field(
               name="📐 Layout",
               value=f"**Left Margin:** {left_margin}\n**Content Box Enabled:** {content_enabled}",
               inline=False
           )
           
           # Config status
           config_status = "✅ WORKING" if raw_config is not None else "❌ BROKEN"
           embed.add_field(
               name="⚙️ Config Status",
               value=f"**File Loading:** {config_status}\n**Thresholds Found:** {'✅ YES' if thresholds != 'NOT FOUND' else '❌ NO'}",
               inline=False
           )
           
           # Font status
           font_status = "✅ LOADED" if font_sizes else "❌ MISSING"
           embed.add_field(
               name="🔤 Fonts",
               value=f"**Status:** {font_status}\n**Sizes:** {list(font_sizes.keys()) if font_sizes else 'NONE'}",
               inline=False
           )
           
           embed.set_footer(text="🔥 If anything shows MISSING/NOT FOUND, your config isn't loading properly")
           
           await inter.edit_original_response(embed=embed)
           
           # Also log detailed info to console
           logger.info(f"[DEBUG] Raw config type: {type(raw_config)}")
           logger.info(f"[DEBUG] Raw config keys: {list(raw_config.keys()) if isinstance(raw_config, dict) else 'NOT A DICT'}")
           logger.info(f"[DEBUG] Tier 10 full effects: {tier_10_effects}")
           logger.info(f"[DEBUG] Thresholds: {thresholds}")
           
       except Exception as e:
           error_embed = disnake.Embed(
               title="💀 Config Debug Failed",
               description=f"**Error:** {str(e)}\n\n*Configuration system has encountered critical errors...*",
               color=0xFF0000
           )
           await inter.edit_original_response(embed=error_embed)
           logger.error(f"Config debug failed: {e}", exc_info=True)
           
def setup(bot):
   bot.add_cog(Admin(bot))