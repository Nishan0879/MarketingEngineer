# Cold-inquiry audit — example-coworking — as of 2026-10-25

_Conversion engine · agent `cold-inquiry-auditor` · Level 0 (observe). Nothing was sent to anyone._

**Source:** lead ledger (260 leads, 1563 events from crm; last import 2026-10-25T05:43:16+00:00). Lead references are IDs in the client's lead-tracking tool; look them up there for names and details.

## Headline

131 of 243 inquiries (54%) went cold, 93 of them for reasons on our side. The biggest fixable leak: we stopped following up too early (27 leads).

Receipts: `L-1176`, `L-1083`, `L-1177`, `L-1216`, `L-1067`, `L-1141`, `L-1100`, `L-1187` and 19 more

## Baseline

Inquiries in the last 180 days: **260** (243 are older than 14 days and can be judged).

| Stage | Leads | From inquiry |
|---|---|---|
| Inquire | 260 | 100% |
| Qualify | 165 | 63% |
| Meet | 98 | 38% |
| Commit | 53 | 20% |

- Won: 53 · Lost: 56 · Open: 151
- Median speed to first response: 3.2 hours
- Never responded to: 31
- Outcome reported for 104 of 231 leads past the sales cycle (45%)

## Where inquiries went cold

A lead counts as cold when it is open, short of commitment, and nothing has happened for 14+ days. **131** leads are cold (54% of judged inquiries); **93** of them went cold for reasons on our side. Recorded value of those 93 leads: **707,400**.

| Why it went cold | Leads | Ours to fix | Receipts |
|---|---|---|---|
| Never got a response from us | 23 | yes | `L-1023`, `L-1054`, `L-1001`, `L-1229`, `L-1138`, `L-1179`, `L-1039`, `L-1152` and 15 more |
| Prospect wrote last and we never answered | 25 | yes | `L-1022`, `L-1087`, `L-1206`, `L-1193`, `L-1212`, `L-1029`, `L-1149`, `L-1144` and 17 more |
| First response came too late | 18 | yes | `L-1043`, `L-1183`, `L-1203`, `L-1258`, `L-1156`, `L-1225`, `L-1006`, `L-1033` and 10 more |
| We stopped following up too early | 27 | yes | `L-1176`, `L-1083`, `L-1177`, `L-1216`, `L-1067`, `L-1141`, `L-1100`, `L-1187` and 19 more |
| Met, then stalled before commitment | 6 | no | `L-1169`, `L-1207`, `L-1034`, `L-1064`, `L-1136`, `L-1071` |
| Followed up properly; prospect went quiet | 32 | no | `L-1115`, `L-1036`, `L-1219`, `L-1205`, `L-1102`, `L-1222`, `L-1171`, `L-1194` and 24 more |

Furthest stage reached by cold leads: inquire 71, qualify 46, meet 14.

## Speed to first response vs. outcome

| First response | Leads | Reached meeting | Won |
|---|---|---|---|
| no response | 27 | 2 (7%) | 1 (4%) |
| ≤ 5m (too few to compare) | 6 | 2 (33%) | 0 (0%) |
| 5m–1h | 99 | 53 (54%) | 33 (33%) |
| 1h–1d | 64 | 17 (27%) | 8 (12%) |
| > 1d | 47 | 19 (40%) | 11 (23%) |

**Confidence: low** — smallest compared group has 27 leads; observational, not a controlled test; 1 group(s) under 10 leads left out. Faster replies may also go to warmer leads, so treat a gap here as a reason to test, not as proof.

## By channel

| Channel | Leads | Reached meeting | Won | Went cold |
|---|---|---|---|---|
| Website form | 128 | 38% | 23% | 56% |
| Google Business | 62 | 48% | 31% | 42% |
| Instagram DM | 27 | 19% | 0% | 74% |
| Referral | 26 | 35% | 15% | 50% |

## Lost reasons

