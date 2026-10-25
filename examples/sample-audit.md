# Cold-inquiry audit — example-coworking — as of 2026-10-25

_Conversion engine · agent `cold-inquiry-auditor` · Level 0 (observe). Nothing was sent to anyone._

**Source:** lead ledger (320 leads, 2032 events from crm; last import 2026-10-25T06:11:44+00:00). Lead references are IDs in the client's lead-tracking tool; look them up there for names and details.

## Headline

Members (B2C): 101 of 195 inquiries (52%) went cold, 78 of them for reasons on our side. The biggest fixable leak: prospect wrote last and we never answered (25 leads).

Receipts: `L-1048`, `L-1267`, `L-1107`, `L-1307`, `L-1216`, `L-1209`, `L-1186`, `L-1001` and 17 more

## By segment

Each segment is judged on its own sales cycle and thresholds.

| Segment | Inquiries | Reached meeting | Won | Went cold | Ours to fix |
|---|---|---|---|---|---|
| Members (B2C) | 206 | 36% | 21% | 101 | 78 |
| Office leases (B2B) | 114 | 41% | 12% | 53 | 38 |

## Members (B2C)

101 of 195 inquiries (52%) went cold, 78 of them for reasons on our side. The biggest fixable leak: prospect wrote last and we never answered (25 leads).

### Baseline

Inquiries in the last 180 days: **206** (195 are older than 14 days and can be judged).

| Stage | Leads | From inquiry |
|---|---|---|
| Inquire | 206 | 100% |
| Qualify | 144 | 70% |
| Meet | 75 | 36% |
| Commit | 43 | 21% |

- Won: 43 · Lost: 49 · Open: 114
- Median speed to first response: 48 minutes
- Never responded to: 20
- Outcome reported for 88 of 189 leads past the sales cycle (47%)

### Where inquiries went cold

A lead counts as cold when it is open, short of commitment, and nothing has happened for 14+ days. **101** leads are cold (52% of judged inquiries); **78** of them went cold for reasons on our side. Recorded value of those 78 leads: **273,600**.

| Why it went cold | Leads | Ours to fix | Receipts |
|---|---|---|---|
| Never got a response from us | 15 | yes | `L-1198`, `L-1121`, `L-1185`, `L-1298`, `L-1214`, `L-1258`, `L-1316`, `L-1066` and 7 more |
| Prospect wrote last and we never answered | 25 | yes | `L-1048`, `L-1267`, `L-1107`, `L-1307`, `L-1216`, `L-1209`, `L-1186`, `L-1001` and 17 more |
| First response came too late | 18 | yes | `L-1074`, `L-1280`, `L-1015`, `L-1140`, `L-1297`, `L-1183`, `L-1302`, `L-1194` and 10 more |
| We stopped following up too early | 20 | yes | `L-1060`, `L-1004`, `L-1169`, `L-1052`, `L-1083`, `L-1289`, `L-1155`, `L-1193` and 12 more |
| Met, then stalled before commitment | 3 | no | `L-1150`, `L-1180`, `L-1188` |
| Followed up properly; prospect went quiet | 20 | no | `L-1021`, `L-1070`, `L-1033`, `L-1288`, `L-1213`, `L-1317`, `L-1230`, `L-1146` and 12 more |

Furthest stage reached by cold leads: qualify 51, inquire 44, meet 6.

### Speed to first response vs. outcome

| First response | Leads | Reached meeting | Won |
|---|---|---|---|
| no response | 18 | 2 (11%) | 2 (11%) |
| ≤ 5m (too few to compare) | 7 | 5 (71%) | 3 (43%) |
| 5m–1h | 84 | 44 (52%) | 23 (27%) |
| 1h–1d | 42 | 10 (24%) | 8 (19%) |
| > 1d | 44 | 11 (25%) | 7 (16%) |

**Confidence: low** — smallest compared group has 18 leads; observational, not a controlled test; 1 group(s) under 10 leads left out. Faster replies may also go to warmer leads, so treat a gap here as a reason to test, not as proof.

### By channel

