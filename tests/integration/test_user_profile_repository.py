"""Integration tests for user profile repository."""

import pytest
import pytest_asyncio
from datetime import datetime
from app.repositories.user_profile import (
    UserProfileRepository,
    UserProfile,
    UserFact,
)


@pytest_asyncio.fixture
async def profile_repo(test_db):
    """User profile repository with test database."""
    return UserProfileRepository(str(test_db))


@pytest.mark.asyncio
async def test_create_and_find_profile(profile_repo):
    """Test creating and finding user profile."""
    # Create profile
    profile = UserProfile(
        user_id=123,
        chat_id=456,
        first_name="Test",
        last_name="User",
        username="testuser",
    )

    await profile_repo.save(profile)

    # Find profile
    found = await profile_repo.find_by_id(123, 456)

    assert found is not None
    assert found.user_id == 123
    assert found.chat_id == 456
    assert found.first_name == "Test"
    assert found.username == "testuser"


@pytest.mark.asyncio
async def test_update_profile(profile_repo):
    """Test updating existing profile."""
    # Create profile
    profile = UserProfile(
        user_id=123,
        chat_id=456,
        first_name="Original",
    )
    await profile_repo.save(profile)

    # Update profile
    profile.first_name = "Updated"
    await profile_repo.save(profile)

    # Verify update
    found = await profile_repo.find_by_id(123, 456)
    assert found.first_name == "Updated"


@pytest.mark.asyncio
async def test_delete_profile(profile_repo):
    """Test deleting user profile."""
    # Create profile
    profile = UserProfile(user_id=123, chat_id=456)
    await profile_repo.save(profile)

    # Delete profile
    deleted = await profile_repo.delete(123, 456)
    assert deleted is True

    # Verify deletion
    found = await profile_repo.find_by_id(123, 456)
    assert found is None


@pytest.mark.asyncio
async def test_add_fact(profile_repo):
    """Test adding fact to user profile."""
    # Create profile first
    profile = UserProfile(user_id=123, chat_id=456)
    await profile_repo.save(profile)

    # Add fact
    fact = UserFact(
        fact_id=None,
        user_id=123,
        chat_id=456,
        category="personal",
        fact_text="Lives in Kyiv",
        confidence=0.9,
    )
    saved_fact = await profile_repo.add_fact(fact)

    assert saved_fact.fact_id is not None
    assert saved_fact.confidence == 0.9


@pytest.mark.asyncio
async def test_get_facts(profile_repo):
    """Test retrieving facts for user."""
    # Create profile
    profile = UserProfile(user_id=123, chat_id=456)
    await profile_repo.save(profile)

    # Add facts
    fact1 = UserFact(
        fact_id=None,
        user_id=123,
        chat_id=456,
        category="personal",
        fact_text="Lives in Kyiv",
        confidence=0.9,
    )
    fact2 = UserFact(
        fact_id=None,
        user_id=123,
        chat_id=456,
        category="preference",
        fact_text="Likes pizza",
        confidence=0.8,
    )

    await profile_repo.add_fact(fact1)
    await profile_repo.add_fact(fact2)

    # Get all facts
    facts = await profile_repo.get_facts(123, 456)
    assert len(facts) == 2

    # Get facts by category
    personal_facts = await profile_repo.get_facts(123, 456, category="personal")
    assert len(personal_facts) == 1
    assert personal_facts[0].fact_text == "Lives in Kyiv"


@pytest.mark.asyncio
async def test_update_fact(profile_repo):
    """Test updating existing fact."""
    # Create profile and fact
    profile = UserProfile(user_id=123, chat_id=456)
    await profile_repo.save(profile)

    fact = UserFact(
        fact_id=None,
        user_id=123,
        chat_id=456,
        category="personal",
        fact_text="Original text",
        confidence=0.5,
    )
    saved_fact = await profile_repo.add_fact(fact)

    # Update fact
    saved_fact.fact_text = "Updated text"
    saved_fact.confidence = 0.9
    await profile_repo.update_fact(saved_fact)

    # Verify update
    facts = await profile_repo.get_facts(123, 456)
    assert len(facts) == 1
    assert facts[0].fact_text == "Updated text"
    assert facts[0].confidence == 0.9


@pytest.mark.asyncio
async def test_delete_fact(profile_repo):
    """Test deleting fact."""
    # Create profile and fact
    profile = UserProfile(user_id=123, chat_id=456)
    await profile_repo.save(profile)

    fact = UserFact(
        fact_id=None,
        user_id=123,
        chat_id=456,
        category="personal",
        fact_text="To be deleted",
        confidence=0.5,
    )
    saved_fact = await profile_repo.add_fact(fact)

    # Delete fact
    deleted = await profile_repo.delete_fact(saved_fact.fact_id)
    assert deleted is True

    # Verify deletion
    facts = await profile_repo.get_facts(123, 456)
    assert len(facts) == 0


@pytest.mark.asyncio
async def test_profile_to_dict(profile_repo):
    """Test converting profile to dictionary."""
    profile = UserProfile(
        user_id=123,
        chat_id=456,
        first_name="Test",
        username="testuser",
    )

    data = profile.to_dict()

    assert data["user_id"] == 123
    assert data["chat_id"] == 456
    assert data["first_name"] == "Test"
    assert data["username"] == "testuser"


@pytest.mark.asyncio
async def test_fact_to_dict(profile_repo):
    """Test converting fact to dictionary."""
    fact = UserFact(
        fact_id=1,
        user_id=123,
        chat_id=456,
        category="personal",
        fact_text="Test fact",
        confidence=0.8,
        metadata={"source": "test"},
    )

    data = fact.to_dict()

    assert data["fact_id"] == 1
    assert data["category"] == "personal"
    assert data["confidence"] == 0.8
    assert data["metadata"]["source"] == "test"
