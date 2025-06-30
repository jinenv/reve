# src/domain/quest_domain.py - Complete rebuild because apparently files delete themselves
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from datetime import datetime
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database.models import Player, Esprit, EspritBase
from src.utils.transaction_logger import transaction_logger, TransactionType
import logging

logger = logging.getLogger(__name__)

@dataclass
class CombatResult:
    """Result of a single attack in boss combat"""
    damage_dealt: int
    boss_current_hp: int
    boss_max_hp: int
    player_stamina: int
    player_max_stamina: int
    is_boss_defeated: bool
    attack_count: int
    total_damage: int

@dataclass
class VictoryReward:
    """Boss victory rewards"""
    jijies: int
    xp: int
    items: Dict[str, int]
    captured_esprit: Optional[Esprit]
    leveled_up: bool

@dataclass
class PendingCapture:
    """Represents an esprit waiting for capture decision"""
    esprit_base: EspritBase
    source: str
    preview_data: Dict[str, Any]
    
    def get_card_data(self) -> Dict[str, Any]:
        """Get data for esprit card generation"""
        return {
            "base": self.esprit_base,
            "name": self.esprit_base.name,
            "element": self.esprit_base.element,
            "tier": self.esprit_base.base_tier,
            "atk": self.esprit_base.base_atk,
            "def": self.esprit_base.base_def,
            "hp": getattr(self.esprit_base, 'base_hp', 100),
            "source": self.source
        }