| Channel | Leads | Reached meeting | Won | Went cold |
|---|---|---|---|---|
| Website form | 98 | 41% | 22% | 47% |
| Google Business | 47 | 43% | 28% | 51% |
| Instagram DM | 30 | 17% | 13% | 67% |
| Referral | 20 | 35% | 20% | 55% |

### Lost reasons

| Reason | Leads | Receipts |
|---|---|---|
| price too high | 12 | `L-1017`, `L-1032`, `L-1036`, `L-1039`, `L-1049`, `L-1084`, `L-1094`, `L-1157` and 4 more |
| chose a competitor | 11 | `L-1011`, `L-1085`, `L-1091`, `L-1096`, `L-1141`, `L-1160`, `L-1161`, `L-1203` and 3 more |
| timing - not ready | 10 | `L-1025`, `L-1099`, `L-1129`, `L-1130`, `L-1133`, `L-1135`, `L-1162`, `L-1231` and 2 more |
| not recorded | 9 | `L-1045`, `L-1078`, `L-1093`, `L-1124`, `L-1175`, `L-1179`, `L-1202`, `L-1244` and 1 more |
| location too far | 7 | `L-1026`, `L-1064`, `L-1090`, `L-1134`, `L-1205`, `L-1232`, `L-1257` |

### Leads worth a second look

Cold for reasons on our side, highest value first. For a human to review in the lead-tracking tool; no message has been drafted or sent.

| Lead | Why | Stage | Channel | Value | Quiet for |
|---|---|---|---|---|---|
| `L-1048` | Prospect wrote last and we never answered | inquire | Google Business | 4,200 | 16 days |
| `L-1074` | First response came too late | qualify | Google Business | 4,200 | 18 days |
| `L-1280` | First response came too late | inquire | Instagram DM | 4,200 | 24 days |
| `L-1267` | Prospect wrote last and we never answered | inquire | Website form | 4,200 | 28 days |
| `L-1107` | Prospect wrote last and we never answered | qualify | Instagram DM | 4,200 | 28 days |
| `L-1015` | First response came too late | qualify | Google Business | 4,200 | 38 days |
| `L-1186` | Prospect wrote last and we never answered | qualify | Google Business | 4,200 | 44 days |
| `L-1168` | Prospect wrote last and we never answered | qualify | Instagram DM | 4,200 | 53 days |
| `L-1083` | We stopped following up too early | inquire | Google Business | 4,200 | 60 days |
| `L-1225` | Prospect wrote last and we never answered | inquire | Referral | 4,200 | 63 days |
| `L-1183` | First response came too late | qualify | Website form | 4,200 | 71 days |
| `L-1079` | Prospect wrote last and we never answered | qualify | Website form | 4,200 | 71 days |
| `L-1155` | We stopped following up too early | qualify | Website form | 4,200 | 78 days |
| `L-1193` | We stopped following up too early | qualify | Website form | 4,200 | 80 days |
| `L-1111` | We stopped following up too early | inquire | Website form | 4,200 | 81 days |
| `L-1172` | Prospect wrote last and we never answered | qualify | Referral | 4,200 | 81 days |
| `L-1218` | We stopped following up too early | qualify | Website form | 4,200 | 86 days |
| `L-1258` | Never got a response from us | inquire | Instagram DM | 4,200 | 89 days |
| `L-1287` | We stopped following up too early | qualify | Website form | 4,200 | 99 days |
| `L-1254` | We stopped following up too early | inquire | Website form | 4,200 | 115 days |
| `L-1077` | First response came too late | qualify | Google Business | 4,200 | 131 days |
| `L-1215` | Prospect wrote last and we never answered | inquire | Referral | 4,200 | 131 days |
| `L-1166` | First response came too late | inquire | Website form | 4,200 | 135 days |
| `L-1047` | Prospect wrote last and we never answered | qualify | Google Business | 4,200 | 140 days |
| `L-1113` | First response came too late | inquire | Website form | 4,200 | 141 days |

### Proposed next tests

Hypotheses for the operator to decide on. None is approved or running.

1. **Prospect wrote last and we never answered** (25 leads). Add a daily 'waiting on us' queue: any lead whose last message is inbound and unanswered for 24h is surfaced to a human. Measure how many cold leads it prevents.
2. **We stopped following up too early** (20 leads). Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked.
3. **First response came too late** (18 leads). Cut speed to first response for one channel (start with the slowest) and compare its inquiry → meeting rate with the baseline period.

