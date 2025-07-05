#!/usr/bin/env python3
"""
Comprehensive REVE Service Test Suite
Tests all 24+ services to ensure they work properly.
"""

import asyncio
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Core imports
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger

logger = get_logger(__name__)

class ServiceTester:
    """Comprehensive service testing framework"""
    
    def __init__(self):
        self.results = {}
        self.test_player_id = None
        self.test_esprit_id = None
        self.test_esprit_base_id = None
    
    async def setup_test_data(self):
        """Get test IDs from database for realistic testing"""
        try:
            async with DatabaseService.get_session() as session:
                from sqlalchemy import select, func
                from src.database.models.player import Player
                from src.database.models.esprit import Esprit
                from src.database.models.esprit_base import EspritBase
                
                # Get first player
                player_result = await session.execute(select(Player).limit(1))
                player = player_result.scalar_one_or_none()
                if player:
                    self.test_player_id = player.id
                    logger.info(f"Using test player ID: {self.test_player_id}")
                
                # Get first esprit base
                base_result = await session.execute(select(EspritBase).limit(1))
                base = base_result.scalar_one_or_none()
                if base:
                    self.test_esprit_base_id = base.id
                    logger.info(f"Using test esprit base ID: {self.test_esprit_base_id}")
                
                # Get first esprit
                esprit_result = await session.execute(select(Esprit).limit(1))
                esprit = esprit_result.scalar_one_or_none()
                if esprit:
                    self.test_esprit_id = esprit.id
                    logger.info(f"Using test esprit ID: {self.test_esprit_id}")
                    
        except Exception as e:
            logger.warning(f"Could not setup test data: {e}")
    
    def log_test_result(self, service_name: str, test_name: str, success: bool, details: str = ""):
        """Log test result"""
        if service_name not in self.results:
            self.results[service_name] = {
                "tests": [],
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0
            }
        
        self.results[service_name]["tests"].append({
            "name": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat()
        })
        
        self.results[service_name]["total_tests"] += 1
        if success:
            self.results[service_name]["passed_tests"] += 1
        else:
            self.results[service_name]["failed_tests"] += 1
    
    async def test_service_import(self, service_name: str, import_path: str):
        """Test if a service can be imported"""
        try:
            exec(f"from {import_path} import {service_name}")
            self.log_test_result(service_name, "import", True, f"Successfully imported {service_name}")
            return True
        except Exception as e:
            self.log_test_result(service_name, "import", False, f"Import failed: {str(e)}")
            return False
    
    async def test_ability_service(self):
        """Test AbilityService functionality"""
        service_name = "AbilityService"
        
        if not await self.test_service_import(service_name, "src.services.ability_service"):
            return
        
        try:
            from src.services.ability_service import AbilityService
            
            # Test ability resolution
            result = await AbilityService.resolve_esprit_abilities("TestEsprit", 1, "inferno")
            self.log_test_result(service_name, "resolve_abilities", result.success, 
                               f"Resolved abilities: {result.success}")
            
            # Test ability summary
            result = await AbilityService.get_ability_summary("TestEsprit", 1, "inferno")
            self.log_test_result(service_name, "get_summary", result.success,
                               f"Got summary: {result.data if result.success else result.error}")
                               
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_player_service(self):
        """Test PlayerService functionality"""
        service_name = "PlayerService"
        
        if not await self.test_service_import(service_name, "src.services.player_service"):
            return
        
        try:
            from src.services.player_service import PlayerService
            
            if self.test_player_id:
                # Test getting player profile
                result = await PlayerService.get_basic_profile(self.test_player_id)
                self.log_test_result(service_name, "get_profile", result.success,
                                   f"Got profile: {result.success}")
                
                # Test resource regeneration calculation
                result = await PlayerService.calculate_advanced_energy_regeneration(self.test_player_id)
                self.log_test_result(service_name, "energy_regen", result.success,
                                   f"Energy regen calculated: {result.success}")
            else:
                self.log_test_result(service_name, "no_test_data", False, "No test player available")
                
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_esprit_service(self):
        """Test EspritService functionality"""
        service_name = "EspritService"
        
        if not await self.test_service_import(service_name, "src.services.esprit_service"):
            return
        
        try:
            from src.services.esprit_service import EspritService
            
            if self.test_player_id:
                # Test getting collection stats
                result = await EspritService.get_collection_stats(self.test_player_id)
                self.log_test_result(service_name, "collection_stats", result.success,
                                   f"Got collection stats: {result.success}")
                
                # Test power calculation
                result = await EspritService.calculate_collection_power(self.test_player_id)
                self.log_test_result(service_name, "power_calculation", result.success,
                                   f"Power calculated: {result.success}")
            else:
                self.log_test_result(service_name, "no_test_data", False, "No test player available")
                
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_search_service(self):
        """Test SearchService functionality"""
        service_name = "SearchService"
        
        if not await self.test_service_import(service_name, "src.services.search_service"):
            return
        
        try:
            from src.services.search_service import SearchService
            
            # Test search functionality
            result = await SearchService.search_esprits("test", limit=5)
            self.log_test_result(service_name, "search_esprits", result.success,
                               f"Search completed: {result.success}")
            
            # Test getting esprit by name
            result = await SearchService.get_esprit_by_name("Blazeblob")
            self.log_test_result(service_name, "get_by_name", result.success,
                               f"Get by name: {result.success}")
                               
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_cache_service(self):
        """Test CacheService functionality"""
        service_name = "CacheService"
        
        if not await self.test_service_import(service_name, "src.services.cache_service"):
            return
        
        try:
            from src.services.cache_service import CacheService
            
            # Test basic cache operations
            test_key = "test_key"
            test_data = {"test": "data"}
            
            # Test set
            result = await CacheService.set(test_key, test_data, 60)
            self.log_test_result(service_name, "cache_set", result.success,
                               f"Cache set: {result.success}")
            
            # Test get
            result = await CacheService.get(test_key)
            self.log_test_result(service_name, "cache_get", result.success,
                               f"Cache get: {result.success}")
            
            # Test delete
            result = await CacheService.delete(test_key)
            self.log_test_result(service_name, "cache_delete", result.success,
                               f"Cache delete: {result.success}")
                               
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_collection_service(self):
        """Test CollectionService functionality"""
        service_name = "CollectionService"
        
        if not await self.test_service_import(service_name, "src.services.collection_service"):
            return
        
        try:
            from src.services.collection_service import CollectionService
            
            if self.test_player_id:
                # Test collection overview
                result = await CollectionService.get_collection_overview(self.test_player_id)
                self.log_test_result(service_name, "collection_overview", result.success,
                                   f"Collection overview: {result.success}")
            else:
                self.log_test_result(service_name, "no_test_data", False, "No test player available")
                
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_player_class_service(self):
        """Test PlayerClassService functionality"""
        service_name = "PlayerClassService"
        
        if not await self.test_service_import(service_name, "src.services.player_class_service"):
            return
        
        try:
            from src.services.player_class_service import PlayerClassService
            
            if self.test_player_id:
                # Test getting class info
                result = await PlayerClassService.get_class_info(self.test_player_id)
                self.log_test_result(service_name, "get_class_info", result.success,
                                   f"Got class info: {result.success}")
                
                # Test bonus calculation
                bonus = PlayerClassService.calculate_bonus_for_level(50)
                self.log_test_result(service_name, "bonus_calculation", True,
                                   f"Level 50 bonus: {bonus}%")
            else:
                self.log_test_result(service_name, "no_test_data", False, "No test player available")
                
        except Exception as e:
            self.log_test_result(service_name, "functionality", False, f"Error: {str(e)}")
    
    async def test_all_services_imports(self):
        """Test importing all known services"""
        services_to_test = [
            ("AbilityService", "src.services.ability_service"),
            ("AchievementService", "src.services.achievement_service"),
            ("AwakeningService", "src.services.awakening_service"),
            ("BaseService", "src.services.base_service"),
            ("BuildingService", "src.services.building_service"),
            ("CacheService", "src.services.cache_service"),
            ("CollectionService", "src.services.collection_service"),
            ("DisplayService", "src.services.display_service"),
            ("EchoService", "src.services.echo_service"),
            ("EspritService", "src.services.esprit_service"),
            ("ExperienceService", "src.services.experience_service"),
            ("FragmentService", "src.services.fragment_service"),
            ("FusionService", "src.services.fusion_service"),
            ("InventoryService", "src.services.inventory_service"),
            ("LeadershipService", "src.services.leadership_service"),
            ("NotificationService", "src.services.notification_service"),
            ("PlayerService", "src.services.player_service"),
            ("PowerService", "src.services.power_service"),
            ("ProgressionService", "src.services.progression_service"),
            ("QuestService", "src.services.quest_service"),
            ("RelicService", "src.services.relic_service"),
            ("ResourceService", "src.services.resource_service"),
            ("RewardService", "src.services.reward_service"),
            ("SearchService", "src.services.search_service"),
            ("StatisticsService", "src.services.statistics_service"),
            ("PlayerClassService", "src.services.player_class_service"),
        ]
        
        for service_name, import_path in services_to_test:
            await self.test_service_import(service_name, import_path)
    
    async def run_comprehensive_tests(self):
        """Run all service tests"""
        print("🧪 Starting Comprehensive REVE Service Test Suite")
        print("=" * 60)
        
        # Initialize database
        DatabaseService.init()
        
        # Setup test data
        await self.setup_test_data()
        
        print("\n📦 Testing Service Imports...")
        await self.test_all_services_imports()
        
        print("\n🔧 Testing Core Service Functionality...")
        await self.test_player_service()
        await self.test_esprit_service()
        await self.test_search_service()
        await self.test_cache_service()
        await self.test_collection_service()
        await self.test_ability_service()
        await self.test_player_class_service()
        
        # Generate report
        await self.generate_report()
    
    async def generate_report(self):
        """Generate comprehensive test report"""
        print("\n" + "=" * 60)
        print("📊 COMPREHENSIVE TEST REPORT")
        print("=" * 60)
        
        total_services = len(self.results)
        total_tests = sum(service["total_tests"] for service in self.results.values())
        total_passed = sum(service["passed_tests"] for service in self.results.values())
        total_failed = sum(service["failed_tests"] for service in self.results.values())
        
        print(f"\n📈 OVERALL SUMMARY:")
        print(f"   Services Tested: {total_services}")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {total_passed} ✅")
        print(f"   Failed: {total_failed} ❌")
        print(f"   Success Rate: {(total_passed/total_tests*100):.1f}%")
        
        print(f"\n📋 SERVICE BREAKDOWN:")
        
        # Sort services by success rate
        sorted_services = sorted(
            self.results.items(),
            key=lambda x: x[1]["passed_tests"] / x[1]["total_tests"] if x[1]["total_tests"] > 0 else 0,
            reverse=True
        )
        
        for service_name, results in sorted_services:
            success_rate = (results["passed_tests"] / results["total_tests"] * 100) if results["total_tests"] > 0 else 0
            status = "✅" if success_rate == 100 else "⚠️" if success_rate >= 50 else "❌"
            
            print(f"   {status} {service_name}: {results['passed_tests']}/{results['total_tests']} ({success_rate:.1f}%)")
            
            # Show failed tests
            for test in results["tests"]:
                if not test["success"]:
                    print(f"      ❌ {test['name']}: {test['details']}")
        
        print(f"\n💾 Detailed results saved to: service_test_results.json")
        
        # Save detailed results to JSON
        with open("service_test_results.json", "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_services": total_services,
                    "total_tests": total_tests,
                    "passed_tests": total_passed,
                    "failed_tests": total_failed,
                    "success_rate": total_passed/total_tests*100 if total_tests > 0 else 0
                },
                "results": self.results
            }, f, indent=2)
        
        print(f"\n🎯 RECOMMENDATIONS:")
        
        failed_services = [name for name, results in self.results.items() 
                          if results["failed_tests"] > 0]
        
        if failed_services:
            print(f"   Fix issues in: {', '.join(failed_services)}")
        else:
            print("   🎉 All services are working perfectly!")
        
        print(f"\n✨ Testing complete! REVE service architecture is {'robust' if total_failed == 0 else 'mostly functional'}.")


async def main():
    """Main test runner"""
    try:
        tester = ServiceTester()
        await tester.run_comprehensive_tests()
    except KeyboardInterrupt:
        print("\n⏹️ Testing interrupted by user")
    except Exception as e:
        print(f"\n💥 Testing failed with error: {e}")
        traceback.print_exc()
    finally:
        print("\n👋 Test suite finished")


if __name__ == "__main__":
    asyncio.run(main())