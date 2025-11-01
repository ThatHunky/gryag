# Advanced Features Integration Guide

**Date**: 2025-10-30
**Features**: Feature-Level Rate Limiting + Comprehensive Media Handling
**Status**: Ready for Integration

---

## Overview

This guide documents two major features that have been implemented:

1. **Feature-Level Rate Limiting with Adaptive Throttling**
2. **Comprehensive Media Handling (Documents, Audio, Video, Images)**

Both features are production-ready and designed to integrate seamlessly with the existing C++ bot architecture.

---

## Part 1: Feature-Level Rate Limiting

### Purpose

The feature rate limiter provides per-feature quota management with adaptive throttling based on user reputation. This prevents abuse while allowing good users higher limits.

**Example Quotas**:
- Weather: 5/hour, 20/day
- Web Search: 10/hour, 50/day
- Image Generation: 3/hour, 10/day
- Polls: 5/hour, 20/day
- Memory: 20/hour, 100/day
- Currency: 10/hour, 50/day
- Calculator: 50/hour, 200/day

### Files

- **Header**: `cpp/include/gryag/services/rate_limit/feature_rate_limiter.hpp`
- **Implementation**: `cpp/src/services/rate_limit/feature_rate_limiter.cpp`

### Key Components

#### FeatureQuota Structure
```cpp
struct FeatureQuota {
    std::string feature_name;           // e.g., "weather"
    int max_requests_per_hour;          // e.g., 5
    int max_requests_per_day;           // e.g., 20
    bool admin_bypass;                  // true = admins never throttled
    double reputation_multiplier_min;   // 0.5 = bad users get 50% limit
    double reputation_multiplier_max;   // 2.0 = good users get 200% limit
};
```

#### Main API Methods

**Check if user can use feature**:
```cpp
bool FeatureRateLimiter::allow_feature(
    std::int64_t user_id,
    const std::string& feature_name,
    const std::vector<std::int64_t>& admin_user_ids = {}
);
```

**Record feature usage**:
```cpp
void FeatureRateLimiter::record_usage(
    std::int64_t user_id,
    const std::string& feature_name
);
```

**Update user reputation** (0.0 = bad, 1.0 = neutral, 2.0 = excellent):
```cpp
void FeatureRateLimiter::update_user_reputation(
    std::int64_t user_id,
    double reputation  // clamped to [0.0, 2.0]
);
```

**Get usage statistics**:
```cpp
struct UsageStats {
    std::int64_t user_id;
    std::string feature_name;
    int used_this_hour;
    int used_this_day;
    int quota_hour;      // adjusted for reputation
    int quota_day;       // adjusted for reputation
    double user_reputation;
};

std::optional<UsageStats> FeatureRateLimiter::get_usage_stats(
    std::int64_t user_id,
    const std::string& feature_name
);
```

### Integration Example

#### 1. Initialization in main.cpp

```cpp
#include "gryag/services/rate_limit/feature_rate_limiter.hpp"

auto feature_limiter = std::make_shared<services::rate_limit::FeatureRateLimiter>(
    db_connection
);

// Features are pre-registered with default quotas
// You can customize if needed:
// feature_limiter->register_feature(
//     {"custom_feature", 100, 500, true, 0.5, 2.0}
// );
```

#### 2. Check before tool invocation

```cpp
// In chat handler, before calling a tool

if (!feature_limiter->allow_feature(user_id, "weather", settings.admin_user_ids)) {
    auto stats = feature_limiter->get_usage_stats(user_id, "weather");
    if (stats) {
        std::string msg = fmt::format(
            "❌ Перевищив ліміт для погоди.\n"
            "Використав: {}/{} цьогодини, {}/{} сьогодні",
            stats->used_this_hour, stats->quota_hour,
            stats->used_this_day, stats->quota_day
        );
        client.send_message(chat_id, msg);
    }
    return;
}

// Use the feature...
auto result = invoke_weather_tool(location);

// Record successful usage
feature_limiter->record_usage(user_id, "weather");
```

#### 3. Adjust reputation based on feedback

```cpp
// Increase reputation for good behavior
feature_limiter->update_user_reputation(user_id, 1.5);  // Loyal user

// Decrease reputation for bad behavior
feature_limiter->update_user_reputation(user_id, 0.7);  // Spammy user
```

