# src/cogs/building_cog.py - example
import disnake
from disnake.ext import commands
import logging
from typing import Dict, Any

from src.services.building_service import BuildingService
from src.utils.database_service import DatabaseService
from src.database.models.player import Player
from sqlalchemy import select

logger = logging.getLogger(__name__)

class BuildingCog(commands.Cog):
    """Building management and income collection commands"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("BuildingCog initialized successfully")

    @commands.command(name="collect")
    async def collect_income(self, ctx):
        """Collect pending building income"""
        # Check if player exists
        async with DatabaseService.get_session() as session:
            stmt = select(Player).where(Player.discord_id == ctx.author.id)
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                embed = disnake.Embed(
                    title="❌ Not Registered",
                    description="You need to `r start` your journey first!",
                    color=0xdc3545
                )
                await ctx.send(embed=embed)
                return
        
        # Get pending income status first
        status_result = await BuildingService.get_pending_income_status(player.id)
        if not status_result.success:
            embed = disnake.Embed(
                title="❌ Error",
                description="Failed to check building status.",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        status = status_result.data
        if not status:
            embed = disnake.Embed(
                title="❌ Error",
                description="Could not retrieve building information.",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        # Check if player has any buildings
        if status["income_generating_slots"] == 0:
            embed = disnake.Embed(
                title="🏗️ No Income Buildings",
                description="You need more than 3 building slots to generate income.\n\nFirst 3 slots are free and don't generate income.",
                color=0x2c2d31
            )
            await ctx.send(embed=embed)
            return
        
        # Collect the income
        result = await BuildingService.collect_pending_income(player.id)
        
        if not result.success:
            embed = disnake.Embed(
                title="❌ Collection Failed",
                description=result.error or "Unknown error occurred",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        collection_data = result.data
        if not collection_data:
            embed = disnake.Embed(
                title="❌ Error",
                description="No collection data returned.",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        # Create success embed
        collected = collection_data["collected"]
        new_balance = collection_data["new_balance"]
        
        if collected == 0:
            embed = disnake.Embed(
                title="💰 No Income Available",
                description="Your building income storage is empty.\n\nIncome generates every 30 minutes.",
                color=0x2c2d31
            )
            embed.add_field(
                name="📊 Building Info",
                value=f"**Income Slots:** {status['income_generating_slots']}\n**Per Tick:** {status['income_per_tick']:,} revies\n**Next Tick:** ~{status['next_tick_minutes']} minutes",
                inline=False
            )
        else:
            embed = disnake.Embed(
                title="💰 Income Collected!",
                description=f"Successfully collected **{collected:,} revies** from your buildings!",
                color=0x28a745
            )
            embed.add_field(
                name="💳 Balance",
                value=f"**{new_balance:,}** revies",
                inline=True
            )
            embed.add_field(
                name="🏗️ Building Stats",
                value=f"**Income Slots:** {status['income_generating_slots']}\n**Per Tick:** {status['income_per_tick']:,} revies",
                inline=True
            )
        
        await ctx.send(embed=embed)

    @commands.command(name="buildings", aliases=["building"])
    async def buildings_status(self, ctx):
        """Check building status and pending income"""
        # Check if player exists
        async with DatabaseService.get_session() as session:
            stmt = select(Player).where(Player.discord_id == ctx.author.id)
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                embed = disnake.Embed(
                    title="❌ Not Registered",
                    description="You need to `r start` your journey first!",
                    color=0xdc3545
                )
                await ctx.send(embed=embed)
                return
        
        # Get comprehensive building status
        building_status_result = await BuildingService.get_building_status(player.id)
        pending_status_result = await BuildingService.get_pending_income_status(player.id)
        
        if not building_status_result.success or not pending_status_result.success:
            embed = disnake.Embed(
                title="❌ Error",
                description="Failed to retrieve building information.",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        building_data = building_status_result.data
        pending_data = pending_status_result.data
        
        if not building_data or not pending_data:
            embed = disnake.Embed(
                title="❌ Error",
                description="Could not retrieve building data.",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        # Create status embed
        embed = disnake.Embed(
            title="🏗️ Building Overview",
            description="Your building empire status",
            color=0x2c2d31
        )
        
        # Building slots info
        current_slots = building_data["current_slots"]
        max_slots = building_data["max_slots"]
        income_slots = pending_data["income_generating_slots"]
        
        embed.add_field(
            name="🏠 Building Slots",
            value=f"**Total:** {current_slots}/{max_slots}\n**Income Generating:** {income_slots}\n**Free Slots:** 3 (no income)",
            inline=True
        )
        
        # Pending income info
        pending_income = pending_data["pending_income"]
        max_storage = pending_data["max_storage"]
        storage_pct = pending_data["storage_percentage"]
        
        if income_slots > 0:
            storage_bar = "🟩" * int(storage_pct // 10) + "⬜" * (10 - int(storage_pct // 10))
            
            embed.add_field(
                name="💰 Pending Income",
                value=f"**Stored:** {pending_income:,} revies\n**Storage:** {storage_bar} {storage_pct:.1f}%\n**Max Storage:** {max_storage:,} revies",
                inline=True
            )
            
            embed.add_field(
                name="📈 Income Rate",
                value=f"**Per Tick:** {pending_data['income_per_tick']:,} revies\n**Interval:** {pending_data['next_tick_minutes']} minutes\n**Daily Potential:** {pending_data['income_per_tick'] * 48:,} revies",
                inline=True
            )
            
            # Collection prompt
            if pending_income > 0:
                embed.add_field(
                    name="💡 Ready to Collect!",
                    value=f"Use `r collect` to claim your **{pending_income:,} revies**",
                    inline=False
                )
        else:
            embed.add_field(
                name="💰 No Income Generation",
                value="You need more than 3 building slots to generate passive income.",
                inline=True
            )
        
        # Upkeep status
        upkeep_status = building_data.get("upkeep_status", {})
        if upkeep_status.get("cost", 0) > 0:
            upkeep_text = "✅ Paid" if upkeep_status.get("is_current", False) else "❌ Overdue"
            embed.add_field(
                name="🔧 Upkeep Status",
                value=f"**Status:** {upkeep_text}\n**Cost:** {upkeep_status.get('cost', 0):,} revies/day",
                inline=True
            )
        
        embed.set_footer(text="💡 Buildings generate income every 30 minutes • Use 'r collect' to claim pending income")
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(BuildingCog(bot))