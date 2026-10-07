import os
import sys
import json
import hashlib
import ast
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/decade-2016-2025"
OUT = ROOT / "artifacts/parallel-experiments-v1"
CACHE = {}
SOURCE = ""
WORKER_SEED = 20162025


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True
    ).encode("utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


def configs():
    result = []

    for strength in (12, 24):
        for width in (200, 400, 800):
            for cap in (.25, .5):
                result.append({
                    "id": (
                        f"class-s{strength}-d{width}"
                        f"-w{int(cap * 100)}"
                    ),
                    "strength": strength,
                    "width": width,
                    "cap": cap,
                    "context": "class"
                })

    for context in ("venue_class", "track_distance"):
        for cap in (.25, .5):
            result.append({
                "id": f"{context}-s12-d400-w{int(cap * 100)}",
                "strength": 12,
                "width": 400,
                "cap": cap,
                "context": context
            })

    return result


def init_worker(source, hashes):
    global CACHE, SOURCE
    SOURCE = source

    for relative, expected in hashes.items():
        path = BASE / relative

        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(
                "入力ファイルが変更されています：" + relative
            )

        envelope = load(path)

        actual = hashlib.sha256(
            encoded(envelope["rows"])
        ).hexdigest()

        if actual != envelope["rows_sha256"]:
            raise ValueError(
                "保存データのハッシュ不一致：" + relative
            )

        CACHE[relative] = envelope["rows"]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(
            "既存コードとの接続箇所が一致しません：" + old[:80]
        )
    return text.replace(old, new, 1)


def transformed(config):
    text = SOURCE

    # 通常の過去勝率は変更せず、候補側だけを変更する
    text = replace_once(
        text,
        "specific = (nw+1)/(nr+12)",
        (
            f"specific = (nw+{config['strength'] / 12!r})"
            f"/(nr+{config['strength']})"
        )
    )

    text = replace_once(
        text,
        "weight = min(.5,nr/(nr+5))",
        f"weight = min({config['cap']!r},nr/(nr+5))"
    )

    text = replace_once(
        text,
        'int(c["distance"])//400',
        f'int(c["distance"])//{config["width"]}'
    )

    if config["context"] == "venue_class":
        text = replace_once(
            text,
            'c["grade"] or "0",c["race_class"]',
            'c["grade"] or "0",c["race_class"],c["venue"]'
        )

    elif config["context"] == "track_distance":
        text = replace_once(
            text,
            'c["grade"] or "0",c["race_class"]',
            '"ALL","ALL"'
        )

    ast.parse(text)
    return text


def execute(config):
    namespace = {
        "__file__": str(ROOT / "src/decade_evaluate.py"),
        "__name__": "experiment_engine"
    }

    exec(
        compile(
            transformed(config),
            "experiment_engine",
            "exec"
        ),
        namespace
    )

    # 読み込んだデータを各候補で再利用
    namespace["snapshot"] = (
        lambda path: CACHE[path.relative_to(BASE).as_posix()]
    )

    from condition_audit import interval

    # 各候補の10年全体について推定幅を計算する
    namespace["interval"] = lambda rows, unit, seed: (
        interval(rows, unit, seed)
        if seed == WORKER_SEED else None
    )

    report, pairs = namespace["compute"](BASE)

    if report["evaluated_years"] != 10:
        raise ValueError("10年分の評価が完了していません")

    reference = load(BASE / "report.json")

    actual_counts = (
        report["overall"]["rows"],
        report["overall"]["races"]
    )

    expected_counts = (
        reference["overall"]["rows"],
        reference["overall"]["races"]
    )

    if actual_counts != expected_counts:
        raise ValueError(
            "比較対象のレース・記録数が一致しません"
        )

    for method in ("baseline", "uniform"):
        for metric in ("logloss", "brier"):
            actual = (
                report["overall"]["metrics"][method][metric]
            )
            expected = (
                reference["overall"]["metrics"][method][metric]
            )

            if abs(actual - expected) > 1e-12:
                raise ValueError("比較基準が再現されません")

    # 現行候補を含め、既存結果の再現も確認する
    if config["id"] == "class-s12-d400-w50":
        for metric in ("logloss", "brier"):
            actual = (
                report["overall"]["metrics"]["candidate"][metric]
            )
            expected = (
                reference["overall"]["metrics"]["candidate"][metric]
            )

            if abs(actual - expected) > 1e-12:
                raise ValueError("現行候補が再現されません")

    # 日別の差を保存する
    daily = {}

    for entry in pairs:
        item = daily.setdefault(entry["day"], {
            "day": entry["day"],
            "rows": 0,
            "races": 0,
            "delta_loss_sum": 0.,
            "delta_brier_sum": 0.
        })

        item["rows"] += entry["rows"]
        item["races"] += 1
        item["delta_loss_sum"] += entry["delta_loss_sum"]
        item["delta_brier_sum"] += entry["delta_brier_sum"]

    return {
        "config": config,
        "report": report,
        "paired_days": [
            daily[key] for key in sorted(daily)
        ],
        "production_approved": False
    }


def render(results, errors, total):
    ranked = sorted(
        results,
        key=lambda result: (
            result["report"]["overall"]["metrics"]
            ["candidate"]["logloss"],
            result["config"]["id"]
        )
    )

    summary = {
        "completed": len(results),
        "requested": total,
        "failed": errors,
        "ranking": [{
            "config": result["config"],
            "overall": result["report"]["overall"],
            "improved_years": result["report"]["improved_years"],
            "day_interval": result["report"]["day_interval"]
        } for result in ranked],
        "production_approved": False,
        "limitations": [
            "全候補は研究用。2016〜2025年は既に確認済みの期間。",
            "順位による選抜と複数比較の影響は95%推定幅に補正していない。",
            "過去の情報公開時点・訂正履歴・公式網羅性は未確認。",
            "収益性・確率校正・ライブ利用は未検証。"
        ]
    }

    save(OUT / "summary.json", summary)

    rows = []

    for rank, item in enumerate(summary["ranking"], 1):
        metrics = item["overall"]["metrics"]["candidate"]

        rows.append(
            f"<tr><td>{rank}</td>"
            f"<td>{item['config']['id']}</td>"
            f"<td>{metrics['logloss']:.8f}</td>"
            f"<td>{metrics['brier']:.8f}</td>"
            f"<td>{item['overall']['delta_logloss']:+.8f}</td>"
            f"<td>{item['improved_years']}/10</td></tr>"
        )

    section = (
        '<!-- PARALLEL_EXPERIMENTS_START -->'
        '<section id="parallel-experiments" '
        'style="max-width:1100px;margin:24px auto;padding:20px;'
        'background:white;color:#17253a;'
        'border:1px solid #888;border-radius:12px">'
        '<h2>複数候補の一括実験</h2>'
        f'<p>完了 {len(results)}/{total}候補・'
        f'失敗 {len(errors)}件。'
        'ページを再読込すると進捗が更新されます。</p>'
        '<p>数値は小さいほど良好。差は通常の過去勝率との比較です。'
        '全候補は研究用で、本番未採用です。</p>'
        '<div style="overflow:auto"><table>'
        '<thead><tr>'
        '<th>順位</th><th>候補</th>'
        '<th>Logloss</th><th>Brier</th>'
        '<th>基準との差</th><th>改善年</th>'
        '</tr></thead><tbody>'
        + "".join(rows) +
        '</tbody></table></div>'
        '<p>s＝平滑化の強さ、d＝距離帯の幅（m）、'
        'w＝条件別成績の最大比重（%）。'
        'class＝距離・トラック・競走条件、'
        'venue_class＝競馬場も追加、'
        'track_distance＝距離とトラック。</p>'
        '<p>同じ期間で多数の候補を比べています。'
        '一位という理由だけで採用しません。</p>'
        '</section>'
        '<!-- PARALLEL_EXPERIMENTS_END -->'
    )

    page = ROOT / "web/index.html"
    text = page.read_text(encoding="utf-8-sig")

    start = "<!-- PARALLEL_EXPERIMENTS_START -->"
    end = "<!-- PARALLEL_EXPERIMENTS_END -->"

    if start in text:
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError("画面の追加欄が重複しています")

        a = text.index(start)
        b = text.index(end) + len(end)
        updated = text[:a] + section + text[b:]

    else:
        import re

        if len(re.findall(r"</html\s*>", text, re.I)) != 1:
            raise ValueError("画面の終了位置を確認できません")

        backup = page.with_name(
            page.name + ".before-parallel-" +
            datetime.now().strftime("%Y%m%d-%H%M%S") +
            ".bak"
        )
        backup.write_bytes(page.read_bytes())

        updated = re.sub(
            r"</html\s*>",
            lambda match: section + match.group(),
            text,
            flags=re.I
        )

    temporary = page.with_name(
        page.name + ".parallel.tmp"
    )
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(page)


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    source = (
        ROOT / "src/decade_evaluate.py"
    ).read_text(encoding="utf-8-sig")

    source = source.split("\ndef main(", 1)[0]
    ast.parse(source)

    candidates = configs()

    global SOURCE
    SOURCE = source

    # 実行前に16候補すべての接続箇所を確認する
    for candidate in candidates:
        transformed(candidate)

    files = sorted(
        list((BASE / "conditions").glob("*.json"))
        + list((BASE / "raw-cache").glob("*.json"))
    )

    if len(files) != 195:
        raise ValueError(
            "15年分195ファイルがそろっていません"
        )

    hashes = {
        path.relative_to(BASE).as_posix():
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }

    protocol = {
        "version": 1,
        "candidates": candidates,
        "input_hashes": hashes,
        "engine_sha256": hashlib.sha256(
            source.encode("utf-8")
        ).hexdigest(),
        "runner_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "uncertainty_sha256": hashlib.sha256(
            (ROOT / "src/condition_audit.py").read_bytes()
        ).hexdigest(),
        "history": (
            "2011 warmup; expanding; "
            "updates after complete day"
        ),
        "evaluation": "2016-2025 retrospective research",
        "workers": 2,
        "production_approved": False
    }

    protocol_path = OUT / "protocol.json"

    if protocol_path.exists():
        if load(protocol_path) != protocol:
            raise ValueError(
                "固定した実験条件が変わっています"
            )

    save(protocol_path, protocol)

    results = []
    pending = []

    for candidate in candidates:
        path = (
            OUT / "results" /
            (candidate["id"] + ".json")
        )

        if path.exists():
            result = load(path)

            if result["config"] != candidate:
                raise ValueError(
                    "保存済み候補の設定が一致しません"
                )

            results.append(result)
            print(
                "再利用：" + candidate["id"],
                flush=True
            )
        else:
            pending.append(candidate)

    errors = []
    render(results, errors, len(candidates))

    if pending:
        print(
            "最大2プロセスで並行実験します。",
            flush=True
        )

        with ProcessPoolExecutor(
            max_workers=min(2, os.cpu_count() or 1),
            initializer=init_worker,
            initargs=(source, hashes)
        ) as executor:

            futures = {
                executor.submit(execute, candidate): candidate
                for candidate in pending
            }

            for future in as_completed(futures):
                candidate = futures[future]

                try:
                    result = future.result()

                    save(
                        OUT / "results" /
                        (candidate["id"] + ".json"),
                        result
                    )

                    results.append(result)

                    score = (
                        result["report"]["overall"]["metrics"]
                        ["candidate"]["logloss"]
                    )

                    print(
                        f"完了 {len(results)}/{len(candidates)}："
                        f"{candidate['id']} / "
                        f"Logloss {score:.8f}",
                        flush=True
                    )

                except Exception as error:
                    errors.append({
                        "id": candidate["id"],
                        "error": str(error)
                    })

                    print(
                        "失敗：" + candidate["id"] +
                        " / " + str(error),
                        flush=True
                    )

                render(
                    results, errors, len(candidates)
                )

    if errors:
        raise RuntimeError(
            "未完了候補があります。"
            "再実行で再試行できます"
        )

    from annual_pipeline import ensure_server
    ensure_server()

    from urllib.request import urlopen

    with urlopen(
        "http://127.0.0.1:8792/",
        timeout=10
    ) as response:
        if b"parallel-experiments" not in response.read():
            raise ValueError(
                "一括実験欄の配信を確認できません"
            )

    summary = load(OUT / "summary.json")

    print(
        "【16候補の一括実験：完了】",
        flush=True
    )

    for rank, item in enumerate(summary["ranking"], 1):
        print(
            f"{rank:02} {item['config']['id']} / "
            f"Logloss "
            f"{item['overall']['metrics']['candidate']['logloss']:.8f}"
            f" / 差 {item['overall']['delta_logloss']:+.8f}"
            f" / 改善 {item['improved_years']}/10年"
        )

    handover = ROOT / "HANDOVER.md"

    note = (
        "\n\n## 複数候補の一括実験\n"
        "- 起動：Run-Parallel-Experiments.cmd\n"
        "- 16候補、最大2プロセス。"
        "完了済み候補は再利用。\n"
        "- 結果："
        "artifacts/parallel-experiments-v1/summary.json\n"
        "- 条件：同じ10年のレース、"
        "翌日から履歴更新。\n"
        "- 研究用比較。本番採用・"
        "未知期間の精度・収益性は未確認。\n"
    )

    if handover.exists():
        text = handover.read_text(encoding="utf-8-sig")

        if "## 複数候補の一括実験" not in text:
            handover.write_text(
                text + note,
                encoding="utf-8"
            )

    print(
        "画面配信確認済み："
        "http://127.0.0.1:8792/",
        flush=True
    )
    print(
        "保存先：" + str(OUT),
        flush=True
    )
    print(
        "本番未採用。順位は研究用の比較です。",
        flush=True
    )


if __name__ == "__main__":
    import msvcrt

    OUT.mkdir(parents=True, exist_ok=True)

    with (OUT / "execution.lock").open("a+b") as lock:
        lock.seek(0)

        if not lock.read(1):
            lock.write(b"0")
            lock.flush()

        lock.seek(0)

        try:
            msvcrt.locking(
                lock.fileno(),
                msvcrt.LK_NBLCK,
                1
            )
        except OSError:
            raise SystemExit(
                "一括実験は既に実行中です"
            )

        main()