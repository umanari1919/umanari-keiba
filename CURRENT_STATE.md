# CURRENT STATE — NEO JIZO KEIBA / THE JOCKEY

更新日: 2026-10-08

## Canonical

- Repository: `umanari1919/umanari-keiba`
- Default branch: `main`
- Current main observed before BAOZ branch: `f127eb71b79a6324800663c6e4744d16d7ab880b`
- GitHub is the canonical code/spec/history store.

## Local rescue / restoration

The previous source rescue is complete. Do not restart it.

Restored lines include:

- jockey-25 baseline
- win / top-2 / top-3 evaluation
- 48 workout candidates
- weekend personal forecast chain
- local UI publication
- weekend reality diagnostics

## WEEKEND-REALITY-GATE-001 latest local evidence

Founder-provided local execution on 2026-10-07 reported:

- Weekend source: `UNAVAILABLE`
- Confirmed runners: unavailable
- Special registrations: kept separate
- 2026-10-03 / 2026-10-04 replay: `replay_completed`
- Replay races: 48
- Replay runners: 711
- Personal forecast: `UNAVAILABLE`
- weekend-source-status: exit 1
- historical-replay-20261003-04: exit 0
- DB read-only field in the report: `False`

Interpretation:

- Historical replay path is proven for the 48-race / 711-runner sample.
- Upcoming live-source readiness is not proven.
- Personal forecast output is not available while the weekend source is unavailable.
- Do not rerun the expensive historical replay solely to reproduce the same evidence.

Mission status: `PARTIAL — LIVE SOURCE UNAVAILABLE`

PR #52 added failure classification and `-DiagnoseLatest` so source/runtime failures can be diagnosed without rerunning the heavy replay.

## Founder priority change — BaoZ / JV-Link / UmaConn

The founder completed the initial BaoZ setup and chose a new research stage.

New research mission:

`BAOZ-BASELINE-001`

Principles:

- BaoZ initial settings are the frozen control group.
- Do not customize BaoZ before baseline measurement.
- Prediction quality and betting ROI are separate.
- BaoZ is private benchmark/research only.
- JV-Link / UmaConn are primary acquisition routes for independent NEO JIZO research.
- BaoZ MDB originals, service keys, and PostgreSQL DB remain local only.
- GitHub stores research code, contracts, tests, and aggregate evidence.

## BAOZ-PROBE-001 local evidence — 2026-10-08

Founder-provided local execution succeeded:

- BaoZ location auto-discovered: YES
- BaoZ files: 28
- MDB files: 27
- JV-Link COM registered: True
- UmaConn COM registered: True
- Row data read: False
- BaoZ files modified: False
- Probe artifact: local temp only

Interpretation:

- BaoZ, JV-Link, and UmaConn are present in the same Windows runtime.
- Schema-only inspection is available without reading race rows.
- No licensed raw database was uploaded to GitHub.
- Next local step is schema summarization from the already-created probe JSON, not another full filesystem scan.

## BAOZ-PROBE-002 local evidence — 2026-10-08

Founder-provided schema summary succeeded:

- MDB databases: 27
- Schema opened: 27
- Schema failed: 0
- ACE provider: Microsoft.ACE.OLEDB.16.0
- Backup copies exist for 2026-10-08
- Active prediction DB: `DB\BaoZ.mdb` (21 tables)
- Active race-entry DB: `DB\BaoZ.ex.mdb` (出走馬T)
- Master race DB: `DB\MasterDB\BaoZ-RA.mdb` (15 tables)
- Master runner DB: `DB\MasterDB\BaoZ-SE.mdb` (出走馬マスタ)
- Training DB: `DB\MasterDB\BaoZ-HC.mdb`
  - ウッドチップ調教T
  - 坂路調教T
  - 出走履歴T
  - 調教分析T
- Odds are separated by wager type in O1-O6 MDB files.
- Betting history DB exists separately as `BaoZ-Bet.mdb`.

Important correction / confirmation:

- BaoZ current local database does contain a dedicated Wood Chip training table.
- BaoZ standard prediction/settings data is separated from near-raw master race/runner data.
- Backup MDBs must not be used as the live baseline source unless explicitly needed for recovery.

Next probe must inspect column metadata only for the minimum active tables. No race rows yet.

## BAOZ-PROBE-003 local evidence — 2026-10-08

Founder-provided column-map probe succeeded:

- Target DBs: 5
- Opened DBs: 5
- Failed DBs: 0
- Columns mapped: 2472
- Keyword hits: 1690
- Metadata only: True
- User rows read: False
- BaoZ modified: False

Key findings:

- `DB\BaoZ.ex.mdb / 出走馬T` has 112 columns and contains, in one row grain:
  - race/runner keys: 競走コード, 馬番, 血統登録番号
  - prediction values: 予想タイム指数, 予想タイム指数順位
  - scoring/ranks: デフォルト得点, 得点, 馬券評価順位, 得点V1/V2/V3 and their ranks
  - market: 単勝オッズ, 単勝人気, 単勝/複勝推定オッズ, 投票直前オッズ
  - outcomes: 単勝配当, 複勝配当, 入線順位, 確定着順
- `DB\BaoZ.mdb / レースT` contains race-level prediction state including 予想勝ち指数, 予想決着指数, 波乱度 and popular-horse score/rank fields.
- `DB\BaoZ.mdb / 予想設定T` is key/value configuration (セクション, キー, データ); there is no explicit static 印 column in the schema.
- `DB\MasterDB\BaoZ-SE.mdb / 出走馬マスタ` independently contains race/runner keys, 確定着順, 単勝オッズ, 単勝人気順 and mining fields.
- `DB\MasterDB\BaoZ-HC.mdb / 調教分析T` contains aggregate Miho/Ritto slope and wood-chip features keyed by 競走コード + 馬番.
- Current local BaoZ training schema explicitly contains both ウッドチップ調教T and 坂路調教T.

Interpretation:

- BAOZ baseline can likely be evaluated from a small number of tables.
- Do not equate GUI ◎ with any one rank column yet; GUI mark-generation logic must be identified first.
- Next probe may read aggregate-only row statistics (COUNT/MIN/MAX/non-null coverage), but must not print horse-level rows.

