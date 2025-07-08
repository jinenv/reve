# src/cogs/system_tasks_cog.py
import disnake
from disnake.ext import commands, tasks
import logging
from datetime import datetime, time
from typing import Dict, Any

# ✅ ALL IMPORTS ARE CORRECT - USING src.* PATTERN
from src.services.resource_service import ResourceService
from src.services.building_service import BuildingService
from src.services.cache_service import CacheService
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

# NO OTHER IMPORTS - especially no bare 'utils' imports!

logger = get_logger(__name__)

class SystemTasksCog(commands.Cog):
    """Background task automation for REVE - ALL LOGIC IS IN SERVICES"""
    
    def __init__(self, bot):
        self.bot = bot
        self.task_stats = {
            "energy_regen": {"runs": 0, "errors": 0, "last_run": None},
            "stamina_regen": {"runs": 0, "errors": 0, "last_run": None},
            "building_income": {"runs": 0, "errors": 0, "last_run": None},
            "cache_cleanup": {"runs": 0, "errors": 0, "last_run": None},
            "daily_reset": {"runs": 0, "errors": 0, "last_run": None}
        }
        logger.info("SystemTasksCog initialized - background tasks ready")

    async def cog_load(self):
        """Start background tasks when cog loads"""
        background_config = ConfigManager.get("background_tasks") or {}
        
        # Start energy regeneration if enabled
        if background_config.get("energy_regeneration", {}).get("enabled", True):
            self.energy_regeneration_task.start()
            logger.info("Started energy regeneration background task")
        
        # Start stamina regeneration if enabled
        if background_config.get("stamina_regeneration", {}).get("enabled", True):
            self.stamina_regeneration_task.start()
            logger.info("Started stamina regeneration background task")
        
        # Start building income if enabled
        if background_config.get("building_income", {}).get("enabled", True):
            self.building_income_task.start()
            logger.info("Started building income background task")
        
        # Start cache cleanup if enabled
        if background_config.get("cache_cleanup", {}).get("enabled", True):
            self.cache_cleanup_task.start()
            logger.info("Started cache cleanup background task")
        
        # Start daily reset if enabled
        if background_config.get("daily_reset", {}).get("enabled", True):
            self.daily_reset_task.start()
            logger.info("Started daily reset background task")

    async def cog_unload(self):
        """Stop background tasks when cog unloads"""
        self.energy_regeneration_task.cancel()
        self.stamina_regeneration_task.cancel()
        self.building_income_task.cancel()
        self.cache_cleanup_task.cancel()
        self.daily_reset_task.cancel()
        logger.info("Stopped all background tasks")

    @tasks.loop(minutes=1)
    async def energy_regeneration_task(self):
        """Energy regeneration every 1 minute - LOGIC IN ResourceService"""
        task_name = "energy_regen"
        try:
            start_time = datetime.utcnow()
            
            # ALL BUSINESS LOGIC IS IN THE SERVICE
            result = await ResourceService.regenerate_energy_for_all()
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            if result.success and result.data:
                stats = result.data
                self.task_stats[task_name]["runs"] += 1
                self.task_stats[task_name]["last_run"] = start_time
                
                # Only log if significant activity
                energy_granted = stats.get('total_energy_granted', 0)
                if energy_granted > 0:
                    logger.info(
                        f"⚡ Energy regeneration: "
                        f"{stats.get('players_processed', 0)} players, "
                        f"{energy_granted} energy granted, "
                        f"{stats.get('errors', 0)} errors ({execution_time:.2f}s)"
                    )
            else:
                raise Exception(result.error or "Unknown error in energy regeneration")
                
        except Exception as e:
            self.task_stats[task_name]["errors"] += 1
            logger.error(f"Energy regeneration task failed: {e}")
            
            # Alert on consecutive failures
            background_config = ConfigManager.get("background_tasks") or {}
            if (background_config.get("performance_monitoring", {}).get("alert_on_errors", True) and
                self.task_stats[task_name]["errors"] >= background_config.get("performance_monitoring", {}).get("max_consecutive_failures", 3)):
                logger.critical(f"⚠️ Energy regeneration has failed {self.task_stats[task_name]['errors']} times consecutively!")

    @tasks.loop(minutes=1)
    async def stamina_regeneration_task(self):
        """Stamina regeneration every 1 minute - LOGIC IN ResourceService"""
        task_name = "stamina_regen"
        try:
            start_time = datetime.utcnow()
            
            # ALL BUSINESS LOGIC IS IN THE SERVICE
            result = await ResourceService.regenerate_stamina_for_all()
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            if result.success and result.data:
                stats = result.data
                self.task_stats[task_name]["runs"] += 1
                self.task_stats[task_name]["last_run"] = start_time
                
                # Only log if significant activity
                stamina_granted = stats.get('total_stamina_granted', 0)
                if stamina_granted > 0:
                    logger.info(
                        f"💪 Stamina regeneration: "
                        f"{stats.get('players_processed', 0)} players, "
                        f"{stamina_granted} stamina granted, "
                        f"{stats.get('errors', 0)} errors ({execution_time:.2f}s)"
                    )
            else:
                raise Exception(result.error or "Unknown error in stamina regeneration")
                
        except Exception as e:
            self.task_stats[task_name]["errors"] += 1
            logger.error(f"Stamina regeneration task failed: {e}")

    @tasks.loop(minutes=30)
    async def building_income_task(self):
        """Building passive income every 30 minutes - LOGIC IN BuildingService"""
        task_name = "building_income"
        try:
            start_time = datetime.utcnow()
            
            # ALL BUSINESS LOGIC IS IN THE SERVICE
            result = await BuildingService.process_passive_income_for_all()
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            if result.success and result.data:
                stats = result.data
                self.task_stats[task_name]["runs"] += 1
                self.task_stats[task_name]["last_run"] = start_time
                
                logger.info(
                    f"🏗️ Building income: "
                    f"{stats.get('players_processed', 0)} players, "
                    f"{stats.get('total_income_granted', 0):,} revies granted, "
                    f"{stats.get('total_ticks_processed', 0)} ticks, "
                    f"{stats.get('errors', 0)} errors ({execution_time:.2f}s)"
                )
            else:
                raise Exception(result.error or "Unknown error in building income")
                
        except Exception as e:
            self.task_stats[task_name]["errors"] += 1
            logger.error(f"Building income task failed: {e}")

    @tasks.loop(hours=6)
    async def cache_cleanup_task(self):
        """Cache cleanup every 6 hours - LOGIC IN CacheService"""
        task_name = "cache_cleanup"
        try:
            start_time = datetime.utcnow()
            
            # ALL BUSINESS LOGIC IS IN THE SERVICE
            result = await CacheService.cleanup_expired_cache()
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            if result.success:
                self.task_stats[task_name]["runs"] += 1
                self.task_stats[task_name]["last_run"] = start_time
                
                logger.info(f"🧹 Cache cleanup completed in {execution_time:.2f}s")
            else:
                raise Exception(result.error or "Unknown error in cache cleanup")
                
        except Exception as e:
            self.task_stats[task_name]["errors"] += 1
            logger.error(f"Cache cleanup task failed: {e}")

    @tasks.loop(time=time(0, 0))  # Daily at midnight UTC
    async def daily_reset_task(self):
        """Daily reset tasks at midnight UTC - LOGIC IN SERVICES"""
        task_name = "daily_reset"
        try:
            start_time = datetime.utcnow()
            
            # This would call various services for daily resets
            # For now, just log that daily reset occurred
            # Future: RewardService.process_daily_rewards(), etc.
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            self.task_stats[task_name]["runs"] += 1
            self.task_stats[task_name]["last_run"] = start_time
            
            logger.info(f"🌅 Daily reset completed in {execution_time:.2f}s")
                
        except Exception as e:
            self.task_stats[task_name]["errors"] += 1
            logger.error(f"Daily reset task failed: {e}")

    @energy_regeneration_task.before_loop
    async def before_energy_regeneration(self):
        """Wait for bot to be ready before starting energy regeneration"""
        await self.bot.wait_until_ready()

    @stamina_regeneration_task.before_loop
    async def before_stamina_regeneration(self):
        """Wait for bot to be ready before starting stamina regeneration"""
        await self.bot.wait_until_ready()

    @building_income_task.before_loop
    async def before_building_income(self):
        """Wait for bot to be ready before starting building income"""
        await self.bot.wait_until_ready()

    @cache_cleanup_task.before_loop
    async def before_cache_cleanup(self):
        """Wait for bot to be ready before starting cache cleanup"""
        await self.bot.wait_until_ready()

    @daily_reset_task.before_loop
    async def before_daily_reset(self):
        """Wait for bot to be ready before starting daily reset"""
        await self.bot.wait_until_ready()

    # =====================================
    # PRETTY ADMIN COMMANDS (NO BUSINESS LOGIC)
    # =====================================
    
    @commands.group(name="system", invoke_without_command=True)
    async def system_admin(self, ctx):
        """System administration commands"""
        if ctx.invoked_subcommand is None:
            embed = disnake.Embed(
                title="🔧 System Administration",
                description="Monitor and manage automated background tasks",
                color=0x2c2d31
            )
            embed.add_field(
                name="📊 Commands",
                value="`r system status` - View all background task status\n`r system trigger <task>` - Manually run a specific task",
                inline=False
            )
            embed.add_field(
                name="⚡ Available Tasks",
                value="`energy` • `stamina` • `income` • `cache`",
                inline=False
            )
            embed.set_footer(text="Background tasks run automatically 24/7")
            await ctx.send(embed=embed)

    @system_admin.command(name="status")
    async def task_status(self, ctx):
        """Show status of all background tasks - PRETTY VERSION"""
        embed = disnake.Embed(
            title="🔧 Background Task Status",
            description="Automated systems running 24/7",
            color=0x2c2d31
        )
        
        # PRETTY TASK NAMES WITH EMOJIS
        pretty_names = {
            "energy_regen": "⚡ Energy Regeneration",
            "stamina_regen": "💪 Stamina Regeneration", 
            "building_income": "🏗️ Building Income",
            "cache_cleanup": "🧹 Cache Cleanup",
            "daily_reset": "🌅 Daily Reset"
        }
        
        # AUTOMATION STATUS
        automation_status = []
        
        for task_name, stats in self.task_stats.items():
            if stats["runs"] > 0:
                status = "🟢 Active"
                if stats["errors"] > 0:
                    status += f" (⚠️ {stats['errors']} errors)"
            else:
                status = "🔴 Not Started"
            
            last_run = stats["last_run"].strftime("%H:%M UTC") if stats["last_run"] else "Never"
            
            pretty_name = pretty_names.get(task_name, task_name.replace('_', ' ').title())
            
            embed.add_field(
                name=pretty_name,
                value=f"**Status:** {status}\n**Runs:** {stats['runs']:,}\n**Last:** {last_run}",
                inline=True
            )
            
            if stats["runs"] > 0:
                automation_status.append("🟢")
            else:
                automation_status.append("🔴")
        
        # Overall system health
        active_tasks = sum(1 for stats in self.task_stats.values() if stats["runs"] > 0)
        total_tasks = len(self.task_stats)
        
        health_status = f"**System Health:** {active_tasks}/{total_tasks} tasks active {''.join(automation_status)}"
        embed.description = f"Automated systems running 24/7\n{health_status}"
        
        embed.set_footer(text="💡 Use 'r system trigger <task>' to manually test a task")
        await ctx.send(embed=embed)

    @system_admin.command(name="trigger")
    async def trigger_task(self, ctx, task: str = None): # type: ignore
        """Manually trigger a background task - UPDATED FOR PENDING INCOME"""
        if not task:
            embed = disnake.Embed(
                title="🔧 Manual Task Trigger",
                description="Manually execute a background task for testing",
                color=0x2c2d31
            )
            embed.add_field(
                name="📝 Usage",
                value="`r system trigger <task>`",
                inline=False
            )
            embed.add_field(
                name="⚡ Available Tasks",
                value="**`energy`** - Process energy regeneration for all players\n**`stamina`** - Process stamina regeneration for all players\n**`income`** - Process building income generation\n**`cache`** - Clean expired cache entries",
                inline=False
            )
            embed.set_footer(text="⚠️ These tasks normally run automatically")
            await ctx.send(embed=embed)
            return
        
        # PRETTY TASK MAPPING (no underscores for users)
        task_mapping = {
            "energy": "energy_regen",
            "stamina": "stamina_regen", 
            "income": "building_income",
            "cache": "cache_cleanup"
        }
        
        if task not in task_mapping:
            embed = disnake.Embed(
                title="❌ Invalid Task",
                description=f"**Valid tasks:** {' • '.join(f'`{t}`' for t in task_mapping.keys())}",
                color=0xdc3545
            )
            await ctx.send(embed=embed)
            return
        
        internal_task = task_mapping[task]
        
        # PRETTY TASK EMOJIS
        task_emojis = {
            "energy": "⚡",
            "stamina": "💪", 
            "income": "🏗️",
            "cache": "🧹"
        }
        
        # Send "working" message with pretty name
        emoji = task_emojis.get(task, "🔄")
        working_msg = await ctx.send(f"{emoji} Processing {task}...")
        
        try:
            start_time = datetime.utcnow()
            
            if internal_task == "energy_regen":
                result = await ResourceService.regenerate_energy_for_all()
            elif internal_task == "stamina_regen":
                result = await ResourceService.regenerate_stamina_for_all()
            elif internal_task == "building_income":
                result = await BuildingService.process_passive_income_for_all()
            elif internal_task == "cache_cleanup":
                result = await CacheService.cleanup_expired_cache()
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            if result.success:
                # PRETTY TITLES WITH EMOJIS
                pretty_titles = {
                    "energy_regen": "⚡ Energy Regeneration",
                    "stamina_regen": "💪 Stamina Regeneration", 
                    "building_income": "🏗️ Building Income Generation",
                    "cache_cleanup": "🧹 Cache Cleanup"
                }
                
                embed = disnake.Embed(
                    title=f"✅ {pretty_titles[internal_task]} Complete",
                    description=f"**Execution Time:** {execution_time:.2f} seconds",
                    color=0x28a745
                )
                
                if result.data:
                    # 🆕 UPDATED STAT NAMES FOR PENDING INCOME
                    pretty_stats = {
                        "players_processed": "👥 Players Processed",
                        "total_energy_granted": "⚡ Energy Granted", 
                        "total_stamina_granted": "💪 Stamina Granted",
                        "income_generated": "💰 Income Generated",  # 🆕 CHANGED FROM income_granted
                        "total_ticks_processed": "🔄 Income Ticks",
                        "errors": "❌ Errors"
                    }
                    
                    stats_text = ""
                    for key, value in result.data.items():
                        if isinstance(value, (int, float)) and key in pretty_stats:
                            stats_text += f"{pretty_stats[key]}: **{value:,}**\n"
                    
                    if stats_text:
                        embed.add_field(name="📊 Results", value=stats_text, inline=False)
                    
                    # 🆕 UPDATED HELPFUL CONTEXT FOR BUILDING INCOME
                    if task == "energy" or task == "stamina":
                        if result.data.get(f'total_{task}_granted', 0) == 0:
                            embed.add_field(name="💡 Note", value="No resources granted - players may already be at maximum", inline=False)
                    elif task == "income":
                        income_generated = result.data.get('income_generated', 0)
                        if income_generated == 0:
                            embed.add_field(name="💡 Note", value="No income generated - players may not have income-generating buildings or next tick isn't due yet", inline=False)
                        else:
                            embed.add_field(name="💡 Note", value=f"Income added to pending storage - players can collect with `r collect`", inline=False)
                        
            else:
                embed = disnake.Embed(
                    title=f"❌ {task.title()} Task Failed",
                    description=result.error or "Unknown error occurred",
                    color=0xdc3545
                )
            
            await working_msg.edit(embed=embed)
            
        except Exception as e:
            embed = disnake.Embed(
                title="❌ Task Execution Failed",
                description=f"**Error:** {str(e)}",
                color=0xdc3545
            )
            await working_msg.edit(embed=embed)


def setup(bot):
    bot.add_cog(SystemTasksCog(bot))