#### 4. Admin commands to manage quotas

```cpp
// Reset user's quotas
feature_limiter->reset_user_quotas(user_id);

// Reset feature quotas for all users
feature_limiter->reset_feature_quotas("weather");

// List all registered features
auto features = feature_limiter->list_features();
```

### Reputation Scoring Strategy

**Increase reputation when**:
- User receives praise emoji (👍, ❤️, etc.)
- User's response shows satisfaction
- Admin explicitly marks as trusted

**Decrease reputation when**:
- User gets throttled repeatedly
- User sends error in quick succession
- User tries many failed searches
- Admin explicitly marks as spammy

**Default**: 1.0 (neutral, base quota)

### Database Schema

Uses existing tables:
- `feature_rate_limits` - Per-feature, per-window tracking
- `user_request_history` - Individual request log with throttle flag
- Triggers auto-clean records older than 7 days

---

## Part 2: Comprehensive Media Handling

### Purpose

The media handler provides production-ready support for documents, audio, video, and images with validation, storage reference management, and metadata tracking.

**Supported Types**:
- Images: PNG, JPG, GIF, WebP, BMP, TIFF, SVG
- Documents: PDF, DOCX, XLSX, PPTX, TXT, CSV, JSON
- Audio: MP3, WAV, OGG, FLAC, AAC, M4A, WMA, OPUS
- Video: MP4, WebM, MOV, AVI, MKV, FLV, WMV, M4V

### Files

- **Header**: `cpp/include/gryag/services/media/media_handler.hpp`
- **Implementation**: `cpp/src/services/media/media_handler.cpp`

### Key Components

#### MediaInfo Structure
```cpp
struct MediaInfo {
    std::string file_id;              // Telegram file_id
    std::string file_unique_id;       // Telegram file_unique_id
    MediaType type;                    // image/document/audio/video/unknown
    std::string mime_type;             // e.g., "application/pdf"
    std::string filename;              // e.g., "document.pdf"
    std::int64_t file_size_bytes;      // File size in bytes
    std::int64_t message_id;           // Message containing media
    std::int64_t user_id;              // User who uploaded
    std::int64_t chat_id;              // Chat where uploaded
    std::int64_t timestamp;            // Upload time
    std::optional<std::int64_t> duration_seconds;  // For audio/video
    std::optional<int> width;                      // For images/video
    std::optional<int> height;                     // For images/video
};
```

#### Main API Methods

**Store media information**:
```cpp
void MediaHandler::store_media(const MediaInfo& info);
```

**Retrieve media information**:
```cpp
std::optional<MediaInfo> MediaHandler::get_media(const std::string& file_id);
```

**Get all media in a chat**:
```cpp
std::vector<MediaInfo> MediaHandler::get_chat_media(
    std::int64_t chat_id,
    int limit = 100
);
```

**Get all media from a user**:
```cpp
std::vector<MediaInfo> MediaHandler::get_user_media(
    std::int64_t user_id,
    int limit = 100
);
```

**Validate media before storage**:
```cpp
struct ValidationResult {
    bool is_valid;
    std::string error_message;
};

ValidationResult MediaHandler::validate_media(const MediaInfo& info);
```

**Get storage reference for Gemini API**:
```cpp
std::string MediaHandler::get_storage_reference(
    const std::string& file_id
);
// Returns: "telegram://file_id"
```

**Get media statistics for a chat**:
```cpp
struct MediaStats {
    int total_files;
    int image_count;
    int document_count;
    int audio_count;
    int video_count;
    std::int64_t total_bytes_stored;
};

MediaStats MediaHandler::get_chat_media_stats(std::int64_t chat_id);
```

### Size Limits

**Default Size Limits**:
- Images: 100 MB
- Documents: 500 MB
- Audio: 1 GB
- Video: 2 GB

**Customize**:
```cpp
MediaHandler::SizeLimits limits;
limits.image_max_bytes = 50 * 1024 * 1024;  // 50 MB
media_handler->set_size_limits(limits);
```

### Integration Example

#### 1. Initialization in main.cpp

