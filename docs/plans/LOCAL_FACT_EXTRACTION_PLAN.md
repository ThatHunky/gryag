# Local Fact Extraction - Implementation Plan

## Goal
Extract user facts **without** making Gemini API calls by using local models and rule-based methods.

## Benefits
- ✅ **Zero API costs** for fact extraction
- ✅ **Better privacy** - data stays local
- ✅ **Faster** - no network latency
- ✅ **More reliable** - no external service dependency
- ✅ **Offline capable** - works without internet

---

## Architecture Overview

### Three-Tier Extraction Strategy

```
User Message
    ↓
1. Rule-Based Extractor (fast, simple patterns)
    ↓ (if complex or uncertain)
2. Local Small Model (CPU inference, ~1-3B params)
    ↓ (fallback only)
3. Gemini API (optional, for very complex cases)
    ↓
Facts stored in database
```

---

## Implementation Plan

### Phase 1: Rule-Based Fact Extraction

**File:** `app/services/fact_extractors/rule_based.py`

**Patterns to detect:**

#### Personal Information
```python
# Location patterns
- "I'm from {city}"
- "я з {міста}"
- "живу в {місті}"
- "я в {місті}"
- Detect city names from common lists

# Age patterns
- "I'm {number} years old"
- "мені {число} років/рік"
- "{number} y.o."

# Name patterns
- "My name is {name}"
- "мене звати {ім'я}"
- "call me {name}"
```

#### Preferences
```python
# Likes/dislikes
- "I love/like {thing}"
- "люблю/подобається {річ}"
- "I hate/dislike {thing}"
- "ненавиджу/не люблю {річ}"

# Favorites
- "my favorite {category} is {item}"
- "улюблений/улюблена {категорія} - {річ}"
```

#### Skills & Languages
```python
# Programming languages
- "I code in {language}"
- "пишу на {мові}"
- Detect: Python, JavaScript, Go, etc.

# Spoken languages
- "I speak {language}"
- "розмовляю {мовою}"
- Detect: Ukrainian, English, Russian, etc.
```

#### Traits & Opinions
```python
# Personality
- "I am {trait}" (introvert, extrovert, etc.)
- "я {риса}"

# Strong opinions
- Detect sentiment around topics
- Political stances
- Preferences
```

**Implementation:**
```python
class RuleBasedFactExtractor:
    def __init__(self):
        self.patterns = self._load_patterns()
        self.city_list = self._load_cities()
        
    def extract(self, message: str) -> list[dict]:
        """Extract facts using regex patterns."""
        facts = []
        
        # Location extraction
        if location := self._extract_location(message):
            facts.append({
                'fact_type': 'personal',
                'fact_key': 'location',
                'fact_value': location,
                'confidence': 0.85,
                'evidence': message[:100]
            })
        
        # Likes/dislikes
        if preference := self._extract_preferences(message):
            facts.extend(preference)
        
        # Languages
        if langs := self._extract_languages(message):
            facts.extend(langs)
        
        return facts
```

**Pros:**
- Instant (microseconds)
- No dependencies
- 100% accurate for known patterns
- Zero resource usage

**Cons:**
- Limited to predefined patterns
- Can't understand context
- Misses nuanced information

---

### Phase 2: Local Small Model

**File:** `app/services/fact_extractors/local_model.py`

#### Model Options

| Model | Size | Speed | Quality | Resource |
|-------|------|-------|---------|----------|
| **TinyLlama 1.1B** | 600MB (Q4) | Very Fast | Good | Low |
| **Phi-3-mini 3.8B** | 2.2GB (Q4) | Fast | Excellent | Medium |
| **Llama-3.2-1B** | 700MB (Q4) | Very Fast | Good | Low |
| **Llama-3.2-3B** | 1.9GB (Q4) | Fast | Very Good | Medium |
| **Gemma-2B** | 1.5GB (Q4) | Fast | Good | Medium |

