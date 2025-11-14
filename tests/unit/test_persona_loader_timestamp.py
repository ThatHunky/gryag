"""Tests for PersonaLoader timestamp variable substitution."""

import pytest

from app.services.persona.loader import PersonaLoader


def test_get_system_prompt_with_timestamp():
    """Test that {timestamp} variable is substituted correctly."""
    loader = PersonaLoader()
    
    # Create a test prompt with timestamp variable
    loader.persona.system_prompt = "The current time is {timestamp}."
    
    # Get prompt with current_time
    current_time = "Monday, January 15, 2025 at 14:30:45"
    result = loader.get_system_prompt(current_time=current_time)
    
    assert "{timestamp}" not in result
    assert current_time in result
    assert "The current time is Monday, January 15, 2025 at 14:30:45." == result


def test_get_system_prompt_with_current_year():
    """Test that {current_year} variable is extracted and substituted."""
    loader = PersonaLoader()
    
    # Create a test prompt with current_year variable
    loader.persona.system_prompt = "The year is {current_year}."
    
    # Get prompt with current_time
    current_time = "Monday, January 15, 2025 at 14:30:45"
    result = loader.get_system_prompt(current_time=current_time)
    
    assert "{current_year}" not in result
    assert "2025" in result
    assert "The year is 2025." == result


def test_get_system_prompt_with_current_date():
    """Test that {current_date} variable is extracted and substituted."""
    loader = PersonaLoader()
    
    # Create a test prompt with current_date variable
    loader.persona.system_prompt = "Today is {current_date}."
    
    # Get prompt with current_time
    current_time = "Monday, January 15, 2025 at 14:30:45"
    result = loader.get_system_prompt(current_time=current_time)
    
    assert "{current_date}" not in result
    assert "Monday, January 15, 2025" in result
    assert "Today is Monday, January 15, 2025." == result


def test_get_system_prompt_with_all_variables():
    """Test that all timestamp variables work together."""
    loader = PersonaLoader()
    
    # Create a test prompt with all variables
    loader.persona.system_prompt = (
        "Timestamp: {timestamp}, Year: {current_year}, Date: {current_date}."
    )
    
    # Get prompt with current_time
    current_time = "Monday, January 15, 2025 at 14:30:45"
    result = loader.get_system_prompt(current_time=current_time)
    
    assert "{timestamp}" not in result
    assert "{current_year}" not in result
    assert "{current_date}" not in result
    assert "Monday, January 15, 2025 at 14:30:45" in result
    assert "2025" in result
    assert "Monday, January 15, 2025" in result


def test_get_system_prompt_without_current_time():
    """Test that fallback timestamp is generated when current_time not provided."""
    loader = PersonaLoader()
    
    # Create a test prompt with timestamp variable
    loader.persona.system_prompt = "The current time is {timestamp}."
    
    # Get prompt without current_time (should generate fallback)
    result = loader.get_system_prompt()
    
    assert "{timestamp}" not in result
    assert "The current time is" in result
    # Should contain a timestamp format
    assert "at" in result or "202" in result  # Basic validation


def test_get_system_prompt_with_custom_variables():
    """Test that custom variables passed via kwargs are substituted."""
    loader = PersonaLoader()
    
    # Create a test prompt with custom variable
    loader.persona.system_prompt = "Hello {name}, the year is {current_year}."
    
    # Get prompt with both current_time and custom variable
    current_time = "Monday, January 15, 2025 at 14:30:45"
    result = loader.get_system_prompt(current_time=current_time, name="TestUser")
    
    assert "{name}" not in result
    assert "{current_year}" not in result
    assert "TestUser" in result
    assert "2025" in result


def test_get_system_prompt_no_variables():
    """Test that prompt without variables is returned as-is."""
    loader = PersonaLoader()
    
    # Create a test prompt without variables
    original_prompt = "This is a plain prompt with no variables."
    loader.persona.system_prompt = original_prompt
    
    # Get prompt
    result = loader.get_system_prompt(current_time="Monday, January 15, 2025 at 14:30:45")
    
    assert result == original_prompt


def test_get_system_prompt_missing_variable():
    """Test that missing variables are handled gracefully."""
    loader = PersonaLoader()
    
    # Create a test prompt with undefined variable
    loader.persona.system_prompt = "Hello {undefined_var}."
    
    # Get prompt - should log warning but not crash
    result = loader.get_system_prompt(current_time="Monday, January 15, 2025 at 14:30:45")
    
    # Should leave placeholder or handle gracefully
    # The exact behavior depends on Python's format() - it will raise KeyError
    # but we catch it and return original, so placeholder might remain
    assert isinstance(result, str)

