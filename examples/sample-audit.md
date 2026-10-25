# Cold-inquiry audit — example-coworking — as of 2026-10-25

_Conversion engine · agent `cold-inquiry-auditor` · Level 0 (observe). Nothing was sent to anyone._

**Source:** lead ledger (320 leads, 1854 events from crm; last import 2026-10-25T06:19:59+00:00). Lead references are IDs in the client's lead-tracking tool; look them up there for names and details.

## Headline

Members (B2C): 129 of 199 inquiries (65%) went cold, 106 of them for reasons on our side. The biggest fixable leak: first response came too late (31 leads).

Receipts: `L-1283`, `L-1071`, `L-1282`, `L-1190`, `L-1307`, `L-1074`, `L-1258`, `L-1061` and 23 more

## By segment

Each segment is judged on its own sales cycle and thresholds.

| Segment | Inquiries | Reached meeting | Won | Went cold | Ours to fix |
|---|---|---|---|---|---|
| Members (B2C) | 216 | 30% | 13% | 129 | 106 |
| Office leases (B2B) | 104 | 32% | 11% | 48 | 40 |

## Members (B2C)

129 of 199 inquiries (65%) went cold, 106 of them for reasons on our side. The biggest fixable leak: first response came too late (31 leads).

### Baseline

Inquiries in the last 180 days: **216** (199 are older than 14 days and can be judged).

| Stage | Leads | From inquiry |
|---|---|---|
| Inquire | 216 | 100% |
| Qualify | 146 | 68% |
| Meet | 64 | 30% |
| Commit | 29 | 13% |

- Won: 29 · Lost: 37 · Open: 150
- Median speed to first response: 8.1 hours
- Never responded to: 33
- Outcome reported for 62 of 187 leads past the sales cycle (33%)

### Where inquiries went cold

A lead counts as cold when it is open, short of commitment, and nothing has happened for 14+ days. **129** leads are cold (65% of judged inquiries); **106** of them went cold for reasons on our side. Recorded value of those 106 leads: **366,000**.

| Why it went cold | Leads | Ours to fix | Receipts |
|---|---|---|---|
| Never got a response from us | 25 | yes | `L-1245`, `L-1091`, `L-1013`, `L-1288`, `L-1055`, `L-1289`, `L-1281`, `L-1178` and 17 more |
| Prospect wrote last and we never answered | 29 | yes | `L-1031`, `L-1202`, `L-1239`, `L-1072`, `L-1280`, `L-1214`, `L-1227`, `L-1073` and 21 more |
| First response came too late | 31 | yes | `L-1283`, `L-1071`, `L-1282`, `L-1190`, `L-1307`, `L-1074`, `L-1258`, `L-1061` and 23 more |
| We stopped following up too early | 21 | yes | `L-1194`, `L-1086`, `L-1054`, `L-1030`, `L-1089`, `L-1159`, `L-1270`, `L-1125` and 13 more |
| Met, then stalled before commitment | 3 | no | `L-1075`, `L-1111`, `L-1104` |
| Followed up properly; prospect went quiet | 20 | no | `L-1053`, `L-1050`, `L-1006`, `L-1068`, `L-1299`, `L-1168`, `L-1250`, `L-1026` and 12 more |

Furthest stage reached by cold leads: qualify 62, inquire 53, meet 14.

### Speed to first response vs. outcome

| First response | Leads | Reached meeting | Won |
|---|---|---|---|
| no response | 29 | 2 (7%) | 2 (7%) |
| ≤ 5m (too few to compare) | 9 | 5 (56%) | 1 (11%) |
| 5m–1h | 64 | 26 (41%) | 12 (19%) |
| 1h–1d | 46 | 12 (26%) | 7 (15%) |
| > 1d | 51 | 15 (29%) | 7 (14%) |

**Confidence: low** — smallest compared group has 29 leads; observational, not a controlled test; 1 group(s) under 10 leads left out. Faster replies may also go to warmer leads, so treat a gap here as a reason to test, not as proof.

### By channel

