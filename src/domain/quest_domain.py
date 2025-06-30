from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import random
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import Player, Esprit, EspritBase
from src.utils.transaction_logger import safe_log_transaction, TransactionType
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
        
        # Get esprit data (simplified for now)
        esprit_data = await cls._get_esprit_data(chosen_esprit)
        if not esprit_data:
            return None
        
        # Calculate boss HP
        hp_multiplier = boss_config.get("hp_multiplier", 3.0)
        base_hp = esprit_data.get("base_hp", 100)
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
        """Get esprit data - stub for now"""
        # TODO: Get from EspritBase model
        return {
            "name": esprit_name,
            "element": "Verdant",
            "base_hp": 100,
            "base_atk": 50,
            "base_def": 25
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
        
        # Calculate damage
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
        """Calculate damage dealt"""
        base_damage = max(1, player_attack - self.base_def)
        # Add 20% variance
        multiplier = 1.0 + random.uniform(-0.2, 0.2)
        return int(base_damage * multiplier)
    
    def is_defeated(self) -> bool:
        """Check if boss is defeated"""
        return self.current_hp <= 0
    
    async def handle_victory(self, session: AsyncSession, player: Player) -> VictoryReward:
        """Handle boss defeat and distribute rewards"""
        # Calculate rewards
        base_jijies = self.quest_data.get("jijies_reward", [100, 300])
        base_xp = self.quest_data.get("xp_reward", 10)
        jijies_mult = self.boss_data.get("bonus_jijies_multiplier", 2.0)
        xp_mult = self.boss_data.get("bonus_xp_multiplier", 3.0)
        
        if isinstance(base_jijies, list):
            reward_jijies = random.randint(int(base_jijies[0] * jijies_mult), int(base_jijies[1] * jijies_mult))
        else:
            reward_jijies = int(base_jijies * jijies_mult)
        
        reward_xp = int(base_xp * xp_mult)
        
        # Apply rewards
        await player.add_currency(session, "jijies", reward_jijies, f"boss_defeat_{self.quest_data['id']}")
        leveled_up = await player.add_experience(session, reward_xp)
        
        # Record quest completion
        player.record_quest_completion(
            self.area_data.get("id", "unknown"), 
            self.quest_data["id"]
        )
        
        # Guaranteed boss capture
        captured_esprit = await self._capture_boss(session, player)
        
        # Item drops
        item_drops = self._get_item_drops()
        if item_drops:
            if player.inventory is None:
                player.inventory = {}
            for item, qty in item_drops.items():
                player.inventory[item] = player.inventory.get(item, 0) + qty
                if player.id:
                    safe_log_transaction(
                        player.id, TransactionType.ITEM_GAINED,
                        item=item, quantity=qty, source=f"boss_defeat_{self.quest_data['id']}"
                    )
        
        return VictoryReward(
            jijies=reward_jijies,
            xp=reward_xp,
            items=item_drops,
            captured_esprit=captured_esprit,
            leveled_up=leveled_up
        )
    
    async def _capture_boss(self, session: AsyncSession, player: Player) -> Optional[Esprit]:
        """Guaranteed boss capture"""
        from sqlalchemy import select
        
        # Find boss esprit in database
        stmt = select(EspritBase).where(EspritBase.name.ilike(self.boss_data['name']))
        boss_base = (await session.execute(stmt)).scalar_one_or_none()
        
        if boss_base and player.id is not None:
            # Add to collection
            new_stack = await Esprit.add_to_collection(
                session=session,
                owner_id=player.id,
                base=boss_base,
                quantity=1
            )
            
            # Log capture
            safe_log_transaction(
                player.id, TransactionType.ESPRIT_CAPTURED,
                name=boss_base.name, tier=boss_base.base_tier,
                element=boss_base.element, source="boss_capture"
            )
            
            # Update power
            await player.recalculate_total_power(session)
            
            return new_stack
        
        return None
    
    def _get_item_drops(self) -> Dict[str, int]:
        """Get boss item drops"""
        quest_id = self.quest_data.get("id", "")  # Default to empty string
        boss_drops = {
            "1-8": {"faded_echo": 1},
            "1-16": {"vivid_echo": 1, "erythl": 2},
            "1-24": {"vivid_echo": 1, "erythl": 5, "energy_potion": 3}
        }
        
        return boss_drops.get(quest_id, {})
    
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
        """Attempt to generate a potential capture with full MW-accurate bonuses"""
        from src.utils.game_constants import GameConstants
        from sqlalchemy import select
        
        capturable_tiers = area_data.get("capturable_tiers", [])
        if not capturable_tiers:
            return None
        
        # Base capture chance from GameConstants
        base_chance = GameConstants.BASE_CAPTURE_CHANCE
        
        # Apply leader bonuses (the full MW calculation)
        final_chance = await CaptureSystem._calculate_capture_chance(session, player, base_chance, area_data)
        
        if random.random() < final_chance:
            # Find potential esprit with element bias
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
        """Calculate final capture chance with all MW-accurate bonuses"""
        
        # Get leader bonuses (your beautiful element scaling system)
        leader_bonuses = await player.get_leader_bonuses(session)
        
        # Extract bonuses from the calculated leader effects
        bonuses = leader_bonuses.get("bonuses", {})
        capture_bonus = bonuses.get("capture_bonus", 0)
        
        # Apply leader bonus multiplicatively (MW style)
        chance_with_leader = base_chance * (1 + capture_bonus)
        
        # Area element synergy bonus (if leader matches area element)
        area_element = area_data.get("element_affinity")
        leader_element = leader_bonuses.get("element")
        
        synergy_bonus = 0.0
        if area_element and leader_element:
            if area_element.lower() == leader_element.lower():
                # 25% bonus for matching element (MW had this kind of synergy)
                synergy_bonus = 0.25
        
        # Apply synergy bonus
        final_chance = chance_with_leader * (1 + synergy_bonus)
        
        # Cap at reasonable maximum (95% like fusion success)
        return min(final_chance, 0.95)
    
    @staticmethod
    async def confirm_capture(
        session: AsyncSession,
        player: Player,
        pending_capture: PendingCapture
    ) -> Esprit:
        """Actually add the esprit to player's collection"""
        if player.id is None:
            raise ValueError("Player must have an ID")
        
        # Add to collection
        new_stack = await Esprit.add_to_collection(
            session=session,
            owner_id=player.id,
            base=pending_capture.esprit_base,
            quantity=1
        )
        
        # Log the capture
        safe_log_transaction(
            player.id, TransactionType.ESPRIT_CAPTURED,
            name=pending_capture.esprit_base.name,
            tier=pending_capture.esprit_base.base_tier,
            element=pending_capture.esprit_base.element,
            source=pending_capture.source
        )
        
        # Update power
        await player.recalculate_total_power(session)
        
        return new_stack