**Recommendation:** Start with **Phi-3-mini-instruct (3.8B)** in Q4_K_M quantization
- Best quality/size ratio
- Instruction-tuned (follows prompts well)
- Runs on CPU efficiently
- ~2.2GB RAM, ~100-500ms inference

#### Setup with llama-cpp-python

**Dependencies:**
```bash
pip install llama-cpp-python
# Or with GPU support:
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
```

**Download Model:**
```bash
# Phi-3-mini Q4 quantized
wget https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf
# Save to: models/phi3-mini-q4.gguf
```

**Implementation:**
```python
from llama_cpp import Llama

class LocalModelFactExtractor:
    def __init__(self, model_path: str):
        self.llm = Llama(
            model_path=model_path,
            n_ctx=2048,        # Context window
            n_threads=4,       # CPU threads
            n_gpu_layers=0,    # CPU only (set >0 for GPU)
            verbose=False
        )
        
    async def extract(
        self, 
        message: str, 
        context: str = ""
    ) -> list[dict]:
        """Extract facts using local model."""
        
        prompt = self._build_prompt(message, context)
        
        # Run inference (blocking - wrap in executor for async)
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            self._run_inference,
            prompt
        )
        
        # Parse JSON response
        facts = self._parse_response(response)
        return facts
    
    def _run_inference(self, prompt: str) -> str:
        output = self.llm(
            prompt,
            max_tokens=512,
            temperature=0.1,
            stop=["</s>", "###"],
            echo=False
        )
        return output['choices'][0]['text']
    
    def _build_prompt(self, message: str, context: str) -> str:
        return f"""<|system|>
You are a fact extraction system. Extract facts from the user's message.
Return JSON only with this structure:
{{"facts": [{{"fact_type": "personal|preference|trait|skill|opinion", "fact_key": "key", "fact_value": "value", "confidence": 0.7-1.0}}]}}

<|user|>
Message: {message}
Context: {context[:500]}

Extract facts as JSON:
<|assistant|>
"""
```

**Pros:**
- No API calls
- Good understanding of context
- Handles complex cases
- Can process Ukrainian text

**Cons:**
- Requires model download (~2-3GB)
- CPU/RAM usage (manageable)
- Slower than rules (~100-500ms)
- Needs async executor wrapper

---

### Phase 3: Hybrid Extractor

**File:** `app/services/fact_extractors/hybrid.py`

**Strategy:**
1. **Try rule-based first** (instant)
2. **If no facts found** → Use local model
3. **If uncertain** → Optionally use Gemini (fallback)

**Implementation:**
```python
class HybridFactExtractor:
    def __init__(
        self, 
        model_path: str | None = None,
        gemini_client: Any | None = None
    ):
        self.rule_based = RuleBasedFactExtractor()
        self.local_model = LocalModelFactExtractor(model_path) if model_path else None
        self.gemini = gemini_client
        
    async def extract(
        self, 
        message: str,
        context: list[dict] = None,
        use_gemini_fallback: bool = False
    ) -> list[dict]:
        """Extract facts using hybrid strategy."""
        
        # Step 1: Rule-based (fast, free)
        facts = self.rule_based.extract(message)
        
        if facts:
            telemetry.increment_counter("facts_extracted_rule_based")
            LOGGER.debug(f"Extracted {len(facts)} facts using rules")
            return facts
        
        # Step 2: Local model (slow, free)
        if self.local_model:
            try:
                context_str = self._format_context(context)
                facts = await self.local_model.extract(message, context_str)
                
                if facts:
                    telemetry.increment_counter("facts_extracted_local_model")
                    LOGGER.debug(f"Extracted {len(facts)} facts using local model")
                    return facts
            except Exception as e:
                LOGGER.error(f"Local model extraction failed: {e}")
                telemetry.increment_counter("local_model_errors")
        
        # Step 3: Gemini fallback (optional)
        if use_gemini_fallback and self.gemini:
            try:
                facts = await self._extract_with_gemini(message, context)
                if facts:
                    telemetry.increment_counter("facts_extracted_gemini")
                    LOGGER.debug(f"Extracted {len(facts)} facts using Gemini")
                    return facts
            except Exception as e:
                LOGGER.error(f"Gemini extraction failed: {e}")
                telemetry.increment_counter("gemini_extraction_errors")
        
        return []
```