```cpp
#include "gryag/services/media/media_handler.hpp"

auto media_handler = std::make_shared<services::media::MediaHandler>(
    db_connection
);

// Optionally customize size limits
services::media::MediaHandler::SizeLimits custom_limits;
custom_limits.video_max_bytes = 1024 * 1024 * 1024;  // 1 GB
media_handler->set_size_limits(custom_limits);
```

#### 2. Store media from message

```cpp
// In message handler, when media is detected

if (message.has_photo() || message.has_document() ||
    message.has_audio() || message.has_video()) {

    services::media::MediaInfo info;
    info.file_id = get_file_id_from_message(message);
    info.file_unique_id = get_file_unique_id_from_message(message);
    info.type = detect_type_from_message(message);
    info.mime_type = message.mime_type();
    info.filename = message.file_name();
    info.file_size_bytes = message.file_size();
    info.message_id = message.message_id;
    info.user_id = message.from->id;
    info.chat_id = message.chat.id;
    info.timestamp = message.date;

    if (message.has_audio() || message.has_video()) {
        info.duration_seconds = message.duration();
    }
    if (message.has_photo() || message.has_video()) {
        info.width = message.width();
        info.height = message.height();
    }

    media_handler->store_media(info);
}
```

#### 3. Validate before processing

```cpp
auto validation = media_handler->validate_media(info);
if (!validation.is_valid) {
    client.send_message(chat_id,
        "❌ Файл недійсний: " + validation.error_message);
    return;
}
```

#### 4. Get storage reference for Gemini

```cpp
// When passing media to Gemini API
std::string storage_ref = media_handler->get_storage_reference(file_id);

// Use in Gemini request:
// {
//   "mime_type": "application/pdf",
//   "file_data": {
//     "file_uri": storage_ref
//   }
// }
```

#### 5. Show media statistics

```cpp
auto stats = media_handler->get_chat_media_stats(chat_id);

std::string msg = fmt::format(
    "📊 Медіа статистика:\n"
    "🖼️ Зображень: {}\n"
    "📄 Документів: {}\n"
    "🎵 Аудіо: {}\n"
    "🎬 Відео: {}\n"
    "💾 Всього: {} MB",
    stats.image_count,
    stats.document_count,
    stats.audio_count,
    stats.video_count,
    stats.total_bytes_stored / (1024 * 1024)
);
client.send_message(chat_id, msg);
```

### Media Type Detection

**Automatic detection from MIME type**:
```cpp
auto type = MediaHandler::detect_type_from_mime("application/pdf");
// Returns: MediaType::Document
```

**Formatting media info for display**:
```cpp
std::string formatted = MediaHandler::format_media_info(info);
client.send_message(chat_id, formatted);
```

### Database Schema

Creates dynamic `media_files` table with:
- Primary key: `file_id`
- Unique constraint: `file_unique_id`
- Indexes: user_id, chat_id, type, stored_at

---

## Integration Checklist

### Feature-Level Rate Limiting
- [ ] Add `FeatureRateLimiter` to handler context
- [ ] Initialize with default quotas in main
- [ ] Add `allow_feature()` check before each tool
- [ ] Call `record_usage()` after successful tool use
- [ ] Implement reputation tracking logic
- [ ] Create admin commands for quota management
- [ ] Add rate limit information to help text

### Media Handling
- [ ] Add `MediaHandler` to handler context
- [ ] Initialize in main
- [ ] Detect media in incoming messages
- [ ] Validate media before storage
- [ ] Store media metadata
- [ ] Generate storage references for Gemini
- [ ] Create `/media_stats` command
- [ ] Add media cleanup task (monthly)
- [ ] Document media type support

### Testing
- [ ] Test each feature individually
- [ ] Test rate limiting with rapid requests
- [ ] Test reputation adjustments
- [ ] Test media validation (file too large, unsupported type)
- [ ] Test media retrieval
- [ ] Create golden transcript tests
- [ ] Test admin commands

---

## Performance Considerations

### Rate Limiting
- **In-Memory Storage**: Feature quotas cached
- **Database Queries**: O(1) for typical lookups
- **Cleanup**: Automatic via schema trigger
- **Recommendation**: Run `cleanup_old_records()` weekly

