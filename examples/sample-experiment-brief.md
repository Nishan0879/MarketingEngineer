+++
id = "EXP-example-coworking-001"
name = "Answer every inquiry within 1 hour"
status = "running"
owner = "operator"
engine = "conversion"
segment = "members"
channels = []
metric = "inquiry_to_meeting"
comparison = "before_after"
baseline_days = 60
min_window_days = 14
min_leads = 20
keep_if = 0.15
kill_if = 0.0
created = "2026-08-20T09:00:00+00:00"
baseline_at_proposal = 0.2414
baseline_n_at_proposal = 58
approved_at = "2026-08-21T09:00:00+00:00"
approved_by = "operator"
criteria_hash = "ef9d1ce99084965e"
running_at = "2026-08-22T09:00:00+00:00"
running_by = "operator"
+++
# Experiment: Answer every inquiry within 1 hour
- **ID:** EXP-example-coworking-001
- **Status:** running
- **Owner:** operator
- **Engine:** conversion

## Customer
Members (B2C)

## Evidence
engines/conversion/audits/ (slow first response, never responded)

## Hypothesis
If every member inquiry gets a reply within an hour, more members will book tours, because the cold-inquiry audit shows slow and missing replies convert worse.

## Offer
_The useful next step offered to the prospect._

## Assets and channel
_What will be created, and where it appears._

## Measurement
- **Primary metric:** Inquiry → meeting rate (increase is better), for Members (B2C) leads
- **Baseline:** the same leads in the 60 days before the start. At proposal: 24% over 58 leads.
- **Minimum observation window:** 14 days and 20 leads in the test group
- **What would make us keep / iterate / kill:** keep if the metric improves by 15% or more; kill if the change is 0% or worse; iterate in between. Fixed when approved.

## Priority score
Customer fit (_/5) + Evidence strength (_/5) + Business impact (_/5) − Effort (_/5) = _

## Result
- **Outcome:**
- **Verdict:**
- **Confidence:**
- **Lesson:**
- **Next test:**

## Measurements log
- 2026-10-25: test 30% (n=66) vs. baseline 34% (n=68), -10%; day 64; suggested **kill** — -10% is at or below the kill bar (0%); confidence medium
