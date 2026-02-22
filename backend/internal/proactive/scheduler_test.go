package proactive

import (
	"testing"
)

func TestWithinActiveHours(t *testing.T) {
	tests := []struct {
		hour, start, end int
		want             bool
	}{
		{12, 9, 22, true},
		{9, 9, 22, true},
		{21, 9, 22, true},
		{22, 9, 22, false},
		{8, 9, 22, false},
		{0, 9, 22, false},
		{23, 22, 6, true},
		{0, 22, 6, true},
		{5, 22, 6, true},
		{6, 22, 6, false},
		{12, 22, 6, false},
	}
	for _, tt := range tests {
		got := withinActiveHours(tt.hour, tt.start, tt.end)
		if got != tt.want {
			t.Errorf("withinActiveHours(%d, %d, %d) = %v, want %v", tt.hour, tt.start, tt.end, got, tt.want)
		}
	}
}