## BAOZ-PROBE-004 local evidence — 2026-10-08

Founder-provided aggregate coverage probe succeeded.

### Active BaoZ runner table

`DB\BaoZ.ex.mdb / 出走馬T` and `DB\BaoZ.mdb / 出走馬T` returned identical aggregate counts:

- rows: 3,227,343
- distinct races: 284,152
- raw date range: 1899-12-30 .. 2026-10-11
- prediction-score coverage: 3,224,007 rows
- betting-rank coverage: 3,209,565 rows
- win odds/popularity coverage: 3,227,343 rows
- win/place payout coverage: 3,226,801 rows
- finish fields are non-null on all rows

Rank=1 counts:

- 予想タイム指数順位: 244,910
- 馬券評価順位: 244,945
- 得点V1順位: 245,080
- 得点V2順位: 245,019
- デフォルト得点順位: 245,003
- 得点V3順位: 244,985

### Master runner table

`DB\MasterDB\BaoZ-SE.mdb / 出走馬マスタ`:

- rows: 4,464,254
- distinct races: 408,856
- date range: 1986-11-02 .. 2026-10-11
- race/runner keys, odds, popularity, and finish fields fully non-null
- popularity rank=1 rows: 329,761

### Race prediction table

`DB\BaoZ.mdb / レースT`:

- rows / distinct races: 473,438
- date range: 1986-01-05 .. 2026-10-11
- 予想勝ち指数 / 予想決着指数 / 波乱度 coverage: 359,687 races

### Important interpretation

- 1899-12-30 is treated as a sentinel/zero date and must not define the historical start boundary.
- Future-dated race-card rows through 2026-10-11 are present; baseline result evaluation must exclude unresolved/future races.
- Non-null finish fields do not prove a valid result; zero/default values must be filtered explicitly.
- `BaoZ.ex.mdb` and `BaoZ.mdb` runner aggregates are identical, so they must not be double-counted.
- Before mapping GUI marks, compare the six available ranking definitions directly on the same valid historical population.

## BAOZ-PROBE-005 local evidence — 2026-10-08

Aggregate rank baseline completed on the untouched BaoZ baseline.

Population:

- cutoff: 2026-10-08
- valid runner rows: 3,189,965
- valid races: 283,878
- valid date range: 1999-06-16 .. 2026-10-07
- zero-finish rows: 36,692
- sentinel-date rows: 2
- future rows: 536

Rank-1 headline metrics:

| rank definition | win | top2 | top3 | win index | place index |
|---|---:|---:|---:|---:|---:|
| 予想タイム指数順位 | 35.48% | 54.62% | 67.07% | 86.598 | 88.775 |
| 馬券評価順位 | 31.01% | 48.56% | 60.60% | 90.757 | 90.173 |
| 得点V1順位 | 33.40% | 51.66% | 63.56% | 87.780 | 88.538 |
| 得点V2順位 | 30.74% | 47.36% | 58.62% | 91.522 | 89.101 |
| デフォルト得点順位 | 33.94% | 52.84% | 65.32% | 88.381 | 89.633 |
| 得点V3順位 | 31.01% | 48.54% | 60.59% | 90.763 | 90.168 |
| 市場1番人気 | 40.81% | 60.82% | 72.73% | 78.302 | 87.002 |

Interpretation:

- Market popularity is substantially stronger for raw hit-rate.
- BaoZ rank-1 selections have materially higher provisional win return indices than market favorite.
- 予想タイム指数順位 is the strongest pure hit-rate rank among the six candidates.
- 得点V2順位 is the strongest provisional win-return rank.
- 馬券評価順位 and 得点V3順位 are nearly numerically identical and may be redundant; exact agreement must be tested.
- No rank definition is above 100 on the unconditional provisional win/place return index. Standard rank-1 flat betting is therefore not yet profitable in aggregate.
- GUI mark mapping remains unresolved and is not inferred from these ranks.

Next:

- cross-tab each rank-1 selection by actual popularity band;
- measure overlap with market favorite;
- test exact agreement/redundancy among ranking definitions;
- preserve aggregate-only output.

## BAOZ-PROBE-006 local evidence — 2026-10-08

Rank-1 x market-popularity cross completed.

### Headline

The strongest provisional win-return pockets are concentrated in longshot selections.

| rank definition | popularity band | n | win | top2 | top3 | win index | place index |
|---|---|---:|---:|---:|---:|---:|---:|
| 予想タイム指数順位=1 | P7+ | 6,435 | 4.32% | 9.98% | 16.99% | 100.988 | 85.688 |
| 馬券評価順位=1 | P7+ | 19,428 | 3.89% | 9.47% | 16.48% | 104.920 | 94.090 |
| 得点V2順位=1 | P7+ | 25,878 | 3.40% | 8.20% | 13.95% | 101.151 | 88.534 |
| 得点V3順位=1 | P7+ | 19,446 | 3.89% | 9.46% | 16.47% | 104.823 | 94.059 |

Other observations:

- BaoZ rank-1 selections that are market favorite have very high hit rates but return indices below 100.
- 馬券評価順位 and 得点V3順位 remain nearly numerically identical at every popularity band.
- payout sanity: minimum positive win payout = 100, maximum = 89,080; minimum positive place payout = 100, maximum = 29,280.
- 283,627 winners were in the valid population; 282,877 had positive win payout. The remaining 750 require anomaly/refund/record-status investigation before formal ROI certification.
- Rank-agreement console table was blank due to a PowerShell output-shape bug; the agreement calculation itself must be rerun with PSCustomObject output.

Interpretation:

- There is a credible longshot-value hypothesis, especially 馬券評価順位/V3 rank=1 at popularity 7+.
- This is not yet declared profitable. It must survive year/era splits and odds-band decomposition and must not be driven by a few extreme payouts.
- GUI mark mapping is still unresolved.

Next:

- repair rank-agreement display;
- test P7+ by year/era, popularity sub-band, and odds band;
- measure concentration of returns and recent-period robustness.

## BAOZ-PROBE-007 local evidence — 2026-10-08

