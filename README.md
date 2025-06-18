# NYXA

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

- **Single Source of Truth**: All game logic is defined inside `src/database/models/` as SQLModel methods.
- **Thin Controllers**: Disnake Cogs are routing shells; they do not contain logic.
- **Atomicity**: All read-modify-write DB operations use `SELECT ... FOR UPDATE`.
- **Stateless Commands**: Discord commands always resolve full state at runtime.
- **Config-Driven Tuning**: All tunables come from central JSON/YAML config via `ConfigManager`.
- **Service-Oriented Utilities**: Redis, logging, and config are exposed as composable services in `src/utils`.

---

## 🗂️ Key Directories

```text
📦 src/
 ┣ 📂 cogs/            # Command routers (no logic)
 ┣ 📂 database/        # SQLModel definitions + game logic
 ┣ 📂 services/        # Future microservices (combat, inventory, etc.)
 ┣ 📂 utils/           # RedisService, ConfigManager, LoggerService
 ┗ 📜 main.py          # Entrypoint dispatcher (imported by run.py)