class BossEncounter:
    """Domain object for boss combat - ALL boss logic lives here"""
    
    def __init__(self, boss_data: Dict[str, Any], quest_data: Dict[str, Any], area_data: Dict[str, Any]):
        self.boss_data = boss_data
        self.quest_data = quest_data
        self.area_data = area_data
        
        # Combat state
        self.max_hp = boss_data.get("max_hp", 1000)
        self.current_hp = boss_data.get("current_hp", self.max_hp)
        self.attack_count = 0
        self.total_damage_dealt = 0
        
        # Boss stats
        self.base_def = boss_data.get("base_def", 25)
        self.name = boss_data.get("name", "Unknown Boss")
        self.element = boss_data.get("element", "Unknown")
    
    @classmethod
    async def create_from_quest(cls, quest_data: Dict[str, Any], area_data: Dict[str, Any]) -> Optional['BossEncounter']:
        """Factory method to create boss encounter from quest data"""
        if not quest_data.get("is_boss"):
            return None
        
        boss_config = quest_data.get("boss_data", {})
        if not boss_config:
            return None
        
        # Pick random boss esprit
        possible_esprits = boss_config.get("possible_esprits", [])
        if not possible_esprits:
            return None
        
        chosen_esprit = random.choice(possible_esprits)
        
        # Get esprit data from database
        esprit_data = await cls._get_esprit_data(chosen_esprit)
        if not esprit_data:
            return None
        
        # Calculate boss HP
        hp_multiplier = boss_config.get("hp_multiplier", 3.0)
        base_hp = esprit_data.get("base_hp", 150)
        boss_max_hp = int(base_hp * hp_multiplier)
        
        # Build boss data
        boss_data = {
            "name": esprit_data.get("name", chosen_esprit),
            "element": esprit_data.get("element", "Unknown"),
            "current_hp": boss_max_hp,
            "max_hp": boss_max_hp,
            "base_def": esprit_data.get("base_def", 25),
            "bonus_jijies_multiplier": boss_config.get("bonus_jijies_multiplier", 2.0),
            "bonus_xp_multiplier": boss_config.get("bonus_xp_multiplier", 3.0)
        }
        
        return cls(boss_data, quest_data, area_data)
    
    @staticmethod
    async def _get_esprit_data(esprit_name: str) -> Optional[Dict[str, Any]]:
        """Get ACTUAL esprit data from database"""
        from src.utils.database_service import DatabaseService
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Find the actual esprit in database
                stmt = select(EspritBase).where(EspritBase.name.ilike(f"%{esprit_name}%"))
                esprit_base = (await session.execute(stmt)).scalar_one_or_none()
                
                if esprit_base:
                    return {
                        "name": esprit_base.name,
                        "element": esprit_base.element,
                        "base_hp": getattr(esprit_base, 'base_hp', 150),
                        "base_atk": esprit_base.base_atk,
                        "base_def": esprit_base.base_def
                    }
                else:
                    # Fallback with reasonable defaults
                    return {
                        "name": esprit_name,
                        "element": "Verdant",
                        "base_hp": 300,
                        "base_atk": 75,
                        "base_def": 35
                    }
        except Exception as e:
            logger.error(f"Failed to get esprit data for {esprit_name}: {e}")
            # Emergency fallback
            return {
                "name": esprit_name,
                "element": "Verdant", 
                "base_hp": 300,
                "base_atk": 75,
                "base_def": 35
            }
    
    async def process_attack(self, session: AsyncSession, player: Player) -> Optional[CombatResult]:
        """Process a single attack against the boss"""
        # Regenerate stamina
        player.regenerate_stamina()
        
        # Check stamina
        stamina_cost = 1
        if player.stamina < stamina_cost:
            return None
        
        # Consume stamina
        if not await player.consume_stamina(session, stamina_cost, f"boss_attack_{self.quest_data['id']}"):
            return None
        
        # Calculate damage using player's actual attack power
        player_attack = await player.get_total_attack(session)
        damage = self._calculate_damage(player_attack)
        
        # Apply damage
        self.current_hp = max(0, self.current_hp - damage)
        self.attack_count += 1
        self.total_damage_dealt += damage
        
        return CombatResult(
            damage_dealt=damage,
            boss_current_hp=self.current_hp,
            boss_max_hp=self.max_hp,
            player_stamina=player.stamina,
            player_max_stamina=player.max_stamina,
            is_boss_defeated=self.is_defeated(),
            attack_count=self.attack_count,
            total_damage=self.total_damage_dealt
        )
    
    def _calculate_damage(self, player_attack: int) -> int:
        """Calculate damage dealt - pure HP sponge, no defense logic"""
        # Raw attack power with variance (proper MW style)
        multiplier = 1.0 + random.uniform(-0.15, 0.15)
        base_damage = int(player_attack * multiplier)
        
        # Critical hit chance (10% for 50% bonus)
        if random.random() < 0.1:
            base_damage = int(base_damage * 1.5)
            
        return max(1, base_damage)  # Always deal at least 1 damage
    
    def is_defeated(self) -> bool:
        """Check if boss is defeated"""
        return self.current_hp <= 0
    
    async def process_victory(self, session: AsyncSession, player: Player) -> VictoryReward:
        """Process boss victory and rewards"""
        # Calculate rewards
        base_jijies = self.quest_data.get("rewards", {}).get("jijies", 100)
        base_xp = self.quest_data.get("rewards", {}).get("xp", 50)
        
        # Apply boss bonuses
        jijies_bonus = self.boss_data.get("bonus_jijies_multiplier", 2.0)
        xp_bonus = self.boss_data.get("bonus_xp_multiplier", 3.0)
        
        final_jijies = int(base_jijies * jijies_bonus)
        final_xp = int(base_xp * xp_bonus)
        
        # Apply rewards to player
        old_jijies = player.jijies
        old_level = player.level
        
        player.jijies += final_jijies
        player.experience += final_xp
        
        # Check level up
        leveled_up = await player._check_level_up(session)
        
        # Boss capture chance (guaranteed for now)
        captured_esprit = await self._attempt_boss_capture(session, player)
        
        # Log rewards
        if player.id is not None:
            transaction_logger.log_transaction(
                player_id=player.id,
                transaction_type=TransactionType.CURRENCY_GAIN,
                details={
                    "amount": final_jijies,
                    "reason": f"boss_victory_{self.quest_data['id']}",
                    "old_balance": old_jijies,
                    "new_balance": player.jijies,
                    "boss_name": self.name
                }
            )
        
        return VictoryReward(
            jijies=final_jijies,
            xp=final_xp,
            items={},  # TODO: Add items system
            captured_esprit=captured_esprit,
            leveled_up=leveled_up
        )
    
    async def _attempt_boss_capture(self, session: AsyncSession, player: Player) -> Optional[Esprit]:
        """Attempt to capture the boss (guaranteed for now)"""
        # Find the boss esprit base
        stmt = select(EspritBase).where(EspritBase.name.ilike(self.name))
        result = await session.execute(stmt)
        boss_base = result.scalar_one_or_none()
        
        if not boss_base or boss_base.id is None or not player.id:
            return None
        
        # Create captured esprit
        new_esprit = Esprit(
            esprit_base_id=boss_base.id,
            owner_id=player.id,
            quantity=1,
            tier=boss_base.base_tier,
            element=boss_base.element
        )
        
        session.add(new_esprit)
        
        # Log capture
        if player.id is not None:
            transaction_logger.log_transaction(
                player_id=player.id,
                transaction_type=TransactionType.ESPRIT_CAPTURED,
                details={
                    "amount": 1,
                    "reason": f"boss_capture_{self.quest_data['id']}",
                    "esprit_name": boss_base.name,
                    "element": boss_base.element,
                    "tier": boss_base.base_tier
                }
            )
        
        return new_esprit
    
    def get_combat_display_data(self) -> Dict[str, Any]:
        """Get data for combat UI display"""
        hp_percent = self.current_hp / self.max_hp if self.max_hp > 0 else 0
        
        return {
            "name": self.name,
            "element": self.element,
            "current_hp": self.current_hp,
            "max_hp": self.max_hp,
            "hp_percent": hp_percent,
            "attack_count": self.attack_count,
            "total_damage": self.total_damage_dealt,
            "color": self._get_hp_color(hp_percent)
        }
    
    def _get_hp_color(self, hp_percent: float) -> int:
        """Get color based on HP percentage"""
        if hp_percent > 0.6:
            return 0xff4444  # Red - healthy
        elif hp_percent > 0.3:
            return 0xffa500  # Orange - wounded
        else:
            return 0xffff00  # Yellow - almost dead

