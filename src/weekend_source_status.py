"""Bounded read-only availability diagnostic; special registrations are not starters."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sample_extract import query

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/jwk-weekend-source-status-v1'
TABLES = ('race_shosai', 'umagoto_race_joho', 'tokubetsu_torokuba', 'tokubetsu_torokubagoto_joho')
JST = timezone(timedelta(hours=9))

def date_window(today):
    return today.strftime('%Y%m%d'), (today + timedelta(days=14)).strftime('%Y%m%d')

def statement(table, year):
    if table not in TABLES or not str(year).isdigit():
        raise ValueError('Unapproved table/year')
    return f"SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT trim(kaisai_nen)||trim(kaisai_gappi) AS day,count(*) rows,count(distinct race_code) races FROM public.{table} WHERE kaisai_nen='{year}' AND keibajo_code IN ('01','02','03','04','05','06','07','08','09','10') GROUP BY 1 ORDER BY 1 DESC LIMIT 16)t"

def summarize(tables, first, last):
    future = {table: [row for row in rows if first <= row['day'] <= last] for table, rows in tables.items()}
    starters = sum(row['rows'] for row in future['umagoto_race_joho'])
    special = sum(row['rows'] for row in future['tokubetsu_torokubagoto_joho'])
    return {'future': future, 'confirmed_runner_rows': starters,
            'special_registration_rows': special,
            'state': 'race_cards_available' if starters else 'awaiting_confirmed_race_cards',
            'special_registrations_are_confirmed_starters': False}

def local_sources():
    result = {}
    path = Path(r'C:\Users\uchih\AppData\Local\JraVanDataLab\jra_race_data.db')
    if path.exists():
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2) as connection:
            connection.execute('PRAGMA query_only=on')
            result['sqlite'] = {'path': str(path), 'read_only': True,
                'counts': {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                           for table in ('races', 'race_entries', 'training', 'odds')}}
    path = Path(r'C:\Program Files\mykeibadb_v4.1\log\log.txt')
    if path.exists():
        # Read bounded tail only. Record progress categories, never configuration/secrets.
        with path.open('rb') as handle:
            handle.seek(max(0, path.stat().st_size - 4096))
            tail = handle.read().decode('utf-8', errors='replace')
        lines = [line for line in tail.splitlines() if line.startswith('0B42:')]
        result['legacy_import_log'] = {'path': str(path), 'modified_at': datetime.fromtimestamp(path.stat().st_mtime, JST).isoformat(),
            'recent_timeseries_odds_record': lines[-1] if lines else None,
            'interpretation': 'Recent log writes are historical odds acquisition evidence; do not interrupt or assume weekend card acquisition.'}
    return result

def main():
    now = datetime.now(JST)
    connection = query("SELECT json_build_object('transaction_read_only',current_setting('transaction_read_only'),'default_transaction_read_only',current_setting('default_transaction_read_only'))")
    if set(connection.values()) != {'on'}:
        raise ValueError('Read-only connection required')
    tables = {table: query(statement(table, now.year)) for table in TABLES}
    first, last = date_window(now)
    report = {'observed_at': now.isoformat(), 'read_only': connection, 'tables': tables,
              **summarize(tables, first, last),
              'provider_release_time_verified': False, 'local_sources': local_sources(),
              'diagnosis': 'Existing confirmed race tables do not yet contain future cards; special registrations are separate and cannot substitute for the final field.',
              'routes': [
                  {'path': r'C:\Users\uchih\Downloads\Realtime\Realtime\readme.txt',
                   'documented_output': 'jv/yyyyMMdd/jvd_(id)yyyyMMdd.tsv',
                   'scope': 'current-day realtime records only; not a demonstrated advance-weekend card capture',
                   'executed': False},
                  {'mechanism': 'JV-Link direct raw record acquisition to separate local files',
                   'state': 'requires verified record selection and runtime implementation; existing database must remain untouched'}],
              'database_modified': False, 'production_promotion': False}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Weekend source availability', '', f"Observed: {now.isoformat()}", '',
             f"Confirmed future runner rows: {report['confirmed_runner_rows']}",
             f"Special registrations: {report['special_registration_rows']} (not confirmed starters)", '',
             '| Table | Latest day | Rows | Races |', '|---|---|---:|---:|']
    for table, rows in tables.items():
        if rows:
            row = rows[0]
            lines.append(f"| {table} | {row['day']} | {row['rows']} | {row['races']} |")
    lines += ['', report['diagnosis'], '', 'Provider publication time is not verified. No import, database update, service operation, or promotion was performed.']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'state': report['state'], 'confirmed_runner_rows': report['confirmed_runner_rows'], 'special_registration_rows': report['special_registration_rows']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
