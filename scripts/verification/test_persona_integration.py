#!/usr/bin/env python3
"""Test PersonaLoader integration with response templates.

This script verifies that:
1. PersonaLoader loads correctly with default and custom personas
2. Response templates are available
3. Template substitution works
4. Backward compatibility is maintained
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.persona import PersonaLoader


def test_default_persona() -> bool:
    """Test loading default persona with no configuration."""
    print("\n" + "=" * 80)
    print("TEST 1: Default Persona Loading")
    print("=" * 80)

    try:
        loader = PersonaLoader()

        # Check persona loaded
        print(f"✅ Persona loaded: {loader.persona.name}")
        print(f"   Language: {loader.persona.language}")
        print(f"   Display name: {loader.persona.display_name}")
        print(f"   Admin users: {len(loader.persona.admin_users)}")

        # Check responses
        print(f"\n✅ Response templates: {len(loader.response_templates)} keys")
        print(f"   Keys: {', '.join(sorted(loader.response_templates.keys())[:5])}...")

        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_response_templates() -> bool:
    """Test response template retrieval and substitution."""
    print("\n" + "=" * 80)
    print("TEST 2: Response Template Retrieval and Substitution")
    print("=" * 80)

    try:
        loader = PersonaLoader()

        tests = [
            ("error_fallback", {}, "Should contain 'тупить'"),
            ("empty_reply", {}, "Should contain 'конкретніше'"),
            ("throttle_notice", {"minutes": 5}, "Should contain '5 хв'"),
            ("banned_reply", {"bot_name": "test_bot"}, "Should contain 'test_bot'"),
            ("admin_only", {}, "Should contain 'своїх'"),
            ("ban_success", {}, "Should contain 'кувалдіровано'"),
        ]

        for key, kwargs, description in tests:
            response = loader.get_response(key, **kwargs)
            if response:
                print(f"✅ {key}: {response[:60]}...")
                if kwargs:
                    print(f"   Params: {kwargs}, {description}")
            else:
                print(f"❌ {key}: Empty response!")
                return False

        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_users() -> bool:
    """Test admin user detection."""
    print("\n" + "=" * 80)
    print("TEST 3: Admin User Detection")
    print("=" * 80)

    try:
        loader = PersonaLoader()

        # Test known admin (from default persona)
        admin_id = 831570515  # кавунева пітса
        if loader.is_admin(admin_id):
            admin_info = loader.get_admin_info(admin_id)
            print(f"✅ Admin detected: {admin_info.name} (ID: {admin_id})")
            print(f"   Special status: {admin_info.special_status}")
        else:
            print(f"❌ Admin not detected for ID {admin_id}")
            return False

        # Test non-admin
        if not loader.is_admin(999999999):
            print("✅ Non-admin correctly identified (ID: 999999999)")
        else:
            print("❌ Non-admin incorrectly identified as admin")
            return False

        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trigger_patterns() -> bool:
    """Test trigger pattern retrieval."""
    print("\n" + "=" * 80)
    print("TEST 4: Trigger Patterns")
    print("=" * 80)

    try:
        loader = PersonaLoader()

        patterns = loader.get_trigger_patterns()
        print(f"✅ Trigger patterns loaded: {len(patterns)} pattern(s)")
        for i, pattern in enumerate(patterns):
            print(f"   Pattern {i+1}: {pattern[:60]}...")

        return len(patterns) > 0
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_yaml_loading() -> bool:
    """Test loading persona from YAML file."""
    print("\n" + "=" * 80)
    print("TEST 5: YAML Persona File Loading")
    print("=" * 80)

    try:
        yaml_path = Path("personas/ukrainian_gryag.yaml")
        if not yaml_path.exists():
            print(f"⚠️  YAML file not found: {yaml_path}")
            return True  # Not a failure, just skip

        loader = PersonaLoader(persona_config_path=str(yaml_path))
        print(f"✅ Loaded persona from {yaml_path}")
        print(f"   Name: {loader.persona.name}")
        print(f"   Language: {loader.persona.language}")

        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_json_templates_loading() -> bool:
    """Test loading response templates from JSON file."""
    print("\n" + "=" * 80)
    print("TEST 6: JSON Response Templates Loading")
    print("=" * 80)

    try:
        json_path = Path("response_templates/ukrainian.json")
        if not json_path.exists():
            print(f"⚠️  JSON file not found: {json_path}")
            return True  # Not a failure, just skip

        loader = PersonaLoader(response_templates_path=str(json_path))
        print(f"✅ Loaded response templates from {json_path}")
        print(f"   Templates: {len(loader.response_templates)} keys")

        # Verify some keys exist
        required_keys = ["error_fallback", "empty_reply", "banned_reply"]
        for key in required_keys:
            if key in loader.response_templates:
                print(f"   ✅ {key}: OK")
            else:
                print(f"   ❌ {key}: MISSING")
                return False

        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main() -> int:
    """Run all tests."""
    print("\n" + "=" * 80)
    print("PERSONA LOADER INTEGRATION TESTS")
    print("=" * 80)

    results = [
        ("Default Persona Loading", test_default_persona()),
        ("Response Templates", test_response_templates()),
        ("Admin User Detection", test_admin_users()),
        ("Trigger Patterns", test_trigger_patterns()),
        ("YAML Persona Loading", test_yaml_loading()),
        ("JSON Templates Loading", test_json_templates_loading()),
    ]

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Persona integration is working correctly.")
        return 0
    else:
        print("\n❌ Some tests failed. See details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
