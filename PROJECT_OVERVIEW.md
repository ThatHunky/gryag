# GRYAG Project Overview

## Project Goal

**GRYAG** is an advanced Telegram group chat bot that implements a sophisticated Ukrainian-speaking persona powered by Google Gemini AI. The project aims to create an intelligent, context-aware, multimodal chat assistant that provides witty, sarcastic responses while maintaining conversation history and implementing robust rate limiting and moderation features.

## Core Objectives

### 1. **Intelligent Conversational AI**

- Integrate Google Gemini 2.5 Flash for natural language generation
- Maintain persistent conversation context using SQLite with optional Redis caching
- Implement semantic search capabilities for historical message retrieval
- Support multimodal interactions (text, images, voice messages, documents)

### 2. **Authentic Ukrainian Persona**

- Develop a distinctive personality: sharp, sarcastic, Ukrainian-speaking character
- Implement contextual awareness of Ukrainian culture and current events
- Support political stance and opinions aligned with Ukrainian perspectives
- Maintain consistent character voice across all interactions

### 3. **Robust Group Chat Management**

- Selective response system (only responds when directly addressed)
- Intelligent trigger detection (@mentions, replies, keyword matching)
- Thread-aware conversation tracking
- Admin-controlled user banning/unbanning system

### 4. **Advanced Rate Limiting & Moderation**

- Adaptive throttling system that adjusts based on user behavior
- Dual-storage quota management (SQLite + optional Redis)
- Admin privilege system with bypass capabilities
- Configurable retention policies for data cleanup

### 5. **Production-Ready Architecture**

- Docker containerization for easy deployment
- Comprehensive error handling and circuit breaker patterns
- Structured logging and telemetry collection
- Environment-based configuration management

## Technical Architecture

### **Core Components**

#### **AI Integration (`app/services/gemini.py`)**

- **Google Gemini Integration**: Async wrapper around Google GenerativeAI SDK
- **Multimodal Support**: Base64 encoding for images, audio, and documents
- **Tool Integration**: Custom function calling for message search and web grounding
- **Circuit Breaker**: Automatic failure detection and recovery mechanisms
- **Embedding Generation**: Semantic vector storage for context search

#### **Context Management (`app/services/context_store.py`)**

- **SQLite Persistence**: Stores messages, quotas, bans, and metadata
- **Semantic Search**: Cosine similarity-based message retrieval
- **Automatic Pruning**: Configurable data retention with background cleanup
- **Metadata Formatting**: Structured conversation context for AI consumption

#### **Message Handling (`app/handlers/chat.py`)**

- **Smart Triggering**: Responds only to @mentions, replies, or keyword matches
- **Context Assembly**: Builds conversation history with fallback mechanisms
- **Media Processing**: Handles photos, documents, voice messages through Telegram API
- **Response Generation**: Orchestrates AI calls with tool integration

#### **Middleware System**

- **Chat Metadata (`app/middlewares/chat_meta.py`)**: Injects dependencies and bot identity
- **Throttling (`app/middlewares/throttle.py`)**: Implements adaptive rate limiting with snarky responses

#### **Media Support (`app/services/media.py`)**

- **File Download**: Secure Telegram file retrieval with timeout handling
- **MIME Detection**: Automatic content type identification
- **Format Support**: Images (JPEG, PNG), Audio (OGG, MP3), Documents

### **Data Management**

#### **Database Schema (`db/schema.sql`)**

- **Messages**: Chat history with embeddings and metadata
- **Quotas**: Per-user rate limiting counters
- **Bans**: Admin-controlled user restrictions
- **Notices**: Throttling notification tracking

#### **Embedding System**

- **Vector Storage**: JSON arrays of float embeddings in SQLite
- **Semantic Similarity**: Cosine distance for context retrieval
- **Rate-Limited Generation**: Semaphore-controlled embedding API calls

## Key Features

### **Enhanced Conversational Intelligence**

- **Smart Context Management**: Up to 50 recent messages with intelligent summarization
- **Metadata Leak Prevention**: Advanced response cleaning to prevent technical data exposure
- **Semantic Memory**: Historical message search using vector embeddings
- **Tool Integration**: Dynamic web search and message history lookup
- **Context Summarization**: Automatic compression of long conversations to maintain relevance
- **Fallback Mechanisms**: Graceful degradation during API failures

