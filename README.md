# REVE

This project implements a **real-time, stateful Discord bot** with RPG and gacha mechanics. It is designed for **scalability**, **atomic state transitions**, and **strict separation of concerns**.

## 📦 Stack Overview

| Layer         | Technology                           |
|--------------|---------------------------------------|
| Bot API      | [Disnake](https://docs.disnake.dev/) (`>=2.9.0`)         |
| Database     | PostgreSQL + [SQLModel](https://sqlmodel.tiangolo.com/) + [asyncpg](https://magicstack.github.io/asyncpg/current/) |
| Migrations   | [Alembic](https://alembic.sqlalchemy.org/) (`>=1.13.0`) |
| Caching      | [Redis (Upstash)](https://upstash.com/) via `redis.asyncio` |
| Config       | `dotenv`-based + `ConfigManager` (centralized loader) |
| Logging      | Dual-stream: ops + structured transactions |
| Runtime      | Python 3.12, fully async, Windows/Unix agnostic |

---

## 🧠 Architectural Principles

### Core Separation of Concerns
- **Pure Data Models**: SQLModel classes contain ONLY data fields, simple calculations, and display helpers
- **Business Logic in Services**: All complex operations, transactions, and workflows live in dedicated service classes
- **Thin Controllers**: Disnake Cogs are routing shells that call services; they contain no business logic
- **Atomic Operations**: All state changes use proper database transactions with rollback capabilities
- **Stateless Commands**: Discord commands always resolve full state at runtime from the database

### Service-Oriented Architecture
- **Single Responsibility**: Each service handles one domain (fusion, awakening, quests, etc.)
- **Dependency Injection**: Services use other services through clean interfaces
- **Cache Management**: Intelligent cache invalidation through dedicated CacheService
- **Transaction Logging**: All business events are logged for analytics and debugging
- **Error Handling**: Consistent error responses with user-friendly messages

### Infrastructure-Only Utils
- **Pure Functions**: Utils contain NO business logic, only infrastructure and data access
- **Configuration-Driven**: All game tuning parameters come from JSON/YAML via `ConfigManager`
- **Infrastructure Services**: Database, Redis, logging, and Discord API operations only
- **Data Access Utilities**: Pure functions for loading and structuring configuration data

---

## 🗂️ Architecture Overview

```text
📦 src/
 ┣ 📂 cogs/              # Discord command routers (EMPTY - awaiting refactor)
 ┣ 📂 database/          # Pure data models + relationships
 ┃ ┣ 📂 models/          
 ┃ ┃ ┣ 📜 player.py      # Player data fields + simple calculations ONLY
 ┃ ┃ ┣ 📜 esprit.py      # Esprit stack data + power calculations ONLY
 ┃ ┃ ┗ 📜 esprit_base.py # Base Esprit stats + display helpers ONLY
 ┃ ┗ 📜 __init__.py      # Model imports
 ┣ 📂 services/          # Business logic layer
 ┃ ┣ 📜 ability_service.py        # Ability resolution, validation, and formatting
 ┃ ┣ 📜 achievement_service.py   # Achievement tracking and unlocking
 ┃ ┣ 📜 awakening_service.py     # Awakening system and star progression
 ┃ ┣ 📜 base_service.py          # Common service patterns and error handling
 ┃ ┣ 📜 building_service.py      # Economic buildings and passive income
 ┃ ┣ 📜 cache_service.py         # Intelligent cache management and invalidation
 ┃ ┣ 📜 collection_service.py    # Collection statistics and completion tracking
 ┃ ┣ 📜 display_service.py       # Discord formatting and emoji management
 ┃ ┣ 📜 echo_service.py          # Echo opening and daily claims
 ┃ ┣ 📜 esprit_service.py        # Esprit collection and power calculations
 ┃ ┣ 📜 experience_service.py    # Level progression and XP management
 ┃ ┣ 📜 fragment_service.py      # Fragment economy and crafting
 ┃ ┣ 📜 fusion_service.py        # Fusion logic, probabilities, and validation
 ┃ ┣ 📜 inventory_service.py     # Item management and storage
 ┃ ┣ 📜 leadership_service.py    # Leader Esprit management and bonuses
 ┃ ┣ 📜 notification_service.py  # Player notification settings
 ┃ ┣ 📜 player_service.py        # Core player data and currency operations
 ┃ ┣ 📜 power_service.py         # Combat power calculations and caching
 ┃ ┣ 📜 progression_service.py   # Character progression and milestones
 ┃ ┣ 📜 relic_service.py         # Relic operations and MW-style stat calculations
 ┃ ┣ 📜 resource_service.py      # Resource generation and management
 ┃ ┣ 📜 reward_service.py        # Reward distribution and processing
 ┃ ┣ 📜 search_service.py        # Esprit search, filtering, and sorting
 ┃ ┗ 📜 statistics_service.py    # Analytics and statistical tracking
 ┣ 📂 utils/             # Pure infrastructure utilities (NO BUSINESS LOGIC)
 ┃ ┣ 📜 database_service.py      # Connection pool + transaction management
 ┃ ┣ 📜 redis_service.py         # Cache operations and Redis infrastructure
 ┃ ┣ 📜 config_manager.py        # Configuration file loading
 ┃ ┣ 📜 transaction_logger.py    # Structured logging infrastructure
 ┃ ┣ 📜 game_constants.py        # Game constants, enums, formulas, and EmbedColors
 ┃ ┣ 📜 embed_colors.py          # Color constants with backward compatibility
 ┃ ┣ 📜 logger.py                # Logging utilities and setup
 ┃ ┣ 📜 ability_system.py        # Pure ability data access (config loading only)
 ┃ ┣ 📜 relic_system.py          # Pure relic data access (config loading only)
 ┃ ┣ 📜 emoji_manager.py         # Discord emoji storage infrastructure
 ┃ ┣ 📜 rate_limiter.py          # Rate limiting utilities
 ┃ ┗ 📜 validation_helpers.py    # Pure validation functions
 ┗ 📜 main.py            # Bot entrypoint
```

---

## 🔄 Service Architecture

### Pure Data Models (Models contain ZERO business logic)
```python
# Models are pure data containers - ALL business logic removed
class Player(SQLModel):
    # Data fields only
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(sa_column=Column(BigInteger, unique=True, index=True))
    revies: int = Field(default=0)
    
    # Simple calculations only
    def get_skill_bonuses(self) -> Dict[str, float]:
        return {"bonus_attack": self.allocated_skills.get("attack", 0) * 0.001}

# ALL business logic moved to services
class PlayerService(BaseService):
    @classmethod
    async def add_currency(cls, player_id: int, currency_type: str, amount: int, source: str):
        # Comprehensive currency workflow with transaction logging
```

### Complete Service Layer
All business logic is distributed across 23 specialized services:

| Service | Domain Responsibilities |
|---------|------------------------|
| **ability_service.py** | Ability resolution, validation, formatting, configuration |
| **achievement_service.py** | Achievement tracking, unlocking, progress calculation |
| **awakening_service.py** | Star progression, copy consumption, awakening validation |
| **base_service.py** | Common patterns, error handling, transaction management |
| **building_service.py** | Economic buildings, passive income, upkeep calculations |
| **cache_service.py** | Redis operations, intelligent invalidation, warming |
| **collection_service.py** | Collection statistics, completion tracking, progress |
| **display_service.py** | Discord formatting, emoji selection, synchronization |
| **echo_service.py** | Daily echo claims, loot table resolution, opening |
| **esprit_service.py** | Esprit collection management, stack operations |
| **experience_service.py** | Level progression, XP gain, milestone rewards |
| **fragment_service.py** | Fragment economy, crafting costs, consumption |
| **fusion_service.py** | Fusion validation, probability calculation, result determination |
| **inventory_service.py** | Item management, storage, consumption tracking |
| **leadership_service.py** | Leader selection, bonus calculation, cache management |
| **notification_service.py** | Player notification preferences, delivery |
| **player_service.py** | Core player operations, currency, energy/stamina |
| **power_service.py** | Combat power calculations, total power caching |
| **progression_service.py** | Character progression, unlock conditions |
| **relic_service.py** | Relic operations, MW-style stat calculations, equipment |
| **resource_service.py** | Resource generation, regeneration, limits |
| **reward_service.py** | Reward distribution, processing, validation |
| **search_service.py** | Esprit filtering, sorting, random selection |
| **statistics_service.py** | Analytics, metrics, behavioral tracking |

---

## 🎮 Game System Architecture

### Monster Warlord-Inspired Design
- **Universal Stacks**: Each Esprit record represents ALL copies a player owns
- **Tier-Based Progression**: 18 tiers with exponential power scaling
- **Awakening System**: Star-based enhancement consuming duplicate copies
- **Fusion System**: Combine same-tier monsters with element-based results
- **Leader Bonuses**: Active leader provides element-specific bonuses
- **Fragment Economy**: Failed fusions/awakenings produce upgrade materials

### Service Transaction Patterns
All services follow consistent patterns:
- **Atomic Operations**: Complete success or complete rollback
- **Transaction Logging**: All business events captured for analytics
- **Cache Invalidation**: Immediate invalidation on state change
- **Error Handling**: Structured error responses with user context
- **Resource Locking**: SELECT FOR UPDATE on all state modifications

---

## 📊 Performance Architecture

### Caching Strategy
- **Player Power**: Cache total combat stats (15min TTL)
- **Leader Bonuses**: Cache active leader effects (30min TTL)
- **Collection Stats**: Cache progress data (15min TTL)
- **Leaderboards**: Cache ranking data (5min TTL)

### Database Optimization
- **Connection Pooling**: Managed by asyncpg
- **Query Optimization**: Specific field selection, proper JOINs
- **Transaction Scope**: Minimal lock duration
- **Index Strategy**: Foreign keys and frequently queried fields

### Concurrency Safety
- **SELECT FOR UPDATE**: All state-modifying operations
- **Atomic Transactions**: Complete success or complete rollback
- **Cache Invalidation**: Immediate on state change
- **Distributed Locking**: Redis-based for cross-instance operations

---

## 🛠️ Current State

### Completed Refactoring - Final Architecture
- **Models**: Pure data containers with ALL business logic extracted to services ✅
- **Services**: 23 specialized service classes implementing comprehensive business logic ✅
- **Utils**: Pure infrastructure utilities with ALL business logic moved to services ✅
- **Architecture**: Complete separation of concerns with zero cross-contamination ✅
- **Transaction Patterns**: Consistent error handling, logging, and caching across all layers ✅

### New Services Created
- **AbilityService**: Complete ability resolution, validation, and formatting system
- **RelicService**: Monster Warlord-style relic operations and stat calculations
- **DisplayService**: Enhanced with emoji management and Discord formatting logic

### Enhanced Existing Services
- **FusionService**: Added probability calculations, result determination, and outcome prediction
- **PlayerService**: Added advanced resource regeneration, level progression, and optimization
- **QuestService**: Added capture probability calculations, area analysis, and strategy optimization

### Utils Cleanup Summary
All utils are now **pure infrastructure** with **zero business logic**:

| Util | Purpose | Business Logic Moved To |
|------|---------|------------------------|
| **database_service.py** | ✅ Connection management | N/A (pure infrastructure) |
| **redis_service.py** | ✅ Cache operations | N/A (pure infrastructure) |
| **config_manager.py** | ✅ Configuration loading | N/A (pure infrastructure) |
| **transaction_logger.py** | ✅ Logging infrastructure | N/A (pure infrastructure) |
| **game_constants.py** | ✅ Constants, enums, EmbedColors | Complex calculations → Services |
| **embed_colors.py** | ✅ Color constants only | Color selection logic → DisplayService |
| **ability_system.py** | ✅ Data access only | Resolution logic → AbilityService |
| **relic_system.py** | ✅ Data access only | Operations → RelicService |
| **emoji_manager.py** | ✅ Discord API only | Business operations → DisplayService |

### Pending Implementation
- **Cogs**: All Discord command handlers need to be implemented using service calls
- **Service Integration**: Cross-service dependencies need to be established
- **Testing**: Comprehensive test suite for service layer
- **Documentation**: Service API documentation and usage patterns

### Migration Requirements
All future cog implementations must use service calls exclusively:
```python
# REQUIRED PATTERN - services only
from src.services.fusion_service import FusionService
result = await FusionService.execute_fusion(player_id, esprit1_id, esprit2_id)

# FORBIDDEN PATTERN - direct model calls
# await esprit.perform_fusion(other_esprit, session)  # THIS WILL FAIL
```

---

## 📈 Monitoring & Analytics

- **Transaction Logging**: All business events captured via TransactionLogger
- **Performance Metrics**: Query timing and cache hit rates
- **Error Tracking**: Structured error logs with full context
- **Business Intelligence**: Player behavior and economy tracking through StatisticsService

This architecture ensures Reve can scale efficiently while maintaining data integrity and providing excellent user experience through consistent, fast responses. With 23 specialized services handling all business logic and pure infrastructure utilities, the codebase is now ready for professional-grade Discord bot development with Monster Warlord-inspired gameplay mechanics.