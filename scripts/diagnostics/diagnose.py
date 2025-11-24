#!/usr/bin/env python3
"""
Quick diagnostic and fix script for Gryag bot issues.

Identifies common problems:
- Redis connection issues
- High CPU usage
- Processing duration problems
- Resource optimization needs
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd, capture_output=True):
    """Run a shell command and return result."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def check_docker():
    """Check if Docker is running and containers are up."""
    print("🐳 Checking Docker status...")

    success, stdout, stderr = run_command("docker info")
    if not success:
        print("❌ Docker is not running")
        return False

    success, stdout, stderr = run_command("docker-compose ps")
    if "Up" in stdout:
        print("✅ Docker containers are running")
        return True
    else:
        print("⚠️  Docker containers may not be running properly")
        print(stdout)
        return False


def check_redis():
    """Check Redis connectivity."""
    print("🔴 Checking Redis...")

    success, stdout, stderr = run_command("docker-compose exec -T redis redis-cli ping")
    if success and "PONG" in stdout:
        print("✅ Redis is responding")

        # Check memory usage
        success, stdout, stderr = run_command(
            "docker-compose exec -T redis redis-cli info memory | grep used_memory_human"
        )
        if success:
            memory = stdout.strip().split(":")[1] if ":" in stdout else "unknown"
            print(f"   Memory usage: {memory}")

        return True
    else:
        print("❌ Redis is not responding")
        print(f"   Error: {stderr}")
        return False


def analyze_bot_logs():
    """Analyze bot logs for issues."""
    print("📜 Analyzing bot logs...")

    # Get recent logs
    success, logs, stderr = run_command("docker-compose logs bot --tail=100")
    if not success:
        print("❌ Could not retrieve bot logs")
        return False

    lines = logs.split("\n")

    # Count issues
    redis_errors = sum(1 for line in lines if "Redis quota lookup failed" in line)
    cpu_critical = sum(1 for line in lines if "CRITICAL: CPU usage" in line)
    duration_zeros = sum(1 for line in lines if "Duration 0 ms" in line)
    duration_normal = sum(
        1 for line in lines if "Duration" in line and "Duration 0 ms" not in line
    )

    print(f"   Redis errors: {redis_errors}")
    print(f"   CPU critical alerts: {cpu_critical}")
    print(f"   Zero duration messages: {duration_zeros}")
    print(f"   Normal duration messages: {duration_normal}")

    # Analyze issues
    issues = []

    if redis_errors > 0:
        issues.append("redis_connection")
        print("   🔍 Issue: Redis connection problems detected")

    if cpu_critical > 3:
        issues.append("high_cpu")
        print("   🔍 Issue: High CPU usage detected")

    if duration_zeros > duration_normal and duration_zeros > 5:
        issues.append("message_processing")
        print("   🔍 Issue: Most messages showing 0ms duration (throttling/filtering)")

    if not issues:
        print("✅ No major issues detected in logs")

    return issues


def check_env_config():
    """Check environment configuration for optimization."""
    print("⚙️  Checking configuration...")

    env_file = Path(".env")
    if not env_file.exists():
        print("❌ .env file not found")
        return False

    config = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                config[key] = value

    # Check key settings
    issues = []

    use_redis = config.get("USE_REDIS", "false").lower()
    if use_redis != "true":
        issues.append("redis_disabled")
        print("   ⚠️  Redis is disabled - may cause quota lookup slowness")

    fact_method = config.get("FACT_EXTRACTION_METHOD", "hybrid")
    if fact_method in ["hybrid", "local_model", "gemini"]:
        issues.append("heavy_extraction")
        print(f"   ⚠️  Using '{fact_method}' extraction - may cause high CPU")

    summarization = config.get("ENABLE_PROFILE_SUMMARIZATION", "false").lower()
    if summarization == "true":
        issues.append("summarization_enabled")
        print("   ⚠️  Profile summarization enabled - may cause CPU spikes")

    window_size = int(config.get("CONVERSATION_WINDOW_SIZE", "8"))
    if window_size > 6:
        issues.append("large_windows")
        print(
            f"   ⚠️  Large conversation windows ({window_size}) - may increase memory usage"
        )

    if not issues:
        print("✅ Configuration looks optimized")

    return issues


def suggest_fixes(issues):
    """Suggest fixes for detected issues."""
    if not issues:
        print("🎉 No issues detected - system appears healthy!")
        return

    print("\n💡 Suggested Fixes:")
    print("==================")

    all_issues = set()
    for issue_list in issues:
        if isinstance(issue_list, list):
            all_issues.update(issue_list)
        elif isinstance(issue_list, str):
            all_issues.add(issue_list)

    if "redis_connection" in all_issues:
        print("\n🔴 Redis Connection Issues:")
        print("   1. Restart Redis: docker-compose restart redis")
        print("   2. Check Redis logs: docker-compose logs redis")
        print("   3. If persistent, disable Redis: set USE_REDIS=false in .env")

    if "high_cpu" in all_issues:
        print("\n🔥 High CPU Usage:")
        print(
            "   1. Switch to rule-based extraction: FACT_EXTRACTION_METHOD=rule_based"
        )
        print("   2. Disable summarization: ENABLE_PROFILE_SUMMARIZATION=false")
        print("   3. Reduce workers: MONITORING_WORKERS=1")
        print("   4. Reduce window size: CONVERSATION_WINDOW_SIZE=3")

    if "message_processing" in all_issues:
        print("\n⚡ Message Processing Issues:")
        print("   1. Check if bot is under resource pressure")
        print("   2. Increase rate limits: PER_USER_PER_HOUR=10")
        print("   3. Enable message filtering: ENABLE_MESSAGE_FILTERING=true")

    if "heavy_extraction" in all_issues:
        print("\n🧠 Heavy Fact Extraction:")
        print("   1. Use rule-based only: FACT_EXTRACTION_METHOD=rule_based")
        print("   2. Disable Gemini fallback: ENABLE_GEMINI_FALLBACK=false")

    if "large_windows" in all_issues:
        print("\n📊 Large Windows:")
        print("   1. Reduce window size: CONVERSATION_WINDOW_SIZE=5")
        print("   2. Reduce concurrent windows: MAX_CONCURRENT_WINDOWS=25")

    print("\n🔧 Quick Fix Command:")
    print("   ./setup.sh optimize && docker-compose restart bot")


def main():
    """Main diagnostic function."""
    print("🔍 Gryag Bot Health Check & Diagnostics")
    print("=======================================\n")

    issues = []

    # Run checks
    if not check_docker():
        print("\n❌ Docker issues detected. Please fix Docker setup first.")
        sys.exit(1)

    print()
    redis_ok = check_redis()
    if not redis_ok:
        issues.append(["redis_connection"])

    print()
    log_issues = analyze_bot_logs()
    if log_issues:
        issues.append(log_issues)

    print()
    config_issues = check_env_config()
    if config_issues:
        issues.append(config_issues)

    print()
    suggest_fixes(issues)

    print("\n📊 For continuous monitoring:")
    print("   Health check: ./setup.sh health")
    print("   Live logs: ./setup.sh logs")
    print("   Full setup: ./setup.sh setup")


if __name__ == "__main__":
    main()