### Data gaps

- Only 47% of leads older than the 21-day cycle have a won/lost outcome. Open leads may really be lost; ask the client to close them out with reasons.

### Settings

`lookback_days` = 180, `cold_after_days` = 14, `slow_response_hours` = 24, `min_followups` = 3, `min_group_size` = 10, `response_buckets_minutes` = [5, 60, 1440], `max_candidates` = 25, `cycle_days` = 21

## Office leases (B2B)

53 of 97 inquiries (55%) went cold, 38 of them for reasons on our side. The biggest fixable leak: we stopped following up too early (12 leads).

### Baseline

Inquiries in the last 180 days: **114** (97 are older than 30 days and can be judged).

| Stage | Leads | From inquiry |
|---|---|---|
| Inquire | 114 | 100% |
| Qualify | 85 | 75% |
| Meet | 47 | 41% |
| Commit | 14 | 12% |

- Won: 14 · Lost: 28 · Open: 72
- Median speed to first response: 42 minutes
- Never responded to: 16
- Outcome reported for 28 of 58 leads past the sales cycle (48%)

### Where inquiries went cold

A lead counts as cold when it is open, short of commitment, and nothing has happened for 30+ days. **53** leads are cold (55% of judged inquiries); **38** of them went cold for reasons on our side. Recorded value of those 38 leads: **1,537,200**.

| Why it went cold | Leads | Ours to fix | Receipts |
|---|---|---|---|
| Never got a response from us | 9 | yes | `L-1174`, `L-1226`, `L-1040`, `L-1306`, `L-1003`, `L-1127`, `L-1219`, `L-1259` and 1 more |
| Prospect wrote last and we never answered | 9 | yes | `L-1069`, `L-1057`, `L-1110`, `L-1136`, `L-1056`, `L-1250`, `L-1260`, `L-1245` and 1 more |
| First response came too late | 8 | yes | `L-1122`, `L-1255`, `L-1177`, `L-1131`, `L-1303`, `L-1067`, `L-1313`, `L-1105` |
| We stopped following up too early | 12 | yes | `L-1204`, `L-1281`, `L-1019`, `L-1061`, `L-1041`, `L-1073`, `L-1266`, `L-1102` and 4 more |
| Met, then stalled before commitment | 5 | no | `L-1200`, `L-1009`, `L-1240`, `L-1163`, `L-1020` |
| Followed up properly; prospect went quiet | 10 | no | `L-1055`, `L-1290`, `L-1294`, `L-1236`, `L-1081`, `L-1221`, `L-1051`, `L-1023` and 2 more |

Furthest stage reached by cold leads: qualify 23, inquire 18, meet 12.

### Speed to first response vs. outcome

| First response | Leads | Reached meeting | Won |
|---|---|---|---|
| no response | 13 | 1 (8%) | 1 (8%) |
| ≤ 5m (too few to compare) | 8 | 5 (62%) | 1 (12%) |
| 5m–1h | 45 | 26 (58%) | 9 (20%) |
| 1h–1d | 16 | 3 (19%) | 1 (6%) |
| > 1d | 15 | 5 (33%) | 2 (13%) |

**Confidence: low** — smallest compared group has 13 leads; observational, not a controlled test; 1 group(s) under 10 leads left out. Faster replies may also go to warmer leads, so treat a gap here as a reason to test, not as proof.

### By channel

| Channel | Leads | Reached meeting | Won | Went cold |
|---|---|---|---|---|
| Website form | 51 | 49% | 14% | 49% |
| Google Business | 28 | 43% | 18% | 50% |
| Instagram DM | 15 | 13% | 7% | 87% |
| Referral | 3 | 33% | 33% | 33% |

### Lost reasons

