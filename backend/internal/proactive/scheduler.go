package proactive

import (
	"context"
	"log/slog"
	"math/rand"
	"time"
)

// Default random interval when within active hours (30 min to 4 hours).
const (
	defaultMinInterval = 30 * time.Minute
	defaultMaxInterval = 4 * time.Hour
	checkInterval      = 15 * time.Minute
)

// Scheduler runs the proactive loop: only during active hours (Kyiv), at random intervals.
func Scheduler(ctx context.Context, r *Runner, startHour, endHour int) {
	logger := slog.With("component", "proactive_scheduler")
	kyiv, err := time.LoadLocation("Europe/Kyiv")
	if err != nil {
		kyiv, err = time.LoadLocation("Europe/Kiev")
		if err != nil {
			logger.Error("could not load Kyiv timezone", "error", err)
			return
		}
	}

	for {
		now := time.Now().In(kyiv)
		hour := now.Hour()
		inWindow := withinActiveHours(hour, startHour, endHour)

		if inWindow {
			r.RunOne(ctx)
			delay := randomDuration(defaultMinInterval, defaultMaxInterval)
			logger.Info("next proactive run scheduled", "in", delay)
			select {
			case <-ctx.Done():
				return
			case <-time.After(delay):
				continue
			}
		}

		// Outside active hours: sleep until next check
		select {
		case <-ctx.Done():
			return
		case <-time.After(checkInterval):
			continue
		}
	}
}

// withinActiveHours returns true if hour is inside [start, end). Handles overnight (e.g. 22-6).
func withinActiveHours(hour, start, end int) bool {
	if start < end {
		return hour >= start && hour < end
	}
	return hour >= start || hour < end
}

func randomDuration(min, max time.Duration) time.Duration {
	if max <= min {
		return min
	}
	d := max - min
	return min + time.Duration(rand.Int63n(int64(d)))
}
