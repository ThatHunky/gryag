"""Pattern definitions for Ukrainian text fact extraction."""

import re

# Location patterns
LOCATION_PATTERNS = [
    r"я з (\w+)",
    r"живу в (\w+)",
    r"я в (\w+)",
    r"я із (\w+)",
    r"з міста (\w+)",
    r"мій город (\w+)",
]

# Preference patterns (likes)
LIKE_PATTERNS = [
    r"люблю (.+?)(?:\.|,|$)",
    r"обожнюю (.+?)(?:\.|,|$)",
    r"подобається (.+?)(?:\.|,|$)",
    r"дуже люблю (.+?)(?:\.|,|$)",
    r"улюблен(?:ий|а|е) (.+?)(?:\.|,|$)",
]

# Preference patterns (dislikes)
DISLIKE_PATTERNS = [
    r"ненавиджу (.+?)(?:\.|,|$)",
    r"не люблю (.+?)(?:\.|,|$)",
    r"не подобається (.+?)(?:\.|,|$)",
    r"терпіти не можу (.+?)(?:\.|,|$)",
]

# Language patterns
LANGUAGE_PATTERNS = [
    r"розмовляю (.+?)(?:\.|,|$)",
    r"говорю (.+?)(?:\.|,|$)",
    r"володію (.+?)(?:\.|,|$)",
    r"знаю (.+?)(?:\.|,|$)",
]

# Profession patterns
PROFESSION_PATTERNS = [
    r"працюю (.+?)(?:\.|,|$)",
    r"я (.+?) за професією",
    r"моя робота - (.+?)(?:\.|,|$)",
    r"роблю (.+?)(?:\.|,|$)",
]

# Programming language patterns
PROG_LANG_PATTERNS = [
    r"пишу на (.+?)(?:\.|,|$)",
    r"кодю на (.+?)(?:\.|,|$)",
    r"програмую на (.+?)(?:\.|,|$)",
]

# Ukrainian cities (common ones)
UKRAINIAN_CITIES = {
    "київ",
    "kyiv",
    "киев",
    "львів",
    "lviv",
    "львов",
    "одеса",
    "odesa",
    "одесса",
    "дніпро",
    "dnipro",
    "днепр",
    "харків",
    "kharkiv",
    "харьков",
    "запоріжжя",
    "zaporizhzhia",
    "запорожье",
    "вінниця",
    "vinnytsia",
    "черкаси",
    "cherkasy",
    "полтава",
    "poltava",
    "херсон",
    "kherson",
    "тернопіль",
    "ternopil",
    "івано-франківськ",
    "ivano-frankivsk",
    "ужгород",
    "uzhhorod",
    "чернівці",
    "chernivtsi",
    "суми",
    "sumy",
    "луцьк",
    "lutsk",
}

# Programming languages keywords
PROGRAMMING_LANGUAGES = {
    "python",
    "пайтон",
    "пітон",
    "javascript",
    "js",
    "джаваскрипт",
    "typescript",
    "ts",
    "java",
    "джава",
    "c++",
    "cpp",
    "сі++",
    "c#",
    "csharp",
    "сішарп",
    "go",
    "golang",
    "го",
    "rust",
    "раст",
    "php",
    "пхп",
    "ruby",
    "рубі",
    "kotlin",
    "котлін",
    "swift",
    "свіфт",
}

# Spoken languages
SPOKEN_LANGUAGES = {
    "українська",
    "ukrainian",
    "українську",
    "english",
    "англійська",
    "англійську",
    "російська",
    "russian",
    "російську",
    "польська",
    "polish",
    "польську",
    "німецька",
    "german",
    "німецьку",
    "французька",
    "french",
    "французьку",
    "іспанська",
    "spanish",
    "іспанську",
}


def compile_patterns(pattern_list: list[str]) -> list[re.Pattern]:
    """Compile regex patterns with case-insensitive flag."""
    return [re.compile(p, re.IGNORECASE | re.UNICODE) for p in pattern_list]
