# src/services/team_service.py
from typing import Dict, List, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.services.base_service import BaseService, ServiceResult
from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.ability_system import AbilitySystem
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.logger import get_logger

logger = get_logger(__name__)

class TeamService(BaseService):
    """Service for managing 3-Esprit combat teams"""
    
    @classmethod
    async def get_current_team(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's current team composition with full details"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                # Get player with team data
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    return {"error": "Player not found"}
                
                # Build team data
                team_data = {
                    "leader": None,
                    "support1": None,
                    "support2": None,
                    "total_team_power": 0,
                    "team_valid": False
                }
                
                # Get leader details
                if player.leader_esprit_stack_id:
                    leader_data = await cls._get_esprit_team_data(session, player.leader_esprit_stack_id, "leader")
                    if leader_data:
                        team_data["leader"] = leader_data
                
                # Get support details
                if hasattr(player, 'support1_esprit_stack_id') and player.support1_esprit_stack_id:
                    support1_data = await cls._get_esprit_team_data(session, player.support1_esprit_stack_id, "support")
                    if support1_data:
                        team_data["support1"] = support1_data
                
                if hasattr(player, 'support2_esprit_stack_id') and player.support2_esprit_stack_id:
                    support2_data = await cls._get_esprit_team_data(session, player.support2_esprit_stack_id, "support")
                    if support2_data:
                        team_data["support2"] = support2_data
                
                # Calculate total team power
                total_power = 0
                team_member_count = 0
                for role in ["leader", "support1", "support2"]:
                    member = team_data.get(role)
                    if member:
                        total_power += member.get("total_atk", 0) + member.get("total_def", 0)
                        team_member_count += 1
                
                team_data["total_team_power"] = total_power
                team_data["team_valid"] = team_member_count >= 1  # At least leader required
                team_data["team_member_count"] = team_member_count
                
                return team_data
        
        return await cls._safe_execute(_operation, "get current team")
    
    @classmethod
    async def _get_esprit_team_data(cls, session, esprit_id: int, role: str) -> Optional[Dict[str, Any]]:
        """Get detailed esprit data for team display"""
        try:
            # Get esprit with base data
            stmt = select(Esprit, EspritBase).where(
                Esprit.id == esprit_id,
                Esprit.esprit_base_id == EspritBase.id
            )
            result = (await session.execute(stmt)).first()
            
            if not result:
                return None
            
            esprit, base = result
            
            # Calculate individual power
            individual_power = esprit.get_individual_power(base)
            
            # Get abilities based on role
            if role == "leader":
                # Leader gets full ability summary
                ability_summary = base.get_ability_summary()
                ability_details = base.get_ability_details()
            else:
                # Support gets support skill
                support_skill = cls._get_support_skill(base.element, base.base_tier)
                ability_summary = f"Support: {support_skill['name']}"
                ability_details = {"support_skill": support_skill}
            
            return {
                "esprit_id": esprit.id,
                "name": base.name,
                "element": esprit.element,
                "tier": esprit.tier,
                "base_tier": base.base_tier,
                "awakening_level": esprit.awakening_level,
                "quantity": esprit.quantity,
                "total_atk": individual_power["atk"],
                "total_def": individual_power["def"],
                "total_hp": individual_power["hp"],
                "ability_summary": ability_summary,
                "ability_details": ability_details,
                "support_skill": cls._get_support_skill(base.element, base.base_tier) if role == "support" else None
            }
            
        except Exception as e:
            logger.error(f"Error getting esprit team data for {esprit_id}: {e}")
            return None
    
    @classmethod
    def _get_support_skill(cls, element: str, tier: int) -> Dict[str, Any]:
        """Get support skill based on element and tier with tier scaling"""
        # Base power scales with tier
        base_power = 80 + (tier * 3)  # 83 at tier 1, 116 at tier 12
        
        # Support skills are element-based with tier scaling
        support_skills = {
            "inferno": {
                "name": "Flame Boost",
                "description": f"+{15 + tier}% team attack for 2 turns",
                "type": "team_buff",
                "power": base_power,
                "cooldown": max(2, 4 - (tier // 3)),  # Cooldown reduces with tier
                "duration": 2,
                "effects": ["attack_boost"],
                "tier_bonus": f"+{tier}% attack boost"
            },
            "verdant": {
                "name": "Nature's Blessing", 
                "description": f"Heal {10 + tier}% HP and +{10 + tier}% defense for 3 turns",
                "type": "heal_buff",
                "power": base_power,
                "cooldown": max(3, 5 - (tier // 3)),
                "duration": 3,
                "effects": ["regeneration", "defense_boost"],
                "tier_bonus": f"+{tier}% healing and defense"
            },
            "tempest": {
                "name": "Lightning Speed",
                "description": f"Next attack has +{25 + (tier * 2)}% crit chance and +{tier * 5}% damage",
                "type": "crit_buff",
                "power": base_power,
                "cooldown": max(2, 4 - (tier // 4)),
                "duration": 1,
                "effects": ["critical_boost"],
                "tier_bonus": f"+{tier * 2}% crit, +{tier * 5}% damage"
            },
            "abyssal": {
                "name": "Tidal Barrier",
                "description": f"Reduce incoming damage by {20 + tier}% for {2 + (tier // 3)} turns",
                "type": "damage_reduction",
                "power": base_power,
                "cooldown": max(3, 5 - (tier // 3)),
                "duration": 2 + (tier // 3),
                "effects": ["damage_shield"],
                "tier_bonus": f"+{tier}% damage reduction"
            },
            "umbral": {
                "name": "Shadow Energy",
                "description": f"Restore {1 + (tier // 4)} stamina and +{10 + tier}% attack for 2 turns",
                "type": "resource_buff",
                "power": base_power,
                "cooldown": max(4, 6 - (tier // 3)),
                "duration": 2,
                "effects": ["stamina_restore", "attack_boost"],
                "tier_bonus": f"+{tier // 4} stamina restore"
            },
            "radiant": {
                "name": "Holy Light",
                "description": f"Remove all debuffs and heal {15 + tier}% HP",
                "type": "cleanse_heal",
                "power": base_power,
                "cooldown": max(3, 5 - (tier // 4)),
                "duration": 0,
                "effects": ["cleanse", "regeneration"],
                "tier_bonus": f"+{tier}% healing"
            }
        }
        
        return support_skills.get(element.lower(), {
            "name": "Basic Support",
            "description": "Provides minor team assistance",
            "type": "basic",
            "power": base_power,
            "cooldown": 3,
            "duration": 1,
            "effects": ["minor_boost"],
            "tier_bonus": "No special bonus"
        })
    
    @classmethod
    async def get_eligible_team_members(
        cls, 
        player_id: int, 
        role: str, 
        exclude_ids: Optional[List[int]] = None
    ) -> ServiceResult[List[Dict[str, Any]]]:
        """Get list of Esprits eligible for team positions"""
        async def _operation():
            if exclude_ids is None:
                exclude_ids = []
            
            async with DatabaseService.get_session() as session:
                # Get player's collection
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id,
                    Esprit.quantity > 0,
                    Esprit.esprit_base_id == EspritBase.id,
                    ~Esprit.id.in_(exclude_ids) if exclude_ids else True
                ).order_by(EspritBase.base_tier.desc(), EspritBase.name.asc())
                
                results = (await session.execute(stmt)).all()
                
                eligible_esprits = []
                
                for esprit, base in results:
                    # Calculate power
                    individual_power = esprit.get_individual_power(base)
                    
                    # Get support skill for preview (all roles show this)
                    support_skill = cls._get_support_skill(base.element, base.base_tier)
                    
                    # Get full ability details if leader role
                    ability_details = None
                    if role == "leader":
                        ability_details = base.get_ability_details()
                    
                    eligible_esprits.append({
                        "esprit_id": esprit.id,
                        "name": base.name,
                        "element": esprit.element,
                        "tier": esprit.tier,
                        "base_tier": base.base_tier,
                        "awakening_level": esprit.awakening_level,
                        "quantity": esprit.quantity,
                        "total_atk": individual_power["atk"],
                        "total_def": individual_power["def"],
                        "total_hp": individual_power["hp"],
                        "support_skill": support_skill,
                        "ability_details": ability_details,
                        "rarity": base.rarity if hasattr(base, 'rarity') else 'common'
                    })
                
                return eligible_esprits
        
        return await cls._safe_execute(_operation, f"get eligible {role} members")
    
    @classmethod
    async def update_team_member(
        cls, 
        player_id: int, 
        role: str, 
        esprit_id: Optional[int]
    ) -> ServiceResult[Dict[str, Any]]:
        """Update a team member position"""
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                # Get player with lock
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    return {"error": "Player not found"}
                
                # Validate esprit ownership if not None
                if esprit_id is not None:
                    esprit_stmt = select(Esprit, EspritBase).where(
                        Esprit.id == esprit_id,
                        Esprit.owner_id == player_id,
                        Esprit.quantity > 0,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                    esprit_result = (await session.execute(esprit_stmt)).first()
                    
                    if not esprit_result:
                        return {"error": "Esprit not found or not owned"}
                    
                    esprit, base = esprit_result
                
                # Store old value for logging
                old_esprit_id = None
                
                # Update the appropriate team slot
                if role == "leader":
                    old_esprit_id = player.leader_esprit_stack_id
                    player.leader_esprit_stack_id = esprit_id
                elif role == "support1":
                    old_esprit_id = getattr(player, 'support1_esprit_stack_id', None)
                    player.support1_esprit_stack_id = esprit_id
                elif role == "support2":
                    old_esprit_id = getattr(player, 'support2_esprit_stack_id', None)
                    player.support2_esprit_stack_id = esprit_id
                else:
                    return {"error": f"Invalid role: {role}"}
                
                player.update_activity()
                await session.commit()
                
                # Log the change
                transaction_logger.log_transaction(
                    player_id=player_id,
                    transaction_type=TransactionType.TEAM_UPDATED,
                    details={
                        "role": role,
                        "old_esprit_id": old_esprit_id,
                        "new_esprit_id": esprit_id,
                        "esprit_name": base.name if esprit_id else None,
                        "esprit_tier": base.base_tier if esprit_id else None,
                        "timestamp": player.last_active.isoformat()
                    }
                )
                
                return {
                    "role": role,
                    "old_esprit_id": old_esprit_id,
                    "new_esprit_id": esprit_id,
                    "esprit_name": base.name if esprit_id else None,
                    "success": True
                }
        
        return await cls._safe_execute(_operation, f"update team {role}")
    
    @classmethod
    async def get_combat_team_abilities(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get team's available abilities for combat (used by CombatService)"""
        async def _operation():
            team_result = await cls.get_current_team(player_id)
            if not team_result.success:
                return {"error": "Failed to load team"}
            
            team_data = team_result.data
            combat_abilities = {
                "leader_abilities": {},
                "support_abilities": [],
                "team_power": team_data.get("total_team_power", 0),
                "leader_tier": 1,  # Default
                "team_elements": []
            }
            
            # Get leader abilities and tier
            leader = team_data.get("leader")
            if leader:
                combat_abilities["leader_abilities"] = leader.get("ability_details", {})
                combat_abilities["leader_tier"] = leader.get("base_tier", 1)
                combat_abilities["team_elements"].append(leader.get("element"))
            
            # Get support abilities
            for support_role in ["support1", "support2"]:
                support = team_data.get(support_role)
                if support and support.get("support_skill"):
                    combat_abilities["support_abilities"].append({
                        "esprit_name": support["name"],
                        "esprit_tier": support.get("base_tier", 1),
                        "role": support_role,
                        "skill": support["support_skill"]
                    })
                    combat_abilities["team_elements"].append(support.get("element"))
            
            return combat_abilities
        
        return await cls._safe_execute(_operation, "get combat team abilities")
    
    @classmethod
    async def get_leader_tier(cls, player_id: int) -> ServiceResult[int]:
        """Get leader Esprit tier for combat effect scaling"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player or not player.leader_esprit_stack_id:
                    return 1  # Default tier if no leader
                
                # Get leader esprit tier
                leader_stmt = select(Esprit, EspritBase).where(
                    Esprit.id == player.leader_esprit_stack_id,
                    Esprit.esprit_base_id == EspritBase.id
                )
                leader_result = (await session.execute(leader_stmt)).first()
                
                if not leader_result:
                    return 1
                
                esprit, base = leader_result
                return base.base_tier
        
        return await cls._safe_execute(_operation, "get leader tier")
    
    @classmethod
    async def validate_team_for_combat(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Validate team is ready for combat"""
        async def _operation():
            team_result = await cls.get_current_team(player_id)
            if not team_result.success:
                return {
                    "valid": False,
                    "errors": ["Failed to load team"],
                    "warnings": []
                }
            
            team_data = team_result.data
            errors = []
            warnings = []
            
            # Must have leader
            if not team_data.get("leader"):
                errors.append("No leader selected! Use /team to set a leader.")
            
            # Warnings for incomplete team
            if not team_data.get("support1"):
                warnings.append("No support member 1 - missing support abilities")
            
            if not team_data.get("support2"):
                warnings.append("No support member 2 - missing support abilities")
            
            # Check for duplicate elements (could be tactical advice)
            elements = []
            for role in ["leader", "support1", "support2"]:
                member = team_data.get(role)
                if member:
                    elements.append(member.get("element"))
            
            if len(set(elements)) != len(elements):
                warnings.append("Team has duplicate elements - consider element diversity for resonance bonuses")
            
            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "team_member_count": team_data.get("team_member_count", 0),
                "total_power": team_data.get("total_team_power", 0)
            }
        
        return await cls._safe_execute(_operation, "validate team for combat")
    
    @classmethod
    async def get_team_stats_summary(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get team statistics summary"""
        async def _operation():
            team_result = await cls.get_current_team(player_id)
            if not team_result.success:
                return {"error": "Failed to load team"}
            
            team_data = team_result.data
            
            # Calculate team statistics
            total_atk = 0
            total_def = 0
            total_hp = 0
            elements = []
            tiers = []
            
            for role in ["leader", "support1", "support2"]:
                member = team_data.get(role)
                if member:
                    total_atk += member.get("total_atk", 0)
                    total_def += member.get("total_def", 0)
                    total_hp += member.get("total_hp", 0)
                    elements.append(member.get("element"))
                    tiers.append(member.get("base_tier", 1))
            
            unique_elements = len(set(elements))
            avg_tier = sum(tiers) / len(tiers) if tiers else 0
            
            return {
                "total_attack": total_atk,
                "total_defense": total_def,
                "total_hp": total_hp,
                "unique_elements": unique_elements,
                "average_tier": avg_tier,
                "element_list": elements,
                "tier_list": tiers,
                "team_size": len([m for m in [team_data.get("leader"), team_data.get("support1"), team_data.get("support2")] if m])
            }
        
        return await cls._safe_execute(_operation, "get team stats summary")