"""Extract source-verified report images; never synthesize or relabel an unconfirmed photo."""
from pathlib import Path
from zipfile import ZipFile
import argparse
import hashlib
import json
from lxml import etree


REVIEWED = {
    'suning': [('org_chart', 'word/media/image2.png', '图1.1- 1  肃宁分公司组织机构图')],
    'yuanping': [('org_chart', 'word/media/image3.png', '图2.1- 1  原平分公司组织机构图')],
    'jiliang': [('org_chart', 'word/media/image2.jpeg', '图1.1- 1 机辆分公司组织机构图'),
                ('office_location', 'word/media/image3.png', '图1.1-2 机辆分公司现场图')],
}


def extract(source_root, defaults):
    provenance=json.loads((defaults/'material-provenance.json').read_text(encoding='utf-8'))
    materials=json.loads((defaults/'report-defaults.json').read_text(encoding='utf-8'))
    profiles={c['company_key']:c for c in materials['companies']}
    for company in provenance['companies']:
        key=company['company_key'];source=source_root/company['source_report']
        if hashlib.sha256(source.read_bytes()).hexdigest()!=company['source_sha256']:
            raise ValueError('Reviewed source changed: '+str(source))
        with ZipFile(source) as archive:
            doc=etree.fromstring(archive.read('word/document.xml'))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            captions=[''.join(p.xpath('.//w:t/text()',namespaces=ns)) for p in doc.xpath('.//w:p',namespaces=ns)]
            for role,member,caption in REVIEWED[key]:
                if caption not in captions:raise ValueError('Reviewed caption missing: '+caption)
                content=archive.read(member);suffix=Path(member).suffix
                relative=f'images/{key}/{role}{suffix}';target=defaults/relative
                target.parent.mkdir(exist_ok=True,parents=True);target.write_bytes(content)
                entry=dict(role=role,filename=f'{role}_{company["source_report_year"]}{suffix}',
                           mime_type='image/png' if suffix=='.png' else 'image/jpeg',path=relative,
                           size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
                profiles[key]['images']=[i for i in profiles[key]['images'] if i['role']!=role]+[entry]
                company['images']=[i for i in company['images'] if i['role']!=role]+[
                    dict(role=role,document_member=member,description=caption,
                         reference_year=company['source_report_year'],
                         user_confirmed_office_location=(key=='jiliang' and role=='office_location'))]
        company['excluded']=[v for v in company['excluded'] if v!='组织机构图']
        company['not_imported_images']=[v for v in company['not_imported_images']
            if v not in ('组织机构图','现场图（无法确认机关所在地）')]
    provenance['image_review_date']='2026-10-22'
    provenance['image_review_policy']='依用户新要求补入三家历史组织图；机辆现场图经用户明确确认可作机关所在地。默认图仅供参考，保留已有人工有效图。线路图和平面图未映射到其他角色。'
    for path,data in [(defaults/'material-provenance.json',provenance),(defaults/'report-defaults.json',materials)]:
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {c['company_key']:len(c['images']) for c in materials['companies']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--defaults',type=Path,default=Path(__file__).resolve().parent.parent/'defaults')
    args=parser.parse_args();print(json.dumps(extract(args.source_root,args.defaults)))
