"""Manual log cleanup utility."""

from pathlib import Path

from app.config import get_settings
from app.core.logging_config import cleanup_old_logs


def main() -> None:
    """Clean up old log files based on retention settings."""
    settings = get_settings()
    print(f"Cleaning logs older than {settings.log_retention_days} days...")
    print(f"Log directory: {settings.log_dir}")
    cleanup_old_logs(settings)
    print("Done!")


if __name__ == "__main__":
    main()
