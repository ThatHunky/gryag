package i18n

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"sync"
)

// Locale holds all translated strings for one language.
type Locale struct {
	mu      sync.RWMutex
	strings map[string]string
	lang    string
}

// Bundle manages multiple locales and provides string lookups.
type Bundle struct {
	locales    map[string]*Locale
	defaultLang string
}

// NewBundle creates a new i18n bundle from a directory of JSON locale files.
// Each file should be named like "uk.json", "en.json", etc.
func NewBundle(localeDir, defaultLang string) (*Bundle, error) {
	b := &Bundle{
		locales:     make(map[string]*Locale),
		defaultLang: defaultLang,
	}

	entries, err := os.ReadDir(localeDir)
	if err != nil {
		return nil, fmt.Errorf("read locale dir %s: %w", localeDir, err)
	}

	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}

		lang := strings.TrimSuffix(entry.Name(), ".json")
		path := localeDir + "/" + entry.Name()

		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read locale file %s: %w", path, err)
		}

		var strings map[string]string
		if err := json.Unmarshal(data, &strings); err != nil {
			return nil, fmt.Errorf("parse locale file %s: %w", path, err)
		}

		b.locales[lang] = &Locale{
			strings: strings,
			lang:    lang,
		}

		slog.Info("loaded locale", "lang", lang, "keys", len(strings))
	}

	if _, ok := b.locales[defaultLang]; !ok {
		return nil, fmt.Errorf("default locale %q not found in %s", defaultLang, localeDir)
	}

	return b, nil
}

// T translates a key using the given language, falling back to the default.
// Supports simple placeholder substitution: {0}, {1}, etc.
func (b *Bundle) T(lang, key string, args ...string) string {
	// Try requested language
	if locale, ok := b.locales[lang]; ok {
		locale.mu.RLock()
		if s, ok := locale.strings[key]; ok {
			locale.mu.RUnlock()
			return substitute(s, args)
		}
		locale.mu.RUnlock()
	}

	// Fall back to default
	if locale, ok := b.locales[b.defaultLang]; ok {
		locale.mu.RLock()
		if s, ok := locale.strings[key]; ok {
			locale.mu.RUnlock()
			return substitute(s, args)
		}
		locale.mu.RUnlock()
	}

	// Key not found — return the key itself
	return key
}

// substitute replaces {0}, {1}, etc. with the corresponding args.
func substitute(template string, args []string) string {
	result := template
	for i, arg := range args {
		result = strings.ReplaceAll(result, fmt.Sprintf("{%d}", i), arg)
	}
	return result
}

// Languages returns all loaded language codes.
func (b *Bundle) Languages() []string {
	langs := make([]string, 0, len(b.locales))
	for lang := range b.locales {
		langs = append(langs, lang)
	}
	return langs
}

// HasLanguage checks if a language is loaded.
func (b *Bundle) HasLanguage(lang string) bool {
	_, ok := b.locales[lang]
	return ok
}
