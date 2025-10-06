# Phase 2 Quick Reference

## Commands

```bash
# Database Migrations
make db-migrate              # Apply pending migrations
make db-version              # Show current version
make db-rollback VERSION=N   # Rollback to version N

# Testing
make test                    # All tests
make test-unit               # Unit tests
make test-integration        # Integration tests
make test-cov                # With coverage

# Development
make format                  # Auto-format code
make lint                    # Check code quality
make clean                   # Clean generated files
```

## Repository Usage

### User Profiles

```python
from app.repositories.user_profile import UserProfileRepository, UserProfile, UserFact

repo = UserProfileRepository(db_path)

# Create profile
profile = UserProfile(user_id=123, chat_id=456, first_name="Taras")
await repo.save(profile)

# Find profile
profile = await repo.find_by_id(123, 456)

# Add fact
fact = UserFact(
    fact_id=None,
    user_id=123,
    chat_id=456,
    category="personal",
    fact_text="Lives in Kyiv",
    confidence=0.9
)
await repo.add_fact(fact)

# Get facts
facts = await repo.get_facts(123, 456)
personal = await repo.get_facts(123, 456, category="personal")
```

### Conversations

```python
from app.repositories.conversation import ConversationRepository, Message

repo = ConversationRepository(db_path)

# Save message
msg = Message(
    message_id=None,
    chat_id=456,
    thread_id=None,
    user_id=123,
    role="user",
    text="Hello!",
    embedding=[0.1, 0.2, 0.3]
)
await repo.save(msg)

# Get recent
recent = await repo.get_recent_messages(chat_id=456, limit=10)

# Search
results = await repo.search_messages(chat_id=456, query_text="pizza")

# Semantic search
similar = await repo.semantic_search(
    chat_id=456,
    query_embedding=[0.1, 0.2, 0.3],
    limit=5
)
```

## Creating Migrations

1. Create file: `app/infrastructure/database/migrations/XXX_description.sql`
2. Add SQL statements
3. Run: `make db-migrate`

**Example: 006_add_poll_analytics.sql**
```sql
CREATE TABLE IF NOT EXISTS poll_analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id TEXT NOT NULL,
    total_votes INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (poll_id) REFERENCES polls(id)
);

CREATE INDEX idx_poll_analytics_poll 
    ON poll_analytics(poll_id);
```

## Creating Repositories

```python
from app.repositories.base import Repository
from typing import Optional

class MyEntity:
    def __init__(self, id: int, name: str):
        self.id = id
        self.name = name

class MyRepository(Repository[MyEntity]):
    async def find_by_id(self, id: int) -> Optional[MyEntity]:
        row = await self._fetch_one(
            "SELECT * FROM my_table WHERE id = ?",
            (id,)
        )
        if not row:
            return None
        return MyEntity(row["id"], row["name"])
    
    async def save(self, entity: MyEntity) -> MyEntity:
        await self._execute(
            "INSERT OR REPLACE INTO my_table (id, name) VALUES (?, ?)",
            (entity.id, entity.name)
        )
        return entity
    
    async def delete(self, id: int) -> bool:
        cursor = await self._execute(
            "DELETE FROM my_table WHERE id = ?",
            (id,)
        )
        return cursor.rowcount > 0
```

## What's Next?

**Phase 3: Event-Driven Architecture & Dependency Injection**
- Event bus for domain events
- DI container for service management
- Cleaner handler code
- Better testability

Run `make help` to see all available commands.
