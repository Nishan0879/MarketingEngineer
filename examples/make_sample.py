"""Generate a fictional lead export for trying the framework.

Every lead is invented. The patterns are planted on purpose so the audit has
something to find: slow or missing replies convert worse, and a share of leads
wrote back and never got an answer.

    python examples/make_sample.py examples/
"""

import csv
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
CHANNELS = [("Website form", 0.45), ("Google Business", 0.25), ("Instagram DM", 0.2), ("Referral", 0.1)]
SEGMENTS = ["Freelancer", "Small team", "Remote employee"]
LOST_REASONS = ["Price too high", "Chose a competitor", "Location too far", "Price too high",
                "Timing - not ready", "No parking", "Chose a competitor"]


def pick(options):
    r, acc = random.random(), 0
    for value, w in options:
        acc += w
        if r <= acc:
            return value
    return options[-1][0]


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def main(out_dir: Path, n: int = 260, seed: int = 7) -> None:
    random.seed(seed)
    leads, acts = [], []
    for i in range(1, n + 1):
        ref = f"L-{1000 + i}"
        created = AS_OF - timedelta(days=random.uniform(0, 180), minutes=random.randint(0, 600))
        channel = pick(CHANNELS)
        segment = random.choice(SEGMENTS)
        value = {"Freelancer": 250, "Small team": 1200, "Remote employee": 350}[segment] * 12

        # Response speed: Instagram DMs get slow or no replies.
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
            for _ in range(random.choice([0, 1, 1, 2, 3, 4])):
                t = touches[-1][0] + timedelta(days=random.uniform(1, 5))
                if t < AS_OF:
                    touches.append((t, "out"))
            if random.random() < 0.45:
                t = first + timedelta(hours=random.uniform(1, 30))
                if t < AS_OF:
                    touches.append((t, "in"))
            # Some prospects reply after our last message and never hear back.
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
            stage = "Tour Booked"
            qualified_at = qualified_at or tour_at
        last = max([created, *(t for t, _ in touches), *(x for x in (qualified_at, tour_at) if x)])
        age = (AS_OF - created).days
        if met and age > 10:
            roll = random.random()
            if roll < 0.5:
                status, stage, closed_at = "Won", "Signed", last + timedelta(days=random.uniform(1, 10))
            elif roll < 0.8:
                status, closed_at = "Lost", last + timedelta(days=random.uniform(2, 15))
                lost_reason = random.choice(LOST_REASONS)
        elif age > 45 and random.random() < 0.25:
            status, closed_at = "Lost", last + timedelta(days=random.uniform(5, 20))
            lost_reason = random.choice(LOST_REASONS + [""])
        if closed_at and closed_at > AS_OF:
            status, closed_at, lost_reason = "Open", None, ""
            stage = "Tour Booked" if met else stage

        outs = [t for t, d in touches if d == "out"]
        ins = [t for t, d in touches if d == "in"]
        leads.append({
            "Lead ID": ref, "Created At": fmt(created), "Source": channel, "Segment": segment,
            "Value": value, "First Response At": fmt(first), "Last Outbound At": fmt(max(outs) if outs else None),
            "Last Inbound At": fmt(max(ins) if ins else None), "Outbound Count": len(outs),
            "Stage": stage, "Qualified At": fmt(qualified_at), "Tour Booked At": fmt(tour_at),
            "Status": status, "Closed At": fmt(closed_at), "Lost Reason": lost_reason,
        })
        acts += [{"Lead ID": ref, "Timestamp": fmt(t), "Direction": "outbound" if d == "out" else "inbound"}
                 for t, d in touches]

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("sample_leads.csv", leads), ("sample_activities.csv", acts)):
        with open(out_dir / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote {len(leads)} leads and {len(acts)} activities to {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "examples"))
