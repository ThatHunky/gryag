# Hybrid Fact Extraction - Implementation Plan

## Goal
Implement local fact extraction using rule-based patterns + small local model (Phi-3-mini), eliminating Gemini API calls for fact extraction.

## Implementation Tasks

### Phase 1: Foundation ✓
- [x] Create plan document
- [ ] Create fact_extractors module structure
- [ ] Add base extractor interface

### Phase 2: Rule-Based Extractor
- [ ] Implement pattern matching for Ukrainian text
- [ ] Implement pattern matching for English text
- [ ] Add location detection (cities)
- [ ] Add preference detection (likes/dislikes)
- [ ] Add language detection
- [ ] Add skill detection
- [ ] Add trait detection
- [ ] Add unit tests

### Phase 3: Local Model Extractor
- [ ] Add llama-cpp-python to requirements
- [ ] Create local model wrapper
- [ ] Implement async inference
- [ ] Add prompt templates
- [ ] Add JSON response parsing
- [ ] Test with Phi-3-mini model
- [ ] Add fallback handling

### Phase 4: Hybrid Extractor
- [ ] Create hybrid coordinator
- [ ] Implement rule-based → local model fallback
- [ ] Add telemetry for each method
- [ ] Add configuration options
- [ ] Test extraction quality

### Phase 5: Integration
- [ ] Update config.py with new settings
- [ ] Replace FactExtractor in user_profile.py
- [ ] Update middleware injection
- [ ] Add model auto-download (optional)
- [ ] Update documentation

### Phase 6: Testing & Deployment
- [ ] Unit tests for each extractor
- [ ] Integration tests
- [ ] Performance benchmarks
- [ ] Docker support
- [ ] Production deployment

## File Structure

```
app/services/fact_extractors/
    __init__.py                 # Exports
    base.py                     # Abstract base class
    rule_based.py              # Pattern matching (no dependencies)
    local_model.py             # Phi-3 inference (llama-cpp-python)
    hybrid.py                  # Coordinator
    patterns/
        __init__.py
        ukrainian.py           # Ukrainian patterns
        english.py             # English patterns
        common.py              # Shared utilities
```

## Configuration

```python
# app/config.py additions
fact_extraction_method: str = "hybrid"  # 'rule_based', 'local_model', 'hybrid'
local_model_path: str = "./models/phi3-mini-q4.gguf"
local_model_enabled: bool = True
local_model_threads: int = 4
local_model_gpu_layers: int = 0
```

## Dependencies

```
# requirements.txt additions
llama-cpp-python>=0.2.0  # Local model inference
```

## Model Download

```bash
# Download Phi-3-mini Q4 quantized (~2.2GB)
mkdir -p models
wget -O models/phi3-mini-q4.gguf \
  https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf
```

## Expected Performance

- **Rule-based:** <1ms, 70% coverage
- **Local model:** 100-500ms, 85% accuracy
- **Hybrid:** 1-500ms avg, 90% accuracy
- **Zero API costs**

## Timeline

- Day 1-2: Rule-based extractor + patterns
- Day 3-4: Local model integration
- Day 5: Hybrid coordinator + testing
- Day 6-7: Integration + deployment

**Total: ~1 week**

---

Let's implement! 🚀
