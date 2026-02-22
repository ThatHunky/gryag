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

func TestStrPtr(t *testing.T) {
	if strPtr("") != nil {
		t.Error("expected nil for empty string")
	}
	p := strPtr("hello")
	if p == nil || *p != "hello" {
		t.Error("expected pointer to 'hello'")
	}
}
