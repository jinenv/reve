# src/domain/quest_domain.py - COMPLETE PRODUCTION VERSION
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
        
        # Store boss esprit data for image generation
        self.boss_esprit_data = boss_data.get("esprit_data", {})
    
    @classmethod
    async def create_from_quest(cls, quest_data: Dict[str, Any], area_data: Dict[str, Any]) -> Optional['BossEncounter']:
        """Factory method to create boss encounter from quest data with COMPLETE implementation"""
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
        
        # Get COMPLETE esprit data from database including image_url
        esprit_data = await cls._get_complete_esprit_data(chosen_esprit)
        if not esprit_data:
            return None
        
        # Calculate boss HP with proper multiplier
        hp_multiplier = boss_config.get("hp_multiplier", 3.0)
        base_hp = esprit_data.get("base_hp", 150)
        boss_max_hp = int(base_hp * hp_multiplier)
        
        # Build COMPLETE boss data with image information
        boss_data = {
        "name": esprit_data.get("name", chosen_esprit),
        "element": esprit_data.get("element", "Unknown"),
        "current_hp": boss_max_hp,
        "max_hp": boss_max_hp,
        "base_def": esprit_data.get("base_def", 25),
        "bonus_jijies_multiplier": boss_config.get("bonus_jijies_multiplier", 2.0),
        "bonus_xp_multiplier": boss_config.get("bonus_xp_multiplier", 3.0),
        "image_url": esprit_data.get("image_url"),
        "sprite_path": esprit_data.get("image_url"),
        "esprit_data": esprit_data,
        "background": boss_config.get("background", "space_forest.png"),
    }
        
        logger.info(f"🎯 Created boss encounter: {boss_data['name']} with image: {boss_data.get('image_url')}")
        
        return cls(boss_data, quest_data, area_data)
    
    @staticmethod
    async def _get_complete_esprit_data(esprit_name: str) -> Optional[Dict[str, Any]]:
        """Get COMPLETE esprit data from database including image_url"""
        from src.utils.database_service import DatabaseService
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Find the actual esprit in database with exact or partial match
                stmt = select(EspritBase).where(EspritBase.name.ilike(f"%{esprit_name}%"))
                esprit_base = (await session.execute(stmt)).scalar_one_or_none()
                
                if esprit_base:
                    complete_data = {
                        "name": esprit_base.name,
                        "element": esprit_base.element,
                        "base_hp": getattr(esprit_base, 'base_hp', 150),
                        "base_atk": esprit_base.base_atk,
                        "base_def": esprit_base.base_def,
                        "base_tier": esprit_base.base_tier,
                        "image_url": esprit_base.image_url,  # CRITICAL for boss images
                        "portrait_url": getattr(esprit_base, 'portrait_url', None),
                        "description": getattr(esprit_base, 'description', ''),
                        "esprit_base_id": esprit_base.id
                    }
                    
                    logger.info(f"✅ Found complete esprit data for {esprit_name}: {complete_data['image_url']}")
                    return complete_data
                else:
                    logger.warning(f"❌ Esprit not found in database: {esprit_name}")
                    # Fallback with reasonable defaults but no image
                    return {
                        "name": esprit_name,
                        "element": "Verdant",
                        "base_hp": 300,
                        "base_atk": 75,
                        "base_def": 35,
                        "base_tier": 5,
                        "image_url": None,
                        "portrait_url": None,
                        "description": f"A mysterious {esprit_name} guardian.",
                        "esprit_base_id": None
                    }
        except Exception as e:
            logger.error(f"Failed to get esprit data for {esprit_name}: {e}")
            # Emergency fallback
            return {
                "name": esprit_name,
                "element": "Verdant", 
                "base_hp": 300,
                "base_atk": 75,
                "base_def": 35,
                "base_tier": 5,
                "image_url": None,
                "portrait_url": None,
                "description": f"A powerful {esprit_name} boss.",
                "esprit_base_id": None
            }
    
    async def process_attack(self, session: AsyncSession, player: Player) -> Optional[CombatResult]:
        """Process a single attack against the boss with proper combat logic"""
        # Regenerate stamina first
        player.regenerate_stamina()
        
        # Check stamina requirement
        stamina_cost = 1
        if player.stamina < stamina_cost:
            return None
        
        # Consume stamina with proper transaction logging
        if not await player.consume_stamina(session, stamina_cost, f"boss_attack_{self.quest_data['id']}"):
            return None
        
        # Calculate damage using player's TOTAL ATTACK POWER from all Esprits
        power_data = await player.recalculate_total_power(session)
        player_attack = power_data["atk"]  # This includes all Esprit stats + skill bonuses
        
        damage = self._calculate_damage_complete(player_attack)
        
        # Apply damage to boss
        self.current_hp = max(0, self.current_hp - damage)
        self.attack_count += 1
        self.total_damage_dealt += damage
        
        logger.debug(f"⚔️ Boss attack #{self.attack_count}: {damage} damage (ATK: {player_attack}), boss HP: {self.current_hp}/{self.max_hp}")
        
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
    
    def _calculate_damage_complete(self, player_attack: int) -> int:
        """COMPLETE damage calculation with Monster Warlord-style variance and boss defense"""
        # Base damage calculation: Attack vs Defense
        base_damage = max(1, player_attack - self.base_def)
        
        # Apply 15% variance (Monster Warlord style)
        variance_multiplier = 1.0 + random.uniform(-0.15, 0.15)
        variable_damage = int(base_damage * variance_multiplier)
        
        # Critical hit chance (10% for 50% bonus damage)
        if random.random() < 0.1:
            variable_damage = int(variable_damage * 1.5)
            logger.debug(f"💥 CRITICAL HIT: {variable_damage} damage!")
        
        # Ensure minimum damage (even if defense is higher than attack)
        final_damage = max(1, variable_damage)
        
        logger.debug(f"⚔️ Damage calc: {player_attack} ATK vs {self.base_def} DEF = {final_damage} damage")
        
        return final_damage
    
    def is_defeated(self) -> bool:
        """Check if boss is defeated"""
        return self.current_hp <= 0
    
    async def process_victory(self, session: AsyncSession, player: Player) -> VictoryReward:
        """Process boss victory and rewards with CORRECT quest reward structure"""
        # Get rewards from quest data (using ACTUAL structure from quests.json)
        jijies_range = self.quest_data.get("jijies_reward", [100, 300])
        base_xp = self.quest_data.get("xp_reward", 50)
        
        # Calculate base rewards
        if isinstance(jijies_range, list) and len(jijies_range) == 2:
            base_jijies = random.randint(jijies_range[0], jijies_range[1])
        else:
            base_jijies = int(jijies_range) if isinstance(jijies_range, (int, float)) else 100
        
        # Apply boss bonuses
        jijies_bonus = self.boss_data.get("bonus_jijies_multiplier", 2.0)
        xp_bonus = self.boss_data.get("bonus_xp_multiplier", 3.0)
        
        final_jijies = int(base_jijies * jijies_bonus)
        final_xp = int(base_xp * xp_bonus)
        
        # Store old values for logging
        old_jijies = player.jijies
        old_level = player.level
        
        # Apply rewards to player
        player.jijies += final_jijies
        
        # Add experience AND check for level up in one call
        leveled_up = await player.add_experience(session, final_xp)
        
        # Attempt boss capture (guaranteed for now, configurable later)
        captured_esprit = await self._attempt_boss_capture(session, player)
        
        # Log the victory transaction
        if player.id is not None:
            transaction_logger.log_transaction(
                player_id=player.id,
                transaction_type=TransactionType.CURRENCY_GAIN,
                details={
                    "amount": final_jijies,
                    "reason": f"boss_victory_{self.quest_data['id']}",
                    "old_balance": old_jijies,
                    "new_balance": player.jijies,
                    "boss_name": self.name,
                    "attacks_taken": self.attack_count,
                    "total_damage": self.total_damage_dealt
                }
            )
        
        logger.info(f"🏆 Boss victory: {self.name} defeated in {self.attack_count} attacks for {final_jijies:,} jijies")
        
        return VictoryReward(
            jijies=final_jijies,
            xp=final_xp,
            items={},  # TODO: Add items system later
            captured_esprit=captured_esprit,
            leveled_up=leveled_up
        )
    
    async def _attempt_boss_capture(self, session: AsyncSession, player: Player) -> Optional[Esprit]:
        """Attempt to capture the boss esprit (currently guaranteed)"""
        try:
            # Find the boss esprit base using the stored data
            esprit_base_id = self.boss_esprit_data.get("esprit_base_id")
            
            if esprit_base_id:
                # Use stored ID for direct lookup
                stmt = select(EspritBase).where(EspritBase.id == esprit_base_id)
            else:
                # Fallback to name lookup
                stmt = select(EspritBase).where(EspritBase.name.ilike(self.name))
            
            result = await session.execute(stmt)
            boss_base = result.scalar_one_or_none()
            
            if not boss_base or not boss_base.id or not player.id:
                logger.warning(f"❌ Cannot capture boss: missing boss_base ({boss_base}) or player ID ({player.id})")
                return None
            
            # Create captured esprit using the universal stack system
            new_esprit = await Esprit.add_to_collection(
                session=session,
                owner_id=player.id,
                base=boss_base,
                quantity=1
            )
            
            # Log the boss capture
            if player.id is not None:
                transaction_logger.log_transaction(
                    player_id=player.id,
                    transaction_type=TransactionType.ESPRIT_CAPTURED,
                    details={
                        "amount": 1,
                        "reason": f"boss_capture_{self.quest_data['id']}",
                        "esprit_name": boss_base.name,
                        "element": boss_base.element,
                        "tier": boss_base.base_tier,
                        "source": "boss_victory"
                    }
                )
            
            logger.info(f"🌟 Boss captured: {boss_base.name} (Tier {boss_base.base_tier})")
            return new_esprit
            
        except Exception as e:
            logger.error(f"Boss capture failed: {e}")
            return None
    
    def get_combat_display_data(self) -> Dict[str, Any]:
        """Get data for combat UI display with enhanced information"""
        hp_percent = self.current_hp / self.max_hp if self.max_hp > 0 else 0
        
        return {
            "name": self.name,
            "element": self.element,
            "current_hp": self.current_hp,
            "max_hp": self.max_hp,
            "hp_percent": hp_percent,
            "attack_count": self.attack_count,
            "total_damage": self.total_damage_dealt,
            "color": self._get_hp_color(hp_percent),
            "image_url": self.boss_data.get("image_url"),  # For image generation
            "base_def": self.base_def
        }
    
    def _get_hp_color(self, hp_percent: float) -> int:
        """Get color based on HP percentage"""
        if hp_percent > 0.6:
            return 0x00ff00  # Green - healthy
        elif hp_percent > 0.3:
            return 0xffa500  # Orange - wounded  
        else:
            return 0xff0000  # Red - critical

