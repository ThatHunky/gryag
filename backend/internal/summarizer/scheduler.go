package summarizer

import (
	"context"
	"log/slog"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/config"
)

const pollInterval = 1 * time.Minute

// Scheduler runs summarization daily at SummaryRunHour (Kyiv). 7-day runs every Summary7DayIntervalDays,
// 30-day every Summary30DayIntervalDays.
func Scheduler(ctx context.Context, r *Runner, cfg *config.Config) {
	logger := slog.With("component", "summarizer_scheduler")
	kyiv, err := time.LoadLocation("Europe/Kyiv")
	if err != nil {
		kyiv, err = time.LoadLocation("Europe/Kiev")
		if err != nil {
			logger.Error("could not load Kyiv timezone", "error", err)
			return
		}
	}
	runHour := cfg.SummaryRunHour
	if runHour < 0 || runHour > 23 {
		runHour = 3
	}
	interval7 := cfg.Summary7DayIntervalDays
	if interval7 <= 0 {
		interval7 = 3
	}
	interval30 := cfg.Summary30DayIntervalDays
	if interval30 <= 0 {
		interval30 = 12
	}

	for {
		now := time.Now().In(kyiv)
		hour := now.Hour()
		if hour == runHour {
			// Run at 3 AM Kyiv: check if 7-day and/or 30-day intervals have elapsed
			run7 := false
			last7, err := r.GetLastRun(ctx, "7day")
			if err != nil {
				logger.Warn("get last run 7day failed", "error", err)
			} else {
				elapsed := now.Unix() - last7
				run7 = last7 == 0 || elapsed >= int64(interval7*24*3600)
			}
			if run7 {
				logger.Info("running 7-day summarization")
				r.RunOne(ctx, "7day")
				_ = r.SetLastRun(ctx, "7day")
			}

			run30 := false
			last30, err := r.GetLastRun(ctx, "30day")
			if err != nil {
				logger.Warn("get last run 30day failed", "error", err)
			} else {
				elapsed := now.Unix() - last30
				run30 = last30 == 0 || elapsed >= int64(interval30*24*3600)
			}
			if run30 {
				logger.Info("running 30-day summarization")
				r.RunOne(ctx, "30day")
				_ = r.SetLastRun(ctx, "30day")
			}
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(pollInterval):
			continue
		}
	}
}
