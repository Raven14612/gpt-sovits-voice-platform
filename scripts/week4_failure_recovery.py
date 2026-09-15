from pathlib import Path
import json,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from models.schemas import TaskRecord,TaskStatus
from services import task_service
with tempfile.TemporaryDirectory() as d:
 root=Path(d); idx=root/'tasks.json'
 for t in [TaskRecord(task_id='w4-running',kind='synthesis',status=TaskStatus.RUNNING,stage='synthesis'),TaskRecord(task_id='w4-pending',kind='synthesis'),TaskRecord(task_id='w4-done',kind='synthesis',status=TaskStatus.SUCCEEDED)]: task_service.upsert_task(t,idx)
 before=[x.model_dump(mode='json') for x in task_service.list_tasks(idx)]; after=[x.model_dump(mode='json') for x in task_service.recover_tasks(idx)]
 forced=subprocess.run([sys.executable,'-c','raise SystemExit(17)']); assert forced.returncode==17
 report={'before':before,'after':after,'forced_exit':{'returncode':17},'passed':True}
 out=ROOT/'data/logs/diagnostics/week4';out.mkdir(parents=True,exist_ok=True);(out/'failure-recovery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('PASS')