---

## Configuration

**Add to `app/config.py`:**
```python
# Fact extraction method: 'local', 'gemini', 'hybrid'
fact_extraction_method: str = Field("local", alias="FACT_EXTRACTION_METHOD")

# Path to local model (GGUF format)
local_model_path: str | None = Field(
    "./models/phi3-mini-q4.gguf", 
    alias="LOCAL_MODEL_PATH"
)

# Enable Gemini fallback in hybrid mode
enable_gemini_fallback: bool = Field(False, alias="ENABLE_GEMINI_FALLBACK")

# Local model settings
local_model_threads: int = Field(4, alias="LOCAL_MODEL_THREADS")
local_model_gpu_layers: int = Field(0, alias="LOCAL_MODEL_GPU_LAYERS")
```

**Add to `.env`:**
```bash
FACT_EXTRACTION_METHOD=hybrid  # or 'local', 'gemini'
LOCAL_MODEL_PATH=./models/phi3-mini-q4.gguf
ENABLE_GEMINI_FALLBACK=false
LOCAL_MODEL_THREADS=4
LOCAL_MODEL_GPU_LAYERS=0  # Set to 20+ if you have GPU
```

---

## File Structure

```
app/services/fact_extractors/
    __init__.py
    base.py              # Abstract base class
    rule_based.py        # Pattern matching
    local_model.py       # Local LLM inference
    hybrid.py            # Combined strategy
    patterns/
        __init__.py
        ukrainian.py     # Ukrainian patterns
        english.py       # English patterns
        cities.py        # City lists
```

---

## Performance Comparison

| Method | Latency | Cost | Accuracy | Privacy |
|--------|---------|------|----------|---------|
| Rule-based | <1ms | Free | 70% | Perfect |
| Local Model | 100-500ms | Free | 85% | Perfect |
| Gemini API | 500-2000ms | $$ | 95% | External |
| Hybrid | 1-500ms | Free* | 90% | Perfect |

*Free if Gemini fallback disabled

---

## Implementation Steps

### Step 1: Add Rule-Based Extractor
- [ ] Create `fact_extractors/rule_based.py`
- [ ] Implement pattern matching for Ukrainian/English
- [ ] Add city/name lists
- [ ] Write unit tests

### Step 2: Add Local Model Support
- [ ] Add `llama-cpp-python` to requirements
- [ ] Create `fact_extractors/local_model.py`
- [ ] Download Phi-3-mini model
- [ ] Implement async wrapper
- [ ] Add model to Docker image (optional)

### Step 3: Create Hybrid Extractor
- [ ] Create `fact_extractors/hybrid.py`
- [ ] Implement fallback logic
- [ ] Add configuration options
- [ ] Update telemetry counters

### Step 4: Integration
- [ ] Update `user_profile.py` to use new extractors
- [ ] Add configuration to `config.py`
- [ ] Update middleware to inject hybrid extractor
- [ ] Update documentation

### Step 5: Docker Support (Optional)
- [ ] Add model download to Dockerfile
- [ ] Configure volume for models
- [ ] Add CPU optimization flags
- [ ] Test in container

---

## Docker Considerations

### Option A: Exclude Model from Image (Recommended)
```dockerfile
# Mount model as volume
volumes:
  - ./models:/app/models
```

**Pros:** Smaller image, flexible model updates  
**Cons:** Need to download model separately

### Option B: Include Model in Image
```dockerfile
RUN wget https://huggingface.co/.../phi3-mini-q4.gguf -O /app/models/phi3.gguf
```

**Pros:** Self-contained  
**Cons:** +2.2GB image size

### Option C: Download on First Run
```python
# Auto-download if missing
if not Path(model_path).exists():
    download_model(model_path)
```

---

## Resource Requirements

