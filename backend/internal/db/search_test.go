package db

import (
	"testing"
)

func TestComposeMessageLink_Supergroup(t *testing.T) {
	msgID := int64(42)
	// -1001234567890 is a private supergroup
	link := ComposeMessageLink(-1001234567890, &msgID)
	expected := "https://t.me/c/1234567890/42"
	if link != expected {
		t.Errorf("expected %q, got %q", expected, link)
	}
}

func TestComposeMessageLink_RealChatID(t *testing.T) {
	msgID := int64(123)
	// Using the actual test chat ID from the architecture
	link := ComposeMessageLink(-1002604868951, &msgID)
	expected := "https://t.me/c/2604868951/123"
	if link != expected {
		t.Errorf("expected %q, got %q", expected, link)
	}
}

func TestComposeMessageLink_BasicGroup(t *testing.T) {
	msgID := int64(42)
	// Basic groups don't support deep links
	link := ComposeMessageLink(-123456, &msgID)
	if link != "" {
		t.Errorf("expected empty link for basic group, got %q", link)
	}
}

func TestComposeMessageLink_PrivateChat(t *testing.T) {
	msgID := int64(42)
	// Private chats don't support deep links
	link := ComposeMessageLink(392817811, &msgID)
	if link != "" {
		t.Errorf("expected empty link for private chat, got %q", link)
	}
}

func TestComposeMessageLink_NilMessageID(t *testing.T) {
	link := ComposeMessageLink(-1001234567890, nil)
	if link != "" {
		t.Errorf("expected empty link for nil message_id, got %q", link)
	}
}
