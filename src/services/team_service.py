# src/services/team_service.py

import asyncio
from typing import Dict, List, Any, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Player, Esprit, EspritBase
from src.services.ability_service import AbilityService
from src.services.base_service import BaseService, ServiceResult
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.logger import get_logger

logger = get_logger(__name__)

class TeamService(BaseService):
    """Service for managing 3-Esprit combat teams"""

    @classmethod
    async def get_current_team(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's current team composition with abilities"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                # Get player data
                player_stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one_or_none()
                
                if not player:
                    return {"error": "Player not found"}

                team_data = {
                    "leader": None,
                    "support1": None,
                    "support2": None,
                    "total_team_power": 0,
                    "team_valid": False
                }

                # Get leader if exists
                if player.leader_esprit_stack_id:
                    leader_data = await cls._get_team_member_data(
                        session, player.leader_esprit_stack_id, "leader"
                    )
                    if leader_data:
                        team_data["leader"] = leader_data

                # Get support members if exist
                if player.support1_esprit_stack_id:
                    support1_data = await cls._get_team_member_data(
                        session, player.support1_esprit_stack_id, "support1"
                    )
                    if support1_data:
                        team_data["support1"] = support1_data

                if player.support2_esprit_stack_id:
                    support2_data = await cls._get_team_member_data(
                        session, player.support2_esprit_stack_id, "support2"
                    )
                    if support2_data:
                        team_data["support2"] = support2_data

                # Calculate team stats
                total_power = 0
                if team_data["leader"]:
                    total_power += team_data["leader"]["total_atk"] + team_data["leader"]["total_def"]
                if team_data["support1"]:
                    total_power += team_data["support1"]["total_atk"] + team_data["support1"]["total_def"]
                if team_data["support2"]:
                    total_power += team_data["support2"]["total_atk"] + team_data["support2"]["total_def"]

                team_data["total_team_power"] = total_power
                team_data["team_valid"] = team_data["leader"] is not None

                return team_data
        
        return await cls._safe_execute(_operation, "get current team")

    @classmethod
    async def _get_team_member_data(
        cls, 
        session: AsyncSession, 
        esprit_stack_id: int, 
        role: str
    ) -> Optional[Dict[str, Any]]:
        """Get detailed data for a team member"""
        try:
            # Get esprit with base data using proper SQLAlchemy syntax
            stmt = select(Esprit, EspritBase).where(
                Esprit.id == esprit_stack_id,  # type: ignore
                Esprit.esprit_base_id == EspritBase.id  # type: ignore
            )
            result = (await session.execute(stmt)).first()
            
            if not result:
                return None

            esprit, base = result

            # Calculate total stats
            total_atk = base.base_attack + esprit.bonus_attack
            total_def = base.base_defense + esprit.bonus_defense
            total_hp = base.base_health + esprit.bonus_health

            member_data = {
                "esprit_id": esprit.id,
                "name": base.name,
                "element": base.element,
                "base_tier": base.base_tier,
                "rarity": base.rarity,
                "total_atk": total_atk,
                "total_def": total_def,
                "total_hp": total_hp,
                "count": esprit.count,
                "stars": esprit.stars
            }

            # Get abilities for leader
            if role == "leader":
                ability_result = await AbilityService.resolve_esprit_abilities(
                    base.name, base.base_tier, base.element
                )
                if ability_result.success and ability_result.data:
                    abilities = ability_result.data.abilities
                    member_data["ability_details"] = {
                        "basic": abilities.basic.to_dict() if abilities.basic else None,
                        "ultimate": abilities.ultimate.to_dict() if abilities.ultimate else None,
                        "passive": abilities.passive.to_dict() if abilities.passive else None
                    }
                    
                    # Create ability summary
                    basic_name = abilities.basic.name if abilities.basic else "Basic Attack"
                    ultimate_name = abilities.ultimate.name if abilities.ultimate else "Ultimate Attack"
                    member_data["ability_summary"] = f"{basic_name} | {ultimate_name}"
                else:
                    member_data["ability_summary"] = "Loading abilities..."

            # Get support skill for support members
            elif role.startswith("support"):
                support_skill = await AbilityService.get_support_skill(base.element, base.base_tier)
                if support_skill.success and support_skill.data:
                    member_data["support_skill"] = support_skill.data
                else:
                    member_data["support_skill"] = {
                        "name": "No Skill",
                        "description": "Support skill not available"
                    }

            return member_data

        except Exception as e:
            logger.error(f"Error getting team member data: {str(e)}")
            return None

    @classmethod
    async def get_eligible_team_members(
        cls, 
        player_id: int, 
        role: str, 
        exclude_ids: Optional[List[int]] = None
    ) -> ServiceResult[List[Dict[str, Any]]]:
        """Get eligible Esprits for team role"""
        async def _operation():
            # Initialize exclude_ids properly
            exclude_esprit_ids = exclude_ids or []
                
            async with DatabaseService.get_session() as session:
                # Build the query with proper SQLAlchemy syntax
                if exclude_esprit_ids:
                    # Use NOT IN when exclude_ids has values
                    stmt = select(Esprit, EspritBase).where(
                        Esprit.player_id == player_id,  # type: ignore
                        Esprit.count > 0,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id,  # type: ignore
                        ~Esprit.id.in_(exclude_esprit_ids)  # type: ignore
                    ).order_by(EspritBase.base_tier.desc(), EspritBase.name)  # type: ignore
                else:
                    # No exclusions needed
                    stmt = select(Esprit, EspritBase).where(
                        Esprit.player_id == player_id,  # type: ignore
                        Esprit.count > 0,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id  # type: ignore
                    ).order_by(EspritBase.base_tier.desc(), EspritBase.name)  # type: ignore

                results = (await session.execute(stmt)).all()

                eligible_members = []
                for esprit, base in results:
                    total_atk = base.base_attack + esprit.bonus_attack
                    total_def = base.base_defense + esprit.bonus_defense

                    member_data = {
                        "esprit_id": esprit.id,
                        "name": base.name,
                        "element": base.element,
                        "base_tier": base.base_tier,
                        "rarity": base.rarity,
                        "total_atk": total_atk,
                        "total_def": total_def,
                        "count": esprit.count,
                        "stars": esprit.stars
                    }

                    # Add role-specific data
                    if role.startswith("support"):
                        support_skill = await AbilityService.get_support_skill(base.element, base.base_tier)
                        if support_skill.success and support_skill.data:
                            member_data["support_skill"] = support_skill.data

                    eligible_members.append(member_data)

                return eligible_members
        
        return await cls._safe_execute(_operation, f"get eligible {role} members")

    @classmethod
    async def update_team_member(
        cls, 
        player_id: int, 
        role: str, 
        esprit_id: Optional[int]
    ) -> ServiceResult[Dict[str, Any]]:
        """Update team member (leader, support1, or support2)"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                # Get player with proper where clause
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    return {"error": "Player not found"}

                # Validate esprit ownership if provided
                base = None
                if esprit_id is not None:
                    esprit_stmt = select(Esprit, EspritBase).where(
                        Esprit.id == esprit_id,  # type: ignore
                        Esprit.player_id == player_id,  # type: ignore
                        Esprit.count > 0,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id  # type: ignore
                    )
                    esprit_result = (await session.execute(esprit_stmt)).first()
                    
                    if not esprit_result:
                        return {"error": "Esprit not found or not owned"}
                    
                    esprit, base = esprit_result

                # Get old esprit_id for logging
                old_esprit_id = None
                if role == "leader":
                    old_esprit_id = player.leader_esprit_stack_id
                    player.leader_esprit_stack_id = esprit_id
                elif role == "support1":
                    old_esprit_id = player.support1_esprit_stack_id
                    player.support1_esprit_stack_id = esprit_id
                elif role == "support2":
                    old_esprit_id = player.support2_esprit_stack_id
                    player.support2_esprit_stack_id = esprit_id
                else:
                    return {"error": "Invalid role"}

                # Update activity and commit
                player.update_activity()
                await session.commit()

                # Log transaction using correct method signature
                transaction_logger.log_transaction(
                    player_id=player_id,
                    transaction_type=TransactionType.TEAM_UPDATED,
                    details={
                        "role": role,
                        "old_esprit_id": old_esprit_id,
                        "new_esprit_id": esprit_id,
                        "esprit_name": base.name if base else None,
                        "esprit_tier": base.base_tier if base else None,
                        "timestamp": player.last_active.isoformat()
                    }
                )
                
                return {
                    "role": role,
                    "old_esprit_id": old_esprit_id,
                    "new_esprit_id": esprit_id,
                    "esprit_name": base.name if base else None,
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
            if not team_data:
                return {"error": "No team data"}
                
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
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player or not player.leader_esprit_stack_id:
                    return 1  # Default tier if no leader
                
                # Get leader esprit tier with proper where clause
                leader_stmt = select(Esprit, EspritBase).where(
                    Esprit.id == player.leader_esprit_stack_id,  # type: ignore
                    Esprit.esprit_base_id == EspritBase.id  # type: ignore
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
            if not team_data:
                return {
                    "valid": False,
                    "errors": ["No team data found"],
                    "warnings": []
                }
                
            errors = []
            warnings = []
            
            # Must have leader
            if not team_data.get("leader"):
                errors.append("No leader selected! Use /team to set a leader.")
            
            # Warnings for missing supports
            if not team_data.get("support1"):
                warnings.append("Support slot 1 is empty. Consider adding a support member for extra abilities.")
            
            if not team_data.get("support2"):
                warnings.append("Support slot 2 is empty. Consider adding a support member for extra abilities.")
            
            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings
            }
        
        return await cls._safe_execute(_operation, "validate team for combat")

    @classmethod
    async def get_team_stats_summary(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive team statistics"""
        async def _operation():
            team_result = await cls.get_current_team(player_id)
            if not team_result.success:
                return {"error": "Failed to load team"}
            
            team_data = team_result.data
            if not team_data:
                return {"error": "No team data"}
            
            # Calculate comprehensive stats
            total_attack = 0
            total_defense = 0
            total_hp = 0
            team_size = 0
            elements = set()
            tiers = []
            
            for role in ["leader", "support1", "support2"]:
                member = team_data.get(role)
                if member:
                    total_attack += member.get("total_atk", 0)
                    total_defense += member.get("total_def", 0)
                    total_hp += member.get("total_hp", 0)
                    team_size += 1
                    elements.add(member.get("element", "unknown"))
                    tiers.append(member.get("base_tier", 1))
            
            average_tier = sum(tiers) / len(tiers) if tiers else 0
            
            return {
                "total_attack": total_attack,
                "total_defense": total_defense,
                "total_hp": total_hp,
                "team_size": team_size,
                "unique_elements": len(elements),
                "element_list": list(elements),
                "average_tier": average_tier
            }
        
        return await cls._safe_execute(_operation, "get team stats summary")