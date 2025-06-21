# src/cogs/utility.py
import disnake
from disnake.ext import commands
from datetime import datetime, timedelta
import platform
import psutil
import os

from src.database.models.player import Player
from src.database.models.esprit import Esprit  
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService, ratelimit
from src.utils.constants import ElementConstants, UIConstants
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager
from sqlmodel import select, func

logger = get_logger(__name__)

class UtilityCog(commands.Cog):
    """Utility commands for player profiles and bot information"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = datetime.utcnow()
    
    @commands.slash_command(
        name="profile",
        description="View your profile or another player's profile"
    )
    @ratelimit(uses=5, per_seconds=60, command_name="profile")
    async def profile(
        self, 
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User = commands.Param(default=None, description="User to view (leave empty for yourself)")
    ):
        """Display comprehensive player profile"""
        await inter.response.defer()
        
        # Get target user
        target = user or inter.author
        
        async with DatabaseService.get_session() as session:
            # Get player data
            stmt = select(Player).where(Player.discord_id == target.id)
            player: Player | None = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                embed = disnake.Embed(
                    title="❌ Profile Not Found",
                    description=f"{target.mention} hasn't started their journey yet!\n\nUse `/start` to begin.",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_response(embed=embed)
                return
            
            # Regenerate energy
            energy_gained = player.regenerate_energy()
            
            # Get collection stats
            if player.id is None:
                logger.error(f"Player {player.discord_id} has no ID")
                return
            collection_stats = await Esprit.get_player_collection_stats(session, player.id)
            
            # Get leader info if set
            leader_info = None
            leader_id = getattr(player, 'leader_esprit_stack_id', None)
            if leader_id:
                leader_stmt = select(Esprit, EspritBase).where(
                    Esprit.id == leader_id,
                    Esprit.esprit_base_id == EspritBase.id
                )
                result = (await session.execute(leader_stmt)).first()
                if result:
                    leader_stack, leader_base = result
                    leader_info = {
                        "name": leader_base.name,
                        "element": leader_stack.element,
                        "type": leader_base.type,
                        "tier": leader_stack.tier,
                        "awakening": leader_stack.awakening_level
                    }
            
            # Create profile embed
            embed = disnake.Embed(
                title=f"📋 {target.display_name}'s Profile",
                color=EmbedColors.DEFAULT
            )
            
            # Set thumbnail
            embed.set_thumbnail(url=target.display_avatar.url)
            
            # Basic Info Field
            basic_info = (
                f"**Level:** {player.level} ({player.experience:,}/{player.xp_for_next_level():,} XP)\n"
                f"**Energy:** {player.energy}/{player.max_energy} ⚡\n"
                f"**Space:** {player.current_space}/{player.max_space} 📦"
            )
            embed.add_field(name="📊 Basic Info", value=basic_info, inline=True)
            
            # Resources Field
            resources = (
                f"**Jijies:** {player.jijies:,} 🪙\n"
                f"**Erythl:** {player.erythl:,} 💎\n"
                f"**Daily Streak:** {player.daily_quest_streak} 🔥"
            )
            embed.add_field(name="💰 Resources", value=resources, inline=True)
            
            # Leader Field
            if leader_info:
                leader_display = (
                    f"**{leader_info['name']}**\n"
                    f"{ElementConstants.get_emoji(leader_info['element'])} {leader_info['element']} | "
                    f"{leader_info['type'].title()}\n"
                    f"Tier {leader_info['tier']} | ⭐ {leader_info['awakening']}"
                )
            else:
                leader_display = "*No leader set*\nUse `/leader` to set one!"
            embed.add_field(name="👑 Leader", value=leader_display, inline=True)
            
            # Collection Overview
            collection_text = (
                f"**Unique Esprits:** {collection_stats['unique_esprits']}\n"
                f"**Total Quantity:** {collection_stats['total_quantity']:,}\n"
                f"**Highest Tier:** {max(collection_stats['by_tier'].keys(), key=lambda x: int(x.split('_')[1]), default='None')}"
            )
            embed.add_field(name="📚 Collection", value=collection_text, inline=True)
            
            # Combat Power
            power_display = (
                f"**Total ATK:** {player.total_attack_power:,} ⚔️\n"
                f"**Total DEF:** {player.total_defense_power:,} 🛡️\n"
                f"**Total HP:** {player.total_hp:,} ❤️"
            )
            embed.add_field(name="💪 Combat Power", value=power_display, inline=True)
            
            # Progress Stats
            progress = (
                f"**Quests:** {player.total_quests_completed:,}\n"
                f"**Battles Won:** {player.battles_won:,}/{player.total_battles:,}\n"
                f"**Fusions:** {player.successful_fusions:,}/{player.total_fusions:,}"
            )
            embed.add_field(name="📈 Progress", value=progress, inline=True)
            
            # Footer with join date
            days_playing = (datetime.utcnow() - player.created_at).days
            embed.set_footer(text=f"Playing for {days_playing} days | ID: {player.id}")
            
            # Update DB with energy changes
            await session.commit()
            
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(
        name="botinfo",
        description="View information about Jiji bot"
    )
    @ratelimit(uses=3, per_seconds=60, command_name="botinfo")
    async def botinfo(self, inter: disnake.ApplicationCommandInteraction):
        """Display bot information and statistics"""
        await inter.response.defer()
        
        # Calculate uptime
        uptime = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        
        # Get bot stats
        total_guilds = len(self.bot.guilds)
        total_users = sum(guild.member_count for guild in self.bot.guilds if guild.member_count)
        
        # Get system stats
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # MB
        
        # Get database stats using raw SQL to avoid table name issues
        async with DatabaseService.get_session() as session:
            total_players = (await session.execute(select(func.count()).select_from(Player))).scalar() or 0
            
            # Use raw SQL for problematic table
            from sqlalchemy import text
            result = await session.execute(text("SELECT COUNT(*) FROM esprit_base"))
            total_esprits = result.scalar() or 0
            
            total_stacks = (await session.execute(select(func.count()).select_from(Esprit))).scalar() or 0
        
        # Create embed
        embed = disnake.Embed(
            title="🤖 Jiji Bot Information",
            description="*Meow* - Your friendly Esprit collection companion!",
            color=EmbedColors.DEFAULT
        )
        
        # Bot icon
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        
        # Technical Info
        tech_info = (
            f"**Version:** 1.0.0\n"
            f"**Library:** disnake {disnake.__version__}\n"
            f"**Python:** {platform.python_version()}\n"
        )
        embed.add_field(name="⚙️ Technical", value=tech_info, inline=True)
        
        # Statistics
        stats = (
            f"**Servers:** {total_guilds:,}\n"
            f"**Users:** {total_users:,}\n"
            f"**Memory:** {memory_usage:.1f} MB"
        )
        embed.add_field(name="📊 Statistics", value=stats, inline=True)
        
        # Uptime
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        embed.add_field(name="⏰ Uptime", value=uptime_str, inline=True)
        
        # Game Content
        content = (
            f"**Esprit Species:** {total_esprits}\n"
            f"**Total Stacks:** {total_stacks:,}\n"
            f"**Max Tier:** 18"
        )
        embed.add_field(name="🎮 Game Content", value=content, inline=True)
        
        # Links
        links = (
            "🔗 [Invite Bot](https://discord.com)\n"
            "📚 [Documentation](https://github.com)\n"
            "💬 [Support Server](https://discord.gg)\n"
        )
        embed.add_field(name="🔗 Links", value=links, inline=True)
        
        # Footer
        embed.set_footer(text="Made with ❤️ by Jiji Team")
        
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(
        name="stats",
        description="View detailed statistics about your journey"
    )
    @ratelimit(uses=5, per_seconds=60, command_name="stats")
    async def stats(
        self,
        inter: disnake.ApplicationCommandInteraction,
        category: str = commands.Param(
            default="overview",
            choices=["overview", "collection", "combat", "economy", "activity"],
            description="Statistics category to view"
        )
    ):
        """Display detailed player statistics"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                embed = disnake.Embed(
                    title="❌ No Profile Found",
                    description="You need to `/start` your journey first!",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_response(embed=embed)
                return
            
            # Create embed based on category
            embed = disnake.Embed(
                title=f"📊 {inter.author.display_name}'s Statistics",
                color=EmbedColors.DEFAULT
            )
            embed.set_thumbnail(url=inter.author.display_avatar.url)
            
            if category == "overview":
                await self._stats_overview(embed, player, session)
            elif category == "collection":
                await self._stats_collection(embed, player, session)
            elif category == "combat":
                await self._stats_combat(embed, player, session)
            elif category == "economy":
                await self._stats_economy(embed, player, session)
            elif category == "activity":
                await self._stats_activity(embed, player, session)
            
            # Footer
            embed.set_footer(text=f"Use /stats [category] to see different statistics")
            
        await inter.edit_original_response(embed=embed)
    
    async def _stats_overview(self, embed: disnake.Embed, player: Player, session):
        """Overview statistics"""
        embed.description = "📋 **General Overview**"
        
        # Get collection stats
        if player.id is None:
            return
        collection_stats = await Esprit.get_player_collection_stats(session, player.id)
        
        # Progress bar for level
        xp_progress = player.experience / player.xp_for_next_level()
        xp_bar = UIConstants.create_progress_bar(player.experience, player.xp_for_next_level())
        
        # General Stats
        general = (
            f"**Account Age:** {(datetime.utcnow() - player.created_at).days} days\n"
            f"**Level Progress:** {xp_bar} {xp_progress*100:.1f}%\n"
            f"**Total Playtime:** {player.total_quests_completed * 5} minutes (est.)\n"
        )
        embed.add_field(name="📅 General", value=general, inline=False)
        
        # Key Achievements
        achievements = (
            f"**Unique Esprits:** {collection_stats['unique_esprits']}/???\n"
            f"**Highest Tier Owned:** {max([int(k.split('_')[1]) for k in collection_stats['by_tier'].keys()] or [0])}\n"
            f"**Max Awakening:** ⭐ {max([v['stacks'] for v in collection_stats['awakened'].values()] or [0])}\n"
            f"**Win Rate:** {player.get_win_rate():.1f}%"
        )
        embed.add_field(name="🏆 Achievements", value=achievements, inline=True)
        
        # Activity Summary
        activity = (
            f"**Quests Today:** {0}\n"  # Would need to track this
            f"**Energy Used:** {(player.max_energy - player.energy)}\n"
            f"**Last Active:** <t:{int(player.last_active.timestamp())}:R>\n"
            f"**Daily Streak:** {player.daily_quest_streak} days"
        )
        embed.add_field(name="📈 Activity", value=activity, inline=True)
    
    async def _stats_collection(self, embed: disnake.Embed, player: Player, session):
        """Collection statistics"""
        embed.description = "📚 **Collection Statistics**"
        
        if player.id is None:
            return
        collection_stats = await Esprit.get_player_collection_stats(session, player.id)
        
        # By Element
        element_text = ""
        for element in ElementConstants.ELEMENTS:
            elem_data = collection_stats['by_element'].get(element.lower(), {'unique': 0, 'total': 0})
            if elem_data['unique'] > 0:
                element_text += f"{ElementConstants.get_emoji(element)} **{element}:** {elem_data['unique']} unique ({elem_data['total']} total)\n"
        
        embed.add_field(name="🌟 By Element", value=element_text or "*No Esprits yet*", inline=False)
        
        # By Tier
        tier_text = ""
        for tier in range(1, 19):
            tier_key = f"tier_{tier}"
            if tier_key in collection_stats['by_tier']:
                tier_data = collection_stats['by_tier'][tier_key]
                tier_text += f"**Tier {tier}:** {tier_data['unique']} unique ({tier_data['total']} total)\n"
        
        embed.add_field(name="📊 By Tier", value=tier_text[:1024] or "*No Esprits yet*", inline=True)
        
        # Awakening Stats
        awaken_text = ""
        for stars in range(1, 6):
            star_key = f"star_{stars}"
            if star_key in collection_stats['awakened']:
                data = collection_stats['awakened'][star_key]
                awaken_text += f"{'⭐' * stars} **{stars}-Star:** {data['stacks']} stacks\n"
        
        embed.add_field(name="✨ Awakening", value=awaken_text or "*No awakened Esprits*", inline=True)
    
    async def _stats_combat(self, embed: disnake.Embed, player: Player, session):
        """Combat statistics"""
        embed.description = "⚔️ **Combat Statistics**"
        
        # Power Stats
        total_power = player.total_attack_power + player.total_defense_power + (player.total_hp // 10)
        power_stats = (
            f"**Total Power:** {total_power:,}\n"
            f"**Attack:** {player.total_attack_power:,} ⚔️\n"
            f"**Defense:** {player.total_defense_power:,} 🛡️\n"
            f"**HP:** {player.total_hp:,} ❤️"
        )
        embed.add_field(name="💪 Power Rating", value=power_stats, inline=True)
        
        # Battle Record
        win_rate = player.get_win_rate()
        battle_stats = (
            f"**Total Battles:** {player.total_battles:,}\n"
            f"**Victories:** {player.battles_won:,}\n"
            f"**Defeats:** {player.total_battles - player.battles_won:,}\n"
            f"**Win Rate:** {win_rate:.1f}%"
        )
        embed.add_field(name="🏆 Battle Record", value=battle_stats, inline=True)
        
        # Leader Bonuses
        leader_bonuses = await player.get_leader_bonuses(session)
        if leader_bonuses:
            bonus_text = f"**Element:** {leader_bonuses['element']}\n"
            for key, value in leader_bonuses['element_bonuses'].items():
                if isinstance(value, (int, float)) and value != 0:
                    bonus_text += f"• {key.replace('_', ' ').title()}: +{value*100:.0f}%\n"
        else:
            bonus_text = "*No leader set*"
        
        embed.add_field(name="👑 Leader Bonuses", value=bonus_text, inline=False)
    
    async def _stats_economy(self, embed: disnake.Embed, player: Player, session):
        """Economy statistics"""
        embed.description = "💰 **Economy Statistics**"
        
        # Current Wealth
        wealth = (
            f"**Jijies:** {player.jijies:,} 🪙\n"
            f"**Erythl:** {player.erythl:,} 💎\n"
            f"**Total Echoes Opened:** {player.total_echoes_opened:,}\n"
        )
        embed.add_field(name="💵 Current Wealth", value=wealth, inline=True)
        
        # Fusion Economy
        fusion_success_rate = player.get_fusion_success_rate()
        fusion_stats = (
            f"**Total Fusions:** {player.total_fusions:,}\n"
            f"**Successful:** {player.successful_fusions:,}\n"
            f"**Failed:** {player.total_fusions - player.successful_fusions:,}\n"
            f"**Success Rate:** {fusion_success_rate:.1f}%"
        )
        embed.add_field(name="🧬 Fusion Economy", value=fusion_stats, inline=True)
        
        # Fragment Collection
        fragment_text = "**Element Fragments:**\n"
        if player.element_fragments:
            for element, count in player.element_fragments.items():
                if count > 0:
                    fragment_text += f"{ElementConstants.get_emoji(element.title())} {element.title()}: {count}\n"
        else:
            fragment_text += "*No fragments collected*"
        
        embed.add_field(name="🧩 Fragments", value=fragment_text, inline=False)
    
    async def _stats_activity(self, embed: disnake.Embed, player: Player, session):
        """Activity statistics"""
        embed.description = "📅 **Activity Statistics**"
        
        # Get collection stats for milestone check
        collection_stats = None
        if player.id:
            collection_stats = await Esprit.get_player_collection_stats(session, player.id)
        
        # Time-based Stats
        days_active = (datetime.utcnow() - player.created_at).days
        avg_quests_per_day = player.total_quests_completed / max(days_active, 1)
        
        time_stats = (
            f"**Days Active:** {days_active}\n"
            f"**Daily Login Streak:** {player.daily_quest_streak} 🔥\n"
            f"**Avg Quests/Day:** {avg_quests_per_day:.1f}\n"
            f"**Last Quest:** <t:{int(player.last_quest.timestamp())}:R>" if player.last_quest else "Never"
        )
        embed.add_field(name="⏰ Time Stats", value=time_stats, inline=True)
        
        # Quest Progress
        quest_stats = (
            f"**Total Quests:** {player.total_quests_completed:,}\n"
            f"**Current Area:** {player.current_area_id}\n"
            f"**Highest Area:** {player.highest_area_unlocked}\n"
            f"**Energy Spent:** {player.total_quests_completed * 7:,} ⚡"
        )
        embed.add_field(name="🗺️ Quest Progress", value=quest_stats, inline=True)
        
        # Milestones
        milestones = "**Recent Milestones:**\n"
        if player.level >= 100:
            milestones += "🏆 Reached Level 100!\n"
        if player.total_quests_completed >= 1000:
            milestones += "🎯 1000 Quests Completed!\n"
        if collection_stats and collection_stats['unique_esprits'] >= 50:
            milestones += "📚 50+ Unique Esprits!\n"
        if player.successful_fusions >= 100:
            milestones += "🧬 100 Successful Fusions!\n"
        
        if milestones == "**Recent Milestones:**\n":
            milestones += "*Keep playing to unlock milestones!*"
        
        embed.add_field(name="🎖️ Milestones", value=milestones, inline=False)

def setup(bot: commands.Bot):
    bot.add_cog(UtilityCog(bot))
    logger.info("✅ UtilityCog loaded successfully")
