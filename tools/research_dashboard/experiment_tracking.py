from __future__ import annotations

import os
from pathlib import Path


def mlflow_enabled() -> bool:
    return os.environ.get("THE_JOCKEY_MLFLOW_ENABLE", "0").strip().lower() in {"1","true","yes","on"}


def mirror_experiment(row: dict, root: Path) -> dict:
    """Best-effort MLflow mirror. CSV ledger remains source of truth."""
    if not mlflow_enabled():
        return {"status":"DISABLED"}
    try:
        import mlflow
        uri=os.environ.get("THE_JOCKEY_MLFLOW_URI") or str((root/"mlruns").resolve())
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(os.environ.get("THE_JOCKEY_MLFLOW_EXPERIMENT","THE-JOCKEY-RESEARCH"))
        params={k:v for k,v in row.items() if k in {"experiment_key","split_id","source","target","feature_set","config","depth","lr","l2","iters","seed","trees","features","status"} and v not in (None,"")}
        metrics={k:float(v) for k,v in row.items() if k in {"selection_logloss","selection_auc","test_logloss","test_auc","oos_logloss_report_only","oos_auc_report_only"} and v not in (None,"")}
        with mlflow.start_run(run_name=str(row.get("experiment_key","experiment"))):
            mlflow.log_params(params)
            if metrics: mlflow.log_metrics(metrics)
            mlflow.set_tags({"the_jockey_governed":"true","oos_report_only":"true","csv_ledger_source_of_truth":"true"})
        return {"status":"MIRRORED","tracking_uri":uri}
    except Exception as e:
        return {"status":"ERROR","error":repr(e)}
