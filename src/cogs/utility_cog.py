# src/cogs/utility.py
from typing import Optional
import disnake
from disnake.ext import commands
from datetime import datetime
import platform
import psutil

from src.utils.config_manager import ConfigManager
from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select, func

class HelpDropdown(disnake.ui.Select):
    """Dropdown for help categories"""
    
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="Getting Started",
                description="New? Start here!",
                emoji="🌟",
                value="start"
            ),
            disnake.SelectOption(
                label="Esprits & Collection",
                description="Learn about your magical companions",
                emoji="✨",
                value="esprits"
            ),
            disnake.SelectOption(
                label="Questing & Resources",
                description="Energy, stamina, and adventures",
                emoji="⚡",
                value="resources"
            ),
            disnake.SelectOption(
                label="Fusion & Awakening",
                description="Making your Esprits stronger",
                emoji="🔮",
                value="fusion"
            ),
            disnake.SelectOption(
                label="Daily Activities",
                description="What to do each day",
                emoji="📅",
                value="daily"
            ),
        ]
        
        super().__init__(
            placeholder="Choose a topic!",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, inter: disnake.MessageInteraction):
        topic = self.values[0]
        
        embeds = {
            "start": disnake.Embed(
                title="🌟 Getting Started",
                description=(
                    "Welcome! Here's how to begin your journey:\n\n"
                    "**First Steps:**\n"
                    "• `/start` - Create your account & get starter gifts!\n"
                    "• `/quest` - Explore areas and find Esprits\n"
                    "• `/profile` - Check your stats anytime\n\n"
                    "**Your Starter Kit:**\n"
                    "• 5,000 Jijies (main currency)\n"
                    "• 10 Erythl (special currency)\n"
                    "• 2 Starter Esprits\n"
                    "• 1 Echo to open later\n\n"
                    "Energy regenerates over time, so pace yourself!"
                ),
                color=EmbedColors.DEFAULT
            ),
            "esprits": disnake.Embed(
                title="✨ Esprits & Collection",
                description=(
                    "Esprits are your magical companions!\n\n"
                    "**Elements:** Each has unique strengths\n"
                    "🔥 **Inferno** - High attack power\n"
                    "🌿 **Verdant** - Balanced defense\n"
                    "🌊 **Abyssal** - High HP pool\n"
                    "🌪️ **Tempest** - Speed focus\n"
                    "🌑 **Umbral** - Glass cannon\n"
                    "✨ **Radiant** - Fusion helper\n\n"
                    "**Tiers:** 1-18, higher = stronger\n"
                    "**Awakening:** Use duplicates for stars (up to 5★)\n"
                    "**Leaders:** Set one for passive bonuses!"
                ),
                color=EmbedColors.DEFAULT
            ),
            "resources": disnake.Embed(
                title="⚡ Questing & Resources",
                description=(
                    "Managing your resources is key!\n\n"
                    "**Energy** (⚡)\n"
                    "• Used for questing\n"
                    "• Regenerates 1 per 6 minutes\n"
                    "• Refills on level up\n\n"
                    "**Stamina** (💪)\n"
                    "• For PvP and bosses (coming soon)\n"
                    "• Regenerates 1 per 10 minutes\n\n"
                    "**Currencies:**\n"
                    "• **Jijies** - Main currency for everything\n"
                    "• **Erythl** - Special items and resets\n"
                    "• **Fragments** - Craft specific Esprits"
                ),
                color=EmbedColors.DEFAULT
            ),
            "fusion": disnake.Embed(
                title="🔮 Fusion & Awakening",
                description=(
                    "Make your Esprits stronger!\n\n"
                    "**Fusion Rules:**\n"
                    "• Need 2 Esprits of same tier\n"
                    "• Success = tier up!\n"
                    "• Failure = get fragments\n"
                    "• Same element = better odds\n\n"
                    "**Awakening Power:**\n"
                    "• Each star = +20% stats\n"
                    "• Costs copies: 1★=1, 2★=2, etc\n"
                    "• Max 5 stars total\n\n"
                    "Tip: Save fragments to guarantee fusions!"
                ),
                color=EmbedColors.DEFAULT
            ),
            "daily": disnake.Embed(
                title="📅 Daily Activities",
                description=(
                    "Make the most of each day!\n\n"
                    "**Daily Checklist:**\n"
                    "• Claim daily echo (free Esprit!)\n"
                    "• Use your energy on quests\n"
                    "• Check shop for deals\n"
                    "• Fuse duplicate Esprits\n\n"
                    "**Weekly Goals:**\n"
                    "• Complete new areas\n"
                    "• Reach fusion milestones\n"
                    "• Save for big purchases\n\n"
                    "Remember: Progress is a marathon, not a sprint!"
                ),
                color=EmbedColors.DEFAULT
            )
        }
        
        embed = embeds.get(topic, embeds["start"])
        await inter.response.edit_message(embed=embed)


