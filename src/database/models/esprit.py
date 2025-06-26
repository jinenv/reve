# src/database/models/esprit.py
from typing import Optional, Dict, List, TYPE_CHECKING, Any
from sqlmodel import SQLModel, Field, select, func, col 
from sqlalchemy import Column, String, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import random
from sqlalchemy import select as sa_select
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService
from src.utils.game_constants import Tiers, FUSION_CHART, get_fusion_result
from src.utils.transaction_logger import transaction_logger, TransactionType

if TYPE_CHECKING:
    from src.database.models import EspritBase
    from src.database.models.player import Player
    from src.database.models.esprit_base import EspritBase

class Esprit(SQLModel, table=True):
    __tablename__: str = "esprit" # type: ignore
    """Universal Stack System - Each row represents ALL copies of an Esprit type a player owns"""
    
    id: Optional[int] = Field(default=None, primary_key=True)
    esprit_base_id: int = Field(foreign_key="esprit_base.id", index=True)
    owner_id: int = Field(foreign_key="player.id", index=True)
    
    # Universal Stack Properties
    quantity: int = Field(sa_column=Column(BigInteger), default=1)
    tier: int = Field(default=1)      # ALL copies share this tier
    awakening_level: int = Field(default=0, ge=0, le=5)  # 0-5 stars
    element: str = Field(sa_column=Column(String))  # Cached from base for quick access
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_modified: datetime = Field(default_factory=datetime.utcnow)
    
    # --- LOGIC METHODS ---   
    def get_individual_power(self, base: "EspritBase") -> Dict[str, int]:
        """Calculate power of one copy in this stack using ACTUAL Esprit stats"""
        # NO MORE TIER LOOKUP - Use the actual stats from EspritBase!
        base_atk = base.base_atk
        base_def = base.base_def
        base_hp = base.base_hp
        
        # Apply awakening bonus (20% per star, multiplicative)
        awakening_multiplier = 1.0 + (self.awakening_level * 0.2)
        
        # Calculate final stats with awakening
        final_atk = int(base_atk * awakening_multiplier)
        final_def = int(base_def * awakening_multiplier)
        final_hp = int(base_hp * awakening_multiplier)
        
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
    
    def get_awakening_cost(self) -> Dict[str, Any]:
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
        
        old_awakening = self.awakening_level
        copies_consumed = cost["copies_needed"]
        
        # Consume the copies
        self.quantity -= copies_consumed
        self.awakening_level += 1
        
        # Update player stats
        from src.database.models import Player
        player_stmt = select(Player).where(Player.id == self.owner_id)
        player = (await session.execute(player_stmt)).scalar_one()
        player.total_awakenings += 1
        
        # Log the awakening
        from src.database.models import EspritBase
        base_stmt = select(EspritBase).where(EspritBase.id == self.esprit_base_id)
        base = (await session.execute(base_stmt)).scalar_one()
        
        if player.id is not None:
            transaction_logger.log_awakening(
                player.id,
                base.name,
                old_awakening,
                self.awakening_level,
                copies_consumed
            )
        
        # Invalidate cache
        if RedisService.is_available() and player.id is not None:
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
            
            # Get fusion cost from Tiers
            tier_data = Tiers.get(self.tier)
            fusion_cost = tier_data.combine_cost_jijies if tier_data else 0

            # Check if player can afford
            if fusion_cost and player.jijies < fusion_cost:
                return None  # Can't afford
            
            # Determine result element based on MW chart
            if self.element == other_stack.element:
                # Same element fusion - always produces same element
                result_element = self.element
                base_success_rate = tier_data.combine_success_rate if tier_data else 0.5
            else:
                # Different element fusion - use fusion chart
                fusion_result = get_fusion_result(self.element, other_stack.element)
                
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
                    
                # Cross-element fusion success rate (uses Tiers method)
                base_success_rate = Tiers.get_fusion_success_rate(self.tier, same_element=False)
            
            # Apply leader bonus if applicable
            leader_bonuses = await player.get_leader_bonuses(session)
            fusion_bonus = leader_bonuses.get("element_bonuses", {}).get("fusion_bonus", 0)
            final_success_rate = min(base_success_rate * (1 + fusion_bonus), 0.95)
            
            # Use fragments for guaranteed success
            if use_fragments and fragments_amount >= 10:
                if player.get_fragment_count(result_element.lower()) >= 10:
                    await player.consume_element_fragments(session, result_element.lower(), 10, "fusion_guarantee")
                    final_success_rate = 1.0  # Guarantee success
            
            # Deduct cost
            if fusion_cost:
                await player.spend_currency(session, "jijies", fusion_cost, "fusion_cost")
            
            # Get bases for logging
            self_base_stmt = select(EspritBase).where(EspritBase.id == self.esprit_base_id)
            self_base = (await session.execute(self_base_stmt)).scalar_one()
            
            other_base_stmt = select(EspritBase).where(EspritBase.id == other_stack.esprit_base_id)
            other_base = (await session.execute(other_base_stmt)).scalar_one()
            
            # Attempt fusion
            player.total_fusions += 1
            
            # Consume materials first
            self.quantity -= 1
            if other_stack.id != self.id:  # Different stacks
                other_stack.quantity -= 1
            
            # Check fusion success
            fusion_succeeded = random.random() <= final_success_rate
            
            # Log the fusion attempt
            if player.id is not None:
                transaction_logger.log_fusion(
                    player.id,
                    {
                        "name": self_base.name,
                        "tier": self.tier,
                        "element": self.element
                    },
                    {
                        "name": other_base.name,
                        "tier": other_stack.tier,
                        "element": other_stack.element
                    },
                    None,  # Will update with result if successful
                    fusion_succeeded,
                    fusion_cost
                )
            
            if not fusion_succeeded:
                # Fusion failed - produce element fragments
                fragments_gained = max(1, self.tier // 2)
                
                # Add fragments for the result element (or random if multiple possible)
                if result_element in ["Multiple possible", "Random"]:
                    fragment_element = random.choice([self.element, other_stack.element])
                else:
                    fragment_element = result_element
                    
                await player.add_element_fragments(session, fragment_element.lower(), fragments_gained, "fusion_failure")
                
                # Clean up empty stacks
                await self._cleanup_empty_stacks(session, other_stack)
                
                # Update player stats
                await player.recalculate_total_power(session)
                
                # Invalidate cache
                if RedisService.is_available() and player.id is not None:
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
                await player.add_element_fragments(session, result_element.lower(), fragments_gained, "fusion_no_result")
                
                await self._cleanup_empty_stacks(session, other_stack)
                
                # Invalidate cache
                if RedisService.is_available() and player.id is not None:
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
            
            # Log successful fusion with result
            if player.id is not None:
                transaction_logger.log_fusion(
                    player.id,
                    {
                        "name": self_base.name,
                        "tier": self.tier,
                        "element": self.element
                    },
                    {
                        "name": other_base.name,
                        "tier": other_stack.tier,
                        "element": other_stack.element
                    },
                    {
                        "name": result_base.name,
                        "tier": result_base.base_tier,
                        "element": result_base.element
                    },
                    True,
                    fusion_cost
                )
            
            # Clean up empty stacks
            await self._cleanup_empty_stacks(session, other_stack)
            
            # Update player stats
            await player.recalculate_total_power(session)
            player.last_fusion = datetime.utcnow()
            
            # Invalidate cache
            if RedisService.is_available() and player.id is not None:
                await RedisService.invalidate_player_cache(player.id)
            
            return result_stack
    
    async def _cleanup_empty_stacks(self, session: AsyncSession, other_stack: "Esprit"):
        """
        Deletes this stack and/or the other stack from the database if their quantity is zero or less.
        """
        stacks_to_check: List["Esprit"] = [self]
        if other_stack.id != self.id:
            stacks_to_check.append(other_stack)
        for stack in stacks_to_check:
            if stack.quantity <= 0:
                await session.delete(stack)
        await session.commit()

    @classmethod
    async def add_to_collection(
        cls,
        session: AsyncSession,
        owner_id: int,
        base: "EspritBase",
        quantity: int = 1
    ) -> "Esprit":
        """
        Adds the specified quantity of an Esprit to the player's collection, stacking if possible.
        """
        esprit_stmt = select(cls).where(
            cls.owner_id == owner_id,
            cls.esprit_base_id == base.id,
            cls.tier == base.base_tier,
            cls.element == base.element
        )
        esprit = (await session.execute(esprit_stmt)).scalar_one_or_none()
        
        if esprit:
            esprit.quantity += quantity
            esprit.last_modified = datetime.utcnow()
        else:
            if base.id is None:
                raise ValueError("EspritBase.id cannot be None when adding to collection.")
            esprit = cls(
                esprit_base_id=base.id,
                owner_id=owner_id,
                quantity=quantity,
                tier=base.base_tier,
                awakening_level=0,
                element=base.element,
                created_at=datetime.utcnow(),
                last_modified=datetime.utcnow()
            )
            session.add(esprit)
        
        # Don't commit here! Let the calling transaction handle it
        # await session.commit()  # REMOVE THIS LINE
        
        return esprit
    @classmethod
    async def get_player_collection_stats(
        cls,
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, Any]:
        """Get collection statistics for a player"""
        # Try cache first
        if RedisService.is_available():
            cached = await RedisService.get_json(f"collection_stats:{player_id}")
            if cached:
                return cached
        
        # Import Esprit class for queries
        from src.database.models.esprit import Esprit
        
        # Total unique Esprits
        unique_stmt = select(func.count()).select_from(Esprit).where(Esprit.owner_id == player_id)
        unique_count = (await session.execute(unique_stmt)).scalar() or 0
        
        # Total quantity
        quantity_stmt = select(func.sum(Esprit.quantity)).where(Esprit.owner_id == player_id)
        total_quantity = (await session.execute(quantity_stmt)).scalar() or 0
        
        # By element
        element_stmt = select(
            Esprit.element,
            func.count().label('unique_count'),
            func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')
        ).select_from(Esprit).where(
            Esprit.owner_id == player_id
        ).group_by(Esprit.element)
        
        element_results = (await session.execute(element_stmt)).all()
        element_stats = {
            row.element.lower(): {"unique": row.unique_count, "total": row.total_quantity}
            for row in element_results
        }
        
        # By tier
        tier_stmt = select(
            Esprit.tier,
            func.count().label('unique_count'),
            func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')
        ).select_from(Esprit).where(
            Esprit.owner_id == player_id
        ).group_by(col(Esprit.tier)).order_by(col(Esprit.tier))  # FIX: Wrap Esprit.tier with col()

        tier_results = (await session.execute(tier_stmt)).all()
        tier_stats = {
            f"tier_{row.tier}": {"unique": row.unique_count, "total": row.total_quantity}
            for row in tier_results
        }
        
        # Awakened stacks
        awakened_stmt = select(
            Esprit.awakening_level,
            func.count().label('stack_count'),
            func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')
        ).select_from(Esprit).where(
            Esprit.owner_id == player_id,
            Esprit.awakening_level > 0
        ).group_by(col(Esprit.awakening_level))
        
        awakened_results = (await session.execute(awakened_stmt)).all()
        awakened_stats = {
            f"star_{row.awakening_level}": {"stacks": row.stack_count, "total": row.total_quantity}
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