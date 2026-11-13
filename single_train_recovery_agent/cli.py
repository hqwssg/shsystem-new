"""Private JSON CLI called by the authenticated Java API."""
from pathlib import Path
import argparse
import json
import sys
from .core import dumps, encode_files, decode_files, PARAMETERS
from .repository import Repository, connect_mysql
from .worker import work, artifact_path, trace_preview

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action');parser.add_argument('--input-file');parser.add_argument('--dept',type=int);parser.add_argument('--user',default='system');parser.add_argument('--target',default='single',choices=('single','energy'))
    args=parser.parse_args();body=json.loads(Path(args.input_file).read_text(encoding='utf-8-sig')) if args.input_file else {}
    db=connect_mysql(autocommit=True);repo=Repository(db,args.dept,args.user)
    try:
        action=args.action
        if action in ('version','save','defaults','publish','upload'):
            if repo.version(body['id'])['target_module']!=args.target:
                raise PermissionError('接口所属模块与版本不匹配')
        if action=='sources':out=repo.sources(args.target)
        elif action=='preview':out=repo.preview(body,args.target)
        elif action=='derive':out=repo.derive(body,args.target)
        elif action=='versions':out=repo.list_versions(args.target)
        elif action=='version':out=repo.version(body['id'])
        elif action=='save':out=repo.save(body['id'],body)
        elif action=='defaults':out=repo.defaults(body['id'])
        elif action=='publish':out=repo.publish(body['id'])
        elif action=='preset':out=repo.preset(body['id'])
        elif action=='create-run':out=repo.create_run(body)
        elif action=='runs':out=repo.runs()
        elif action=='run':out=repo.run(body['id'])
        elif action=='cancel':out=repo.cancel(body['id'])
        elif action=='trace':out=trace_preview(repo,body['id'])
        elif action=='artifact':
            a=repo.artifact(body['id']);out={**a,'localPath':str(artifact_path(a))}
        elif action=='work':out=work(db)
        elif action=='upload':
            v=repo.version(body['id']);files=decode_files(v['files']);params=v['parameters']
            from database.user_excel import convert_excel_files
            excels=[Path(x['localPath']) for x in body['uploads'] if x['name'].lower().endswith('.xlsx')]
            if excels:files.update(convert_excel_files(excels,files))
            for item in body['uploads']:
                name=item['name'].replace('\\','/');path=Path(item['localPath'])
                if name.lower().endswith('.xlsx'):continue
                key=Path(name).name.removesuffix('_parameters.json')
                if name.endswith('_parameters.json') and key in PARAMETERS:params[key]=json.loads(path.read_text(encoding='utf-8-sig'))
                else:files[name]=path.read_bytes()
            out=repo.save(body['id'],{'files':encode_files(files),'parameters':params})
        else:raise ValueError('未知操作')
        # MySQL datetime values are formatted without exposing connection settings.
        print(json.dumps(out,ensure_ascii=False,allow_nan=False,default=lambda x:x.isoformat() if hasattr(x,'isoformat') else str(x)))
    finally:db.close()

if __name__=='__main__':
    try:main()
    except Exception as ex:
        print(str(ex),file=sys.stderr);sys.exit(1)
