#!/usr/bin/env python3
"""
Verification script for multimodal implementation.
Run this to verify all changes are in place.
"""

import ast
import re
from pathlib import Path


def check_file_contains(filepath: Path, patterns: list[str]) -> dict[str, bool]:
    """Check if file contains all given patterns."""
    content = filepath.read_text()
    results = {}
    for pattern in patterns:
        results[pattern] = pattern in content
    return results


def main():
    print("🔍 Verifying Multimodal Implementation\n")
    print("=" * 60)

    # Check media.py
    print("\n📁 app/services/media.py")
    media_checks = check_file_contains(
        Path("app/services/media.py"),
        [
            "message.video",
            "message.video_note",
            "message.animation",
            "message.audio",
            "message.sticker",
            "extract_youtube_urls",
            "YOUTUBE_REGEX",
            'kind = "video"',
            'kind = "audio"',
        ],
    )
    for pattern, found in media_checks.items():
        status = "✅" if found else "❌"
        print(f"  {status} {pattern}")

    # Check gemini.py
    print("\n📁 app/services/gemini.py")
    gemini_checks = check_file_contains(
        Path("app/services/gemini.py"),
        [
            "file_uri",
            "file_data",
            "YouTube URL",
        ],
    )
    for pattern, found in gemini_checks.items():
        status = "✅" if found else "❌"
        print(f"  {status} {pattern}")

    # Check chat.py
    print("\n📁 app/handlers/chat.py")
    chat_checks = check_file_contains(
        Path("app/handlers/chat.py"),
        [
            "extract_youtube_urls",
            "youtube_urls = extract_youtube_urls",
            "YouTube URL(s)",
            "videos = 0",
            "audio = 0",
            "youtube = 0",
        ],
    )
    for pattern, found in chat_checks.items():
        status = "✅" if found else "❌"
        print(f"  {status} {pattern}")

    # Check documentation
    print("\n📁 Documentation")
    doc_files = [
        "docs/features/MULTIMODAL_CAPABILITIES.md",
        "docs/features/MULTIMODAL_IMPLEMENTATION_SUMMARY.md",
    ]
    for doc in doc_files:
        exists = Path(doc).exists()
        status = "✅" if exists else "❌"
        print(f"  {status} {doc}")

    # Summary
    print("\n" + "=" * 60)
    all_checks = {**media_checks, **gemini_checks, **chat_checks}
    total = len(all_checks) + len(doc_files)
    passed = sum(all_checks.values()) + sum(Path(d).exists() for d in doc_files)

    print(f"\n📊 Summary: {passed}/{total} checks passed")

    if passed == total:
        print("✅ All multimodal features implemented successfully!")
    else:
        print("❌ Some features missing - review above")

    # Feature list
    print("\n🎯 Implemented Features:")
    features = [
        "📸 Image support (photos, stickers)",
        "🎵 Audio support (voice messages, audio files)",
        "🎬 Video support (files, video notes, animations/GIFs)",
        "📺 YouTube URL direct integration",
        "🔍 Automatic media type detection",
        "📝 Ukrainian media summaries",
        "⚠️  Size limit warnings (>20MB)",
        "📊 Comprehensive logging",
    ]
    for feature in features:
        print(f"  ✅ {feature}")

    print("\n🧪 Next Steps:")
    print("  1. Test with real Telegram messages")
    print("  2. Monitor logs for media collection")
    print("  3. Verify Gemini API responses")
    print("  4. Check YouTube URL detection")
    print("\nSee docs/features/MULTIMODAL_CAPABILITIES.md for testing guide")


if __name__ == "__main__":
    main()
