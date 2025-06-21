# src/utils/pagination.py
import disnake
from typing import List, Optional, Callable, Any
from src.utils.embed_colors import EmbedColors

class PaginationView(disnake.ui.View):
    """Reusable pagination view for displaying lists"""
    
    def __init__(
        self,
        embeds: List[disnake.Embed],
        author_id: int,
        timeout: int = 180
    ):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.current_page = 0
        self.message: Optional[disnake.Message] = None
        
        # Update buttons
        self._update_buttons()
    
    def _update_buttons(self):
        """Update button states based on current page"""
        self.first_button.disabled = self.current_page == 0
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= len(self.embeds) - 1
        self.last_button.disabled = self.current_page >= len(self.embeds) - 1
        
        # Update page counter
        self.page_button.label = f"{self.current_page + 1}/{len(self.embeds)}"
    
    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        """Only allow the command author to use buttons"""
        if interaction.author.id != self.author_id:
            await interaction.response.send_message(
                "You cannot control this menu!",
                ephemeral=True
            )
            return False
        return True
    
    @disnake.ui.button(emoji="⏮️", style=disnake.ButtonStyle.secondary)
    async def first_button(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction
    ):
        """Go to first page"""
        self.current_page = 0
        self._update_buttons()
        await inter.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @disnake.ui.button(emoji="◀️", style=disnake.ButtonStyle.secondary)
    async def prev_button(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction
    ):
        """Go to previous page"""
        self.current_page -= 1
        self._update_buttons()
        await inter.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @disnake.ui.button(label="1/1", style=disnake.ButtonStyle.primary, disabled=True)
    async def page_button(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction
    ):
        """Page counter (non-interactive)"""
        pass
    
    @disnake.ui.button(emoji="▶️", style=disnake.ButtonStyle.secondary)
    async def next_button(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction
    ):
        """Go to next page"""
        self.current_page += 1
        self._update_buttons()
        await inter.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @disnake.ui.button(emoji="⏭️", style=disnake.ButtonStyle.secondary)
    async def last_button(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction
    ):
        """Go to last page"""
        self.current_page = len(self.embeds) - 1
        self._update_buttons()
        await inter.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    async def on_timeout(self):
        """Disable all buttons on timeout"""
        for item in self.children:
            if isinstance(item, disnake.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass


class SelectMenuPaginator:
    """Helper to create paginated select menus (Discord limit: 25 options)"""
    
    @staticmethod
    def create_pages(
        items: List[Any],
        format_func: Callable[[Any], dict],
        max_per_page: int = 25,
        placeholder: str = "Select an option"
    ) -> List[disnake.ui.Select]:
        """
        Create paginated select menus.
        
        Args:
            items: List of items to paginate
            format_func: Function that takes an item and returns 
                        {"label": str, "value": str, "description": str, "emoji": str}
            max_per_page: Maximum options per select menu
            placeholder: Placeholder text for select menu
        
        Returns:
            List of Select menus
        """
        selects = []
        
        for i in range(0, len(items), max_per_page):
            page_items = items[i:i + max_per_page]
            options = []
            
            for item in page_items:
                option_data = format_func(item)
                options.append(
                    disnake.SelectOption(
                        label=option_data.get("label", "Unknown"),
                        value=option_data.get("value", "unknown"),
                        description=option_data.get("description"),
                        emoji=option_data.get("emoji")
                    )
                )
            
            select = disnake.ui.Select(
                placeholder=f"{placeholder} (Page {len(selects) + 1})",
                options=options,
                min_values=1,
                max_values=1
            )
            selects.append(select)
        
        return selects