| Channel | Leads | Reached meeting | Won | Went cold |
|---|---|---|---|---|
| Website form | 75 | 29% | 15% | 60% |
| Google Business | 48 | 35% | 17% | 69% |
| Instagram DM | 47 | 30% | 15% | 64% |
| Referral | 29 | 24% | 10% | 72% |

### Lost reasons

| Reason | Leads | Receipts |
|---|---|---|
| price too high | 11 | `L-1012`, `L-1038`, `L-1066`, `L-1085`, `L-1117`, `L-1121`, `L-1134`, `L-1238` and 3 more |
| chose a competitor | 11 | `L-1060`, `L-1064`, `L-1144`, `L-1146`, `L-1170`, `L-1171`, `L-1223`, `L-1264` and 3 more |
| timing - not ready | 8 | `L-1039`, `L-1087`, `L-1096`, `L-1100`, `L-1179`, `L-1211`, `L-1253`, `L-1294` |
| not recorded | 5 | `L-1015`, `L-1160`, `L-1251`, `L-1257`, `L-1297` |
| location too far | 2 | `L-1051`, `L-1256` |

### Leads worth a second look

Cold for reasons on our side, highest value first. For a human to review in the lead-tracking tool; no message has been drafted or sent.

| Lead | Why | Stage | Channel | Value | Quiet for |
|---|---|---|---|---|---|
| `L-1031` | Prospect wrote last and we never answered | inquire | Website form | 4,200 | 16 days |
| `L-1245` | Never got a response from us | inquire | Google Business | 4,200 | 18 days |
| `L-1194` | We stopped following up too early | qualify | Google Business | 4,200 | 18 days |
| `L-1071` | First response came too late | qualify | Google Business | 4,200 | 18 days |
| `L-1086` | We stopped following up too early | qualify | Website form | 4,200 | 21 days |
| `L-1054` | We stopped following up too early | inquire | Website form | 4,200 | 27 days |
| `L-1288` | Never got a response from us | inquire | Referral | 4,200 | 28 days |
| `L-1258` | First response came too late | qualify | Instagram DM | 4,200 | 41 days |
| `L-1281` | Never got a response from us | inquire | Instagram DM | 4,200 | 41 days |
| `L-1145` | Never got a response from us | inquire | Website form | 4,200 | 45 days |
| `L-1061` | First response came too late | qualify | Instagram DM | 4,200 | 46 days |
| `L-1089` | We stopped following up too early | qualify | Website form | 4,200 | 49 days |
| `L-1101` | Never got a response from us | inquire | Instagram DM | 4,200 | 57 days |
| `L-1232` | First response came too late | meet | Google Business | 4,200 | 61 days |
| `L-1204` | First response came too late | qualify | Instagram DM | 4,200 | 62 days |
| `L-1196` | First response came too late | qualify | Google Business | 4,200 | 73 days |
| `L-1029` | Prospect wrote last and we never answered | inquire | Website form | 4,200 | 76 days |
| `L-1201` | First response came too late | qualify | Google Business | 4,200 | 76 days |
| `L-1262` | First response came too late | qualify | Google Business | 4,200 | 86 days |
| `L-1270` | We stopped following up too early | meet | Google Business | 4,200 | 91 days |
| `L-1166` | We stopped following up too early | meet | Website form | 4,200 | 94 days |
| `L-1126` | Never got a response from us | inquire | Instagram DM | 4,200 | 95 days |
| `L-1220` | Never got a response from us | inquire | Website form | 4,200 | 100 days |
| `L-1273` | Prospect wrote last and we never answered | qualify | Website form | 4,200 | 102 days |
| `L-1065` | Never got a response from us | inquire | Website form | 4,200 | 103 days |

### Proposed next tests

Hypotheses for the operator to decide on. None is approved or running.