Longshot-stability validation completed.

### Rank agreement

- 馬券評価順位 vs 得点V3順位:
  - exact rank equality: 99.91%
  - rank-1 overlap: 243,911
  - rank-1 Jaccard: 99.90%
- Treat these as operationally near-duplicates until the small disagreement set is explained.

### P7+ longshot result

`馬券評価順位=1 x popularity 7+`:

- n: 19,428
- win: 3.89%
- top3: 16.48%
- provisional win index: 104.920
- provisional place index: 94.090

Popularity sub-bands:

- P7-9: n 14,805 / win index 103.541
- P10-12: n 3,851 / win index 98.634
- P13+: n 772 / win index 162.707

However, era stability shows strong decay:

- 2010-2014: 130.611
- 2015-2019: 104.268
- 2020-2024: 95.114
- 2025-2026: 81.812

Recent annual win index:

- 2020: 101.88
- 2021: 88.27
- 2022: 104.59
- 2023: 112.27
- 2024: 72.03
- 2025: 80.65
- 2026: 83.31

Tail contribution is not extreme:

- payouts >= 5,000: 19.605% of total win return
- payouts >= 10,000: 5.797%
- payouts >= 20,000: 0%

### Other ranking longshot results

- 得点V2順位=1 x P7+: overall 101.151, but 2025-2026 = 87.864
- 得点V3順位=1 x P7+: overall 104.823, but 2025-2026 = 81.670
- 予想タイム指数順位=1 x P7+: overall 100.988, but 2025-2026 = 68.592

### Interpretation

- The historical P7+ edge is real enough to study, but it is not stable in the recent regime.
- Do NOT promote the historical 100%+ result into a current betting rule.
- The 2024-2026 deterioration is the new primary research target.
- Since 馬券評価順位 and 得点V3順位 are 99.9% equivalent, future work can use 馬券評価順位 as the canonical representative unless disagreement analysis requires otherwise.
- Rank fields show no observations in 1999-2009 for the P7+ focus; exact first-coverage date/regime must be measured.

Next:

- identify the exact rank-coverage start date;
- locate the 2024 regime break by venue/organizer, surface, class, field size, and popularity/odds bands;
- compare recent vs historical disagreement with market popularity;
- keep BaoZ settings frozen.

## BAOZ-PROBE-008 local evidence — 2026-10-08

Regime-break probe completed.

### Effective rank coverage

All six BaoZ rank fields are non-null back to 1999-06-16, but the first actual `rank=1` observation for every rank definition is 2012-01-01.

Therefore:

- 1999-2011 must not be treated as valid ranked-baseline history.
- The primary ranked baseline period is fixed to 2012-01-01 onward.
- Earlier non-null rank values are treated as pre-ranking/default-state records until proven otherwise.

### Longshot focus: 馬券評価順位=1 x popularity 7+

Organizer aggregate:

- organizer 1: n 10,743 / win index 103.69 / place index 92.08
- organizer 2: n 8,685 / win index 106.45 / place index 96.58

Track-type aggregate:

- code 1: n 13,344 / win index 109.05
- code 0: n 5,578 / win index 94.77
- code 2: n 506 / win index 107.91

Field-size aggregate:

- 10-12: 108.15
- 13-15: 106.86
- <=9: 102.63
- 16+: 99.44

Recent organizer x year confirms deterioration is not isolated to only one organizer:

- 2024: organizer 1 = 92.72 / organizer 2 = 49.72
- 2025: organizer 1 = 74.58 / organizer 2 = 86.82
- 2026: organizer 1 = 95.02 / organizer 2 = 72.68

### Odds scale sanity

- minimum positive-looking stored odds observed: 0.8
- maximum: 999.9
- average market favorite: 2.186
- average popularity 7-9: 63.705
- average popularity 13+: 207.533

Interpretation:

- stored odds appear decimal-like, but sub-1.0 anomalies require explicit filtering/validation before odds-band analysis;
- 2024-2026 deterioration appears across both organizer codes, so it is not explained by a single organizer alone;
- venue-code-only analysis is insufficient; next probe must resolve venue names and compare matched segments before/after 2024.

## BAOZ-PROBE-009 local evidence — 2026-10-08

Prediction-drift probe completed for 馬券評価順位=1.

### Yearly quality is broadly stable

2019-2026:

- win rate remains roughly 0.30-0.32
- top2 remains roughly 0.47-0.49
- top3 remains roughly 0.59-0.62
- average popularity remains roughly 2.45-2.84
- favorite-share remains roughly 0.40-0.45

This means the 2024-2026 return-index deterioration observed in P7+ selections is not explained by a broad collapse in rank-1 predictive accuracy.

### Organizer comparison: 2019-2023 vs 2024-2026

- organizer 2: win 0.34 -> 0.34 / top3 0.65 -> 0.64
- organizer 1: win 0.18 -> 0.17 / top3 0.43 -> 0.42

Only small deterioration.

### Track type

- code 1: win 0.32 -> 0.32 / top3 0.62 -> 0.62
- code 0: win 0.17 -> 0.17 / top3 0.43 -> 0.42
- code 2: small sample, no broad degradation

### Field size

Most field-size groups are stable. The clearest weak point is 16+ runners:

- win 0.17 -> 0.14
- top3 0.40 -> 0.38
- average popularity 4.21 -> 4.40

### Venue-specific shifts

Notable deterioration:
- 名古屋: win 0.37 -> 0.32 / top3 0.68 -> 0.63
- 盛岡: top3 0.66 -> 0.61
- 門別: win 0.35 -> 0.32 / top3 0.67 -> 0.64
- 姫路: win 0.35 -> 0.30

Notable improvement:
- 大井: win 0.25 -> 0.30 / top3 0.52 -> 0.58
- 佐賀: win 0.37 -> 0.39 / top3 0.67 -> 0.69
- 函館: win 0.16 -> 0.19 / top3 0.40 -> 0.44

### Interpretation

- The broad rank-1 model did not materially lose predictive accuracy after 2024.
- Therefore the previously observed longshot return decay is more likely caused by:
  1. changes in market pricing/odds for the same predictive signal;
  2. a narrower longshot-specific hit-rate shift not visible in all rank-1 selections;
  3. venue-mix changes in some segments.
