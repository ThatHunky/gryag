package i18n

import (
	"os"
	"path/filepath"
	"testing"
)

func setupTestLocales(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()

	en := `{
		"greeting": "Hello, {0}!",
		"farewell": "Goodbye.",
		"with_args": "{0} owes {1} money."
	}`
	uk := `{
		"greeting": "Привіт, {0}!",
		"farewell": "До побачення."
	}`

	os.WriteFile(filepath.Join(dir, "en.json"), []byte(en), 0644)
	os.WriteFile(filepath.Join(dir, "uk.json"), []byte(uk), 0644)
	return dir
}

func TestBundle_BasicTranslation(t *testing.T) {
	dir := setupTestLocales(t)
	b, err := NewBundle(dir, "en")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	result := b.T("en", "farewell")
	if result != "Goodbye." {
		t.Errorf("expected 'Goodbye.', got '%s'", result)
	}
}

func TestBundle_UkrainianTranslation(t *testing.T) {
	dir := setupTestLocales(t)
	b, err := NewBundle(dir, "en")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	result := b.T("uk", "farewell")
	if result != "До побачення." {
		t.Errorf("expected 'До побачення.', got '%s'", result)
	}
}

func TestBundle_PlaceholderSubstitution(t *testing.T) {
	dir := setupTestLocales(t)
	b, err := NewBundle(dir, "en")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	result := b.T("en", "greeting", "Vsevolod")
	if result != "Hello, Vsevolod!" {
		t.Errorf("expected 'Hello, Vsevolod!', got '%s'", result)
	}

	result = b.T("uk", "greeting", "Всеволод")
	if result != "Привіт, Всеволод!" {
		t.Errorf("expected 'Привіт, Всеволод!', got '%s'", result)
	}
}

func TestBundle_FallbackToDefault(t *testing.T) {
	dir := setupTestLocales(t)
	b, err := NewBundle(dir, "en")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// "with_args" only exists in en, not uk — should fall back
	result := b.T("uk", "with_args", "Alice", "Bob")
	if result != "Alice owes Bob money." {
		t.Errorf("expected fallback 'Alice owes Bob money.', got '%s'", result)
	}
}

func TestBundle_MissingKey(t *testing.T) {
	dir := setupTestLocales(t)
	b, err := NewBundle(dir, "en")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	result := b.T("en", "nonexistent.key")
	if result != "nonexistent.key" {
		t.Errorf("expected raw key 'nonexistent.key', got '%s'", result)
	}
}

func TestBundle_Languages(t *testing.T) {
	dir := setupTestLocales(t)
	b, err := NewBundle(dir, "en")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	langs := b.Languages()
	if len(langs) != 2 {
		t.Errorf("expected 2 languages, got %d", len(langs))
	}
	if !b.HasLanguage("en") || !b.HasLanguage("uk") {
		t.Errorf("expected en and uk, got %v", langs)
	}
}

func TestBundle_MissingDefaultLocale(t *testing.T) {
	dir := setupTestLocales(t)
	_, err := NewBundle(dir, "fr")
	if err == nil {
		t.Error("expected error for missing default locale 'fr'")
	}
}
