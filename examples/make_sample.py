"""Generate fictional exports for a coworking space that also leases offices.

Every lead and note is invented. Patterns are planted on purpose so the audit and
customer truth have something to find:
- slow or missing replies convert worse, and some prospects wrote back and never got an answer
- office leads take far longer to close than memberships
- parking complaints rise sharply in the last 30 days, mostly from office prospects
- month-to-month flexibility comes up more with members who sign; price with members who don't

    python examples/make_sample.py examples/
"""

import csv
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
CHANNELS = [("Website form", 0.45), ("Google Business", 0.25), ("Instagram DM", 0.2), ("Referral", 0.1)]
SEGMENTS = {  # segment value: (share, annual value, is_office)
    "Freelancer": (0.35, 250 * 12, False),
    "Remote employee": (0.3, 350 * 12, False),
    "Office - small team": (0.25, 2400 * 12, True),
    "Office - company": (0.1, 6500 * 12, True),
}
MEMBER_LOST = ["Price too high", "Chose a competitor", "Location too far", "Timing - not ready"]
OFFICE_LOST = ["No parking for the team", "Chose a competitor", "Price too high", "Lease term too long",
               "Office too small for growth"]

NOTES = {
    "price": ["Asked twice about the price; said it is above their budget.",
              "Felt the monthly cost was too much compared with working from home."],
    "parking": ["Main concern was parking. Team of six drives in and the garage is full by 9.",
                "Asked whether we have reserved parking spots; we don't.",
                "Loved the space but parking is a dealbreaker for their staff."],
    "flexibility": ["Wants month-to-month, no long-term commitment.",
                    "Liked that membership is flexible and can pause in summer."],
    "meeting_rooms": ["Needs a meeting room twice a week for client calls.",
                      "Asked how many conference room hours are included."],
    "quiet": ["Needs somewhere quiet for calls; worried about noise in the open area.",
              "Asked about phone booths for private calls."],
    "community": ["Moved from home for the community and events.",
                  "Asked about networking events and other members in tech."],
    "growth": ["Team is growing to 12 next year; needs room to expand.",
               "Asked if they can move to a bigger office mid-lease."],
    "internet": ["Asked about internet speed; they upload large video files."],
}
REVIEWS = ["Great community and the coffee is good.", "Fast internet and quiet phone booths.",
           "Parking is impossible after 9am.", "Flexible month to month plans made it easy to start.",
           "A bit expensive but worth it for the meeting rooms."]


def pick(options):
    r, acc = random.random(), 0
    for value, w in options:
        acc += w
        if r <= acc:
            return value
    return options[-1][0]


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def note_for(themes, office, recent, losing=True):
    """A tour or call note built from a few themes."""
    picks = list(themes)
    if office:
        p = (0.75 if recent else 0.3) if losing else 0.05
        if random.random() < p:
            picks.append("parking")
    if not picks:
        picks = [random.choice(list(NOTES))]
    return " ".join(random.choice(NOTES[t]) for t in dict.fromkeys(picks))


