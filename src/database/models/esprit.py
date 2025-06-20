# src/database/models/esprit.py
from typing import Optional, Dict, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, select, func, col, Column
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import math
import random

from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService

if TYPE_CHECKING:
    from src.database.models import EspritBase

class Esprit(SQLModel, table=True):
    """Universal Stack System - Each row represents ALL copies of an Esprit type a player owns"""
    
    id: Optional[int] = Field(default=None, primary_key=True)
    esprit_base_id: int = Field(foreign_key="esprit_base.id", index=True)
    owner_id: int = Field(foreign_key="player.id", index=True)
    
    # Universal Stack Properties
    quantity: int = Field(default=1)  # Total copies in this stack (can be thousands)
    tier: int = Field(default=1)      # ALL copies share this tier
    awakening_level: int = Field(default=0, ge=0, le=5)  # 0-5 stars
    element: str                      # Cached from base for quick access
    
    # Space System (MW Style)
    space_per_unit: int = Field(default=1)  # Space value per copy
    total_space: int = Field(default=1)     # Total space this stack uses
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_modified: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    # --- LOGIC METHODS ---
    
    def calculate_space_value(self) -> int:
        """Calculate space value based on tier using team_cost from tiers.json"""
        tiers_config = ConfigManager.get("tiers") or {}
        tier_data = tiers_config.get(str(self.tier), {})
        
        # Use team_cost as space value (it's already balanced)
        return tier_data.get("team_cost", 1)
    
    def update_space_values(self):
        """Update space calculations when tier or quantity changes"""
        self.space_per_unit = self.calculate_space_value()
        self.total_space = self.space_per_unit * self.quantity
        
    def get_individual_power(self, base: "EspritBase") -> Dict[str, int]:
        """Calculate power of one copy in this stack"""
        # Get tier config
        tiers_config = ConfigManager.get("tiers") or {}
        tier_data = tiers_config.get(str(self.tier), {})
        
        base_atk = tier_data.get("base_attack", 15)
        
        # Apply awakening bonus (20% per star, multiplicative)
        awakening_multiplier = 1.0 + (self.awakening_level * 0.2)
        
        # Calculate final stats
        final_atk = int(base_atk * awakening_multiplier)
        final_def = int(final_atk * 0.7)  # 70% of ATK
        final_hp = final_atk * 10  # 10x ATK
        
        return {
            "atk": final_atk,
            "def": final_def,
            "hp": final_hp,
            "power": final_atk + final_def + (final_hp // 10)
        }
    
    def get_stack_total_power(self, base: "EspritBase") -> Dict[str, int]:
        """Calculate total power of entire stack"""
        individual = self.get_individual_power(base)
        return {
            "atk": individual["atk"] * self.quantity,
            "def": individual["def"] * self.quantity,
            "hp": individual["hp"] * self.quantity,
            "power": individual["power"] * self.quantity
        }
    
    def get_awakening_cost(self) -> Dict[str, any]:
        """
        Get cost to awaken this stack to next level.
        1st star: 1 copy, 2nd: 2 copies, etc.
        """
        if self.awakening_level >= 5:
            return {"copies_needed": 0, "can_awaken": False}
        
        copies_needed = self.awakening_level + 1
        
        return {
            "copies_needed": copies_needed,
            "can_awaken": self.quantity > copies_needed  # Need extras to consume
        }
    
    async def perform_awakening(self, session: AsyncSession) -> bool:
        """
        Awakens the ENTIRE stack by consuming copies.
        Star 1: 1 copy, Star 2: 2 copies, etc.
        Returns True if successful, False if not enough copies.
        """
        cost = self.get_awakening_cost()
        
        if not cost["can_awaken"]:
            return False
        
        # Consume the copies
        self.quantity -= cost["copies_needed"]
        self.awakening_level += 1
        
        # Update space values
        self.update_space_values()
        self.last_modified = datetime.utcnow()
        
        # Update player stats
        from src.database.models import Player
        player_stmt = select(Player).where(Player.id == self.owner_id)
        player = (await session.execute(player_stmt)).scalar_one()
        player.total_awakenings += 1
        
        # Invalidate cache
        if RedisService.is_available():
            await RedisService.invalidate_player_cache(player.id)
        
        # Recalculate total power
        await player.recalculate_total_power(session)
        
        return True
    
    async def perform_fusion(
        self, 
        other_stack: "Esprit", 
        session: AsyncSession,
        use_fragments: bool = False,
        fragments_amount: int = 0
    ) -> Optional["Esprit"]:
        """
        Fuses two stacks following MW fusion rules.
        Returns the resulting Esprit stack if successful, None if failed.
        Fragments guarantee success, not just specific tier monsters.
        """
        from src.database.models import Player, EspritBase
        
        # Must be same tier
        if self.tier != other_stack.tier:
            return None
            
        # Need at least 1 copy from each stack
        if self.quantity < 1 or other_stack.quantity < 1:
            return None
            
        # Get player for costs and fragments
        player_stmt = select(Player).where(Player.id == self.owner_id).with_for_update()
        player = (await session.execute(player_stmt)).scalar_one()
        
        # Get fusion cost from tiers.json
        tiers_config = ConfigManager.get("tiers") or {}
        tier_data = tiers_config.get(str(self.tier), {})
        fusion_cost = tier_data.get("combine_cost_jijies", 0)
        
        # Check if player can afford
        if fusion_cost and player.jijies < fusion_cost:
            return None  # Can't afford
        
        # Get fusion chart
        fusion_config = ConfigManager.get("elements") or {}
        fusion_chart = fusion_config.get("fusion_chart", {})
        
        # Determine result element based on MW chart
        if self.element == other_stack.element:
            # Same element fusion - always produces same element
            result_element = self.element
            base_success_rate = tier_data.get("combine_success_rate", 0.5)
        else:
            # Different element fusion - check chart
            fusion_key = f"{self.element.lower()}_{other_stack.element.lower()}"
            reverse_key = f"{other_stack.element.lower()}_{self.element.lower()}"
            
            fusion_result = fusion_chart.get(fusion_key) or fusion_chart.get(reverse_key)
            
            if not fusion_result:
                return None  # Invalid combination
                
            # Handle MW style results
            if isinstance(fusion_result, list):
                # 50/50 chance
                result_element = random.choice(fusion_result).title()
            elif fusion_result == "random":
                # Random any element
                result_element = random.choice(["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"])
            else:
                result_element = fusion_result.title()
                
            # Cross-element uses lower rate
            base_success_rate = tier_data.get("combine_success_rate", 0.5) * 0.8
        
        # Apply leader bonus if applicable
        leader_bonuses = await player.get_leader_bonuses(session)
        fusion_bonus = leader_bonuses.get("element_bonuses", {}).get("fusion_bonus", 0)
        final_success_rate = min(base_success_rate * (1 + fusion_bonus), 0.95)
        
        # Use fragments for guaranteed success
        if use_fragments and fragments_amount >= 10:
            if player.get_fragment_count(result_element.lower()) >= 10:
                player.consume_element_fragments(result_element.lower(), 10)
                final_success_rate = 1.0  # Guarantee success
        
        # Deduct cost
        if fusion_cost:
            player.jijies -= fusion_cost
        
        # Attempt fusion
        player.total_fusions += 1
        
        # Consume materials first
        self.quantity -= 1
        if other_stack.id != self.id:  # Different stacks
            other_stack.quantity -= 1
        
        # Check fusion success
        if random.random() > final_success_rate:
            # Fusion failed - produce element fragments
            fragments_gained = max(1, self.tier // 2)
            
            # Add fragments for the result element (or random if multiple possible)
            if result_element in ["Multiple possible", "Random"]:
                fragment_element = random.choice([self.element, other_stack.element])
            else:
                fragment_element = result_element
                
            player.add_element_fragments(fragment_element.lower(), fragments_gained)
            
            # Clean up empty stacks
            await self._cleanup_empty_stacks(session, other_stack)
            
            # Update player stats
            await player.recalculate_space(session)
            await player.recalculate_total_power(session)
            
            # Invalidate cache
            if RedisService.is_available():
                await RedisService.invalidate_player_cache(player.id)
            
            return None
        
        # Fusion succeeded
        player.successful_fusions += 1
        
        # Find a random Esprit of the result element and next tier
        target_tier = self.tier + 1
        base_stmt = select(EspritBase).where(
            EspritBase.element == result_element,
            EspritBase.base_tier == target_tier
        )
        possible_bases = (await session.execute(base_stmt)).scalars().all()
        
        if not possible_bases:
            # No Esprit exists at this tier/element - give fragments instead
            fragments_gained = max(1, self.tier // 2)
            player.add_element_fragments(result_element.lower(), fragments_gained)
            
            await self._cleanup_empty_stacks(session, other_stack)
            
            # Invalidate cache
            if RedisService.is_available():
                await RedisService.invalidate_player_cache(player.id)
            return None
            
        result_base = random.choice(list(possible_bases))
        
        # Add result to collection
        result_stack = await Esprit.add_to_collection(
            session=session,
            owner_id=self.owner_id,
            base=result_base,
            quantity=1
        )
        
        # Clean up empty stacks
        await self._cleanup_empty_stacks(session, other_stack)
        
        # Update player stats
        await player.recalculate_space(session)
        await player.recalculate_total_power(session)
        player.last_fusion = datetime.utcnow()
        
        # Invalidate cache
        if RedisService.is_available():
            await RedisService.invalidate_player_cache(player.id)
        
        return result_stack
    
    async def _cleanup_empty_stacks(self, session: AsyncSession, other_stack: "Esprit"):
        """Clean up empty stacks after fusion"""
        if self.quantity == 0:
            await session.delete(self)
        else:
            self.update_space_values()
            
        if other_stack.quantity == 0 and other_stack.id != self.id:
            await session.delete(other_stack)
        elif other_stack.id != self.id:
            other_stack.update_space_values()
    
    @classmethod
    async def add_to_collection(
        cls,
        session: AsyncSession,
        owner_id: int,
        base: "EspritBase",
        quantity: int = 1,
        tier: Optional[int] = None
    ) -> "Esprit":
        """
        Adds Esprits to a player's collection using the universal stack system.
        Creates new stack or adds to existing one.
        """
        if tier is None:
            tier = base.base_tier
            
        # Check if stack already exists with lock
        existing_stmt = select(cls).where(
            cls.owner_id == owner_id,
            cls.esprit_base_id == base.id
        ).with_for_update()
        existing_stack = (await session.execute(existing_stmt)).scalar_one_or_none()
        
        if existing_stack:
            # Add to existing stack
            existing_stack.quantity += quantity
            existing_stack.last_modified = datetime.utcnow()
            existing_stack.update_space_values()
            return existing_stack
        else:
            # Create new stack
            new_stack = cls(
                esprit_base_id=base.id,
                owner_id=owner_id,
                quantity=quantity,
                tier=tier,
                element=base.element,
                awakening_level=0
            )
            new_stack.update_space_values()
            
            session.add(new_stack)
            await session.flush()
            return new_stack
    
    @classmethod
    async def get_player_collection_stats(
        cls,
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, any]:
        """Get collection statistics for a player"""
        # Try cache first
        if RedisService.is_available():
            cached = await RedisService.get_json(f"collection_stats:{player_id}")
            if cached:
                return cached
        
        # Total unique Esprits
        unique_stmt = select(func.count(cls.id)).where(cls.owner_id == player_id)
        unique_count = (await session.execute(unique_stmt)).scalar() or 0
        
        # Total quantity
        quantity_stmt = select(func.sum(cls.quantity)).where(cls.owner_id == player_id)
        total_quantity = (await session.execute(quantity_stmt)).scalar() or 0
        
        # By element
        element_stmt = select(
            cls.element,
            func.count(cls.id),
            func.sum(cls.quantity)
        ).where(
            cls.owner_id == player_id
        ).group_by(cls.element)
        
        element_results = (await session.execute(element_stmt)).all()
        element_stats = {
            row[0].lower(): {"unique": row[1], "total": row[2]}
            for row in element_results
        }
        
        # By tier
        tier_stmt = select(
            cls.tier,
            func.count(cls.id),
            func.sum(cls.quantity)
        ).where(
            cls.owner_id == player_id
        ).group_by(cls.tier).order_by(cls.tier)
        
        tier_results = (await session.execute(tier_stmt)).all()
        tier_stats = {
            f"tier_{row[0]}": {"unique": row[1], "total": row[2]}
            for row in tier_results
        }
        
        # Awakened stacks
        awakened_stmt = select(
            cls.awakening_level,
            func.count(cls.id),
            func.sum(cls.quantity)
        ).where(
            cls.owner_id == player_id,
            cls.awakening_level > 0
        ).group_by(cls.awakening_level)
        
        awakened_results = (await session.execute(awakened_stmt)).all()
        awakened_stats = {
            f"star_{row[0]}": {"stacks": row[1], "total": row[2]}
            for row in awakened_results
        }
        
        stats = {
            "unique_esprits": unique_count,
            "total_quantity": total_quantity,
            "by_element": element_stats,
            "by_tier": tier_stats,
            "awakened": awakened_stats
        }
        
        # Cache for 15 minutes
        if RedisService.is_available():
            await RedisService.set_json(f"collection_stats:{player_id}", stats, 900)
        
        return stats