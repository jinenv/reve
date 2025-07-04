# test_connections.py
import asyncio
import os
from dotenv import load_dotenv
import asyncpg
import redis.asyncio as redis
import psycopg2
from datetime import datetime

async def test_postgres():
    """Test PostgreSQL connection"""
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ DATABASE_URL not found in .env file")
        return False
    
    print(f"📊 Testing PostgreSQL connection...")
    print(f"   URL: {db_url.split('@')[1] if '@' in db_url else 'invalid url'}")
    
    try:
        # Extract connection details
        if "postgresql+asyncpg://" in db_url:
            sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        else:
            sync_url = db_url
            
        # Try sync connection first for better error messages
        try:
            conn = psycopg2.connect(sync_url)
            conn.close()
            print("✅ PostgreSQL sync connection successful")
        except Exception as e:
            print(f"❌ PostgreSQL sync connection failed: {e}")
            return False
        
        # Now try async
        conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://"))
        version = await conn.fetchval('SELECT version()')
        await conn.close()
        
        print(f"✅ PostgreSQL is running!")
        print(f"   Version: {version.split(',')[0]}")
        return True
        
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        print("\n💡 Possible fixes:")
        print("   1. Make sure PostgreSQL is running")
        print("   2. Check your DATABASE_URL in .env")
        print("   3. Verify database 'reve' exists")
        print("   4. Check username/password")
        return False

async def test_redis():
    """Test Redis connection"""
    load_dotenv()
    redis_url = os.getenv("REDIS_URL")
    
    if not redis_url:
        print("\n⚠️  REDIS_URL not found in .env file")
        print("   Redis is optional but recommended for caching")
        return None
    
    print(f"\n🔴 Testing Redis connection...")
    
    try:
        client = redis.from_url(redis_url)
        pong = await client.ping()
        
        # Test basic operations
        await client.set("test_key", "test_value", ex=5)
        value = await client.get("test_key")
        await client.delete("test_key")
        
        await client.close()
        
        if pong:
            print("✅ Redis is running and functional!")
            return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("\n💡 Possible fixes:")
        print("   1. Make sure Redis is running")
        print("   2. Check your REDIS_URL in .env")
        print("   3. For Upstash: verify your endpoint and password")
        return False

async def check_database_exists():
    """Check if the 'reve' database exists"""
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        return False
    
    # Connect to postgres database to check if reve exists
    admin_url = db_url.replace("/reve", "/postgres")
    admin_url = admin_url.replace("postgresql+asyncpg://", "postgresql://")
    
    try:
        conn = await asyncpg.connect(admin_url)
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = 'reve')"
        )
        
        if not exists:
            print("\n⚠️  Database 'reve' does not exist!")
            print("Creating database...")
            await conn.execute('CREATE DATABASE reve')
            print("✅ Database 'reve' created successfully!")
        else:
            print("\n✅ Database 'reve' exists")
            
        await conn.close()
        return True
    except Exception as e:
        print(f"\n❌ Could not check/create database: {e}")
        return False

async def main():
    print("🐱 Reve Database Connection Test")
    print("=" * 40)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 40)
    
    # Test connections
    postgres_ok = await test_postgres()
    
    if postgres_ok:
        await check_database_exists()
    
    redis_ok = await test_redis()
    
    print("\n" + "=" * 40)
    print("Summary:")
    print(f"  PostgreSQL: {'✅ Working' if postgres_ok else '❌ Not working'}")
    print(f"  Redis: {'✅ Working' if redis_ok else '⚠️ Not configured' if redis_ok is None else '❌ Not working'}")
    
    return postgres_ok

if __name__ == "__main__":
    asyncio.run(main())