| Reason | Leads | Receipts |
|---|---|---|
| price too high | 8 | `L-1071`, `L-1112`, `L-1126`, `L-1144`, `L-1158`, `L-1167`, `L-1195`, `L-1261` |
| lease term too long | 6 | `L-1029`, `L-1138`, `L-1181`, `L-1274`, `L-1304`, `L-1310` |
| no parking for the team | 5 | `L-1128`, `L-1148`, `L-1159`, `L-1212`, `L-1311` |
| chose a competitor | 4 | `L-1050`, `L-1201`, `L-1220`, `L-1265` |
| office too small for growth | 4 | `L-1154`, `L-1223`, `L-1235`, `L-1315` |
| not recorded | 1 | `L-1192` |

### Leads worth a second look

Cold for reasons on our side, highest value first. For a human to review in the lead-tracking tool; no message has been drafted or sent.

| Lead | Why | Stage | Channel | Value | Quiet for |
|---|---|---|---|---|---|
| `L-1204` | We stopped following up too early | meet | Website form | 78,000 | 32 days |
| `L-1019` | We stopped following up too early | inquire | Website form | 78,000 | 53 days |
| `L-1040` | Never got a response from us | inquire | Instagram DM | 78,000 | 58 days |
| `L-1122` | First response came too late | meet | Instagram DM | 78,000 | 81 days |
| `L-1266` | We stopped following up too early | inquire | Website form | 78,000 | 82 days |
| `L-1255` | First response came too late | qualify | Website form | 78,000 | 94 days |
| `L-1102` | We stopped following up too early | meet | Website form | 78,000 | 101 days |
| `L-1131` | First response came too late | qualify | Instagram DM | 78,000 | 123 days |
| `L-1262` | We stopped following up too early | meet | Google Business | 78,000 | 166 days |
| `L-1069` | Prospect wrote last and we never answered | meet | Website form | 28,800 | 32 days |
| `L-1281` | We stopped following up too early | qualify | Website form | 28,800 | 33 days |
| `L-1174` | Never got a response from us | inquire | Instagram DM | 28,800 | 47 days |
| `L-1226` | Never got a response from us | inquire | Instagram DM | 28,800 | 51 days |
| `L-1057` | Prospect wrote last and we never answered | qualify | Google Business | 28,800 | 57 days |
| `L-1306` | Never got a response from us | inquire | Website form | 28,800 | 61 days |
| `L-1003` | Never got a response from us | inquire | Instagram DM | 28,800 | 65 days |
| `L-1127` | Never got a response from us | inquire | Referral | 28,800 | 67 days |
| `L-1061` | We stopped following up too early | qualify | Website form | 28,800 | 73 days |
| `L-1041` | We stopped following up too early | qualify | Instagram DM | 28,800 | 73 days |
| `L-1073` | We stopped following up too early | inquire | Google Business | 28,800 | 74 days |
| `L-1219` | Never got a response from us | inquire | Instagram DM | 28,800 | 80 days |
| `L-1110` | Prospect wrote last and we never answered | qualify | Website form | 28,800 | 84 days |
| `L-1136` | Prospect wrote last and we never answered | inquire | Instagram DM | 28,800 | 88 days |
| `L-1259` | Never got a response from us | inquire | Instagram DM | 28,800 | 99 days |
| `L-1177` | First response came too late | qualify | Instagram DM | 28,800 | 102 days |

### Proposed next tests

Hypotheses for the operator to decide on. None is approved or running.

1. **We stopped following up too early** (12 leads). Run a short nurture sequence (drafted from approved facts, human-approved) for open leads that got fewer than the minimum follow-ups. Measure replies and meetings booked.
2. **Never got a response from us** (9 leads). Guarantee a first response for every inquiry: route new inquiries to an instant, approved-facts reply (conversion agent at Level 1 drafts, human sends) and measure inquiry → meeting rate against the baseline above.
3. **Prospect wrote last and we never answered** (9 leads). Add a daily 'waiting on us' queue: any lead whose last message is inbound and unanswered for 24h is surfaced to a human. Measure how many cold leads it prevents.

### Data gaps

- Only 48% of leads older than the 90-day cycle have a won/lost outcome. Open leads may really be lost; ask the client to close them out with reasons.

### Settings

`lookback_days` = 180, `cold_after_days` = 30, `slow_response_hours` = 24, `min_followups` = 5, `min_group_size` = 10, `response_buckets_minutes` = [5, 60, 1440], `max_candidates` = 25, `cycle_days` = 90

