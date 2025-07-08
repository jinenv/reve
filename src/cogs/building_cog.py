# src/cogs/building_cog.py - example
import disnake
from disnake.ext import commands
from typing import Literal
from sqlalchemy import select

# SOURCE: src/services/building_service.py
from src.services.building_service import BuildingService
# SOURCE: src/services/player_service.py  
from src.services.player_service import PlayerService
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import ratelimit
from src.utils.logger import get_logger

logger = get_logger(__name__)

class BuildingCog(commands.Cog):
    """Building system commands - ALL LOGIC IS IN SERVICES"""
    
    def __init__(self, bot):
        self.bot = bot

    async def _get_player_id(self, discord_id: int) -> int:
        """Get player ID with validation - returns valid player ID or raises exception"""
        async with DatabaseService.get_session() as session:
            stmt = select(Player).where(Player.discord_id == discord_id)  # type: ignore[arg-type]
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                raise ValueError("Player not registered")
            
            if not player.id:
                raise ValueError("Player has invalid ID")
                
            return player.id

    def _create_error_embed(self, title: str, description: str) -> disnake.Embed:
        """Create standardized error embed"""
        return disnake.Embed(
            title=title,
            description=description,
            color=EmbedColors.ERROR
        )

    def _create_success_embed(self, title: str, description: str) -> disnake.Embed:
        """Create standardized success embed"""
        return disnake.Embed(
            title=title,
            description=description,
            color=EmbedColors.SUCCESS
        )

    @commands.slash_command(name="build", description="Build a new structure")
    @ratelimit(uses=10, per_seconds=60, command_name="build")
    async def build_command(
        self, 
        inter: disnake.ApplicationCommandInteraction,
        building_type: Literal["shrine", "cluster"] = commands.Param(description="Type of building to construct")
    ):
        """Build a new structure (shrine or cluster)"""
        await inter.response.defer()
        
        try:
            # Get validated player ID
            player_id = await self._get_player_id(inter.author.id)
            
            # SOURCE: src/services/building_service.py - build_structure()
            result = await BuildingService.build_structure(player_id, building_type)
            
            if not result.success:
                embed = self._create_error_embed("Building Failed", result.error or "Unknown error")
                return await inter.edit_original_response(embed=embed)
            
            # Safely access data with validation
            data = result.data
            if not data:
                embed = self._create_error_embed("Building Failed", "No data returned from service")
                return await inter.edit_original_response(embed=embed)
            
            building_name = "Sacred Shrine" if building_type == "shrine" else "Energy Cluster"
            
            embed = disnake.Embed(
                title=f"🏗️ {building_name} Constructed!",
                description=(
                    f"**Cost:** {data['cost']:,} revies\n"
                    f"**Buildings:** {data['total_buildings']}/{data['total_buildings'] + data['available_slots']}\n"
                    f"**Remaining Revies:** {data['remaining_revies']:,}"
                ),
                color=EmbedColors.SUCCESS
            )
            
            await inter.edit_original_response(embed=embed)
            logger.info(f"Player {player_id} built {building_type}")
            
        except ValueError as e:
            embed = self._create_error_embed("Not Registered", "Use `/awaken` to start playing REVE")
            await inter.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"Build command error: {e}")
            embed = self._create_error_embed("Command Error", "An unexpected error occurred")
            await inter.edit_original_response(embed=embed)

    @commands.slash_command(name="upgrade", description="Instantly upgrade all buildings of a type")
    @ratelimit(uses=5, per_seconds=60, command_name="upgrade")
    async def upgrade_command(
        self, 
        inter: disnake.ApplicationCommandInteraction,
        building_type: Literal["shrine", "cluster"] = commands.Param(description="Type of buildings to upgrade")
    ):
        """Instantly upgrade all buildings of a type"""
        await inter.response.defer()
        
        try:
            # Get validated player ID
            player_id = await self._get_player_id(inter.author.id)
            
            # SOURCE: src/services/building_service.py - upgrade_buildings()
            result = await BuildingService.upgrade_buildings(player_id, building_type)
            
            if not result.success:
                embed = self._create_error_embed("Upgrade Failed", result.error or "Unknown error")
                return await inter.edit_original_response(embed=embed)
            
            # Safely access data with validation
            data = result.data
            if not data:
                embed = self._create_error_embed("Upgrade Failed", "No data returned from service")
                return await inter.edit_original_response(embed=embed)
            
            building_name = "Sacred Shrines" if building_type == "shrine" else "Energy Clusters"
            
            embed = disnake.Embed(
                title=f"⬆️ {building_name} Upgraded!",
                description=(
                    f"**Buildings:** {data['building_count']}x {building_type}s\n"
                    f"**Level:** {data['from_level']} → {data['to_level']}\n"
                    f"**Cost:** {data['cost_per_building']:,} revies each\n"
                    f"**Total Cost:** {data['total_cost']:,} revies\n"
                    f"**Income Increase:** +{data['income_increase_per_building']:,} per building\n"
                    f"**New Income:** {data['new_income_per_building']:,} per building\n"
                    f"**Remaining Revies:** {data['remaining_revies']:,}"
                ),
                color=EmbedColors.SUCCESS
            )
            
            await inter.edit_original_response(embed=embed)
            logger.info(f"Player {player_id} upgraded {data['building_count']} {building_type}s to level {data['to_level']}")
            
        except ValueError as e:
            embed = self._create_error_embed("Not Registered", "Use `/awaken` to start playing REVE")
            await inter.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"Upgrade command error: {e}")
            embed = self._create_error_embed("Command Error", "An unexpected error occurred")
            await inter.edit_original_response(embed=embed)

    @commands.slash_command(name="collect", description="Collect all pending building income")
    async def collect_command(self, inter: disnake.ApplicationCommandInteraction):
        """Collect all pending income from buildings"""
        await inter.response.defer()
        
        try:
            # Get validated player ID
            player_id = await self._get_player_id(inter.author.id)
            
            # Execute income collection
            result = await BuildingService.collect_income(player_id)
            
            if not result.success:
                embed = self._create_error_embed("Collection Failed", result.error or "Collection error")
                return await inter.edit_original_response(embed=embed)
            
            # Safely access data
            data = result.data
            if not data:
                embed = self._create_error_embed("Collection Failed", "No collection data returned")
                return await inter.edit_original_response(embed=embed)
            
            income_parts = []
            
            if data["revies_collected"] > 0:
                income_parts.append(f"**Revies:** {data['revies_collected']:,}")
            if data["erythl_collected"] > 0:
                income_parts.append(f"**Erythl:** {data['erythl_collected']:,}")
            
            embed = self._create_success_embed(
                "💰 Income Collected!",
                "\n".join(income_parts) + "\n\n" +
                f"**New Balances:**\n"
                f"Revies: {data['new_revies']:,}\n"
                f"Erythl: {data['new_erythl']:,}"
            )
            
            await inter.edit_original_response(embed=embed)
            logger.info(f"Player {player_id} collected {data['revies_collected'] + data['erythl_collected']} total income")
            
        except ValueError as e:
            embed = self._create_error_embed("Not Registered", "Use `/awaken` to start playing REVE")
            await inter.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"Collect command error: {e}")
            embed = self._create_error_embed("Command Error", "An unexpected error occurred")
            await inter.edit_original_response(embed=embed)

    @commands.slash_command(name="buildings", description="View your buildings and upgrade options")
    async def buildings_command(self, inter: disnake.ApplicationCommandInteraction):
        """Show owned buildings and upgrade options"""
        await inter.response.defer()
        
        try:
            # Get validated player ID
            player_id = await self._get_player_id(inter.author.id)
            
            # Get building status
            result = await BuildingService.get_building_status(player_id)
            
            if not result.success:
                embed = self._create_error_embed("Status Error", result.error or "Failed to get building status")
                return await inter.edit_original_response(embed=embed)
            
            # Safely access data
            data = result.data
            if not data:
                embed = self._create_error_embed("Status Error", "No building data returned")
                return await inter.edit_original_response(embed=embed)
            
            # Create embed
            embed = disnake.Embed(
                title="🏗️ Building Management",
                color=disnake.Color.blue()
            )
            
            # Building slots info
            embed.add_field(
                name="📊 Building Slots",
                value=(
                    f"**Used:** {data['buildings_owned']}/{data['building_slots']}\n"
                    f"**Available:** {data['available_slots']}\n"
                    f"**Max Possible:** {data['max_slots']}"
                ),
                inline=True
            )
            
            # Pending income
            pending_parts = []
            if data["pending_revies"] > 0:
                pending_parts.append(f"Revies: {data['pending_revies']:,}")
            if data["pending_erythl"] > 0:
                pending_parts.append(f"Erythl: {data['pending_erythl']:,}")
            
            embed.add_field(
                name="💰 Pending Income",
                value="\n".join(pending_parts) if pending_parts else "No income to collect",
                inline=True
            )
            
            # Expansion cost
            if data.get("next_slot_cost"):
                embed.add_field(
                    name="📈 Slot Expansion",
                    value=f"Cost: {data['next_slot_cost']:,} revies",
                    inline=True
                )
            
            # Building details
            building_info = data.get("building_info", {})
            for building_type, info in building_info.items():
                if info["count"] > 0:
                    status_parts = [
                        f"**Count:** {info['count']}",
                        f"**Level:** {info['level']}/{info['max_level']}",
                        f"**Income:** {info['income_per_building']:,} {info['currency_type']}/building",
                        f"**Total:** {info['total_income']:,} {info['currency_type']}/30min"
                    ]
                    
                    if info["can_upgrade"]:
                        status_parts.extend([
                            f"**Next Level Income:** {info['next_income_per_building']:,}/building",
                            f"**Upgrade Cost:** {info['upgrade_cost_per_building']:,} revies each",
                            f"**Total Upgrade Cost:** {info['total_upgrade_cost']:,} revies"
                        ])
                    elif info["level"] == info["max_level"]:
                        status_parts.append("**Status:** ⭐ MAX LEVEL")
                    
                    embed.add_field(
                        name=f"🏢 {info['name']}",
                        value="\n".join(status_parts),
                        inline=False
                    )
            
            # Available building types
            available_buildings = []
            building_configs = data.get("building_configs", {})
            for building_type, config in building_configs.items():
                name = config.get("name", building_type.title())
                cost = config.get("cost", 0)
                currency = config.get("currency_type", "revies")
                income = config.get("income_per_tick", 0)
                available_buildings.append(f"**{name}** - {cost:,} revies - {income} {currency}/30min")
            
            if available_buildings:
                embed.add_field(
                    name="🛒 Available Buildings",
                    value="\n".join(available_buildings),
                    inline=False
                )
            
            embed.set_footer(text="Use /build to construct • /collect for income • /upgrade <type> to level up all buildings of that type")
            
            await inter.edit_original_response(embed=embed)
            logger.info(f"Player {player_id} viewed building status")
            
        except ValueError as e:
            embed = self._create_error_embed("Not Registered", "Use `/awaken` to start playing REVE")
            await inter.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"Buildings command error: {e}")
            embed = self._create_error_embed("Command Error", "An unexpected error occurred")
            await inter.edit_original_response(embed=embed)

    @commands.slash_command(name="expand_slots", description="Expand your building slots")
    async def expand_slots_command(self, inter: disnake.ApplicationCommandInteraction):
        """Expand building slots for more constructions"""
        await inter.response.defer()
        
        try:
            # Get validated player ID
            player_id = await self._get_player_id(inter.author.id)
            
            # Execute slot expansion
            result = await BuildingService.expand_building_slots(player_id)
            
            if not result.success:
                embed = self._create_error_embed("Expansion Failed", result.error or "Expansion error")
                return await inter.edit_original_response(embed=embed)
            
            # Safely access data
            data = result.data
            if not data:
                embed = self._create_error_embed("Expansion Failed", "No expansion data returned")
                return await inter.edit_original_response(embed=embed)
            
            embed = self._create_success_embed(
                "📈 Building Slots Expanded!",
                f"**Slots:** {data['old_slots']} → {data['new_slots']}\n"
                f"**Cost:** {data['cost']:,} revies\n"
                f"**Remaining Revies:** {data['remaining_revies']:,}"
            )
            
            await inter.edit_original_response(embed=embed)
            logger.info(f"Player {player_id} expanded building slots to {data['new_slots']}")
            
        except ValueError as e:
            embed = self._create_error_embed("Not Registered", "Use `/awaken` to start playing REVE")
            await inter.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"Expand slots command error: {e}")
            embed = self._create_error_embed("Command Error", "An unexpected error occurred")
            await inter.edit_original_response(embed=embed)

def setup(bot):
    bot.add_cog(BuildingCog(bot))