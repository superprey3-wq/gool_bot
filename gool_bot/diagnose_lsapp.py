"""One-shot diagnostic for Flashscore -> LSApp integration. Does not send Telegram."""
import asyncio
from datetime import UTC, datetime

import prematch_scanner as s


def main():
    matches = s._discover_from_feeds()
    if not matches:
        matches = asyncio.run(s._discover_from_browser())
    now = datetime.now(UTC)
    future = sorted((m for m in matches if m.kickoff > now), key=lambda m: m.kickoff)
    print(f"DIAG discovered={len(matches)} future={len(future)}")
    if not future:
        return
    # Try several nearby fixtures because some minor competitions may have no bookmaker odds.
    for match in future[:8]:
        mins = (match.kickoff - now).total_seconds() / 60
        print(f"DIAG trying {match.event_id} {match.home} - {match.away} in {mins:.0f}m")
        entries = s._fetch_event_odds(match.event_id)
        if not entries:
            print("DIAG no LSApp odds")
            continue
        types = sorted({str(e.get('bettingType')) for e in entries if e.get('bettingType')})
        scopes = sorted({str(e.get('bettingScope')) for e in entries if e.get('bettingScope')})
        total_entries = [e for e in entries if e.get('bettingType') == 'OVER_UNDER' or 'TOTAL' in str(e.get('bettingType') or '')]
        print(f"DIAG SUCCESS entries={len(entries)} total_entries={len(total_entries)}")
        print("DIAG types=" + ",".join(types))
        print("DIAG scopes=" + ",".join(scopes))
        for entry in total_entries[:12]:
            print(f"DIAG total type={entry.get('bettingType')} scope={entry.get('bettingScope')} bookmaker={entry.get('bookmakerId')}")
            for item in (entry.get('odds') or [])[:6]:
                if isinstance(item, dict):
                    print("DIAG item", {
                        'selection': item.get('selection'),
                        'opening': item.get('opening'),
                        'value': item.get('value'),
                        'handicap': item.get('handicap'),
                        'participant': item.get('eventParticipantId'),
                    })
        return


if __name__ == '__main__':
    main()
