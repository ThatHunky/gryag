#!/usr/bin/env python3
"""
Phase 3 Validation Test Script

Tests continuous learning implementation:
1. Database schema validation
2. Window processing simulation
3. Fact extraction verification
4. Quality processing validation
5. Performance metrics

Run: python test_phase3.py
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))


class Phase3Validator:
    """Validate Phase 3 implementation."""

    def __init__(self):
        self.db_path = Path(__file__).parent / "gryag.db"
        self.results = {"passed": [], "failed": [], "warnings": []}

    def run_all_tests(self):
        """Run all validation tests."""
        print("=" * 70)
        print("Phase 3 Validation Tests")
        print("=" * 70)
        print()

        # Test 1: Database schema
        print("Test 1: Database Schema Validation")
        print("-" * 70)
        self.test_database_schema()
        print()

        # Test 2: Configuration
        print("Test 2: Configuration Validation")
        print("-" * 70)
        self.test_configuration()
        print()

        # Test 3: Database state
        print("Test 3: Current Database State")
        print("-" * 70)
        self.test_database_state()
        print()

        # Test 4: Module imports
        print("Test 4: Module Import Validation")
        print("-" * 70)
        self.test_module_imports()
        print()

        # Summary
        self.print_summary()

    def test_database_schema(self):
        """Validate database schema has Phase 3 tables."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check for required tables
            required_tables = [
                "conversation_windows",
                "fact_quality_metrics",
                "message_metadata",
            ]

            cursor.execute(
                """
                SELECT name FROM sqlite_master 
                WHERE type='table' 
                ORDER BY name
            """
            )
            existing_tables = [row[0] for row in cursor.fetchall()]

            print(f"Found {len(existing_tables)} tables in database:")
            for table in existing_tables:
                marker = "✓" if table in required_tables else " "
                print(f"  [{marker}] {table}")

            # Check each required table
            for table in required_tables:
                if table in existing_tables:
                    # Get column info
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = cursor.fetchall()
                    self.results["passed"].append(
                        f"Table {table} exists ({len(columns)} columns)"
                    )
                else:
                    self.results["failed"].append(f"Table {table} missing")

            # Check for embedding column in user_facts
            if "user_facts" in existing_tables:
                cursor.execute("PRAGMA table_info(user_facts)")
                columns = [col[1] for col in cursor.fetchall()]
                if "embedding" in columns:
                    self.results["passed"].append("user_facts.embedding column exists")
                else:
                    self.results["warnings"].append(
                        "user_facts.embedding column missing (quality processing limited)"
                    )

            conn.close()

        except Exception as e:
            self.results["failed"].append(f"Database schema check failed: {e}")
            print(f"  ✗ Error: {e}")

    def test_configuration(self):
        """Validate configuration settings."""
        try:
            from app.config import get_settings

            settings = get_settings()

            # Check Phase 3 settings
            phase3_settings = {
                "ENABLE_CONTINUOUS_MONITORING": settings.ENABLE_CONTINUOUS_MONITORING,
                "ENABLE_MESSAGE_FILTERING": settings.ENABLE_MESSAGE_FILTERING,
                "ENABLE_ASYNC_PROCESSING": settings.ENABLE_ASYNC_PROCESSING,
                "CONVERSATION_WINDOW_SIZE": settings.CONVERSATION_WINDOW_SIZE,
                "CONVERSATION_WINDOW_TIMEOUT": settings.CONVERSATION_WINDOW_TIMEOUT,
            }

            print("Current configuration:")
            for key, value in phase3_settings.items():
                marker = "✓" if value else "○"
                print(f"  [{marker}] {key} = {value}")

            # Validate expected state
            if settings.ENABLE_CONTINUOUS_MONITORING:
                self.results["passed"].append("Continuous monitoring enabled")
            else:
                self.results["warnings"].append(
                    "Continuous monitoring disabled (expected for testing)"
                )

            if not settings.ENABLE_MESSAGE_FILTERING:
                self.results["passed"].append(
                    "Message filtering disabled (safe default)"
                )
            else:
                self.results["warnings"].append(
                    "Message filtering enabled (may process fewer messages)"
                )

            if not settings.ENABLE_ASYNC_PROCESSING:
                self.results["passed"].append(
                    "Async processing disabled (safe default)"
                )
            else:
                self.results["warnings"].append(
                    "Async processing enabled (ensure workers running)"
                )

        except Exception as e:
            self.results["failed"].append(f"Configuration check failed: {e}")
            print(f"  ✗ Error: {e}")

    def test_database_state(self):
        """Check current database state and statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Count records in key tables
            tables_to_check = [
                "conversation_windows",
                "fact_quality_metrics",
                "user_facts",
                "message_metadata",
            ]

            print("Record counts:")
            for table in tables_to_check:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    print(f"  {table:30} {count:>6} records")

                    if table == "conversation_windows" and count > 0:
                        # Show recent windows
                        cursor.execute(
                            f"""
                            SELECT id, chat_id, message_count, closure_reason, created_at
                            FROM {table}
                            ORDER BY created_at DESC
                            LIMIT 3
                        """
                        )
                        windows = cursor.fetchall()
                        if windows:
                            print(f"    Recent windows:")
                            for w in windows:
                                print(
                                    f"      ID {w[0]}: {w[2]} messages, closed by {w[3]}"
                                )

                    if table == "fact_quality_metrics" and count > 0:
                        # Show quality stats
                        cursor.execute(
                            f"""
                            SELECT 
                                COUNT(*) as total,
                                AVG(duplicates_removed) as avg_dupes,
                                AVG(conflicts_resolved) as avg_conflicts,
                                AVG(processing_time_ms) as avg_time_ms
                            FROM {table}
                        """
                        )
                        stats = cursor.fetchone()
                        if stats[0] > 0:
                            print(f"    Quality processing:")
                            print(f"      Avg duplicates removed: {stats[1]:.1f}")
                            print(f"      Avg conflicts resolved: {stats[2]:.1f}")
                            print(f"      Avg processing time: {stats[3]:.0f}ms")

                    if table == "user_facts" and count > 0:
                        # Check for window-extracted facts
                        cursor.execute(
                            f"""
                            SELECT COUNT(*)
                            FROM {table}
                            WHERE evidence_text LIKE '%extracted_from_window%'
                        """
                        )
                        window_facts = cursor.fetchone()[0]
                        if window_facts > 0:
                            print(f"    Window-extracted facts: {window_facts}")
                            self.results["passed"].append(
                                f"Found {window_facts} window-extracted facts"
                            )
                        else:
                            self.results["warnings"].append(
                                "No window-extracted facts found (Phase 3 may not be running)"
                            )

                except sqlite3.OperationalError as e:
                    print(f"  {table:30} Table doesn't exist")
                    self.results["warnings"].append(f"Table {table} doesn't exist")

            conn.close()

        except Exception as e:
            self.results["failed"].append(f"Database state check failed: {e}")
            print(f"  ✗ Error: {e}")

    def test_module_imports(self):
        """Test that Phase 3 modules can be imported."""
        modules_to_test = [
            ("app.services.monitoring.continuous_monitor", "ContinuousMonitor"),
            ("app.services.monitoring.message_classifier", "MessageClassifier"),
            ("app.services.monitoring.conversation_analyzer", "ConversationAnalyzer"),
            ("app.services.monitoring.fact_quality_manager", "FactQualityManager"),
        ]

        print("Module imports:")
        for module_path, class_name in modules_to_test:
            try:
                module = __import__(module_path, fromlist=[class_name])
                cls = getattr(module, class_name)
                print(f"  ✓ {module_path}.{class_name}")
                self.results["passed"].append(f"Import {class_name} successful")
            except Exception as e:
                print(f"  ✗ {module_path}.{class_name}: {e}")
                self.results["failed"].append(f"Import {class_name} failed: {e}")

    def print_summary(self):
        """Print test summary."""
        print()
        print("=" * 70)
        print("Test Summary")
        print("=" * 70)

        total = (
            len(self.results["passed"])
            + len(self.results["failed"])
            + len(self.results["warnings"])
        )

        print(f"\n✓ Passed:   {len(self.results['passed']):>3}")
        for item in self.results["passed"]:
            print(f"    • {item}")

        if self.results["warnings"]:
            print(f"\n⚠ Warnings: {len(self.results['warnings']):>3}")
            for item in self.results["warnings"]:
                print(f"    • {item}")

        if self.results["failed"]:
            print(f"\n✗ Failed:   {len(self.results['failed']):>3}")
            for item in self.results["failed"]:
                print(f"    • {item}")
        else:
            print(f"\n✗ Failed:   {len(self.results['failed']):>3}")

        print()
        print("-" * 70)

        if not self.results["failed"]:
            print("✓ All tests passed!")
            print("\nNext steps:")
            print("  1. Start the bot: python -m app.main")
            print("  2. Send 8-10 messages in a test chat")
            print("  3. Wait 3+ minutes for window to close")
            print("  4. Check logs for: 'Extracted N facts from window'")
            print("  5. Run: python test_phase3.py (again to see new facts)")
            return 0
        else:
            print("✗ Some tests failed. Fix issues before proceeding.")
            print("\nTroubleshooting:")
            print("  • Missing tables? Run: python -m app.main (creates schema)")
            print("  • Import errors? Check: pip install -r requirements.txt")
            print("  • Config issues? Check: .env file settings")
            return 1


def main():
    """Run validation tests."""
    validator = Phase3Validator()
    exit_code = validator.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
