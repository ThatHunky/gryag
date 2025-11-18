"""
Tests for shared text processing utilities.
"""

from app.utils.text_processing import cosine_similarity, extract_keywords


class TestKeywordExtraction:
    def test_basic_extraction(self):
        text = "Hello world this is a test"
        keywords = extract_keywords(text)
        assert "hello" in keywords
        assert "world" in keywords
        assert "test" in keywords
        assert "is" not in keywords  # Stop word
        assert "a" not in keywords  # Stop word

    def test_removes_punctuation(self):
        text = "Hello, world! This is a test."
        keywords = extract_keywords(text)
        assert "hello" in keywords
        assert "world" in keywords

    def test_filters_short_words(self):
        text = "a b c hello world"
        keywords = extract_keywords(text)
        assert "hello" in keywords
        assert "world" in keywords
        assert "a" not in keywords
        assert "b" not in keywords
        assert "c" not in keywords

    def test_empty_text(self):
        assert extract_keywords("") == []
        assert extract_keywords(None) == []

    def test_custom_stop_words(self):
        text = "hello world test"
        custom_stops = {"hello", "world"}
        keywords = extract_keywords(text, stop_words=custom_stops)
        assert "hello" not in keywords
        assert "world" not in keywords
        assert "test" in keywords


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]
        result = cosine_similarity(a, b)
        assert abs(result - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        result = cosine_similarity(a, b)
        assert abs(result) < 0.001

    def test_similar_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]  # 2x scaling
        result = cosine_similarity(a, b)
        assert abs(result - 1.0) < 0.001  # Should be 1.0 (same direction)

    def test_different_lengths(self):
        a = [1.0, 2.0]
        b = [1.0, 2.0, 3.0]
        result = cosine_similarity(a, b)
        assert result == 0.0

    def test_empty_vectors(self):
        assert cosine_similarity([], [1, 2, 3]) == 0.0
        assert cosine_similarity([1, 2, 3], []) == 0.0
        assert cosine_similarity([], []) == 0.0

    def test_zero_vectors(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        result = cosine_similarity(a, b)
        assert result == 0.0