class CaptureSystem:
    """Domain object for capture logic with proper MW-style calculations"""
    
    @staticmethod
    async def attempt_capture(
        session: AsyncSession, 
        player: Player, 
        area_data: Dict[str, Any]
    ) -> Optional[PendingCapture]:
        """Attempt to generate a potential capture"""
        capturable_tiers = area_data.get("capturable_tiers", [])
        if not capturable_tiers:
            return None
        
        # Base capture chance
        base_chance = 0.15
        
        # Apply bonuses
        final_chance = await CaptureSystem._calculate_capture_chance(session, player, base_chance, area_data)
        
        if random.random() < final_chance:
            # Find potential esprit
            chosen_base = await CaptureSystem._select_esprit(session, area_data, capturable_tiers)
            
            if chosen_base:
                return PendingCapture(
                    esprit_base=chosen_base,
                    source=area_data.get("name", "quest"),
                    preview_data={
                        "capture_chance": final_chance,
                        "base_chance": base_chance,
                        "area_element": area_data.get("element_affinity")
                    }
                )
        
        return None
    
    @staticmethod
    async def _calculate_capture_chance(
        session: AsyncSession,
        player: Player,
        base_chance: float,
        area_data: Dict[str, Any]
    ) -> float:
        """Calculate final capture chance with all bonuses"""
        final_chance = base_chance
        
        # Area-specific bonuses
        area_bonus = area_data.get("capture_bonus", 0.0)
        final_chance += area_bonus
        
        # Player level bonus
        level_bonus = player.level * 0.001  # 0.1% per level
        final_chance += level_bonus
        
        return min(0.8, final_chance)  # Cap at 80%
    
    @staticmethod
    async def _select_esprit(
        session: AsyncSession,
        area_data: Dict[str, Any],
        capturable_tiers: List[int]
    ) -> Optional[EspritBase]:
        """Select an esprit to potentially capture"""
        # Get all esprits that match the capturable tiers
        stmt = select(EspritBase).where(EspritBase.base_tier.in_(capturable_tiers))
        result = await session.execute(stmt)
        potential_esprits = result.scalars().all()
        
        if not potential_esprits:
            return None
        
        # Element affinity bias
        area_element = area_data.get("element_affinity")
        if area_element:
            # 60% chance to pick matching element
            matching_element = [e for e in potential_esprits if e.element.lower() == area_element.lower()]
            if matching_element and random.random() < 0.6:
                return random.choice(matching_element)
        
        # Random selection from all potential
        return random.choice(potential_esprits)