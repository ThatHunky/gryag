"""Pattern definitions for English text fact extraction."""

import re

# Location patterns
LOCATION_PATTERNS = [
    r"I'm from (\w+)",
    r"I am from (\w+)",
    r"I live in (\w+)",
    r"living in (\w+)",
    r"based in (\w+)",
    r"my city is (\w+)",
]

# Preference patterns (likes)
LIKE_PATTERNS = [
    r"I love (.+?)(?:\.|,|$)",
    r"I like (.+?)(?:\.|,|$)",
    r"I enjoy (.+?)(?:\.|,|$)",
    r"I'm a fan of (.+?)(?:\.|,|$)",
    r"my favorite (.+?)(?:\.|,|$)",
    r"favourite (.+?)(?:\.|,|$)",
]

# Preference patterns (dislikes)
DISLIKE_PATTERNS = [
    r"I hate (.+?)(?:\.|,|$)",
    r"I don't like (.+?)(?:\.|,|$)",
    r"I dislike (.+?)(?:\.|,|$)",
    r"can't stand (.+?)(?:\.|,|$)",
]

# Language patterns
LANGUAGE_PATTERNS = [
    r"I speak (.+?)(?:\.|,|$)",
    r"I know (.+?)(?:\.|,|$)",
    r"fluent in (.+?)(?:\.|,|$)",
    r"learning (.+?)(?:\.|,|$)",
]

# Profession patterns
PROFESSION_PATTERNS = [
    r"I work as (.+?)(?:\.|,|$)",
    r"I'm a (.+?)(?:\.|,|$)",
    r"I am a (.+?)(?:\.|,|$)",
    r"my job is (.+?)(?:\.|,|$)",
    r"profession is (.+?)(?:\.|,|$)",
]

# Programming language patterns
PROG_LANG_PATTERNS = [
    r"I code in (.+?)(?:\.|,|$)",
    r"I program in (.+?)(?:\.|,|$)",
    r"I write (.+?)(?:\.|,|$)",
    r"using (.+?)(?:\.|,|$)",
]

# Age patterns
AGE_PATTERNS = [
    r"I'm (\d+) years? old",
    r"I am (\d+) years? old",
    r"age is (\d+)",
]

# Programming languages keywords (same as Ukrainian for detection)
PROGRAMMING_LANGUAGES = {
    "python", "javascript", "js", "typescript", "ts",
    "java", "c++", "cpp", "c#", "csharp", "go", "golang",
    "rust", "php", "ruby", "kotlin", "swift", "scala",
    "perl", "r", "matlab", "julia", "dart", "elixir",
}

# Spoken languages
SPOKEN_LANGUAGES = {
    "ukrainian", "english", "russian", "polish", "german",
    "french", "spanish", "italian", "chinese", "japanese",
    "korean", "arabic", "portuguese", "dutch", "turkish",
}


def compile_patterns(pattern_list: list[str]) -> list[re.Pattern]:
    """Compile regex patterns with case-insensitive flag."""
    return [re.compile(p, re.IGNORECASE) for p in pattern_list]
