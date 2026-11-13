"""Explicit, additive seed for an already migrated deployment; never update existing versions."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]


def initialize(repo, args):
    sources = repo.query(
        "SELECT p.project_code,v.version_id,v.version_code FROM energy_project p "
        "JOIN energy_project_version v USING(project_id) "
        "WHERE p.project_code=%s AND v.version_code=%s AND v.lifecycle_status='published'",
        (args.source_project, args.source_version))
    if len(sources) != 1:
        raise ValueError('需要唯一的已发布重空协同来源版本；先导入来源，不使用占位基础数据替代')
    source = sources[0]
    existing = repo.query(
        "SELECT version_id FROM single_version WHERE target_module='single' "
        "AND project_code=%s AND version_code=%s", (args.source_project, args.version_code))
    if existing:
        value = repo.version(existing[0]['version_id'])
        if (value['status'] != 'published' or
                value['provenance'].get('sourceVersionId') != source['version_id']):
            raise ValueError('目标编码已有草稿或来源不一致；不覆盖，请选择新编码或在页面处理')
        return {'action': 'EXISTING_UNCHANGED', 'versionId': value['version_id'],
                'status': value['status'], 'readiness': value['readiness']}
    body = {'sourceModule': 'energy', 'sourceVersionId': source['version_id'],
            'versionCode': args.version_code, 'versionName': args.version_name}
    preview = repo.preview(body, 'single')
    if not args.apply:
        return {'action': 'PREVIEW_ONLY', 'source': preview['source'],
                'copiedFiles': preview['files'], 'willApplyDefaultTemplate': True,
                'note': '执行后生成独立单列车版本；不修改来源，不复制部门授权'}
    lock = 'single_seed_' + __import__('hashlib').sha256(
        (args.source_project + '/' + args.version_code).encode()).hexdigest()[:40]
    if repo.query('SELECT GET_LOCK(%s,0) acquired', (lock,))[0]['acquired'] != 1:
        raise ValueError('该初始化正在执行，请稍后重新预览')
    try:
        with repo.atomic():
            value = repo.derive(body, 'single')
            value = repo.defaults(value['version_id'])
            if not value['readiness']['ready']:
                raise ValueError('来源与专用模板尚不能运行：' + json.dumps(value['readiness'], ensure_ascii=False))
            value = repo.publish(value['version_id'])
        return {'action': 'CREATED', 'versionId': value['version_id'], 'status': value['status'],
                'contentSha256': value['content_sha256'], 'readiness': value['readiness'],
                'provenance': value['provenance']}
    finally:
        repo.query('SELECT RELEASE_LOCK(%s)', (lock,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='明确创建并发布新版本；默认仅预览')
    parser.add_argument('--source-project', default='shuohuang_demo')
    parser.add_argument('--source-version', default='v1')
    parser.add_argument('--version-code', default='single_demo_v1')
    parser.add_argument('--version-name', default='朔黄单列车回收测试 / 第1版')
    args = parser.parse_args()
    if not os.environ.get('ENERGY_DATABASE_URL'):
        parser.error('请由部署人员在环境中配置 ENERGY_DATABASE_URL；本脚本不读取或输出账号密码')
    sys.path.insert(0, str(ROOT))
    from single_train_recovery_agent.repository import Repository, connect_mysql
    db = connect_mysql(autocommit=True)
    try:
        result = initialize(Repository(db, user='single-train-initializer'), args)
        print(json.dumps(result, ensure_ascii=False, default=str))
    finally:
        db.close()


if __name__ == '__main__':
    main()
