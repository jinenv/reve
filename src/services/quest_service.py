# src/services/quest_service.py
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from sqlalchemy import select
import random

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.game_constants import GameConstants
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class CaptureCalculationResult:
    """Result of capture probability calculation"""
    base_capture_chance: float
    final_capture_chance: float
    bonuses_applied: Dict[str, float]
    area_modifiers: Dict[str, float]
    success_guaranteed: bool

@dataclass
class AreaAnalysisResult:
    """Comprehensive analysis of a quest area"""
    area_id: str
    difficulty_rating: float
    capturable_tiers: List[int]
    element_affinity: Optional[str]
    level_requirement: int
    recommended_power: int
    expected_rewards: Dict[str, Any]

class QuestService(BaseService):
    """Service for quest operations, area analysis, and capture mechanics"""
    
    @classmethod
    async def calculate_capture_probability(
        cls,
        player_id: int,
        area_data: Dict[str, Any],
        apply_bonuses: bool = True
    ) -> ServiceResult[CaptureCalculationResult]:
        """
        Calculate comprehensive capture probability with all modifiers.
        Includes base rates, area modifiers, and player bonuses.
        """
        async def _operation():
            # Get base capture chance from GameConstants
            base_capture_chance = GameConstants.BASE_CAPTURE_CHANCE
            
            area_modifiers = {}
            bonuses_applied = {}
            final_chance = base_capture_chance
            
            # Apply area-specific modifiers
            area_capture_modifier = area_data.get("capture_rate_modifier", 1.0)
            if area_capture_modifier != 1.0:
                area_modifiers["area_modifier"] = area_capture_modifier
                final_chance *= area_capture_modifier
            
            # Apply difficulty-based modifiers
            difficulty = area_data.get("difficulty", 1.0)
            if difficulty > 1.0:
                difficulty_penalty = 1.0 / difficulty
                area_modifiers["difficulty_penalty"] = difficulty_penalty
                final_chance *= difficulty_penalty
            
            if apply_bonuses:
                # Get player and apply bonuses
                async with DatabaseService.get_session() as session:
                    stmt = select(Player).where(Player.id == player_id) # type: ignore
                    player = (await session.execute(stmt)).scalar_one()
                    
                    # Apply leader bonuses
                    leader_bonuses = await player.get_leader_bonuses(session)
                    element_bonuses = leader_bonuses.get("bonuses", {})
                    
                    capture_bonus = element_bonuses.get("capture_bonus", 0)
                    if capture_bonus > 0:
                        bonuses_applied["leader_capture_bonus"] = capture_bonus
                        final_chance *= (1 + capture_bonus)
                    
                    # Apply element affinity bonus
                    area_element = area_data.get("element_affinity")
                    leader_element = leader_bonuses.get("element")
                    if area_element and leader_element and area_element.lower() == leader_element.lower():
                        element_affinity_bonus = 0.2  # 20% bonus for matching element
                        bonuses_applied["element_affinity"] = element_affinity_bonus
                        final_chance *= (1 + element_affinity_bonus)
                    
                    # Apply level-based bonus (higher level = slightly better capture)
                    level_bonus = min(player.level * 0.001, 0.1)  # Max 10% bonus at level 100
                    if level_bonus > 0:
                        bonuses_applied["level_bonus"] = level_bonus
                        final_chance *= (1 + level_bonus)
                    
                    # Apply skill-based bonuses (if any skills affect capture in the future)
                    skill_bonuses = player.get_skill_bonuses()
                    # Placeholder for potential capture-affecting skills
            
            # Cap the final chance (never 100% unless guaranteed)
            final_chance = min(final_chance, 0.95)
            
            # Check for guaranteed capture conditions
            success_guaranteed = area_data.get("guaranteed_capture", False)
            if success_guaranteed:
                final_chance = 1.0
            
            return CaptureCalculationResult(
                base_capture_chance=base_capture_chance,
                final_capture_chance=final_chance,
                bonuses_applied=bonuses_applied,
                area_modifiers=area_modifiers,
                success_guaranteed=success_guaranteed
            )
        
        return await cls._safe_execute(_operation, f"calculate capture probability for player {player_id}")

    @classmethod
    async def analyze_quest_area(
        cls,
        area_id: str,
        player_level: Optional[int] = None
    ) -> ServiceResult[AreaAnalysisResult]:
        """
        Provide comprehensive analysis of a quest area.
        Includes difficulty assessment, rewards analysis, and recommendations.
        """
        async def _operation():
            quests_config = ConfigManager.get("quests")
            if not quests_config or area_id not in quests_config:
                raise ValueError(f"Area {area_id} not found in configuration")
            
            area_data = quests_config[area_id]
            
            # Calculate difficulty rating
            base_difficulty = area_data.get("difficulty", 1.0)
            level_requirement = area_data.get("level_requirement", 1)
            
            # Adjust difficulty based on player level if provided
            difficulty_rating = base_difficulty
            if player_level:
                level_factor = max(1.0, (level_requirement / player_level) ** 0.5)
                difficulty_rating *= level_factor
            
            # Analyze capturable content
            capturable_tiers = area_data.get("capturable_tiers", [])
            element_affinity = area_data.get("element_affinity")
            
            # Calculate recommended power
            if capturable_tiers:
                max_tier = max(capturable_tiers)
                # Rough power calculation based on tier
                recommended_power = cls._estimate_recommended_power(max_tier, difficulty_rating)
            else:
                recommended_power = 1000  # Default minimum
            
            # Analyze expected rewards
            expected_rewards = cls._analyze_area_rewards(area_data)
            
            return AreaAnalysisResult(
                area_id=area_id,
                difficulty_rating=difficulty_rating,
                capturable_tiers=capturable_tiers,
                element_affinity=element_affinity,
                level_requirement=level_requirement,
                recommended_power=recommended_power,
                expected_rewards=expected_rewards
            )
        
        return await cls._safe_execute(_operation, f"analyze quest area {area_id}")

    @classmethod
    async def optimize_quest_strategy(
        cls,
        player_id: int,
        goal: str = "experience"
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Provide optimal quest strategy recommendations based on player state and goals.
        Goals: 'experience', 'capture', 'efficiency', 'progression'
        """
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get available areas
                quests_config = ConfigManager.get("quests")
                if not quests_config:
                    raise ValueError("No quest configuration found")
                
                available_areas = []
                for area_id, area_data in quests_config.items():
                    if player.can_access_area(area_id):
                        analysis = await cls.analyze_quest_area(area_id, player.level)
                        if analysis.success:
                            available_areas.append((area_id, area_data, analysis.data))
                
                recommendations = {
                    "goal": goal,
                    "player_level": player.level,
                    "current_energy": player.energy,
                    "recommended_areas": [],
                    "strategy_notes": [],
                    "efficiency_tips": []
                }
                
                if goal == "experience":
                    # Prioritize areas with best XP/energy ratio
                    for area_id, area_data, analysis in available_areas:
                        xp_reward = cls._extract_xp_reward(area_data)
                        energy_cost = area_data.get("energy_cost", 10)
                        xp_efficiency = xp_reward / energy_cost if energy_cost > 0 else 0
                        
                        recommendations["recommended_areas"].append({
                            "area_id": area_id,
                            "xp_efficiency": xp_efficiency,
                            "energy_cost": energy_cost,
                            "xp_reward": xp_reward
                        })
                    
                    # Sort by efficiency
                    recommendations["recommended_areas"].sort(key=lambda x: x["xp_efficiency"], reverse=True)
                    recommendations["strategy_notes"].append("Focus on highest XP/energy ratio areas")
                    
                elif goal == "capture":
                    # Prioritize areas with best capture opportunities
                    for area_id, area_data, analysis in available_areas:
                        capture_calc = await cls.calculate_capture_probability(player_id, area_data)
                        if capture_calc.success:
                            capture_value = cls._calculate_capture_value(analysis.capturable_tiers)
                            
                            recommendations["recommended_areas"].append({
                                "area_id": area_id,
                                "capture_chance": capture_calc.data.final_capture_chance if capture_calc.data else 0.0,
                                "capture_value": capture_value,
                                "capturable_tiers": analysis.capturable_tiers
                            })
                    
                    # Sort by capture value * chance
                    recommendations["recommended_areas"].sort(
                        key=lambda x: x["capture_chance"] * x["capture_value"], 
                        reverse=True
                    )
                    recommendations["strategy_notes"].append("Target areas with valuable captures and good success rates")
                    
                elif goal == "efficiency":
                    # Balance all factors for overall efficiency
                    for area_id, area_data, analysis in available_areas:
                        energy_cost = area_data.get("energy_cost", 10)
                        xp_reward = cls._extract_xp_reward(area_data)
                        
                        # Calculate overall efficiency score
                        efficiency_score = (xp_reward / energy_cost) * analysis.difficulty_rating
                        
                        recommendations["recommended_areas"].append({
                            "area_id": area_id,
                            "efficiency_score": efficiency_score,
                            "energy_cost": energy_cost,
                            "difficulty": analysis.difficulty_rating
                        })
                    
                    recommendations["recommended_areas"].sort(key=lambda x: x["efficiency_score"], reverse=True)
                    recommendations["strategy_notes"].append("Balanced approach optimizing time and energy")
                
                # Add general efficiency tips
                recommendations["efficiency_tips"] = [
                    f"Current energy: {player.energy}/{player.max_energy}",
                    "Use leader bonuses that match area elements",
                    "Consider regeneration time vs immediate questing"
                ]
                
                if player.energy < player.max_energy * 0.5:
                    recommendations["efficiency_tips"].append("⚠️ Low energy - consider waiting for regeneration")
                
                return recommendations
        
        return await cls._safe_execute(_operation, f"optimize quest strategy for player {player_id}")

    @classmethod
    async def simulate_quest_outcomes(
        cls,
        player_id: int,
        area_id: str,
        attempts: int = 10,
        use_current_energy: bool = True
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Simulate multiple quest attempts to show expected outcomes.
        Useful for planning and decision making.
        """
        async def _operation():
            quests_config = ConfigManager.get("quests")
            if not quests_config or area_id not in quests_config:
                raise ValueError(f"Area {area_id} not found")
            
            # Use actual_attempts everywhere - NEVER reassign attempts parameter
            actual_attempts = attempts
            area_data = quests_config[area_id]
            energy_cost = area_data.get("energy_cost", 10)
            
            # Check if player has enough energy
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if use_current_energy:
                    max_attempts = player.energy // energy_cost
                    actual_attempts = min(actual_attempts, max_attempts)  # ✅ Update actual_attempts
            
            if actual_attempts <= 0:  # ✅ Use actual_attempts
                return {
                    "attempts": 0,
                    "reason": "Insufficient energy",
                    "energy_needed": energy_cost,
                    "current_energy": player.energy if use_current_energy else "Not checked"
                }
            
            # Get capture probability
            capture_calc = await cls.calculate_capture_probability(player_id, area_data)
            if not capture_calc.success:
                raise ValueError("Failed to calculate capture probability")
            
            capture_chance = capture_calc.data.final_capture_chance if capture_calc.data else 0.0
            
            # Simulate attempts
            simulation_results = {
                "attempts": actual_attempts,  # ✅ Use actual_attempts
                "energy_cost": energy_cost * actual_attempts,  # ✅ Use actual_attempts
                "captures": 0,
                "total_xp": 0,
                "total_revies": 0,
                "captured_esprits": [],
                "success_rate": 0.0
            }
            
            xp_reward = cls._extract_xp_reward(area_data)
            revies_range = area_data.get("revies_reward", [50, 100])
            
            for attempt in range(actual_attempts):  # ✅ Use actual_attempts
                # Always get quest rewards
                simulation_results["total_xp"] += xp_reward
                revies_gain = random.randint(revies_range[0], revies_range[1])
                simulation_results["total_revies"] += revies_gain
                
                # Check for capture
                if random.random() < capture_chance:
                    simulation_results["captures"] += 1
                    # Simulate which esprit would be captured
                    capturable_tiers = area_data.get("capturable_tiers", [])
                    if capturable_tiers:
                        captured_tier = random.choice(capturable_tiers)
                        simulation_results["captured_esprits"].append({
                            "tier": captured_tier,
                            "attempt": attempt + 1
                        })
            
            simulation_results["success_rate"] = (simulation_results["captures"] / actual_attempts * 100) if actual_attempts > 0 else 0  # ✅ Use actual_attempts
            
            # Add efficiency metrics
            simulation_results["xp_per_energy"] = simulation_results["total_xp"] / (energy_cost * actual_attempts) if actual_attempts > 0 else 0  # ✅ Use actual_attempts
            simulation_results["captures_per_energy"] = simulation_results["captures"] / (energy_cost * actual_attempts) if actual_attempts > 0 else 0  # ✅ Use actual_attempts
            
            return simulation_results
        
        return await cls._safe_execute(_operation, f"simulate quest outcomes for {area_id}")

    @classmethod
    def _estimate_recommended_power(cls, max_tier: int, difficulty: float) -> int:
        """Estimate recommended power for an area based on max tier and difficulty"""
        # Base power estimation per tier (rough calculation)
        base_power_per_tier = {
            1: 100, 2: 200, 3: 400, 4: 800, 5: 1600,
            6: 3200, 7: 6400, 8: 12800, 9: 25600, 10: 51200,
            11: 102400, 12: 204800
        }
        
        base_power = base_power_per_tier.get(max_tier, 1000)
        return int(base_power * difficulty * 0.7)  # Recommend 70% of estimated max power

    @classmethod
    def _analyze_area_rewards(cls, area_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the reward structure of an area"""
        rewards = {}
        
        # XP rewards
        xp_reward = cls._extract_xp_reward(area_data)
        rewards["xp"] = xp_reward
        
        # Currency rewards
        revies_range = area_data.get("revies_reward", [0, 0])
        rewards["revies_min"] = revies_range[0]
        rewards["revies_max"] = revies_range[1]
        rewards["revies_avg"] = sum(revies_range) / 2
        
        # Capture rewards
        capturable_tiers = area_data.get("capturable_tiers", [])
        if capturable_tiers:
            rewards["capture_tiers"] = capturable_tiers
            rewards["capture_value"] = cls._calculate_capture_value(capturable_tiers)
        
        return rewards

    @classmethod
    def _extract_xp_reward(cls, area_data: Dict[str, Any]) -> int:
        """Extract XP reward from area data"""
        quests = area_data.get("quests", [])
        if quests:
            # Return average XP across all quests in the area
            total_xp = sum(quest.get("xp_reward", 0) for quest in quests)
            return total_xp // len(quests) if quests else 0
        return area_data.get("xp_reward", 50)  # Default XP

    @classmethod
    def _calculate_capture_value(cls, capturable_tiers: List[int]) -> float:
        """Calculate the relative value of captures in an area"""
        if not capturable_tiers:
            return 0.0
        
        # Higher tiers are exponentially more valuable
        tier_values = {tier: 2 ** (tier - 1) for tier in capturable_tiers}
        return sum(tier_values.values()) / len(capturable_tiers)