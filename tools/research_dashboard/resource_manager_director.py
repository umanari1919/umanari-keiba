from __future__ import annotations
import json,os,shutil
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CHECK=ROOT/'checkpoints';REPORTS=ROOT/'CORE'/'reports'
STATE=CHECK/'resource_manager_director_state.json';REPORT=REPORTS/'RESOURCE_MANAGER_report.json';CONTROL=REPORTS/'OPERATION_control.json'
for p in (CHECK,REPORTS):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def run_once():
 disk=shutil.disk_usage(ROOT);disk_free=disk.free/disk.total if disk.total else 0
 cpu=os.cpu_count() or 1;mem_total=mem_avail=None
 try:
  import psutil
  vm=psutil.virtual_memory();mem_total=int(vm.total);mem_avail=int(vm.available);mem_free=vm.available/vm.total;cpu_pct=float(psutil.cpu_percent(interval=.2))
 except Exception:
  mem_free=None;cpu_pct=None
 reasons=[];mode='TURBO'
 if disk_free<.08:reasons.append('disk_free_below_8pct');mode='PAUSE_EXPERIMENTS'
 elif disk_free<.15:reasons.append('disk_free_below_15pct');mode='THROTTLE'
 if mem_free is not None and mem_free<.08:reasons.append('memory_free_below_8pct');mode='PAUSE_EXPERIMENTS'
 elif mem_free is not None and mem_free<.15 and mode=='TURBO':reasons.append('memory_free_below_15pct');mode='THROTTLE'
 threads=cpu if mode=='TURBO' else max(1,cpu//2 if mode=='THROTTLE' else 1)
 out={'updated':now(),'status':'PASS' if mode=='TURBO' else 'WARN','mode':mode,'recommended_threads':threads,'cpu_count':cpu,'cpu_percent':cpu_pct,'memory_total':mem_total,'memory_available':mem_avail,'memory_free_rate':mem_free,'disk_total':disk.total,'disk_free':disk.free,'disk_free_rate':disk_free,'reasons':reasons}
 writej(REPORT,out);writej(CONTROL,{'updated':now(),'experiment_mode':mode,'recommended_threads':threads,'reasons':reasons});writej(STATE,{'pid':os.getpid(),'updated':now(),'status':out['status'],'mode':mode,'detail':reasons});return out