### **Multimodal Capabilities**

- **Image Analysis**: Photo and document processing through Gemini Vision
- **Voice Processing**: Audio message transcription and analysis
- **Media Summarization**: Automatic content description in responses
- **Rich Context**: Media information integrated into conversation flow

### **Advanced Rate Limiting**

- **Adaptive Quotas**: Behavior-based limit adjustments
- **Dual Storage**: SQLite persistence with Redis performance optimization
- **Admin Exemptions**: Bypass system for privileged users
- **Granular Controls**: Per-chat, per-user, per-hour restrictions

### **Moderation & Administration**

- **User Banning**: Admin-controlled access restrictions
- **Quota Management**: Reset capabilities for quota and ban cleanup
- **Activity Monitoring**: Request logging and usage analytics
- **Notice Throttling**: Prevents spam of rate limit warnings

### **Operational Features**

- **Docker Deployment**: Complete containerization with volume persistence
- **Environment Configuration**: Comprehensive settings through environment variables
- **Health Monitoring**: Circuit breaker patterns and failure recovery
- **Data Retention**: Automatic cleanup with configurable retention periods

## Configuration & Deployment

### **Environment Variables**

- `TELEGRAM_TOKEN`: Bot authentication token
- `GEMINI_API_KEY`: Google AI API credentials
- `GEMINI_MODEL`: AI model selection (default: gemini-2.5-flash)
- `CONTEXT_SUMMARY_THRESHOLD`: Messages threshold for context summarization (default: 30)
- `ADMIN_USER_IDS`: Comma-separated list of admin Telegram user IDs
- `USE_REDIS`: Enable Redis for enhanced performance
- `ENABLE_SEARCH_GROUNDING`: Toggle Google Search integration

### **Deployment Options**

- **Docker Compose**: Production-ready container orchestration
- **Local Development**: Python virtual environment setup
- **Volume Persistence**: SQLite database mounted for data retention

## Persona Characteristics

### **Identity**

- **Name**: "gryag" (гряг)
- **Language**: Colloquial Ukrainian (розмовна українська)
- **Personality**: Sharp, sarcastic, witty, culturally aware
- **Political Stance**: Pro-Ukrainian, critical of Russian aggression

### **Behavioral Traits**

- **Response Style**: Concise, ranging from single words to multiple sentences
- **Humor**: Dark humor, creative profanity, cultural references
- **Knowledge**: Freely shares information with distinctive commentary
- **Restrictions**: No generic profanity, maintains character consistency

## Use Cases

### **Primary Applications**

- **Group Chat Enhancement**: Intelligent conversation participation
- **Information Retrieval**: Context-aware answers from chat history
- **Media Analysis**: Description and commentary on shared content
- **Community Moderation**: Automated response management

### **Advanced Features**

- **Historical Search**: Semantic retrieval of past conversations
- **Multimodal Interaction**: Comprehensive media understanding
- **Adaptive Behavior**: Learning from user interaction patterns
- **Cultural Engagement**: Ukrainian-specific content and perspectives

## Technical Excellence

### **Reliability**

- **Error Handling**: Comprehensive exception management
- **Circuit Breaking**: Automatic service protection
- **Data Integrity**: ACID compliance through SQLite WAL mode
- **Backup Strategies**: Dual-storage redundancy options

### **Performance**

- **Async Architecture**: Non-blocking I/O throughout
- **Connection Pooling**: Efficient database resource management
- **Caching Layers**: Redis integration for high-frequency operations
- **Rate Limiting**: Prevents API quota exhaustion

### **Security**

- **Input Validation**: Comprehensive data sanitization
- **Access Control**: Admin privilege verification
- **Data Protection**: Secure file handling and storage
- **API Security**: Token-based authentication

## Project Vision

GRYAG represents a sophisticated approach to AI-powered chat bot development, combining advanced language models with robust engineering practices. The project demonstrates how to build production-ready conversational AI that maintains consistent personality, handles complex group dynamics, and provides reliable service at scale.

The bot serves as both a functional group chat assistant and a technical showcase of modern AI integration patterns, multimodal processing capabilities, and scalable architecture design in the context of Ukrainian digital culture and community needs.