- Next analysis should compare longshot rank-1 selections before/after 2024 on average odds, realized win rate, winner payout, and implied market probability.

## BAOZ-PROBE-010 local evidence — 2026-10-08

Price-vs-accuracy decomposition completed for `馬券評価順位=1`.

### Overall shift: 2019-2023 -> 2024-2026

- win rate: 30.76% -> 30.36%
- top3: 60.13% -> 59.62%
- average odds: 7.307 -> 7.826
- average winner payout: 291.71 -> 275.80
- provisional return index: 89.742 -> 83.722

Broad rank-1 predictive quality is nearly stable.

### Longshot shift: popularity 7+

- n: 6,093 -> 3,589
- win rate: 3.94% -> 2.79%
- top3: 16.79% -> 14.46%
- average odds: 38.530 -> 42.637
- average winner payout: 2,718.17 -> 2,811.40
- average implied probability: 3.80% -> 3.53%
- provisional return index: 107.067 -> 78.334

Interpretation:

- recent deterioration is NOT primarily explained by shorter prices;
- prices became longer on average while hit rate deteriorated materially;
- the dominant issue is longshot-selection accuracy decay.

### Popularity sub-bands

P7-9:
- win 4.42% -> 3.12%
- average odds 29.781 -> 33.667
- return index 99.974 -> 75.817

P10-12:
- win 2.46% -> 1.48%
- average odds 59.357 -> 64.786
- average winner payout 4,601.03 -> 3,128.00
- return index 113.172 -> 46.204

P13+:
- very small samples: n 226 -> 127
- win 1.77% -> 2.36%
- return index is unstable/extreme and must not drive conclusions

### Odds-band evidence within P7+

The same accuracy deterioration appears across several odds bands:

- odds 10-19.9: win 6.97% -> 4.68%
- odds 20-39.9: win 3.77% -> 3.22%
- odds 40-79.9: win 1.69% -> 1.08%
- odds 80-159.9: win 1.21% -> 0.93%

This reinforces a model-signal degradation hypothesis rather than simple price compression.

### Yearly P7+

- 2019: win 4.48% / top3 16.18%
- 2020: 4.04% / 18.00%
- 2021: 2.69% / 15.92%
- 2022: 4.71% / 17.67%
- 2023: 4.00% / 16.49%
- 2024: 2.66% / 13.79%
- 2025: 2.99% / 15.41%
- 2026: 2.68% / 14.07%

Conclusion:

- Broad rank-1 accuracy remains stable.
- Longshot-specific rank-1 accuracy has deteriorated since 2024.
- The next research target is not "find profitable conditions"; it is to identify which longshot subsegments account for the accuracy decay.
- BaoZ settings remain frozen.

## BAOZ-PROBE-011 local evidence — 2026-10-08

Accuracy-decay decomposition completed for `馬券評価順位=1 x popularity 7+`.

Overall:

- 2019-2023 win rate: 3.94%
- 2024-2026 win rate: 2.79%
- after-period observations: 3,589
- expected wins at old rate: 141.37
- observed wins: 100
- total win deficit: -41.37

### Popularity contribution

- P7-9: -35.97 wins versus old rate
- P10-12: -6.65
- P13+: +0.75

P7-9 explains about 87% of the total deficit before offsets.

### Organizer contribution

- organizer 2: -25.07
- organizer 1: -16.61

Both organizers contribute; the problem is not isolated to one organizer.

### Track-type contribution

- track type 1: -37.42
- track type 0: -3.84
- track type 2: -0.47

Track type 1 accounts for about 90% of the total deficit before offsets and is the strongest current concentration signal.

### Field-size contribution

- 10-12: -16.44
- 13-15: -13.73
- 16+: -7.30
- <=9: -3.15

The decay is spread across field sizes, with 10-15 runners carrying most of the deficit.

### Venue contribution

Largest negative contributions:

- 小倉: -8.77
- 園田: -6.46
- 佐賀: -4.26
- 川崎: -4.11
- 水沢: -4.07
- 門別: -3.83
- 中山: -3.42
- 大井: -3.09

Positive offsets include 高知, 名古屋, 京都, 函館.

### Interpretation

- The longshot accuracy decay is concentrated mainly in P7-9 and track-type code 1.
- Race-condition and grade codes are not yet interpreted causally because they may encode organizer-specific structure and are highly confounded.
- Next diagnostic target: resolve track-type semantics and decompose the intersection `P7-9 x track_type=1` by organizer, venue and year.
- Continue prediction-quality diagnosis only; do not convert these findings into a wagering rule.

## BAOZ-PROBE-012 local evidence — 2026-10-08

Intersection analysis completed for `馬券評価順位=1 x popularity 7-9 x track_type=1`.

### Structure

Organizer x track-type counts in ranked history:

- organizer 1 / type 0: 24,541
- organizer 1 / type 1: 24,476
- organizer 1 / type 2: 1,776
- organizer 2 / type 0: 818
- organizer 2 / type 1: 192,407

This structure strongly suggests type 1 is the dominant surface for organizer 2 and one of two major surfaces for organizer 1, but BaoZ-local semantics are not yet canonically labeled.

### 2019-2023 vs 2024-2026

Organizer 2:
- n 2,467 -> 1,549
- win 4% -> 3%
- top3 20% -> 17%
- expected after wins at old rate: 67.81
- observed: 45
- deficit: -22.81

Organizer 1:
- n 1,016 -> 549
- win 5% -> 3%
- top3 20% -> 14%
- expected after wins at old rate: 27.02
- observed: 17
- deficit: -10.02

Combined deficit in this intersection is -32.83 wins, about 79% of the total P7+ deficit (-41.37).

### Venue concentration

Largest negative contributions include:

- 園田: -5.48
- 川崎: -5.38
- 小倉: -4.98
- 佐賀: -4.14
- 京都: -3.29
- 水沢: -2.95
- 中山: -2.60
- 笠松: -2.48
- 門別: -2.21