1. **First response came too late** (31 leads). Cut speed to first response for one channel (start with the slowest) and compare its inquiry → meeting rate with the baseline period.
2. **Prospect wrote last and we never answered** (29 leads). Add a daily 'waiting on us' queue: any lead whose last message is inbound and unanswered for 24h is surfaced to a human. Measure how many cold leads it prevents.
3. **Never got a response from us** (25 leads). Guarantee a first response for every inquiry: route new inquiries to an instant, approved-facts reply (conversion agent at Level 1 drafts, human sends) and measure inquiry → meeting rate against the baseline above.

### Data gaps

- Only 33% of leads older than the 21-day cycle have a won/lost outcome. Open leads may really be lost; ask the client to close them out with reasons.

### Settings

`lookback_days` = 180, `cold_after_days` = 14, `slow_response_hours` = 24, `min_followups` = 3, `min_group_size` = 10, `response_buckets_minutes` = [5, 60, 1440], `max_candidates` = 25, `cycle_days` = 21

## Office leases (B2B)

48 of 91 inquiries (53%) went cold, 40 of them for reasons on our side. The biggest fixable leak: we stopped following up too early (14 leads).

### Baseline

Inquiries in the last 180 days: **104** (91 are older than 30 days and can be judged).

| Stage | Leads | From inquiry |
|---|---|---|
| Inquire | 104 | 100% |
| Qualify | 67 | 64% |
| Meet | 33 | 32% |
| Commit | 11 | 11% |

- Won: 11 · Lost: 25 · Open: 68
- Median speed to first response: 48 minutes
- Never responded to: 18
- Outcome reported for 28 of 57 leads past the sales cycle (49%)

### Where inquiries went cold

A lead counts as cold when it is open, short of commitment, and nothing has happened for 30+ days. **48** leads are cold (53% of judged inquiries); **40** of them went cold for reasons on our side. Recorded value of those 40 leads: **1,890,000**.

| Why it went cold | Leads | Ours to fix | Receipts |
|---|---|---|---|
| Never got a response from us | 11 | yes | `L-1215`, `L-1261`, `L-1052`, `L-1059`, `L-1107`, `L-1246`, `L-1285`, `L-1189` and 3 more |
| Prospect wrote last and we never answered | 7 | yes | `L-1097`, `L-1197`, `L-1141`, `L-1147`, `L-1231`, `L-1003`, `L-1243` |
| First response came too late | 8 | yes | `L-1213`, `L-1224`, `L-1058`, `L-1298`, `L-1078`, `L-1127`, `L-1275`, `L-1311` |
| We stopped following up too early | 14 | yes | `L-1277`, `L-1219`, `L-1084`, `L-1276`, `L-1230`, `L-1040`, `L-1234`, `L-1235` and 6 more |
| Met, then stalled before commitment | 1 | no | `L-1267` |
| Followed up properly; prospect went quiet | 7 | no | `L-1180`, `L-1093`, `L-1167`, `L-1009`, `L-1188`, `L-1019`, `L-1011` |

Furthest stage reached by cold leads: inquire 23, qualify 19, meet 6.

### Speed to first response vs. outcome

| First response | Leads | Reached meeting | Won |
|---|---|---|---|
| no response | 14 | 1 (7%) | 1 (7%) |
| ≤ 5m (too few to compare) | 3 | 1 (33%) | 0 (0%) |
| 5m–1h | 37 | 20 (54%) | 10 (27%) |
| 1h–1d | 19 | 2 (11%) | 0 (0%) |
| > 1d | 18 | 5 (28%) | 0 (0%) |

**Confidence: low** — smallest compared group has 14 leads; observational, not a controlled test; 1 group(s) under 10 leads left out. Faster replies may also go to warmer leads, so treat a gap here as a reason to test, not as proof.

### By channel

| Channel | Leads | Reached meeting | Won | Went cold |
|---|---|---|---|---|
| Website form | 37 | 27% | 11% | 57% |
| Google Business | 26 | 42% | 19% | 38% |
| Instagram DM | 18 | 22% | 0% | 61% |
| Referral | 10 | 40% | 20% | 60% |

### Lost reasons

