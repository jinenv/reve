# src/cogs/team_cog.py
import disnake
from typing import Dict, List, Any, Optional
from sqlalchemy import select

from src.database.models import Player
from src.services.team_service import TeamService
from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.logger import get_logger

logger = get_logger(__name__)

class TeamCog(disnake.Cog):
    """Team management with 3-Esprit combat system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @disnake.slash_command(
        name="team",
        description="🛡️ Manage your 3-Esprit combat team"
    )
    async def team_command(self, inter: disnake.ApplicationCommandInteraction):
        """Show current team and allow editing"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            stmt = select(Player).where(Player.discord_id == inter.user.id)
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                embed = disnake.Embed(
                    title="❌ Player Not Found",
                    description="You need to start your journey first! Use `/start`",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_response(embed=embed)
                return
            
            # Get current team setup
            team_result = await TeamService.get_current_team(player.id)
            if not team_result.success:
                embed = disnake.Embed(
                    title="❌ Team Load Error",
                    description=f"Failed to load team: {team_result.error}",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_response(embed=embed)
                return
            
            team_data = team_result.data
            
            # Show team interface
            view = TeamManagementView(player.id, team_data)
            embed = create_team_display_embed(team_data)
            
            await inter.edit_original_response(embed=embed, view=view)

class TeamManagementView(disnake.ui.View):
    """Main team management interface"""
    
    def __init__(self, player_id: int, team_data: Dict[str, Any]):
        super().__init__(timeout=300)
        self.player_id = player_id
        self.team_data = team_data
    
    @disnake.ui.button(label="👑 Change Leader", style=disnake.ButtonStyle.primary)
    async def change_leader_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Open leader selection dropdown"""
        if inter.user.id != self.player_id:
            await inter.response.send_message("Not your team!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Get eligible leaders
        current_leader_id = self.team_data.get("leader", {}).get("esprit_id")
        exclude_ids = [
            self.team_data.get("support1", {}).get("esprit_id"),
            self.team_data.get("support2", {}).get("esprit_id")
        ]
        exclude_ids = [id for id in exclude_ids if id is not None]
        
        eligible_result = await TeamService.get_eligible_team_members(
            self.player_id, role="leader", exclude_ids=exclude_ids
        )
        
        if not eligible_result.success:
            await inter.followup.send(f"Error: {eligible_result.error}", ephemeral=True)
            return
        
        # Show leader selection
        view = EspritSelectionView(
            player_id=self.player_id,
            esprits=eligible_result.data,
            role="leader",
            current_team=self.team_data,
            parent_view=self
        )
        
        embed = disnake.Embed(
            title="👑 Select New Leader",
            description="Choose your team leader. Leaders can use their full ability set in combat.",
            color=EmbedColors.PRIMARY
        )
        
        await inter.edit_original_response(embed=embed, view=view)
    
    @disnake.ui.button(label="🛡️ Change Support 1", style=disnake.ButtonStyle.secondary)
    async def change_support1_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Open support 1 selection dropdown"""
        await self._change_support(inter, slot=1)
    
    @disnake.ui.button(label="⚔️ Change Support 2", style=disnake.ButtonStyle.secondary)
    async def change_support2_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Open support 2 selection dropdown"""
        await self._change_support(inter, slot=2)
    
    @disnake.ui.button(label="📊 Team Stats", style=disnake.ButtonStyle.success)
    async def team_stats_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Show detailed team statistics"""
        if inter.user.id != self.player_id:
            await inter.response.send_message("Not your team!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        stats_result = await TeamService.get_team_stats_summary(self.player_id)
        if not stats_result.success:
            await inter.followup.send("Failed to load team stats", ephemeral=True)
            return
        
        stats = stats_result.data
        
        embed = disnake.Embed(
            title="📊 Team Statistics",
            color=EmbedColors.INFO
        )
        
        embed.add_field(
            name="⚔️ Combat Power",
            value=f"**Attack:** {stats['total_attack']:,}\n**Defense:** {stats['total_defense']:,}\n**HP:** {stats['total_hp']:,}",
            inline=True
        )
        
        embed.add_field(
            name="🌟 Team Composition",
            value=f"**Team Size:** {stats['team_size']}/3\n**Unique Elements:** {stats['unique_elements']}\n**Average Tier:** {stats['average_tier']:.1f}",
            inline=True
        )
        
        embed.add_field(
            name="🎨 Elements",
            value=" | ".join([f"{_get_element_emoji(e)} {e.title()}" for e in stats['element_list']]) if stats['element_list'] else "None",
            inline=False
        )
        
        # Combat readiness
        validation_result = await TeamService.validate_team_for_combat(self.player_id)
        if validation_result.success:
            validation = validation_result.data
            if validation["valid"]:
                embed.add_field(
                    name="✅ Combat Ready",
                    value="Team is ready for battle!",
                    inline=False
                )
            else:
                embed.add_field(
                    name="⚠️ Combat Issues",
                    value="\n".join(validation["errors"]),
                    inline=False
                )
        
        await inter.edit_original_response(embed=embed, view=self)
    
    async def _change_support(self, inter: disnake.MessageInteraction, slot: int):
        """Handle support member selection"""
        if inter.user.id != self.player_id:
            await inter.response.send_message("Not your team!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Get eligible supports (exclude current leader and other support)
        exclude_ids = [
            self.team_data.get("leader", {}).get("esprit_id"),
            self.team_data.get("support1" if slot == 2 else "support2", {}).get("esprit_id")
        ]
        exclude_ids = [id for id in exclude_ids if id is not None]
        
        eligible_result = await TeamService.get_eligible_team_members(
            self.player_id, 
            role="support",
            exclude_ids=exclude_ids
        )
        
        if not eligible_result.success:
            await inter.followup.send(f"Error: {eligible_result.error}", ephemeral=True)
            return
        
        # Show support selection with support skills visible
        view = EspritSelectionView(
            player_id=self.player_id,
            esprits=eligible_result.data,
            role=f"support{slot}",
            current_team=self.team_data,
            parent_view=self
        )
        
        embed = disnake.Embed(
            title=f"🛡️ Select Support Member {slot}",
            description="Choose a support member. You'll see their support skill that will be available in combat.",
            color=EmbedColors.SECONDARY
        )
        
        await inter.edit_original_response(embed=embed, view=view)

class EspritSelectionView(disnake.ui.View):
    """Dropdown selection for team members with support skill display"""
    
    def __init__(self, player_id: int, esprits: List[Dict[str, Any]], role: str, 
                 current_team: Dict[str, Any], parent_view: TeamManagementView):
        super().__init__(timeout=300)
        self.player_id = player_id
        self.esprits = esprits
        self.role = role
        self.current_team = current_team
        self.parent_view = parent_view
        
        # Add back button
        back_button = disnake.ui.Button(label="← Back to Team", style=disnake.ButtonStyle.secondary)
        back_button.callback = self._back_to_team
        self.add_item(back_button)
        
        # Create selection dropdown(s)
        self._add_selection_dropdowns()
    
    def _add_selection_dropdowns(self):
        """Create paginated dropdowns for Esprit selection"""
        # Group esprits into pages of 20 (Discord limit is 25, leaving room for "None" option)
        max_per_page = 20
        
        for page_num, i in enumerate(range(0, len(self.esprits), max_per_page)):
            page_esprits = self.esprits[i:i + max_per_page]
            
            # Create options for this page
            options = []
            
            # Add "None" option for support roles
            if self.role.startswith("support"):
                options.append(disnake.SelectOption(
                    label="❌ No Support Member",
                    value="none",
                    description="Leave this support slot empty",
                    emoji="❌"
                ))
            
            # Add Esprit options
            for esprit_data in page_esprits:
                option = self._format_esprit_option(esprit_data)
                options.append(option)
            
            # Create select menu
            select_menu = disnake.ui.Select(
                placeholder=f"Choose {self.role}... (Page {page_num + 1})" if len(self.esprits) > max_per_page else f"Choose {self.role}...",
                options=options,
                min_values=1,
                max_values=1
            )
            
            # Set callback
            select_menu.callback = self._selection_callback
            self.add_item(select_menu)
    
    def _format_esprit_option(self, esprit_data: Dict[str, Any]) -> disnake.SelectOption:
        """Format Esprit data into dropdown option with support skill visible"""
        name = esprit_data["name"]
        atk = esprit_data["total_atk"]
        def_stat = esprit_data["total_def"]
        element = esprit_data["element"]
        tier = esprit_data["base_tier"]
        
        # Get element emoji
        element_emoji = _get_element_emoji(element)
        
        # Get support skill name (all roles show this)
        support_skill = esprit_data.get("support_skill", {})
        skill_name = support_skill.get("name", "No Skill")
        
        # Format: <emoji> Name (T#) | ATK: X DEF: Y | Support: Skill Name
        label = f"{element_emoji} {name} (T{tier}) | ATK: {atk:,} DEF: {def_stat:,} | {skill_name}"
        
        # Truncate if too long (Discord limit: 100 chars)
        if len(label) > 100:
            label = f"{element_emoji} {name[:15]}... (T{tier}) | {atk//1000}k/{def_stat//1000}k | {skill_name[:15]}..."
        
        # Description shows skill effect
        description = support_skill.get("description", "No support skill available")[:100]
        
        return disnake.SelectOption(
            label=label,
            value=str(esprit_data["esprit_id"]),
            description=description,
            emoji=element_emoji
        )
    
    async def _selection_callback(self, inter: disnake.MessageInteraction):
        """Handle esprit selection"""
        if inter.user.id != self.player_id:
            await inter.response.send_message("Not your selection!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        selected_value = inter.data.values[0]
        
        # Handle "none" selection for support roles
        if selected_value == "none":
            esprit_id = None
        else:
            esprit_id = int(selected_value)
        
        # Update team via service
        update_result = await TeamService.update_team_member(
            player_id=self.player_id,
            role=self.role,
            esprit_id=esprit_id
        )
        
        if not update_result.success:
            await inter.followup.send(f"Failed to update team: {update_result.error}", ephemeral=True)
            return
        
        # Get updated team data
        team_result = await TeamService.get_current_team(self.player_id)
        if team_result.success:
            self.parent_view.team_data = team_result.data
        
        # Return to team view
        embed = create_team_display_embed(team_result.data if team_result.success else self.current_team)
        await inter.edit_original_response(embed=embed, view=self.parent_view)
    
    async def _back_to_team(self, inter: disnake.MessageInteraction):
        """Return to main team view"""
        if inter.user.id != self.player_id:
            await inter.response.send_message("Not your team!", ephemeral=True)
            return
        
        embed = create_team_display_embed(self.current_team)
        await inter.response.edit_message(embed=embed, view=self.parent_view)

def create_team_display_embed(team_data: Dict[str, Any]) -> disnake.Embed:
    """Create embed showing current team composition"""
    embed = disnake.Embed(
        title="🛡️ Your Combat Team",
        description="Your 3-Esprit team for turn-based combat",
        color=EmbedColors.PRIMARY
    )
    
    # Leader section
    leader = team_data.get("leader")
    if leader:
        leader_text = f"**{leader['name']}** (Tier {leader['base_tier']})\n"
        leader_text += f"⚔️ ATK: {leader['total_atk']:,} | 🛡️ DEF: {leader['total_def']:,}\n"
        leader_text += f"**Abilities:** {leader.get('ability_summary', 'Loading...')}"
        
        embed.add_field(
            name=f"{_get_element_emoji(leader['element'])} Leader - Full Combat Access",
            value=leader_text,
            inline=False
        )
    else:
        embed.add_field(
            name="👑 Leader - Full Combat Access",
            value="❌ No leader selected",
            inline=False
        )
    
    # Support members
    for i in [1, 2]:
        support = team_data.get(f"support{i}")
        if support:
            support_skill = support.get("support_skill", {})
            skill_name = support_skill.get("name", "No Skill")
            skill_desc = support_skill.get("description", "")
            tier_bonus = support_skill.get("tier_bonus", "")
            
            support_text = f"**{support['name']}** (Tier {support['base_tier']})\n"
            support_text += f"⚔️ ATK: {support['total_atk']:,} | 🛡️ DEF: {support['total_def']:,}\n"
            support_text += f"**Support Skill:** {skill_name}\n*{skill_desc}*"
            if tier_bonus:
                support_text += f"\n*{tier_bonus}*"
            
            embed.add_field(
                name=f"{_get_element_emoji(support['element'])} Support {i} - {skill_name}",
                value=support_text,
                inline=True
            )
        else:
            embed.add_field(
                name=f"🛡️ Support {i} - Support Skill",
                value="❌ No support member",
                inline=True
            )
    
    # Team power summary
    total_power = team_data.get("total_team_power", 0)
    team_valid = team_data.get("team_valid", False)
    
    embed.add_field(
        name="💪 Team Status",
        value=f"**Total Power:** {total_power:,}\n**Combat Ready:** {'✅ Yes' if team_valid else '❌ No (need leader)'}",
        inline=False
    )
    
    embed.set_footer(text="💡 Tip: Leader uses full abilities, supports provide one skill each in combat")
    
    return embed

def _get_element_emoji(element: str) -> str:
    """Helper to get element emoji"""
    element_map = {
        "inferno": "🔥", "verdant": "🌿", "tempest": "⚡",
        "abyssal": "🌊", "umbral": "🌙", "radiant": "☀️"
    }
    return element_map.get(element.lower(), "⭐")

def setup(bot):
    bot.add_cog(TeamCog(bot))