Positive offsets include 高知, 浦和, 名古屋, 東京, 京都-independent? (venue-level variation remains mixed).

### Yearly behavior

The intersection is historically around 4-6% win rate through most of 2012-2023, with:
- 2019: 5%
- 2020: 5%
- 2021: 3%
- 2022: 6%
- 2023: 5%

Then:
- 2024: 3%
- 2025: 3%
- 2026: 3%

Top3 also declines from roughly 19-22% in stronger years to 15-17% in 2024-2026.

### Interpretation

- The longshot degradation is highly concentrated in `P7-9 x track_type=1`.
- Both organizers degrade in the same direction.
- This looks like a cross-organizer regime shift rather than a single venue failure.
- Next step: map BaoZ `トラック種別コード` to raw `トラックコード` locally, then split the intersection by organizer x year with the resolved surface semantics.

## BAOZ-PROBE-013 local evidence — 2026-10-08

Track semantics and the P7-9 x track_type=1 regime shift were confirmed.

### Track semantics

BaoZ `トラック種別コード` maps cleanly to JV-Data raw track codes:

- type 0 -> raw 10/11/12/17/18/20/21 (flat turf family)
- type 1 -> raw 23/24/26 (flat dirt family)
- type 2 -> raw 52/54/55/56/57 (jump/obstacle family)

Therefore, for this dataset:
- track_type 0 = turf
- track_type 1 = dirt
- track_type 2 = obstacle/jump

### P7-9 x dirt x 馬券評価順位=1

2019-2023 vs 2024-2026:

Organizer 2:
- n 2,467 -> 1,549
- win about 4% -> 3%
- top3 20% -> 17%
- win deficit vs old rate: -22.81

Organizer 1:
- n 1,016 -> 549
- win about 5% -> 3%
- top3 20% -> 14%
- win deficit vs old rate: -10.02

Combined deficit: -32.83 wins, about 79% of the total P7+ deficit (-41.37).

### Yearly pattern

The P7-9 dirt intersection is mostly around 4-6% win rate through 2012-2023, then:

- 2024: ~3%
- 2025: ~3%
- 2026: ~3%

Top3 also declines.

### Important methodology gate

Before attributing the post-2024 decay to model logic, training, bloodline, market structure, or any racing feature, we must prove temporal integrity of the historical BaoZ prediction fields.

Required next checks:

- historical prediction/scoring fields existed before or at race time, not only after result ingestion;
- `データ作成年月日` / race date relationship is understood;
- no obvious post-race leakage indicator contaminates rank fields;
- backfilled/recalculated historical predictions are distinguished from contemporaneous predictions if possible.

Until this gate passes, the 2024 dirt-longshot regime shift remains a descriptive observation, not a causal model diagnosis.

## BAOZ-PROBE-014 local evidence — 2026-10-08

Temporal-integrity probe completed.

### Strong pre-result evidence

Future race-card rows after the 2026-10-08 cutoff:

- runner rows: 536
- rank non-null: 536
- rank=1 rows: 55
- score non-null: 536
- finish zero/unresolved: 536
- finish-zero rows with rank non-null: 536

This proves BaoZ can generate rank and score values before final results exist.

### Historical unresolved rows

- unresolved/zero-finish rows in 2012..cutoff: 31,539
- rank non-null among them: 17,240
- rank=1: 872

These are compatible with pre-result/pre-final states, but may include scratches, cancellations, or other abnormal-result records and are not by themselves a clean contemporaneous-history proof.

### Source creation date is not prediction timestamp

Among rank-bearing historical runner rows:

- source creation before race date: 696
- same day: 1,784,774
- after race date: 889,292
- missing: 0

JRA-VAN documentation describes JV-Data as being supplied by record type and data creation date, and advises applying the newer data-creation-date version. Therefore BaoZ `データ作成年月日` must not be interpreted as a prediction-computation timestamp.

### CS / CR

- CS rows: 0
- CR rows: 0

These tables provide no temporal evidence in the current installation.

### Temporal-integrity status

PARTIAL PASS:

- PASS: rank/score can exist pre-result.
- UNRESOLVED: whether each historical rank was calculated contemporaneously using only the information state available at that historical race date, or recomputed/backfilled later.
- Therefore historical performance remains a retrospective evaluation, not yet a certified archived-forecast backtest.

Next gate:

- inspect prediction/calculation/provenance-related schema fields and prediction-computed flags;
- determine whether BaoZ stores a calculation timestamp, settings/version identifier, or other evidence that distinguishes contemporaneous predictions from later recomputation.

## BAOZ-PROBE-015 local evidence — 2026-10-08

Prediction-provenance metadata probe completed.

### Candidate current-snapshot/statistics tables

BaoZ.mdb contains:

- 最新コース成績T
- 最新騎手成績T
- 最新血統成績T
- 最新調教師成績T
- 最新票数T
- 条件別着順タイム指数
- 着順指数Ｔ
- 設定T
- 予想設定T

The presence of multiple `最新...` tables creates a material temporal-leakage question if historical prediction fields can be recomputed using current snapshots.

### Race provenance-related columns

`レースT` includes:

- データ作成年月日
- 月日
- 発走時刻
- 予想計算済み
- 予想勝ち指数
- 予想決着指数
- タイム指数誤差
- オッズ取得時刻
- 投票直前オッズ時刻
- 予想計算状況フラグ
- 馬体重取得時刻
- レコード作成fromtime

### Prediction-computed flag is not a reliable provenance indicator

- 2012-2018: 115,313 races, calcNonZero 35,862
- 2019-2023: 83,774 races, calcNonZero 0
- 2024-2026: 47,259 races, calcNonZero 0
- future: 55 races, calcNonZero 0

Yet `予想勝ち指数` and `波乱度` are non-null essentially throughout all periods, including future races.

Therefore `予想計算済み` cannot be interpreted as a current-version “prediction exists” flag. It likely changed semantics, became deprecated, or is no longer maintained.

### Settings metadata

- `予想設定T` exists but has 0 rows in the current DB.
- No useful model/version provenance was found there.

### Temporal-integrity status remains PARTIAL PASS

Proven:
- rank/score can exist pre-result.