### CPU-Only Mode (Recommended)
- **RAM:** +2-3GB for model
- **CPU:** 4 cores recommended
- **Disk:** +2-3GB for model file
- **Inference:** 100-500ms per extraction

### GPU Mode (Optional)
- **VRAM:** +2-3GB
- **Inference:** 50-100ms per extraction
- Requires CUDA/ROCm setup

---

## Testing Strategy

### Unit Tests
```python
def test_rule_based_location():
    extractor = RuleBasedFactExtractor()
    facts = extractor.extract("I'm from Kyiv")
    assert facts[0]['fact_key'] == 'location'
    assert facts[0]['fact_value'] == 'Kyiv'

def test_local_model_extraction():
    extractor = LocalModelFactExtractor('models/phi3.gguf')
    facts = await extractor.extract("Я люблю каву")
    assert any(f['fact_key'] == 'preference' for f in facts)
```

### Integration Tests
- Test with real messages
- Verify JSON parsing
- Check confidence scores
- Measure latency

### Load Tests
- 100 concurrent extractions
- Memory usage over time
- CPU utilization

---

## Migration Path

### Phase 1: Add alongside existing (1 week)
- Implement rule-based extractor
- Keep Gemini as default
- Test in parallel

### Phase 2: Add local model (1 week)
- Add llama-cpp-python
- Download and test model
- Benchmark performance

### Phase 3: Switch to hybrid (3 days)
- Deploy hybrid extractor
- Monitor errors
- Tune confidence thresholds

### Phase 4: Deprecate Gemini (optional)
- Disable Gemini fallback
- Monitor fact quality
- Adjust if needed

---

## Fallback Strategy

If local extraction fails:
1. Log error with telemetry
2. Return empty list (don't crash)
3. Profile still updates (interaction counts)
4. Retry on next message

---

## Monitoring

### New Metrics
```python
telemetry.increment_counter("facts_extracted_rule_based")
telemetry.increment_counter("facts_extracted_local_model")
telemetry.increment_counter("facts_extracted_gemini")
telemetry.increment_counter("local_model_errors")
telemetry.increment_counter("local_model_inference_time", value=ms)
```

### Logging
```python
LOGGER.info(f"Local model loaded: {model_path}")
LOGGER.debug(f"Extracted {len(facts)} facts in {elapsed}ms using {method}")
LOGGER.warning(f"Local model inference slow: {elapsed}ms > threshold")
```

---

## Alternative: No-Model Approach

If you want **zero** dependencies:

### Pure Rule-Based
- Only use pattern matching
- Cover 70-80% of common cases
- Miss complex/nuanced facts
- Instant, zero overhead

### Named Entity Recognition (NER)
```bash
pip install spacy
python -m spacy download uk_core_news_sm  # Ukrainian
python -m spacy download en_core_web_sm   # English
```

**Lighter than LLM:**
- ~15-50MB models
- <10ms inference
- Good for names, places, dates
- Limited to entity extraction

---

## Recommendation

**Start with:** Hybrid approach (rule-based + local model)

**Why:**
1. **Rule-based** handles 60-70% of simple cases instantly
2. **Local model** handles remaining 20-30% without API calls
3. **Zero ongoing costs** for fact extraction
4. **Better privacy** - all local
5. **Optional Gemini fallback** for edge cases

**Ideal setup:**
```env
FACT_EXTRACTION_METHOD=hybrid
LOCAL_MODEL_PATH=./models/phi3-mini-q4.gguf
ENABLE_GEMINI_FALLBACK=false
```

This gives you:
- ✅ No API costs
- ✅ Fast extraction (1-500ms)
- ✅ Good accuracy (~85%)
- ✅ Full privacy
- ✅ Offline capable

---

## Next Steps

1. **Prototype rule-based extractor** (1 day)
2. **Test with real messages** (1 day)
3. **Add local model support** (2 days)
4. **Benchmark and tune** (1 day)
5. **Deploy and monitor** (1 day)

**Total: ~1 week** for full local extraction system

Would you like me to start implementing this?
