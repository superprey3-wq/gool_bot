"""Run prematch scanner for standard football total lines with diagnostics."""
from __future__ import annotations

from typing import Any
import prematch_scanner as base

ALLOWED_LINES = {
    "FULL_TIME": {2.5},
    "FIRST_HALF": {0.5, 1.0, 1.5},
    "SECOND_HALF": {0.5, 1.0, 1.5},
}

_original_extract = base._extract_signals


def _filtered_extract(entries: list[dict[str, Any]], match):
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        allowed = ALLOWED_LINES.get(scope)
        if not allowed:
            continue
        betting_type = str(entry.get("bettingType") or "")
        if not (betting_type == "OVER_UNDER" or ("TOTAL" in betting_type and "SCORE" not in betting_type)):
            if betting_type == "HOME_DRAW_AWAY":
                filtered.append(entry)
            continue
        kept_items = []
        for item in entry.get("odds") or []:
            if not isinstance(item, dict):
                continue
            handicap = item.get("handicap") or {}
            try:
                line = float(handicap.get("value"))
            except (TypeError, ValueError, AttributeError):
                continue
            if line in allowed:
                kept_items.append(item)
        if kept_items:
            copied = dict(entry)
            copied["odds"] = kept_items
            filtered.append(copied)
    return _original_extract(filtered, match)


base._extract_signals = _filtered_extract


def main() -> int:
    matches = base._discover_matches()
    base.logger.info(
        "PREMATCH_SCAN window=%s-%s min | matches_in_window=%d | min_books=%d consensus=%.0f%% drop>=%.1f%%",
        base.MIN_MINUTES_TO_KICKOFF,
        base.MAX_MINUTES_TO_KICKOFF,
        len(matches),
        base.MIN_BOOKMAKERS,
        base.MIN_CONSENSUS * 100,
        base.MIN_MEDIAN_DROP,
    )
    sent = 0
    with_odds = 0
    with_signals = 0
    for match in matches:
        minutes = (match.kickoff - base.datetime.now(base.UTC)).total_seconds() / 60
        entries = base._fetch_event_odds(match.event_id)
        if entries:
            with_odds += 1
        signals = _filtered_extract(entries, match) if entries else []
        base.logger.info(
            "PREMATCH_EVAL %.1fmin %s — %s | odds_rows=%d | qualified=%d",
            minutes,
            match.home,
            match.away,
            len(entries),
            len(signals),
        )
        if not signals:
            continue
        with_signals += 1
        if base._telegram_send(base._format(match, signals)):
            base._record_prematch(match, signals)
            sent += 1
            base.logger.info("PREMATCH_SENT %s — %s | signals=%d", match.home, match.away, len(signals))
        else:
            base.logger.error("PREMATCH_TELEGRAM_FAILED %s — %s", match.home, match.away)
    base.logger.info(
        "PREMATCH_SUMMARY matches=%d with_odds=%d with_signals=%d sent=%d",
        len(matches), with_odds, with_signals, sent,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