Not proven:
- historical rank values were frozen contemporaneously;
- historical rank values were not recomputed using current `最新...` snapshot tables.

Next gate:
- inspect schema, row counts, date/version fields, and time coverage of the `最新...` tables;
- determine whether they are pure current snapshots or retain historical/as-of structure;
- inspect `設定T` metadata names for model/version/calculation provenance without outputting setting values.

## BAOZ-PROBE-016 local evidence — 2026-10-08

Snapshot/as-of audit completed.

### Current-snapshot tables are single-date snapshots

All four core `最新...` statistics tables have a single creation date of 2026-10-01:

- 最新コース成績T: 258 rows, 作成年月日 min=max=2026-10-01
- 最新騎手成績T: 1,471 rows, 作成年月日 min=max=2026-10-01
- 最新血統成績T: 2,043 rows, 作成年月日 min=max=2026-10-01
- 最新調教師成績T: 1,886 rows, 作成年月日 min=max=2026-10-01

These tables do not retain historical/as-of snapshots.

### Other supporting tables

- 最新票数T: 299 rows, no date/version field
- 条件別着順タイム指数: 2,008 rows, no date/version field
- 着順指数Ｔ: 81 rows, no date/version field
- 設定T: 41 rows, fields セクション / キー / データ, no date/version field

### Temporal-integrity implication

This is a material leakage warning, not yet proof of leakage.

Two possible architectures remain:

1. SAFE possibility:
   - current `最新...` tables are used only when computing new/current predictions;
   - historical prediction feature values were materialized into each historical runner/race row at computation time and remain frozen there.

2. UNSAFE possibility:
   - historical predictions are recomputed or refreshed using the current 2026-10-01 snapshot tables;
   - this would contaminate retrospective historical evaluation with future information.

Next gate:

- inspect materialized historical feature columns in `出走馬T`;
- determine whether jockey/trainer/bloodline/course evaluation values are stored per race and vary historically for the same entity;
- do not label the retrospective evaluation leakage-safe until this is resolved.

## BAOZ-PROBE-017 local evidence — 2026-10-08

Materialized historical feature audit completed.

### Strong evidence of per-race historical materialization

Within `出走馬T`, historical feature values exist across the full ranked period and into future cards.

Key same-entity variation:

- jockey key `騎手コード`
  - entities with 騎手評価 values: 849
  - entities whose 騎手評価 changes historically: 795
  - about 93.6% show historical variation

- trainer key `調教師コード`
  - entities with 調教師評価 values: 976
  - entities whose 調教師評価 changes historically: 933
  - about 95.6% show historical variation

This is strong evidence that at least jockey/trainer evaluation values are materialized per race/runner and are not simply the current 2026-10-01 snapshot copied uniformly across all history.

### Historical feature coverage

Materialized columns include:

- 予想タイム指数
- デフォルト得点 / 得点 / 得点V1/V2/V3
- 血統距離評価 / 血統トラック評価 / 血統成長力評価 / 血統総合評価
- B variants of bloodline evaluations
- 騎手評価 / 調教師評価
- 枠順評価 / 脚質評価
- タイム指数回帰系
- 騎手ランキング / 調教師ランキング

These values are populated historically and future cards also contain many prediction-side values.

### Important limitation

This does not yet prove that every historical feature was computed strictly from data available as of that historical race date.

The remaining high-value provenance test is cross-version stability:

- compare the same historical race-period aggregates across active and backup BaoZ databases from different dates;
- if historical materialized values remain unchanged while current snapshots differ, that strongly supports frozen historical predictions;
- if old historical values change across BaoZ database versions, historical recomputation/backfill is occurring.

### Display bug

The console table under `CANDIDATE FEATURE COLUMNS` printed dictionary keys repeatedly because ordered dictionaries were passed directly to `Format-Table`. This is a presentation bug only; the actual period/variation calculations completed successfully.

## BAOZ-PROBE-018 first run — inconclusive due active-DB selection bug

The first cross-version-freeze run discovered two comparable runner databases:

- Backup/2026-10-08/BaoZ.ex.mdb
  - last write 2026-10-08 01:20:30
  - size 2,047.97 MB
- DB/BaoZ.ex.mdb
  - last write 2026-10-08 01:35:09
  - size 1,715.66 MB

However, the comparison section was empty because the probe incorrectly selected `DB/BaoZ.mdb` as the active comparison baseline instead of `DB/BaoZ.ex.mdb`.

Status of this run: INCONCLUSIVE, not PASS/FAIL.

The probe has been patched to compare active `BaoZ.ex.mdb` directly against backup `BaoZ.ex.mdb` copies.

## BAOZ-PROBE-018 local evidence — 2026-10-08

Cross-copy freeze audit completed.

### Exact aggregate consistency

For all three fixed periods below, aggregate fingerprints were exactly identical across the active `DB/BaoZ.ex.mdb` and every comparable same-day copy:

- 2012-2018: 1,257,472 runner rows
- 2019-2023: 915,062 runner rows
- 2024-2025: 375,687 runner rows

Comparable copies:

- Backup/2026-10-08/BaoZ.ex.mdb
- Backup/2026-10-08/BaoZ.MDB
- DB/BaoZ.ex.mdb
- DB/BaoZ.mdb

Compared metrics included row count plus aggregate fingerprints for:
- 馬券評価順位
- 騎手評価
- 調教師評価
- 血統総合評価
- 予想タイム指数
- デフォルト得点
- 得点

All comparisons reported `exact_aggregate_match=True`.

### Interpretation

This is a strong SAME-DAY FREEZE PASS:

- historical materialized prediction/evaluation values are stable across the backup/current copies available on 2026-10-08;
- there is no evidence that the 01:20-01:47 refresh interval rewrote historical prediction aggregates.

However, this is not yet a true multi-version longitudinal freeze test because every discovered comparable MDB is dated 2026-10-08.

Temporal-integrity status therefore improves to:

- pre-result prediction capability: PASS
- per-race historical materialization for jockey/trainer features: STRONG PASS
- same-day backup/current historical stability: PASS
- long-horizon historical no-recompute proof: UNRESOLVED

