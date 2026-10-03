# THE JOCKEY Turbo Research Mode

- Experiment Director keeps CORE-004 data resident in memory.
- Normal inter-experiment wait: 0 seconds.
- CatBoost thread_count defaults to all logical CPU cores.
- 2024 is model-selection data, 2025 is test, and 2026 remains report-only OOS.
- Failed experiments are logged and the engine continues after a short recovery delay.
- Environment overrides:
  - THE_JOCKEY_EXPERIMENT_THREADS
  - THE_JOCKEY_EXPERIMENT_ERROR_SLEEP
