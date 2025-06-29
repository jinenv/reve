# src/utils/boss_encounter.py
import random
from typing import Dict, Any, Optional
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager

logger = get_logger(__name__)

class BossEncounterBuilder:
    """Builds boss encounter data from quest configuration"""
    
    @staticmethod
    def calculate_boss_rewards(boss_data: Dict[str, Any], base_quest_rewards: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate enhanced rewards for defeating a boss
        
        Args:
            boss_data: Boss encounter data
            base_quest_rewards: Base quest jijies/xp rewards
            
        Returns:
            Enhanced reward package
        """
        try:
            # Get multipliers
            jijies_mult = boss_data.get("bonus_jijies_multiplier", 2.0)
            xp_mult = boss_data.get("bonus_xp_multiplier", 3.0)
            
            # Calculate enhanced rewards
            base_jijies = base_quest_rewards.get("jijies_reward", [100, 300])
            base_xp = base_quest_rewards.get("xp_reward", 10)
            
            # Apply boss multipliers
            if isinstance(base_jijies, list):
                enhanced_jijies = [int(j * jijies_mult) for j in base_jijies]
            else:
                enhanced_jijies = int(base_jijies * jijies_mult)
            
            enhanced_xp = int(base_xp * xp_mult)
            
            rewards = {
                "jijies": enhanced_jijies,
                "xp": enhanced_xp,
                "guaranteed_items": boss_data.get("guaranteed_items", {}),
                "boss_tier": boss_data.get("tier", 1)
            }
            
            # Roll for rare drops
            rare_chance = boss_data.get("rare_drop_chance", 0.1)
            import random
            if random.random() < rare_chance:
                rewards["rare_drop"] = BossEncounterBuilder._get_rare_boss_drop(boss_data)
            
            logger.info(f"Boss {boss_data['name']} rewards: {enhanced_jijies} jijies, {enhanced_xp} xp")
            return rewards
            
        except Exception as e:
            logger.error(f"Error calculating boss rewards: {e}")
            return base_quest_rewards
    
    
    @staticmethod
    def _get_rare_boss_drop(boss_data: Dict[str, Any]) -> Dict[str, int]:
        """Get rare drop based on boss tier"""
        tier = boss_data.get("tier", 1)
        
        # Tier-appropriate rare drops
        if tier <= 2:
            return {"energy_potion": 1}
        elif tier <= 4:
            return {"xp_orb": 3}
        elif tier <= 6:
            return {"capture_charm": 1}
        else:
            return {"fusion_catalyst": 1}
        
    @staticmethod
    def create_boss_encounter(quest_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert quest boss_data into boss card data
        
        Args:
            quest_data: Quest with boss_data section
            
        Returns:
            Boss card data ready for image generation, or None if failed
        """
        try:
            if not quest_data.get("is_boss"):
                logger.warning("Tried to create boss encounter for non-boss quest")
                return None
            
            boss_config = quest_data.get("boss_data", {})
            if not boss_config:
                logger.error("Boss quest missing boss_data section")
                return None
            
            # Pick random esprit from possible list
            possible_esprits = boss_config.get("possible_esprits", [])
            if not possible_esprits:
                logger.error("No possible_esprits defined for boss")
                return None
            
            chosen_esprit_name = random.choice(possible_esprits)
            
            # Get esprit base data
            esprit_data = BossEncounterBuilder._get_esprit_data(chosen_esprit_name)
            if not esprit_data:
                logger.error(f"Could not find esprit data for {chosen_esprit_name}")
                return None
            
            # Calculate boss stats
            hp_multiplier = boss_config.get("hp_multiplier", 3.0)
            base_hp = esprit_data.get("base_hp", 100)
            boss_max_hp = int(base_hp * hp_multiplier)
            
            # Build boss encounter data (rewards, not captures!)
            boss_encounter = {
                "name": esprit_data.get("name", chosen_esprit_name),
                "element": esprit_data.get("element", "Unknown"),
                "background": boss_config.get("background", "space_default.png"),
                "current_hp": boss_max_hp,  # Start at full HP
                "max_hp": boss_max_hp,
                "base_atk": esprit_data.get("base_atk", 50),
                "base_def": esprit_data.get("base_def", 25),
                "tier": esprit_data.get("base_tier", 1),
                "hp_multiplier": hp_multiplier,
                # Boss rewards instead of capture
                "bonus_jijies_multiplier": boss_config.get("bonus_jijies_multiplier", 2.0),
                "bonus_xp_multiplier": boss_config.get("bonus_xp_multiplier", 3.0),
                "guaranteed_items": boss_config.get("guaranteed_items", {}),
                "rare_drop_chance": boss_config.get("rare_drop_chance", 0.1)
            }
            
            logger.info(f"Created boss encounter: {chosen_esprit_name} with {boss_max_hp} HP")
            return boss_encounter
            
        except Exception as e:
            logger.error(f"Failed to create boss encounter: {e}")
            return None
    
    @staticmethod
    def _get_esprit_data(esprit_name: str) -> Optional[Dict[str, Any]]:
        """Get esprit base data from esprits.json"""
        try:
            esprits_config = ConfigManager.get("esprits")
            if not esprits_config:
                logger.error("Could not load esprits config")
                return None
            
            esprits_list = esprits_config.get("esprits", [])
            
            # Find matching esprit (case insensitive)
            for esprit in esprits_list:
                if esprit.get("name", "").lower() == esprit_name.lower():
                    return esprit
            
            logger.warning(f"Esprit not found in config: {esprit_name}")
            return None
            
        except Exception as e:
            logger.error(f"Error loading esprit data for {esprit_name}: {e}")
            return None
    
    @staticmethod
    def update_boss_hp(boss_data: Dict[str, Any], damage_dealt: int) -> Dict[str, Any]:
        """
        Update boss HP after taking damage
        
        Args:
            boss_data: Current boss data
            damage_dealt: Damage to subtract from current HP
            
        Returns:
            Updated boss data with new current_hp
        """
        current_hp = boss_data.get("current_hp", 0)
        new_hp = max(0, current_hp - damage_dealt)
        
        boss_data["current_hp"] = new_hp
        
        logger.debug(f"Boss HP: {current_hp} -> {new_hp} (took {damage_dealt} damage)")
        return boss_data
    
    @staticmethod
    def is_boss_defeated(boss_data: Dict[str, Any]) -> bool:
        """Check if boss is defeated (HP <= 0)"""
        return boss_data.get("current_hp", 0) <= 0


# Example usage function for testing
async def test_boss_encounter():
    """Test function showing how to use the boss system"""
    
    # Sample quest data (like from your quests.json)
    sample_quest = {
        "id": "1-8", 
        "name": "Guardian of the Glade", 
        "is_boss": True,
        "boss_data": {
            "possible_esprits": ["Muddroot", "Boulderback", "Verdiant"],
            "hp_multiplier": 4.0,
            "background": "forest_nebula.png",
            "capture_guarantee": True
        }
    }
    
    # Create boss encounter
    boss_encounter = BossEncounterBuilder.create_boss_encounter(sample_quest)
    
    if boss_encounter:
        print(f"Boss created: {boss_encounter['name']}")
        print(f"Element: {boss_encounter['element']}")
        print(f"HP: {boss_encounter['current_hp']}/{boss_encounter['max_hp']}")
        print(f"Background: {boss_encounter['background']}")
        
        # Generate boss card
        from src.utils.boss_image_generator import generate_boss_card
        boss_file = await generate_boss_card(boss_encounter, "test_boss.png")
        
        return boss_file
    else:
        print("Failed to create boss encounter!")
        return None


# Integration with your quest system
def integrate_with_quest_cog():
    """
    Example of how to integrate this with your quest cog
    
    In your quest_cog.py, when a player hits a boss quest:
    """
    
    # Example quest flow:
    """
    # In your quest command when is_boss is True:
    
    if next_quest.get("is_boss"):
        # Create boss encounter
        boss_encounter = BossEncounterBuilder.create_boss_encounter(next_quest)
        
        if boss_encounter:
            # Generate boss card
            from src.utils.boss_image_generator import generate_boss_card
            boss_file = await generate_boss_card(boss_encounter, f"{boss_encounter['name']}_boss.png")
            
            # Show epic boss encounter
            embed = disnake.Embed(
                title=f"⚔️ BOSS ENCOUNTER!",
                description=f"A wild **{boss_encounter['name']}** appears!\n"
                           f"This {boss_encounter['element']} guardian blocks your path!",
                color=0xff4444
            )
            
            embed.add_field(
                name="Boss Stats",
                value=f"💚 **HP:** {boss_encounter['current_hp']:,}\n"
                     f"⚔️ **Tier:** {boss_encounter['tier']}\n"
                     f"🌟 **Element:** {boss_encounter['element']}",
                inline=True
            )
            
            # Auto-victory for now (or implement actual combat)
            if quest_config.get("always_auto_victory", True):
                embed.add_field(
                    name="⚔️ VICTORY!",
                    value=f"You defeated the {boss_encounter['name']}!\n"
                         f"{'🎁 **GUARANTEED CAPTURE!**' if boss_encounter['capture_guarantee'] else '🎲 Capture chance!'}",
                    inline=False
                )
                
                # Handle capture
                if boss_encounter['capture_guarantee']:
                    # Force capture the boss esprit
                    captured_esprit = await player.force_capture_esprit(session, boss_encounter['name'])
            
            # Send boss card + embed
            await inter.edit_original_response(embed=embed, file=boss_file)
        else:
            # Fallback if boss creation fails
            await inter.edit_original_response(content="Boss encounter failed to load!")
    """