Next gate:
- inspect `レースT.レコード作成fromtime` and other timestamp-like fields by historical period;
- determine whether historical rows carry creation timestamps consistent with historical race periods or only recent reload/rebuild timestamps.

## BAOZ-PROBE-019 local evidence — 2026-10-08

Creation-time and backup-history audit completed.

### レコード作成fromtime

Column exists as a date/time type, but historical coverage is essentially absent:

- 2012-2018: 115,313 races / non-null 0
- 2019-2023: 83,774 / non-null 0
- 2024-2025: 34,184 / non-null 0
- 2026: 13,130 / non-null 25
- future 2026-10-09..11: 55 / non-null 22

Observed recent values are around 2026-10-06..07.

Conclusion:
- `レコード作成fromtime` cannot prove historical contemporaneous computation.
- The date-relation query failed with a provider type mismatch, but this does not materially affect the conclusion because historical non-null coverage is zero.

### 予想計算状況フラグ

Across 2012..2026-10-08:
- races: 246,346
- null: 71
- zero: 1,333
- nonzero: 244,942

This field is much more populated than `予想計算済み`, but without documented semantics it is not treated as proof of historical provenance.

### Backup history

Only same-day backup-generation artifacts were found:

- BaoZ-Bet.mdb: last write 2026-10-07
- BaoZ-RA.mdb: 2026-10-08
- BaoZ.ex.mdb: 2026-10-08
- BaoZ.MDB: 2026-10-08

No older longitudinal MDB/archive generation was discovered.

### Final temporal-integrity policy for BAOZ-BASELINE-001

Stop provenance drilling here due diminishing evidence returns.

Status:

- pre-result prediction capability: PASS
- per-race materialized jockey/trainer feature history: STRONG PASS
- same-day backup/current historical stability: PASS
- long-horizon contemporaneous archived-forecast proof: UNRESOLVED

Therefore all historical BaoZ results remain labeled **retrospective evaluation**, not certified archived-forecast backtests.

The baseline research may now return to the main performance question:
- why `馬券評価順位=1 x popularity 7-9 x dirt` deteriorated after 2024.

## BAOZ-PROBE-020 local evidence — 2026-10-08

Feature-drift analysis completed for `馬券評価順位=1 x popularity 7-9 x dirt`, comparing 2019-2023 vs 2024-2026.

### Signals whose winner/non-winner separation became stronger

Raw mean separation (`winner mean - nonwinner mean`) increased notably for:

- 予想タイム指数: +0.38 -> +4.23
- 先行指数: +2.15 -> +5.32
- 血統距離評価: -0.23 -> +1.14
- 血統トラック評価: +1.18 -> +2.32
- 血統総合評価: +1.14 -> +2.22
- 枠順評価: -0.65 -> +2.08
- 脚質評価: +2.97 -> +3.65
- タイム指数回帰推定値: +2.04 -> +3.54

These results argue against a blanket collapse of all BaoZ predictive features in the recent P7-9 dirt population.

### Signals whose raw winner separation weakened or flipped

- 騎手評価: -0.05 -> -0.90
- 調教師評価: +0.41 -> -1.32
- 血統距離評価B: -0.15 -> -0.91
- 血統トラック評価B: -0.19 -> -0.83
- 血統成長力評価B: +0.40 -> -1.15
- 血統総合評価B: -0.19 -> -1.16
- タイム指数上昇係数: +0.72 -> -1.06
- 得点V1: +0.84 -> +0.40
- 得点V2: +1.02 -> +0.51

`得点` / `得点V3` winner separation is almost unchanged (~+0.35 -> +0.33), despite the actual win-rate drop in this segment.

### Composition shifts

Largest raw mean shifts include:

- 距離増減: 34.21 -> 61.50
- 脚質評価: 49.20 -> 45.44
- 先行指数: 45.34 -> 42.38
- 血統総合評価B: 48.76 -> 47.03
- 血統トラック評価B: 51.76 -> 50.13
- 騎手評価: 45.30 -> 44.04
- 調教師評価: 47.62 -> 46.32

These suggest the recent selected population is compositionally different, but raw-scale shifts are not directly comparable across features.

### Important methodological caution

Raw mean separation is scale-dependent and does not establish causal feature importance.

Next gate:
- compute standardized winner-vs-nonwinner effect sizes using within-period dispersion;
- rank which features genuinely gained/lost discrimination on a comparable scale;
- include winner/nonwinner sample sizes and yearly stability before proposing any BaoZ weighting hypothesis.

## BAOZ-PROBE-021 local evidence — 2026-10-08

Standardized discrimination analysis completed for `馬券評価順位=1 x popularity 7-9 x dirt`.

Population:
- 2019-2023: n=3,483 / winners=158
- 2024-2026: n=2,098 / winners=62

### Recent standardized winner/nonwinner separation

Strongest recent absolute effects include:

- 予想タイム指数: d +0.28
- 先行指数: d +0.25
- タイム指数上昇係数: d -0.25
- 血統トラック評価: d +0.22
- 血統総合評価: d +0.20
- 得点 / 得点V3: d about +0.14
- 枠順評価: d +0.13
- タイム指数回帰推定値: d +0.13

### Discrimination that weakened

- 得点V2: +0.23 -> +0.11
- 得点V1: +0.17 -> +0.08
- デフォルト得点: +0.10 -> -0.06

### Sign changes / unstable signals

- タイム指数上昇係数: +0.16 -> -0.25
- 調教師評価: +0.04 -> -0.11
- 血統成長力評価B: +0.04 -> -0.11
- 枠順評価: -0.05 -> +0.13
- 血統距離評価: -0.02 -> +0.11

Yearly winner counts are small (roughly 19-39), so single-year effect estimates are noisy. In particular, 予想タイム指数 is very strong in 2024, nearly neutral in 2025, and positive again in 2026.

### Interpretation

The recent decline is not a blanket loss of all BaoZ feature discrimination. Several individual signals remain useful or stronger, while some composite score variants and other inputs weaken or reverse.

However, this is still not sufficient to call the problem BaoZ-specific model degradation.