def main(out_dir: Path, n: int = 320, seed: int = 7) -> None:
    random.seed(seed)
    leads, acts, signals = [], [], []
    note_id = 5000
    for i in range(1, n + 1):
        ref = f"L-{1000 + i}"
        created = AS_OF - timedelta(days=random.uniform(0, 180), minutes=random.randint(0, 600))
        channel = pick(CHANNELS)
        segment = pick([(k, v[0]) for k, v in SEGMENTS.items()])
        _, value, office = SEGMENTS[segment]
        recent = (AS_OF - created).days < 30

        r = random.random()
        if channel == "Instagram DM":
            delay = None if r < 0.3 else timedelta(hours=random.uniform(6, 72))
        else:
            delay = None if r < 0.08 else (timedelta(minutes=random.uniform(1, 50)) if r < 0.6
                                           else timedelta(hours=random.uniform(2, 40)))
        first = created + delay if delay else None
        if first and first > AS_OF:
            first = None

        p_meet = 0.08 if first is None else (0.55 if delay <= timedelta(hours=1) else 0.3)
        met = random.random() < p_meet
        touches = []
        if first:
            touches.append((first, "out"))
            n_follow = random.choice([0, 1, 1, 2, 3, 4] + ([4, 5, 6] if office else []))
            for _ in range(n_follow):
                t = touches[-1][0] + timedelta(days=random.uniform(1, 8 if office else 5))
                if t < AS_OF:
                    touches.append((t, "out"))
            if random.random() < 0.45:
                t = first + timedelta(hours=random.uniform(1, 30))
                if t < AS_OF:
                    touches.append((t, "in"))
            if not met and random.random() < 0.18:
                t = max(x[0] for x in touches) + timedelta(hours=random.uniform(2, 48))
                if t < AS_OF:
                    touches.append((t, "in"))
        touches.sort()

        stage, qualified_at, tour_at, status, closed_at, lost_reason = "New Inquiry", None, None, "Open", None, ""
        if first and random.random() < 0.6:
            qualified_at = first + timedelta(hours=random.uniform(1, 48))
            stage = "Qualified"
        if met:
            tour_at = (qualified_at or created) + timedelta(days=random.uniform(1, 6))
            stage = "Site Visit" if office else "Tour Booked"
            qualified_at = qualified_at or tour_at
            if office and random.random() < 0.6:
                stage = "Proposal Sent"
        last = max([created, *(t for t, _ in touches), *(x for x in (qualified_at, tour_at) if x)])
        age = (AS_OF - created).days

        # Themes this prospect cares about, planted to differ between won and lost.
        themes = set()
        will_win = met and random.random() < (0.45 if office else 0.5)
        if not office:
            if random.random() < (0.55 if will_win else 0.15):
                themes.add("flexibility")
            if random.random() < (0.15 if will_win else 0.5):
                themes.add("price")
            if random.random() < 0.3:
                themes.add(random.choice(["community", "quiet", "internet"]))
        else:
            themes.add(random.choice(["meeting_rooms", "growth", "quiet"]))
            if random.random() < (0.1 if will_win else 0.35):
                themes.add("price")

        close_after = random.uniform(20, 60) if office else random.uniform(1, 10)
        if met and age > (25 if office else 10):
            if will_win:
                status, closed_at = "Won", last + timedelta(days=close_after)
                stage = "Lease Signed" if office else "Signed"
            elif random.random() < 0.6:
                status, closed_at = "Lost", last + timedelta(days=random.uniform(2, 20))
                lost_reason = random.choice(OFFICE_LOST if office else MEMBER_LOST)
        elif age > 45 and random.random() < 0.25:
            status, closed_at = "Lost", last + timedelta(days=random.uniform(5, 20))
            lost_reason = random.choice((OFFICE_LOST if office else MEMBER_LOST) + [""])
        if closed_at and closed_at > AS_OF:
            status, closed_at, lost_reason = "Open", None, ""
            if met:
                stage = "Proposal Sent" if office else "Tour Booked"

        outs = [t for t, d in touches if d == "out"]
        ins = [t for t, d in touches if d == "in"]
        leads.append({
            "Lead ID": ref, "Created At": fmt(created), "Source": channel, "Segment": segment,
            "Value": value, "First Response At": fmt(first), "Last Outbound At": fmt(max(outs) if outs else None),
            "Last Inbound At": fmt(max(ins) if ins else None), "Outbound Count": len(outs),
            "Stage": stage, "Qualified At": fmt(qualified_at), "Tour Booked At": fmt(tour_at),
            "Status": status, "Closed At": fmt(closed_at), "Lost Reason": lost_reason,
            "Do Not Contact": "Yes" if random.random() < 0.04 else "",
            # Recent office inquiries from the website came in on a parking post (content attribution demo).
            "UTM Campaign": "mefw-parking-offices" if office and channel == "Website form" and (AS_OF - created).days < 20
            else "",
        })
        acts += [{"Lead ID": ref, "Timestamp": fmt(t), "Direction": "outbound" if d == "out" else "inbound"}
                 for t, d in touches]

        # Signals: the inquiry message, a tour note for those who toured, a lost note sometimes.
        note_id += 1
        msg = note_for(set(list(themes)[:1]), office, recent, not will_win)
        signals.append({"Note ID": f"N-{note_id}", "Type": "inquiry", "Date": fmt(created), "Lead ID": ref,
                        "Segment": segment, "Text": msg})
        if tour_at and tour_at < AS_OF:
            note_id += 1
            signals.append({"Note ID": f"N-{note_id}", "Type": "tour", "Date": fmt(tour_at), "Lead ID": ref,
                            "Segment": segment,
                            "Text": note_for(themes, office, (AS_OF - tour_at).days < 30, not will_win)})
        if status == "Lost" and random.random() < 0.5:
            note_id += 1
            text = random.choice(NOTES["parking"]) if office and "parking" in lost_reason.lower() \
                else f"Lost: {lost_reason or 'went quiet'}."
            signals.append({"Note ID": f"N-{note_id}", "Type": "lost", "Date": fmt(closed_at), "Lead ID": ref,
                            "Segment": segment, "Text": text})

    # One prospect is upset; drafts must route them to a human instead.
    note_id += 1
    upset = next(l for l in leads if l["Status"] == "Open" and not l["First Response At"])
    signals.append({"Note ID": f"N-{note_id}", "Type": "inquiry", "Date": upset["Created At"],
                    "Lead ID": upset["Lead ID"], "Segment": upset["Segment"],
                    "Text": "Second time asking. Nobody answers the phone; I want to make a complaint."})

    for j in range(40):
        at = AS_OF - timedelta(days=random.uniform(0, 120))
        text = random.choice(REVIEWS)
        if (AS_OF - at).days < 30 and random.random() < 0.3:
            text = "Parking is impossible after 9am."
        signals.append({"Note ID": f"R-{j + 1}", "Type": "review", "Date": fmt(at), "Lead ID": "",
                        "Segment": "", "Text": text})

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("sample_leads.csv", leads), ("sample_activities.csv", acts),
                       ("sample_signals.csv", signals)):
        with open(out_dir / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote {len(leads)} leads, {len(acts)} activities and {len(signals)} signals to {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "examples"))