class TutorialDropdown(disnake.ui.Select):
    """Dropdown for tutorial sections"""
    
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="Basic Commands",
                description="Essential commands to know",
                emoji="📝",
                value="commands"
            ),
            disnake.SelectOption(
                label="Your First Quest",
                description="Step-by-step quest guide",
                emoji="🗺️",
                value="quest_guide"
            ),
            disnake.SelectOption(
                label="Understanding Stats",
                description="What do all these numbers mean?",
                emoji="📊",
                value="stats"
            ),
            disnake.SelectOption(
                label="Fusion Strategy",
                description="When and how to fuse",
                emoji="🎯",
                value="strategy"
            ),
            disnake.SelectOption(
                label="Common Mistakes",
                description="Things to avoid!",
                emoji="⚠️",
                value="mistakes"
            ),
        ]
        
        super().__init__(
            placeholder="Pick a tutorial section!",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, inter: disnake.MessageInteraction):
        section = self.values[0]
        
        tutorials = {
            "commands": disnake.Embed(
                title="📝 Basic Commands",
                description=(
                    "Here's what you'll use most:\n\n"
                    "`/quest` - Your main activity! Costs energy\n"
                    "`/profile` - See your stats & resources\n"
                    "`/collection` - Browse your Esprits\n"
                    "`/fusion` - Combine for stronger Esprits\n"
                    "`/leader` - Set your leader for bonuses\n"
                    "`/echo` - Open mystery boxes\n\n"
                    "Pro tip: Start with quests until you have duplicates to fuse!"
                ),
                color=EmbedColors.INFO
            ),
            "quest_guide": disnake.Embed(
                title="🗺️ Your First Quest",
                description=(
                    "Let's do a quest together!\n\n"
                    "1. Use `/quest` command\n"
                    "2. Pick an area (start with Area 1)\n"
                    "3. Spend energy to complete it\n"
                    "4. Get XP, Jijies, maybe an Esprit!\n\n"
                    "**What happens:**\n"
                    "• Instant completion (no waiting)\n"
                    "• 10% chance to catch Esprits\n"
                    "• Bosses give better rewards\n\n"
                    "Complete all quests in an area to unlock the next!"
                ),
                color=EmbedColors.INFO
            ),
            "stats": disnake.Embed(
                title="📊 Understanding Stats",
                description=(
                    "Numbers everywhere! Here's what matters:\n\n"
                    "**Esprit Stats:**\n"
                    "• **ATK** - Damage power\n"
                    "• **DEF** - Damage reduction\n"
                    "• **HP** - Health points\n\n"
                    "**Your Stats:**\n"
                    "• **Level** - Unlocks new areas\n"
                    "• **Total Power** - Sum of all Esprits\n"
                    "• **Energy/Stamina** - Action points\n\n"
                    "Higher tier = much better stats\n"
                    "Awakening = +20% per star!"
                ),
                color=EmbedColors.INFO
            ),
            "strategy": disnake.Embed(
                title="🎯 Fusion Strategy",
                description=(
                    "Fusion is risky but rewarding!\n\n"
                    "**When to fuse:**\n"
                    "• Have duplicate low tiers\n"
                    "• Need specific higher tiers\n"
                    "• Have fragments for safety\n\n"
                    "**Smart tips:**\n"
                    "• Same element = better odds\n"
                    "• Tier 1-3 have good rates\n"
                    "• Save high tiers for awakening\n"
                    "• 10 fragments = guaranteed success\n\n"
                    "Failed fusions give fragments, so it's never a total loss!"
                ),
                color=EmbedColors.INFO
            ),
            "mistakes": disnake.Embed(
                title="⚠️ Common Mistakes",
                description=(
                    "Learn from others! Avoid these:\n\n"
                    "**Don't:**\n"
                    "• Fuse your only copy of high tiers\n"
                    "• Ignore element bonuses\n"
                    "• Waste Erythl on resets early\n"
                    "• Forget to set a leader\n\n"
                    "**Do:**\n"
                    "• Keep favorites for awakening\n"
                    "• Match leader to playstyle\n"
                    "• Save fragments for important fusions\n"
                    "• Enjoy the journey!\n\n"
                    "Remember: There's no rush!"
                ),
                color=EmbedColors.INFO
            )
        }
        
        embed = tutorials.get(section, tutorials["commands"])
        await inter.response.edit_message(embed=embed)