Critical missing control:
- compare BaoZ-selected P7-9 dirt candidates against the base win/top3 rate of **all** P7-9 dirt runners in the same periods and odds bands.

If the whole market segment became harder, raw selected-candidate win-rate decline overstates model deterioration.
If BaoZ's lift over that market baseline fell materially, the model-specific degradation case becomes much stronger.

## BAOZ-PROBE-022 local evidence — 2026-10-08

Market-relative lift control completed for `P7-9 x dirt`.

### Main comparison

Before (2019-2023), BaoZ-selected candidates clearly outperformed the base P7-9 dirt runner population.

Visible headline:
- ALL base win rate: about 2%
- ALL BaoZ-selected win rate: about 5%
- before win lift: 2.32x

After (2024-2026):
- ALL base win rate remains about 2%
- ALL BaoZ-selected win rate falls to about 3%

The console table truncated the explicit `after_win_lift` column, so the exact post-period lift must be printed separately before making a precise model-specific degradation claim.

### Calibration evidence

For the selected ALL population:
- 2019-2023 average implied probability: about 4%
- actual selected win rate: about 5%
- calibration gap: +0.21 percentage points

2024-2026:
- average implied probability: about 4%
- actual selected win rate: about 3%
- calibration gap: -0.97 percentage points

This is strong evidence that the recent selected population underperforms the price-implied probability, whereas the earlier period was slightly above it.

The same qualitative deterioration appears in P7/P8/P9 and both organizers.

### Odds-band observations

- ODDS10-19.9 selected calibration gap: +0.88pt -> -1.85pt
- ODDS20-39.9: about 0.00pt -> -0.78pt
- ODDS40-79.9: -0.04pt -> -0.38pt
- ODDS<10 is poor in both periods and tiny.
- ODDS80+ is very sparse and unstable.

### Next required control

Print exact yearly market-relative lift for 2019-2026:
- all P7-9 dirt runners vs BaoZ rank1 selected subset
- exact wins/n and win rates
- lift
- selected implied probability
- selected calibration gap

This will establish whether 2024 is a genuine step-change in model-specific lift rather than a period-average artifact.

## BAOZ-PROBE-024 local evidence — 2026-10-08

Regime-significance gate completed for `馬券評価順位=1 x popularity 7-9 x dirt`.

### Selected-candidate win-rate change

- 2019-2023: 158 / 3,483 = 4.536%
- 2024-2026: 62 / 2,098 = 2.955%
- difference: -1.581 percentage points
- z = 2.940
- two-sided p = 0.003281

The BaoZ-selected candidate win rate declined materially and statistically.

### Base market-segment change

All P7-9 dirt runners:

- 2019-2023: 3,915 / 199,966 = 1.958%
- 2024-2026: 2,137 / 113,832 = 1.877%
- difference: -0.081 percentage points
- z = 1.577
- two-sided p = 0.114896

The underlying market segment did not show a comparably strong change.

### Selection advantage vs non-selected runners

- 2019-2023 selection OR: 2.438
  - 95% CI [2.071, 2.869]
- 2024-2026 selection OR: 1.609
  - 95% CI [1.245, 2.080]

Post/pre OR ratio:

- 0.660
- 95% CI [0.487, 0.894]
- z = -2.679
- p = 0.007374

### Frozen conclusion for this regime

Within the untouched BaoZ baseline, the `馬券評価順位=1 x popularity 7-9 x dirt` segment shows a statistically supported loss of market-relative selection strength from 2024 onward.

This conclusion is scoped to this regime only. It must not be generalized to all BaoZ races or all BaoZ prediction fields.

Historical evidence remains labeled **retrospective evaluation**, not a certified contemporaneous archived-forecast backtest.

### Design implication for NEO JIZO

Do not imitate BaoZ's composite score.

Use BaoZ as a private benchmark and independently test:
- 予想タイム系 / speed signal
- 先行・脚質 / pace-position signal
- bloodline track/distance suitability
- course/field/race context
- Field Strength
- training
- jockey/trainer signals with time-aware validation

The next engineering/research mission is `NEO-JIZO-DIRT-EDGE-025`.

## Current model/research state

- NEO JIZO baseline: `jockey-25`
- Three targets: win / top-2 / top-3
- Workout research: 48 candidates
- Production promotion: not approved
- Automatic wagering: disabled
- BaoZ customization: not started
- BaoZ baseline evidence: pending local read-only extraction

## Operating rule

- GitHub first for specifications, code, tests, and history.
- Work only when local PC / WSL / PostgreSQL / BaoZ files are indispensable.
- One Work should serve one bounded Mission.
- Large local data and licensed/private artifacts never move to GitHub.

## NEO-JIZO-DIRT-EDGE-025 implementation state — 2026-10-08

GitHub implementation is active on branch `research/neo-jizo-dirt-edge-025` / Draft PR #54.

Implemented:

- `src/neo_jizo_dirt_edge.py`
  - separate win / top2 / top3 evaluation
  - Brier scores and calibration gaps
  - Wilson 95% confidence intervals
  - market-relative lift
  - selection win odds-ratio and 95% CI
  - yearly and organizer splits
  - duplicate race+runner rejection
  - probability monotonicity gate

- `src/neo_jizo_dirt_edge_adapter.py`
  - consumes existing calibrated probability output
  - freezes model rank from p_win before market/result join
  - one-to-one prediction/context join
  - ignores retrospective label columns for ranking
  - popularity/odds cannot influence model rank

- `tools/neo_jizo_dirt_edge_context_discovery_025.py`
  - PostgreSQL read-only metadata/aggregate discovery
  - auto-discovers probability artifact
  - inventories candidate popularity/odds/finish/track columns
  - emits no horse-level rows

- `tools/run_neo_jizo_dirt_edge_context_discovery_025.ps1`
  - one-line launcher for the local discovery step

CI:

- NEO JIZO evaluator/adapter contract
- restored training core compatibility
- modern stack quality
- Windows/Linux x Python 3.13/3.14
- PowerShell launcher syntax parsing

Local dependency remaining:

Run the read-only market-context discovery once. The result determines the exact PostgreSQL source for popularity and win odds. Do not write model code or tune weights until this mapping is resolved.