| Reason | Leads | Receipts |
|---|---|---|
| chose a competitor | 17 | `L-1013`, `L-1031`, `L-1049`, `L-1057`, `L-1074`, `L-1075`, `L-1077`, `L-1090` and 9 more |
| price too high | 15 | `L-1004`, `L-1011`, `L-1046`, `L-1047`, `L-1082`, `L-1085`, `L-1104`, `L-1140` and 7 more |
| no parking | 9 | `L-1058`, `L-1092`, `L-1096`, `L-1112`, `L-1113`, `L-1157`, `L-1167`, `L-1217` and 1 more |
| location too far | 6 | `L-1007`, `L-1018`, `L-1081`, `L-1099`, `L-1114`, `L-1236` |
| not recorded | 6 | `L-1107`, `L-1129`, `L-1153`, `L-1160`, `L-1185`, `L-1257` |
| timing - not ready | 3 | `L-1119`, `L-1180`, `L-1238` |

## Leads worth a second look

Cold for reasons on our side, highest value first. For a human to review in the lead-tracking tool; no message has been drafted or sent.

| Lead | Why | Stage | Channel | Value | Quiet for |
|---|---|---|---|---|---|
| `L-1043` | First response came too late | inquire | Instagram DM | 14,400 | 23 days |
| `L-1177` | We stopped following up too early | meet | Instagram DM | 14,400 | 24 days |
| `L-1067` | We stopped following up too early | qualify | Instagram DM | 14,400 | 34 days |
| `L-1023` | Never got a response from us | inquire | Website form | 14,400 | 35 days |
| `L-1141` | We stopped following up too early | meet | Website form | 14,400 | 38 days |
| `L-1087` | Prospect wrote last and we never answered | inquire | Instagram DM | 14,400 | 38 days |
| `L-1196` | We stopped following up too early | inquire | Website form | 14,400 | 44 days |
| `L-1206` | Prospect wrote last and we never answered | qualify | Website form | 14,400 | 44 days |
| `L-1193` | Prospect wrote last and we never answered | inquire | Website form | 14,400 | 47 days |
| `L-1212` | Prospect wrote last and we never answered | qualify | Google Business | 14,400 | 50 days |
| `L-1201` | We stopped following up too early | inquire | Website form | 14,400 | 53 days |
| `L-1144` | Prospect wrote last and we never answered | inquire | Instagram DM | 14,400 | 54 days |
| `L-1225` | First response came too late | inquire | Referral | 14,400 | 59 days |
| `L-1138` | Never got a response from us | inquire | Instagram DM | 14,400 | 62 days |
| `L-1098` | Prospect wrote last and we never answered | inquire | Website form | 14,400 | 65 days |
| `L-1154` | We stopped following up too early | inquire | Website form | 14,400 | 66 days |
| `L-1084` | Prospect wrote last and we never answered | inquire | Website form | 14,400 | 77 days |
| `L-1179` | Never got a response from us | inquire | Instagram DM | 14,400 | 78 days |
| `L-1126` | Prospect wrote last and we never answered | inquire | Website form | 14,400 | 85 days |
| `L-1127` | Prospect wrote last and we never answered | qualify | Website form | 14,400 | 97 days |
| `L-1252` | First response came too late | qualify | Website form | 14,400 | 98 days |
| `L-1197` | We stopped following up too early | qualify | Website form | 14,400 | 109 days |
| `L-1243` | Never got a response from us | inquire | Google Business | 14,400 | 125 days |
| `L-1008` | We stopped following up too early | meet | Website form | 14,400 | 128 days |
| `L-1213` | Never got a response from us | inquire | Referral | 14,400 | 131 days |

## Proposed next tests

Hypotheses for the operator to decide on. None is approved or running.

1. **We stopped following up too early** (27 leads). Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked.
2. **Prospect wrote last and we never answered** (25 leads). Add a daily 'waiting on us' queue: any lead whose last message is inbound and unanswered for 24h is surfaced to a human. Measure how many cold leads it prevents.
3. **Never got a response from us** (23 leads). Guarantee a first response for every inquiry: route new inquiries to an instant, approved-facts reply (conversion agent at Level 1 drafts, human sends) and measure inquiry → meeting rate against the baseline above.

## Data gaps

- Only 45% of leads older than the 30-day cycle have a won/lost outcome. Open leads may really be lost; ask the client to close them out with reasons.

## Settings

`lookback_days` = 180, `cold_after_days` = 14, `slow_response_hours` = 24, `min_followups` = 3, `min_group_size` = 10, `response_buckets_minutes` = [5, 60, 1440], `max_candidates` = 25