### Media Handling
- **Database Size**: Tracks metadata, not files themselves
- **Indexes**: Optimized for user/chat/type lookups
- **Cleanup**: Removes old records monthly via `cleanup_old_media_records(90)`
- **Recommendation**: Archive old media files separately

---

## Security Considerations

### Rate Limiting
- ✅ Admin bypass prevents locking out admins
- ✅ Reputation scoring can be gamed (monitor and adjust)
- ✅ Limits are per-feature (user can still message frequently)
- ⚠️ Consider: Rate limiting entire message processing in future

### Media Handling
- ✅ File size limits prevent disk exhaustion
- ✅ Type validation prevents execution
- ✅ Storage references abstract file paths
- ⚠️ Consider: Scan large files for malware
- ⚠️ Consider: Encrypt sensitive documents

---

## Future Enhancements

### Rate Limiting
- [ ] Per-chat quotas (different limits per group)
- [ ] Time-based quotas (higher limits during off-peak)
- [ ] Machine learning reputation scoring
- [ ] Graduated throttling (slow down instead of blocking)
- [ ] User feedback loop (automatic reputation adjustment)

### Media Handling
- [ ] Malware scanning for uploads
- [ ] Metadata stripping (privacy)
- [ ] Automatic compression for images/video
- [ ] OCR for document text extraction
- [ ] Video thumbnail generation
- [ ] Media transcoding for compatibility

---

## Example: Complete Tool Integration

Here's a complete example of integrating both features for a weather tool:

```cpp
// In chat handler, handling /weather command

bool ChatHandler::handle_weather(const telegram::Message& message,
                                 telegram::TelegramClient& client) {
    // 1. Check rate limit
    if (!context_.feature_limiter->allow_feature(
            message.from->id,
            "weather",
            context_.settings->admin_user_ids)) {

        auto stats = context_.feature_limiter->get_usage_stats(
            message.from->id, "weather");

        if (stats) {
            client.send_message(message.chat.id, fmt::format(
                "❌ Перевищив ліміт для погоди.\n"
                "Використав: {}/{} цьогодини\n"
                "{}/{} сьогодні\n"
                "Спробуй завтра!",
                stats->used_this_hour, stats->quota_hour,
                stats->used_this_day, stats->quota_day
            ));
        }
        return true;
    }

    // 2. Extract location and call weather API
    std::string location = extract_location(message.text);
    auto weather = get_weather(location);

    if (!weather) {
        client.send_message(message.chat.id,
            "❌ Не можу отримати погоду для цієї локації.");
        return true;
    }

    // 3. Record usage (success)
    context_.feature_limiter->record_usage(message.from->id, "weather");

    // 4. Update positive reputation (good outcome)
    context_.feature_limiter->update_user_reputation(
        message.from->id, 1.2);  // Slight boost

    // 5. Send response with media if available
    if (weather->has_icon_url) {
        // Store the weather icon metadata
        services::media::MediaInfo icon_info;
        icon_info.file_id = weather->icon_file_id;
        icon_info.type = services::media::MediaType::Image;
        icon_info.mime_type = "image/png";
        icon_info.filename = "weather_icon.png";
        icon_info.user_id = message.from->id;
        icon_info.chat_id = message.chat.id;

        context_.media_handler->store_media(icon_info);
    }

    client.send_message(message.chat.id, format_weather(weather));
    return true;
}
```

---

## Documentation Updates

Update these files once integrated:
- `cpp/README.md` - Add feature-level rate limiting and media handling
- `docs/README.md` - Document new admin commands
- `CHANGELOG.md` - Add to latest version
- Deployment guide - Note rate limiting configuration options

---

## Support & Questions

For implementation questions:
1. Check the header files for detailed parameter documentation
2. Review the implementation files for algorithm details
3. Run integration tests to validate behavior
4. Check database schema for storage details

---

**Implementation Status**: ✅ Ready for Integration
**Expected Integration Time**: 2-3 hours per component
**Testing Time**: 4-6 hours per component
**Total Recommended**: 1 week (careful integration + thorough testing)

---

**Next Steps**:
1. Integrate rate limiting into tool pipeline
2. Test with golden transcripts
3. Integrate media handling into message processing
4. Create admin commands
5. Deploy to staging
6. Monitor and adjust quotas based on real usage