class HelpView(disnake.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.add_item(HelpDropdown())
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("This isn't your menu! Use `/help` for your own.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, disnake.ui.Select):
                item.disabled = True


class TutorialView(disnake.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.add_item(TutorialDropdown())
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("Get your own tutorial with `/tutorial`!", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, disnake.ui.Select):
                item.disabled = True


class Utility(commands.Cog):
    """Helpful information commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.utcnow()
    
    @commands.slash_command(name="botinfo", description="Learn about Jiji!")
    async def botinfo(self, inter: disnake.ApplicationCommandInteraction):
        """Show bot information"""
        await inter.response.defer()
        
        # Calculate uptime
        uptime = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Get bot stats
        total_guilds = len(self.bot.guilds)
        total_users = sum(g.member_count for g in self.bot.guilds if g.member_count)
        
        # System info
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        embed = disnake.Embed(
            title="✨ About Jiji",
            description=(
                "Mreow! I'm Jiji, your friendly Esprit collection companion!\n\n"
                "I help trainers collect magical creatures called Esprits, "
                "fuse them into stronger forms, and build the ultimate team!\n\n"
                "**Created by:** Jiji Squad\n"
            ),
            color=EmbedColors.DEFAULT
        )
        
        embed.add_field(
            name="📊 Stats",
            value=(
                f"**Servers:** {total_guilds}\n"
                f"**Trainers:** {total_users:,}\n"
                f"**Uptime:** {hours}h {minutes}m\n"
                f"**Ping:** {round(self.bot.latency * 1000)}ms"
            ),
            inline=True
        )
        
        embed.add_field(
            name="🖥️ System",
            value=(
                f"**CPU:** {cpu_usage}%\n"
                f"**Memory:** {memory.percent}%\n"
                f"**Python:** {platform.python_version()}\n"
                f"**Disnake:** {disnake.__version__}"
            ),
            inline=True
        )
        
        embed.add_field(
            name="🔗 Links",
            value=(
                "[Invite Me](https://discord.com) | "
                "[Support](https://discord.com) | "
                "[Vote](https://top.gg)"
            ),
            inline=False
        )
        
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Thank you for playing!")
        
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="stats", description="See game statistics")
    async def stats(self, inter: disnake.ApplicationCommandInteraction):
        """Show game statistics"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get total players
                total_players = await session.scalar(
                    select(func.count()).select_from(Player)
                )
                
                # Get total esprits
                total_esprits = await session.scalar(
                    select(func.sum(Esprit.quantity))
                ) or 0
                
                # Get unique esprit types owned
                unique_owned = await session.scalar(
                    select(func.count(func.distinct(Esprit.esprit_base_id)))
                ) or 0
                
                # Get total available esprit types
                total_available = await session.scalar(
                    select(func.count()).select_from(EspritBase)
                )
                
                # Get highest level player
                highest_player_result = await session.execute(
                    select(Player.level).order_by(Player.level.desc()).limit(1) # type: ignore
                )
                highest_player = highest_player_result.scalar() or 0
                
                # Get total fusions
                total_fusions = await session.scalar(
                    select(func.sum(Player.total_fusions))
                ) or 0
                
                # Get total quests
                total_quests = await session.scalar(
                    select(func.sum(Player.total_quests_completed))
                ) or 0
            
            embed = disnake.Embed(
                title="📈 Game Statistics",
                description="Here's what's happening in the world of Jiji!",
                color=EmbedColors.INFO
            )
            
            # Calculate collection rate safely
            collection_rate = 0.0
            if total_available and total_available > 0:
                collection_rate = (unique_owned / total_available * 100)
            
            embed.add_field(
                name="👥 Trainers",
                value=(
                    f"**Total:** {total_players:,}\n"
                    f"**Highest Level:** {highest_player}\n"
                    f"**This Week:** Coming Soon"
                ),
                inline=True
            )
            
            embed.add_field(
                name="✨ Esprits",
                value=(
                    f"**Total Caught:** {total_esprits:,}\n"
                    f"**Unique Owned:** {unique_owned}/{total_available}\n"
                    f"**Collection Rate:** {collection_rate:.1f}%"
                ),
                inline=True
            )
            
            embed.add_field(
                name="🎮 Activity",
                value=(
                    f"**Quests Done:** {total_quests:,}\n"
                    f"**Fusions Tried:** {total_fusions:,}\n"
                    f"**Daily Active:** Coming Soon"
                ),
                inline=True
            )
            
            embed.set_footer(text="Mreow! Thanks for being part of our community!")
            
        except Exception as e:
            embed = disnake.Embed(
                title="Stats Unavailable",
                description="Couldn't fetch stats right now, try again later!",
                color=EmbedColors.ERROR
            )
        
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="help", description="Learn how to play!")
    async def help(self, inter: disnake.ApplicationCommandInteraction):
        """Interactive help menu"""
        await inter.response.defer()
        
        embed = disnake.Embed(
            title="💫 Jiji Help Center",
            description=(
                "Hello! Pick a topic from the dropdown below!\n\n"
                "New to the game? Start with **Getting Started**\n"
                "Need specific help? Browse the categories\n\n"
                "Remember: There's no wrong way to play! Explore at your own pace."
            ),
            color=EmbedColors.DEFAULT
        )
        
        embed.set_footer(text="Select a topic below!")
        
        view = HelpView(inter.author.id)
        await inter.edit_original_response(embed=embed, view=view)
    
    @commands.slash_command(name="tutorial", description="Interactive game tutorial")
    async def tutorial(self, inter: disnake.ApplicationCommandInteraction):
        """Interactive tutorial"""
        await inter.response.defer()
        
        # Check if registered
        async with DatabaseService.get_session() as session:
            stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                embed = disnake.Embed(
                    title="Not Registered!",
                    description="You need to `/start` first before the tutorial!",
                    color=EmbedColors.WARNING
                )
                await inter.edit_original_response(embed=embed)
                return
        
        embed = disnake.Embed(
            title="📚 Interactive Tutorial",
            description=(
                f"Welcome back, {inter.author.mention}!\n\n"
                "Pick what you'd like to learn about!\n"
                "Each section has quick, helpful tips.\n\n"
                "Don't worry about memorizing everything - "
                "you can always come back here."
            ),
            color=EmbedColors.INFO
        )
        
        embed.set_footer(text="Choose a section below!")
        
        view = TutorialView(inter.author.id)
        await inter.edit_original_response(embed=embed, view=view)
    
    @commands.slash_command(name="invite", description="Invite Jiji to your server!")
    async def invite(self, inter: disnake.ApplicationCommandInteraction):
        """Show invite link"""
        await inter.response.defer()
        
        # Generate invite link
        invite_url = disnake.utils.oauth_url(
            self.bot.user.id,
            permissions=disnake.Permissions(
                send_messages=True,
                embed_links=True,
                use_slash_commands=True,
                read_messages=True,
                read_message_history=True
            )
        )
        
        embed = disnake.Embed(
            title="💌 Invite Jiji!",
            description=(
                "Want to share the fun with friends?\n\n"
                f"[**Click here to invite me!**]({invite_url})\n\n"
                "Thank you for spreading the word!"
            ),
            color=EmbedColors.SUCCESS
        )
        
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        await inter.edit_original_response(embed=embed)

    @commands.slash_command(name="profile", description="View your adventure profile and stats")
    async def profile(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: Optional[disnake.User] = commands.Param(
            default=None,
            description="User to view (defaults to yourself)"
        )
    ):
        """Show player profile with all stats"""
        await inter.response.defer()
        
        # Default to self if no user specified
        target_user = user or inter.author
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == target_user.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Profile Not Found",
                        description=f"{target_user.mention} hasn't started their journey yet!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Regenerate resources for accurate display
                player.regenerate_energy()
                player.regenerate_stamina()
                
                # Get total power
                power_stats = await player.recalculate_total_power(session)
                
                # Get leader info if set
                leader_info = None
                if player.leader_esprit_stack_id:
                    from src.database.models import Esprit, EspritBase
                    stmt = select(Esprit, EspritBase).where(
                        Esprit.id == player.leader_esprit_stack_id, # type: ignore
                        Esprit.esprit_base_id == EspritBase.id # type: ignore
                    )
                    result = (await session.execute(stmt)).first()
                    if result:
                        leader_stack, leader_base = result
                        leader_info = (leader_stack, leader_base)
                
                # Create profile embed
                embed = disnake.Embed(
                    title=f"{target_user.display_name}'s Profile",
                    color=EmbedColors.DEFAULT
                )
                
                # Basic info
                embed.add_field(
                    name="📊 Basic Info",
                    value=(
                        f"**Level:** {player.level}\n"
                        f"**XP:** {player.experience:,}/{player.xp_for_next_level():,}\n"
                        f"**Joined:** {self._format_date(player.created_at)}"
                    ),
                    inline=True
                )
                
                # Resources
                embed.add_field(
                    name="💰 Resources",
                    value=(
                        f"**Jijies:** {player.jijies:,}\n"
                        f"**Erythl:** {player.erythl}\n"
                        f"**Energy:** {player.energy}/{player.max_energy} ⚡"
                    ),
                    inline=True
                )
                
                # Combat Power
                total_power = power_stats["total"]
                embed.add_field(
                    name="⚔️ Combat Power",
                    value=(
                        f"**Total:** {total_power:,}\n"
                        f"**ATK:** {power_stats['atk']:,}\n"
                        f"**DEF:** {power_stats['def']:,}"
                    ),
                    inline=True
                )
                
                # Leader Esprit
                if leader_info:
                    leader_stack, leader_base = leader_info
                    stars = "⭐" * leader_stack.awakening_level if leader_stack.awakening_level > 0 else ""
                    embed.add_field(
                        name="👑 Leader Esprit",
                        value=(
                            f"{leader_base.get_element_emoji()} **{leader_base.name}** {stars}\n"
                            f"Tier {leader_base.base_tier} | {leader_stack.quantity:,} owned"
                        ),
                        inline=False
                    )
                
                # Progress Stats
                embed.add_field(
                    name="📈 Progress",
                    value=(
                        f"**Quests:** {player.total_quests_completed:,}\n"
                        f"**Fusions:** {player.successful_fusions}/{player.total_fusions}\n"
                        f"**Echoes:** {player.total_echoes_opened:,}"
                    ),
                    inline=True
                )
                
                # Collection Stats
                from src.database.models import Esprit
                unique_stmt = select(func.count(Esprit.id)).where(Esprit.owner_id == player.id) # type: ignore
                unique_count = (await session.execute(unique_stmt)).scalar() or 0
                
                embed.add_field(
                    name="✨ Collection",
                    value=(
                        f"**Unique:** {unique_count}\n"
                        f"**Awakenings:** {player.total_awakenings}\n"
                        f"**Favorite:** {player.favorite_element or 'None'}"
                    ),
                    inline=True
                )
                
                # Activity
                embed.add_field(
                    name="🕐 Activity",
                    value=(
                        f"**Last Quest:** {self._format_time_ago(player.last_quest)}\n"
                        f"**Last Active:** {self._format_time_ago(player.last_active)}\n"
                        f"**Daily Streak:** {player.daily_quest_streak}"
                    ),
                    inline=True
                )
                
                # Set thumbnail
                embed.set_thumbnail(url=target_user.display_avatar.url)
                
                # Footer with friend code if they have one
                footer_text = f"ID: {player.id}"
                if player.friend_code:
                    footer_text += f" | Friend Code: {player.friend_code}"
                embed.set_footer(text=footer_text)
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Profile Error",
                description="Couldn't load profile data!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="index", description="View your items and fragments")
    async def index(self, inter: disnake.ApplicationCommandInteraction):
        """Show inventory index with items and fragments"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` your journey first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                embed = disnake.Embed(
                    title="📦 Your Index",
                    description="All your items and fragments",
                    color=EmbedColors.DEFAULT
                )
                
                # Items section
                if player.inventory:
                    items_text = ""
                    items_config = ConfigManager.get("items") or {}
                    
                    for item_id, quantity in sorted(player.inventory.items()):
                        if quantity > 0:
                            item_data = items_config.get("items", {}).get(item_id, {})
                            item_name = item_data.get("name", item_id.replace("_", " ").title())
                            item_emoji = item_data.get("icon", "📦")
                            items_text += f"{item_emoji} **{item_name}** x{quantity}\n"
                    
                    if items_text:
                        embed.add_field(
                            name="🎒 Items",
                            value=items_text[:1024],  # Discord limit
                            inline=False
                        )
                else:
                    embed.add_field(
                        name="🎒 Items",
                        value="*No items yet!*",
                        inline=False
                    )
                
                # Tier Fragments
                if player.tier_fragments:
                    tier_text = ""
                    for tier, count in sorted(player.tier_fragments.items(), key=lambda x: int(x[0])):
                        if count > 0:
                            from src.utils.game_constants import Tiers
                            tier_data = Tiers.get(int(tier))
                            tier_name = tier_data.name if tier_data else f"Tier {tier}"
                            tier_text += f"**{tier_name}** Fragments: {count}\n"
                    
                    if tier_text:
                        embed.add_field(
                            name="🧩 Tier Fragments",
                            value=tier_text[:1024],
                            inline=True
                        )
                else:
                    embed.add_field(
                        name="🧩 Tier Fragments",
                        value="*No tier fragments yet!*",
                        inline=True
                    )
                
                # Element Fragments
                if player.element_fragments:
                    element_text = ""
                    from src.utils.game_constants import Elements
                    
                    for element, count in sorted(player.element_fragments.items()):
                        if count > 0:
                            elem = Elements.from_string(element)
                            if elem:
                                element_text += f"{elem.emoji} **{elem.display_name}**: {count}\n"
                            else:
                                element_text += f"**{element.title()}**: {count}\n"
                    
                    if element_text:
                        embed.add_field(
                            name="🔮 Element Fragments",
                            value=element_text[:1024],
                            inline=True
                        )
                else:
                    embed.add_field(
                        name="🔮 Element Fragments",
                        value="*No element fragments yet!*",
                        inline=True
                    )
                
                # Summary stats
                total_items = sum(player.inventory.values()) if player.inventory else 0
                total_tier_frags = sum(player.tier_fragments.values()) if player.tier_fragments else 0
                total_elem_frags = sum(player.element_fragments.values()) if player.element_fragments else 0
                
                embed.set_footer(
                    text=f"Total: {total_items} items | {total_tier_frags} tier frags | {total_elem_frags} element frags"
                )
                
                await inter.edit_original_response(embed=embed)
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Index Error",
                description="Couldn't load your inventory!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    def _format_date(self, date: datetime) -> str:
        """Format date nicely"""
        return date.strftime("%B %d, %Y")

    def _format_time_ago(self, dt: Optional[datetime]) -> str:
        """Return a human-readable 'time ago' string from a datetime."""
        if not dt:
            return "Never"
        now = datetime.utcnow()
        diff = now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"

def setup(bot):
    bot.add_cog(Utility(bot))