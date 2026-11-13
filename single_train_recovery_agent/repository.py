"""Department-scoped version and run persistence, without changing source versions."""
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4, UUID
import hashlib
import json
import tempfile

import pymysql
from database.mysql import SimulationRepository, connect_mysql
from database.file_names import records_to_algorithm_names
from database.snapshots import collect_file_records, materialize_file_records
from .core import *

class Repository:
    def __init__(self, connection, dept=None, user='system'):
        self.db=connection;self.dept=dept;self.user=user;self.in_transaction=False

    @contextmanager
    def atomic(self):
        self.db.begin();self.in_transaction=True
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback();raise
        finally:self.in_transaction=False

    def query(self, sql, args=()):
        with self.db.cursor(pymysql.cursors.DictCursor) as c:
            c.execute(sql,args or None);return c.fetchall()

    def write(self, sql, args=()):
        with self.db.cursor() as c:
            c.execute(sql,args or None);count=c.rowcount
        if not self.in_transaction:self.db.commit()
        return count

    def guard(self, module, project):
        if module not in ('energy','single'): raise ValueError('未知来源模块')
        if self.dept is None:return
        table='energy_dept_project' if module=='energy' else 'single_dept_project'
        if not self.query(f'SELECT 1 FROM {table} WHERE dept_id=%s AND project_code=%s AND enabled=1',(self.dept,project)):
            raise PermissionError('当前部门无权访问该项目')

    def list_versions(self, target='single'):
        if target not in ('single','energy'):raise ValueError('未知模块')
        where='target_module=%s';args=[target]
        if self.dept is not None:
            table='single_dept_project' if target=='single' else 'energy_dept_project'
            where+=f' AND project_code IN (SELECT project_code FROM {table} WHERE dept_id=%s AND enabled=1)';args.append(self.dept)
        rows=self.query('SELECT * FROM single_version WHERE '+where+' ORDER BY created_at DESC',args)
        return [self.version_view(row, detail=False) for row in rows]

    def version_view(self, row, detail=True):
        snapshot={'files':json.loads(row['files_json']),'parameters':json.loads(row['parameters_json'])}
        result={k:v for k,v in row.items() if not k.endswith('_json')}
        result['provenance']=json.loads(row['provenance_json']);result['readiness']=readiness(snapshot,row['target_module'])
        result['fileNames']=sorted(snapshot['files'])
        if detail:
            result.update(snapshot)
            if row['target_module']=='single':result['parameterMetadata']=parameter_metadata(snapshot['parameters'])
        return result

    def version(self, id):
        rows=self.query('SELECT * FROM single_version WHERE version_id=%s',(str(id),))
        if not rows:raise ValueError('数据版本不存在')
        row=rows[0];self.guard(row['target_module'],row['project_code'])
        return self.version_view(row)

    def sources(self, target='single'):
        out=[]
        if target not in ('single','energy'):raise ValueError('未知模块')
        sql="SELECT p.project_code,p.project_name,p.route_name,v.version_id,v.version_code,v.version_name,v.data_status,v.content_sha256 FROM energy_project p JOIN energy_project_version v ON p.project_id=v.project_id WHERE v.lifecycle_status='published'"
        args=[]
        if self.dept is not None:
            sql+=' AND p.project_code IN (SELECT project_code FROM energy_dept_project WHERE dept_id=%s AND enabled=1)';args.append(self.dept)
        for row in self.query(sql+' ORDER BY v.published_at',args):
            try:self.guard(target,row['project_code'])
            except PermissionError:continue
            out.append(dict(row,module='energy'))
        for row in self.list_versions('single'):
            if row['status']!='published':continue
            try:self.guard(target,row['project_code'])
            except PermissionError:continue
            out.append({k:row[k] for k in ('project_code','route_name','version_id','version_code','version_name','data_status','content_sha256')}|{'module':'single','project_name':row['project_code']})
        return out

    def source(self, module, version_id):
        if module=='single':
            v=self.version(version_id)
            if v['target_module']!='single' or v['status']!='published':raise ValueError('来源须为已发布单列车版本')
            return v,decode_files(v['files'])
        if module!='energy':raise ValueError('未知来源模块')
        rows=self.query("SELECT p.project_code,p.route_name,v.* FROM energy_project p JOIN energy_project_version v ON p.project_id=v.project_id WHERE v.version_id=%s AND v.lifecycle_status='published'",(version_id,))
        if not rows:raise ValueError('来源版本不存在')
        v=rows[0];self.guard('energy',v['project_code'])
        records=records_to_algorithm_names(SimulationRepository(self.db).load_version_files(UUID(version_id)))
        for record in records:
            if hashlib.sha256(record.content).hexdigest()!=record.content_sha256:raise ValueError('来源文件校验失败')
        return v,{r.relative_path:r.content for r in records}

    def preview(self, body, target):
        v,files=self.source(body['sourceModule'],body['sourceVersionId']);self.guard(target,v['project_code'])
        facts=compatible_facts(files)
        snapshot={'files':encode_files(facts),'parameters':{}}
        return {'source':{k:v.get(k) for k in ('project_code','route_name','version_id','version_code','content_sha256','data_status')},
            'files':[{'name':k,'size':len(x),'sha256':hashlib.sha256(x).hexdigest()} for k,x in facts.items()],
            'readiness':readiness(snapshot,target),'factsSha256':digest(snapshot['files'])}

    def derive(self, body, target):
        v,files=self.source(body['sourceModule'],body['sourceVersionId'])
        self.guard(target,v['project_code'])
        facts=compatible_facts(files);snapshot={'files':encode_files(facts),'parameters':{}}
        code=str(body.get('versionCode','')).strip();name=str(body.get('versionName',code)).strip()
        if not code or len(code)>100 or not name or len(name)>200:raise ValueError('请填写有效的新版本编码和名称')
        provenance={'sourceModule':body['sourceModule'],'sourceVersionId':body['sourceVersionId'],
            'sourceVersionCode':v['version_code'],'sourceSnapshotSha256':v['content_sha256'],
            'factsSha256':digest(snapshot['files']),'sourceFilesSha256':digest(encode_files(files)),
            'copiedFiles':sorted(facts),'sourceDataStatus':v['data_status'],
            'conversion':'mass_tons→mass_kg ×1000；length_km→length_m ×1000；共享列车阻力与牵引制动上限冻结供节能驾驶使用，电气参数独立填写'}
        id=str(uuid4())
        try:
            self.write('INSERT INTO single_version(version_id,target_module,project_code,version_code,version_name,route_name,data_status,files_json,parameters_json,provenance_json,content_sha256,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (id,target,v['project_code'],code,name,v['route_name'],'derived',dumps(snapshot['files']),dumps({}),dumps(provenance),digest(snapshot),self.user))
        except pymysql.err.IntegrityError:raise ValueError('新版本编码已存在，请换一个编码')
        return self.version(id)

    def save(self, id, body):
        v=self.version(id)
        if v['status']!='draft':raise ValueError('已发布版本不可修改，请创建新版本')
        files=body.get('files',v['files']);params=body.get('parameters',v['parameters'])
        if not isinstance(files,dict) or not isinstance(params,dict):raise ValueError('数据格式不正确')
        for name in files:validate_name(name)
        decoded=decode_files(files)
        if sum(len(x) for x in decoded.values())>64*1024*1024:raise ValueError('版本文件大小超过 64MB')
        if set(params)-set(PARAMETERS):raise ValueError('未知参数主题')
        snapshot={'files':files,'parameters':params}
        if self.write("UPDATE single_version SET files_json=%s,parameters_json=%s,content_sha256=%s WHERE version_id=%s AND status='draft'",(dumps(files),dumps(params),digest(snapshot),id))!=1:raise ValueError('版本状态已变化')
        return self.version(id)

    def defaults(self, id):
        v=self.version(id)
        if v['target_module']!='single':raise ValueError('重空协同专用数据需自行补充，不能套用单列车模板')
        files=default_rolling_stock(decode_files(v['files']))
        for name,content in default_auxiliary_files().items():files.setdefault(name,content)
        result=self.save(id,{'files':encode_files(files),'parameters':default_parameters(files)})
        p=result['provenance'];p['defaultTemplate']='2026-11-08算法默认参数；缺失机车编组及曲线按模板补齐，质量和功率镜像从本版本编组派生；占位和假设状态保留'
        self.write('UPDATE single_version SET provenance_json=%s WHERE version_id=%s',(dumps(p),id));return self.version(id)

    def upload(self, id, paths):
        v=self.version(id);files=decode_files(v['files']);parameters=v['parameters']
        from database.user_excel import convert_excel_files
        excel=[Path(p) for p in paths if Path(p).suffix.lower()=='.xlsx']
        if excel:files.update(convert_excel_files(excel,files))
        for raw in paths:
            p=Path(raw)
            if p.suffix.lower()=='.xlsx':continue
            key=p.name
            if key.endswith('_parameters.json') and key[:-16] in PARAMETERS:
                parameters[key[:-16]]=json.loads(p.read_text(encoding='utf-8-sig'))
            else:
                # Java preserves original relative paths in the request mapping.
                raise ValueError('CSV/JSON 上传需提供文件名称映射')
        return self.save(id,{'files':encode_files(files),'parameters':parameters})

    def publish(self,id):
        lock='single_publish_'+str(id)
        if self.query('SELECT GET_LOCK(%s,0) acquired',(lock,))[0]['acquired']!=1:raise ValueError('此版本正在发布，请稍后刷新')
        try:return self._publish_version(id)
        finally:self.query('SELECT RELEASE_LOCK(%s)',(lock,))

    def _publish_version(self,id):
        v=self.version(id)
        if v['status']=='published':return v
        report=v['readiness']
        if not report['ready']:raise ValueError('数据尚未就绪：'+dumps(report))
        if v['status']!='publishing' and self.write("UPDATE single_version SET status='publishing' WHERE version_id=%s AND status='draft' AND content_sha256=%s",(id,v['content_sha256']))!=1:
            raise ValueError('草稿正在发布或已变化，请重新读取')
        try:
            self._publish_locked(v)
        except Exception:
            self.write("UPDATE single_version SET status='draft' WHERE version_id=%s AND status='publishing'",(id,))
            raise
        self.write("UPDATE single_version SET status='published' WHERE version_id=%s AND status='publishing'",(id,))
        return self.version(id)

    def _publish_locked(self,v):
        if v['target_module']=='energy':
            # Fail before insertion when heavy-private data or projection is incompatible.
            with tempfile.TemporaryDirectory(prefix='single_to_energy_') as t:
                root=Path(t)
                for name,content in decode_files(v['files']).items():
                    p=root/validate_name(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
                provenance=root/'platform/basic_data_provenance.json';provenance.parent.mkdir(exist_ok=True);provenance.write_text(dumps(v['provenance']),encoding='utf-8')
                projects=self.query('SELECT project_name,route_name FROM energy_project WHERE project_code=%s',(v['project_code'],))
                if not projects:raise ValueError('目标重空协同项目不存在，请先建立项目绑定')
                was_autocommit=self.db.get_autocommit();self.db.autocommit(False)
                try:
                    SimulationRepository(self.db).import_dataset(root,project_code=v['project_code'],project_name=projects[0]['project_name'],route_name=projects[0]['route_name'],version_code=v['version_code'],data_status='planning_placeholder',source_note='来自单列车基础事实快照；本模块专用数据已另行补充')
                finally:self.db.autocommit(was_autocommit)

    def preset(self,id):
        v=self.version(id)
        if v['target_module']!='single':raise ValueError('请选择单列车数据版本')
        if not v['readiness']['ready']:return {'readiness':v['readiness'],'scenarios':[]}
        t,bundle,scenarios=scenarios_for(v,{})
        try:
            from .eco import preset
            try:eco={'ready':True,**preset(v)}
            except ValueError as ex:eco={'ready':False,'message':str(ex)}
            return {'readiness':v['readiness'],'scenarios':[{'key':s.label,'name':s.description,'family':s.family,'variant':s.variant,**scenario_speed_bounds(bundle,s)} for s in scenarios],
                'ecoDriving':eco,'socInitial':bundle.storage_params.soc_initial,'socMin':bundle.storage_params.soc_min,'socMax':bundle.storage_params.soc_max,'disclaimer':DISCLAIMER}
        finally:t.cleanup()

    def create_run(self,body):
        v=self.version(body['versionId'])
        if v['target_module']!='single' or v['status']!='published' or not v['readiness']['ready']:raise ValueError('请选择已发布且就绪的单列车版本')
        kind=body['runType'];params=body.get('parameters',{});validate_operator_parameters(params,kind)
        key=str(body.get('idempotencyKey','')).strip()
        if not key or len(key)>100:raise ValueError('需要有效幂等键')
        request=digest({'versionId':v['version_id'],'runType':kind,'parameters':params,'dept':self.dept})
        rows=self.query('SELECT run_id,request_sha256 FROM single_run WHERE requested_by=%s AND idempotency_key=%s',(self.user,key))
        if rows:
            if rows[0]['request_sha256']!=request:raise ValueError('重复提交键对应的请求内容不同')
            return self.run(rows[0]['run_id'])
        if self.query("SELECT COUNT(*) n FROM single_run WHERE status='queued'")[0]['n']>=32:raise ValueError('任务队列已满，请稍后重试')
        if kind=='eco_driving':
            from .eco import inputs
            with inputs(v,params):pass
            count=2
        else:
            t,b,scenarios=scenarios_for(v,params)
            try:
                if any(len(s.series)>2_000_000 for s in scenarios):raise ValueError('案例超过两百万步上限，请缩短业务工况')
            finally:t.cleanup()
            count=len(scenarios)*(1 if kind=='simulation' else 9)
        id=str(uuid4());snapshot={k:v[k] for k in ('files','parameters','provenance','content_sha256','version_name')}
        try:
            self.write('INSERT INTO single_run(run_id,version_id,project_code,dept_id,requested_by,run_type,status,idempotency_key,request_sha256,snapshot_json,parameters_json,code_sha256,total_cases) VALUES(%s,%s,%s,%s,%s,%s,\'queued\',%s,%s,%s,%s,%s,%s)',
                (id,v['version_id'],v['project_code'],self.dept,self.user,kind,key,request,dumps(snapshot),dumps(params),code_digest(),count))
        except pymysql.err.IntegrityError:
            existing=self.query('SELECT run_id,request_sha256 FROM single_run WHERE requested_by=%s AND idempotency_key=%s',(self.user,key))
            if not existing or existing[0]['request_sha256']!=request:raise ValueError('重复提交键对应的请求内容不同')
            return self.run(existing[0]['run_id'])
        return self.run(id)

    def runs(self):
        sql='SELECT run_id FROM single_run';args=[]
        if self.dept is not None:sql+=' WHERE dept_id=%s';args=[self.dept]
        return [self.run(r['run_id'],False) for r in self.query(sql+' ORDER BY created_at DESC LIMIT 100',args)]

    def run(self,id,detail=True):
        rows=self.query("SELECT r.*, (SELECT COUNT(*) FROM single_case c WHERE c.run_id=r.run_id AND c.status IN ('completed','failed')) actual_completed_cases FROM single_run r WHERE r.run_id=%s",(str(id),))
        if not rows:raise ValueError('任务不存在')
        r=rows[0]
        r['completed_cases']=r.pop('actual_completed_cases')
        if self.dept is not None and r['dept_id']!=self.dept:raise PermissionError('当前部门无权访问该任务')
        self.guard('single',r['project_code'])
        r['parameters']=json.loads(r.pop('parameters_json'));snap=json.loads(r.pop('snapshot_json'))
        r['versionName']=snap['version_name'];r['snapshotSha256']=snap['content_sha256'];r['provenance']=snap['provenance'];r['disclaimer']=DISCLAIMER
        if detail:
            r['cases']=self.query('SELECT * FROM single_case WHERE run_id=%s ORDER BY scenario_key,controller_key',(id,))
            for c in r['cases']:c['metrics']=json.loads(c.pop('metrics_json'));c['audit']=json.loads(c.pop('audit_json'))
            from regenerative_braking.io.output_presentation import field_glossary
            keys={key for case in r['cases'] for key in case['metrics']}
            r['metricFields']={key:field_glossary(key) for key in sorted(keys)}
            if r['run_type']=='eco_driving':
                from .eco import FIELDS
                r['metricFields'].update({key:FIELDS[key] for key in keys if key in FIELDS})
            r['artifacts']=self.query('SELECT * FROM single_artifact WHERE run_id=%s ORDER BY relative_path',(id,))
        return r

    def cancel(self,id):
        self.run(id)
        self.write("UPDATE single_run SET cancel_requested=1,status=IF(status='queued','cancelled',status),finished_at=IF(status='queued',UTC_TIMESTAMP(6),finished_at) WHERE run_id=%s AND status IN ('queued','running')",(id,))
        return self.run(id)

    def artifact(self,id):
        rows=self.query('SELECT * FROM single_artifact WHERE artifact_id=%s',(id,))
        if not rows:raise ValueError('文件不存在')
        a=rows[0];self.run(a['run_id']);return a