class CaptureSystem:
    """Domain object for capture logic with proper Monster Warlord-style calculations"""
    
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
        
        # Apply capture bonuses
        final_chance = await CaptureSystem._calculate_capture_chance(session, player, base_chance, area_data)
        
        # Roll for capture encounter
        if random.random() < final_chance:
            # Find potential esprit to capture
            chosen_base = await CaptureSystem._select_esprit_for_capture(session, area_data, capturable_tiers)
            
            if chosen_base:
                logger.info(f"🌟 Capture encounter: {chosen_base.name} (chance: {final_chance:.1%})")
                
                return PendingCapture(
                    esprit_base=chosen_base,
                    source=area_data.get("name", "quest"),
                    preview_data={
                        "capture_chance": final_chance,
                        "base_chance": base_chance,
                        "area_element": area_data.get("element_affinity"),
                        "player_level": player.level
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
        
        # Area-specific capture bonus
        area_bonus = area_data.get("capture_bonus", 0.0)
        final_chance += area_bonus
        
        # Player level bonus (0.1% per level)
        level_bonus = player.level * 0.001
        final_chance += level_bonus
        
        # TODO: Add equipment bonuses, leader bonuses, etc.
        
        # Cap at reasonable maximum
        return min(0.8, final_chance)
    
    @staticmethod
    async def _select_esprit_for_capture(
        session: AsyncSession,
        area_data: Dict[str, Any],
        capturable_tiers: List[int]
    ) -> Optional[EspritBase]:
        """Select an esprit to potentially capture with element affinity"""
        try:
            # Get all esprits that match the capturable tiers
            stmt = select(EspritBase).where(EspritBase.base_tier.in_(capturable_tiers))
            result = await session.execute(stmt)
            potential_esprits = result.scalars().all()
            
            if not potential_esprits:
                logger.warning(f"No capturable esprits found for tiers: {capturable_tiers}")
                return None
            
            # Apply element affinity bias (60% chance to pick matching element)
            area_element = area_data.get("element_affinity")
            if area_element:
                matching_element = [e for e in potential_esprits if e.element.lower() == area_element.lower()]
                if matching_element and random.random() < 0.6:
                    chosen = random.choice(matching_element)
                    logger.debug(f"🎯 Element affinity selection: {chosen.name} ({area_element})")
                    return chosen
            
            # Random selection from all potential esprits
            chosen = random.choice(potential_esprits)
            logger.debug(f"🎲 Random selection: {chosen.name}")
            return chosen
            
        except Exception as e:
            logger.error(f"Failed to select esprit for capture: {e}")
            return None

class QuestRewardCalculator:
    """Utility class for calculating quest rewards consistently"""
    
    @staticmethod
    def calculate_quest_rewards(quest_data: Dict[str, Any], player: Player) -> Dict[str, Any]:
        """Calculate rewards for normal quest completion"""
        rewards = {}
        
        # Calculate jijies reward
        jijies_range = quest_data.get("jijies_reward", [50, 150])
        if isinstance(jijies_range, list) and len(jijies_range) == 2:
            rewards["jijies"] = random.randint(jijies_range[0], jijies_range[1])
        else:
            rewards["jijies"] = int(jijies_range) if isinstance(jijies_range, (int, float)) else 50
        
        # Calculate XP reward
        rewards["xp"] = quest_data.get("xp_reward", 10)
        
        # TODO: Add item rewards when item system is implemented
        
        return rewards
    
    @staticmethod
    def apply_level_bonuses(rewards: Dict[str, Any], player_level: int) -> Dict[str, Any]:
        """Apply level-based bonuses to rewards"""
        # Small level bonus (1% per level up to 50%)
        level_bonus = min(0.5, player_level * 0.01)
        
        if "jijies" in rewards:
            rewards["jijies"] = int(rewards["jijies"] * (1 + level_bonus))
        
        if "xp" in rewards:
            rewards["xp"] = int(rewards["xp"] * (1 + level_bonus))
        
        return rewards

# Utility functions for backwards compatibility
async def create_boss_encounter(quest_data: Dict[str, Any], area_data: Dict[str, Any]) -> Optional[BossEncounter]:
    """Create boss encounter - backwards compatible function"""
    return await BossEncounter.create_from_quest(quest_data, area_data)

async def attempt_area_capture(session: AsyncSession, player: Player, area_data: Dict[str, Any]) -> Optional[PendingCapture]:
    """Attempt capture in area - backwards compatible function"""
    return await CaptureSystem.attempt_capture(session, player, area_data)