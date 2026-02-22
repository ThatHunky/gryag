package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHealthCheck(t *testing.T) {
	req := httptest.NewRequest("GET", "/health", nil)
	w := httptest.NewRecorder()

	HealthCheck(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}

	var resp map[string]string
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["status"] != "ok" {
		t.Errorf("expected status 'ok', got '%s'", resp["status"])
	}
}

func TestProcess_InvalidPayload(t *testing.T) {
	// Handler with nil deps will fail on decode before touching any service
	h := &Handler{}

	req := httptest.NewRequest("POST", "/api/v1/process", strings.NewReader("not json"))
	req.Header.Set("X-Request-ID", "test-123")
	w := httptest.NewRecorder()

	h.Process(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", w.Code)
	}
}

func TestRespondJSON(t *testing.T) {
	w := httptest.NewRecorder()
	resp := &ProcessResponse{
		Reply:     "test reply",
		RequestID: "abc123",
		MediaURL:  "https://example.com/image.png",
		MediaType: "photo",
	}

	respondJSON(w, resp)

	if w.Header().Get("Content-Type") != "application/json" {
		t.Errorf("expected application/json, got %s", w.Header().Get("Content-Type"))
	}

	var decoded ProcessResponse
	json.Unmarshal(w.Body.Bytes(), &decoded)

	if decoded.Reply != "test reply" {
		t.Errorf("expected 'test reply', got '%s'", decoded.Reply)
	}
	if decoded.MediaURL != "https://example.com/image.png" {
		t.Errorf("expected media URL, got '%s'", decoded.MediaURL)
	}
}

// TestRespondJSON_MediaBase64 verifies that ProcessResponse serializes media_base64 and media_type
// (used when the backend returns a generated image as base64 to the frontend).
func TestRespondJSON_MediaBase64(t *testing.T) {
	w := httptest.NewRecorder()
	resp := &ProcessResponse{
		Reply:       "Here's your image.",
		RequestID:   "req-456",
		MediaBase64: "iVBORw0KGgo=",
		MediaType:   "photo",
	}

	respondJSON(w, resp)

	var decoded ProcessResponse
	if err := json.Unmarshal(w.Body.Bytes(), &decoded); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if decoded.MediaBase64 == "" {
		t.Error("expected media_base64 to be set")
	}
	if decoded.MediaBase64 != "iVBORw0KGgo=" {
		t.Errorf("expected media_base64 %q, got %q", "iVBORw0KGgo=", decoded.MediaBase64)
	}
	if decoded.MediaType != "photo" {
		t.Errorf("expected media_type photo, got %q", decoded.MediaType)
	}
}

// TestRespondJSON_MediaBase64_Document verifies that media_type "document" is serialized for send-as-file.
func TestRespondJSON_MediaBase64_Document(t *testing.T) {
	w := httptest.NewRecorder()
	resp := &ProcessResponse{
		Reply:       "Here's your file.",
		RequestID:   "req-789",
		MediaBase64: "iVBORw0KGgo=",
		MediaType:   "document",
	}

	respondJSON(w, resp)

	var decoded ProcessResponse
	if err := json.Unmarshal(w.Body.Bytes(), &decoded); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if decoded.MediaType != "document" {
		t.Errorf("expected media_type document, got %q", decoded.MediaType)
	}
	if decoded.MediaBase64 != "iVBORw0KGgo=" {
		t.Errorf("expected media_base64 to be set")
	}
}

func TestStrPtr(t *testing.T) {
	if strPtr("") != nil {
		t.Error("expected nil for empty string")
	}
	p := strPtr("hello")
	if p == nil || *p != "hello" {
		t.Error("expected pointer to 'hello'")
	}
}

func TestInferMimeType(t *testing.T) {
	if inferMimeType("photo", "") != "image/jpeg" {
		t.Error("photo should be image/jpeg")
	}
	if inferMimeType("voice", "") != "audio/ogg" {
		t.Error("voice should be audio/ogg")
	}
	if inferMimeType("", "image/png") != "image/png" {
		t.Error("mime_type should be used when set")
	}
	if inferMimeType("document", "image/gif") != "image/gif" {
		t.Error("mime_type should override media_type")
	}
}