| Reason | Leads | Receipts |
|---|---|---|
| lease term too long | 6 | `L-1004`, `L-1036`, `L-1177`, `L-1216`, `L-1229`, `L-1302` |
| price too high | 6 | `L-1027`, `L-1076`, `L-1193`, `L-1210`, `L-1217`, `L-1274` |
| chose a competitor | 4 | `L-1005`, `L-1130`, `L-1296`, `L-1308` |
| no parking for the team | 3 | `L-1008`, `L-1022`, `L-1090` |
| office too small for growth | 3 | `L-1045`, `L-1156`, `L-1198` |
| not recorded | 3 | `L-1056`, `L-1057`, `L-1153` |

### Leads worth a second look

Cold for reasons on our side, highest value first. For a human to review in the lead-tracking tool; no message has been drafted or sent.

| Lead | Why | Stage | Channel | Value | Quiet for |
|---|---|---|---|---|---|
| `L-1097` | Prospect wrote last and we never answered | inquire | Google Business | 78,000 | 47 days |
| `L-1219` | We stopped following up too early | meet | Google Business | 78,000 | 49 days |
| `L-1261` | Never got a response from us | inquire | Instagram DM | 78,000 | 68 days |
| `L-1235` | We stopped following up too early | qualify | Website form | 78,000 | 80 days |
| `L-1018` | We stopped following up too early | inquire | Referral | 78,000 | 83 days |
| `L-1052` | Never got a response from us | inquire | Website form | 78,000 | 93 days |
| `L-1275` | First response came too late | meet | Instagram DM | 78,000 | 94 days |
| `L-1059` | Never got a response from us | inquire | Instagram DM | 78,000 | 94 days |
| `L-1233` | We stopped following up too early | inquire | Website form | 78,000 | 109 days |
| `L-1285` | Never got a response from us | inquire | Website form | 78,000 | 112 days |
| `L-1189` | Never got a response from us | inquire | Website form | 78,000 | 116 days |
| `L-1161` | We stopped following up too early | meet | Website form | 78,000 | 125 days |
| `L-1003` | Prospect wrote last and we never answered | inquire | Website form | 78,000 | 149 days |
| `L-1243` | Prospect wrote last and we never answered | inquire | Google Business | 78,000 | 164 days |
| `L-1200` | Never got a response from us | inquire | Referral | 78,000 | 164 days |
| `L-1213` | First response came too late | qualify | Instagram DM | 28,800 | 30 days |
| `L-1224` | First response came too late | qualify | Website form | 28,800 | 32 days |
| `L-1277` | We stopped following up too early | qualify | Website form | 28,800 | 33 days |
| `L-1058` | First response came too late | inquire | Website form | 28,800 | 40 days |
| `L-1298` | First response came too late | qualify | Website form | 28,800 | 48 days |
| `L-1078` | First response came too late | qualify | Google Business | 28,800 | 50 days |
| `L-1084` | We stopped following up too early | qualify | Referral | 28,800 | 52 days |
| `L-1127` | First response came too late | qualify | Website form | 28,800 | 56 days |
| `L-1276` | We stopped following up too early | meet | Referral | 28,800 | 57 days |
| `L-1230` | We stopped following up too early | inquire | Google Business | 28,800 | 62 days |

### Proposed next tests

Hypotheses for the operator to decide on. None is approved or running.

1. **We stopped following up too early** (14 leads). Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked.
2. **Never got a response from us** (11 leads). Guarantee a first response for every inquiry: route new inquiries to an instant, approved-facts reply (conversion agent at Level 1 drafts, human sends) and measure inquiry → meeting rate against the baseline above.
3. **First response came too late** (8 leads). Cut speed to first response for one channel (start with the slowest) and compare its inquiry → meeting rate with the baseline period.

### Data gaps

- Only 49% of leads older than the 90-day cycle have a won/lost outcome. Open leads may really be lost; ask the client to close them out with reasons.

### Settings

`lookback_days` = 180, `cold_after_days` = 30, `slow_response_hours` = 24, `min_followups` = 5, `min_group_size` = 10, `response_buckets_minutes` = [5, 60, 1440], `max_candidates` = 25, `cycle_days` = 90

