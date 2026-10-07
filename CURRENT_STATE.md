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
