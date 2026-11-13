"""Extract reviewed first-chapter equipment tables, keeping historical provenance."""
from pathlib import Path
import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation
from docx import Document


def extract(source_root, defaults_dir):
    provenance_path = defaults_dir / 'material-provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    materials_path = defaults_dir / 'report-defaults.json'
    materials = json.loads(materials_path.read_text(encoding='utf-8'))
    profiles = {c['company_key']: c for c in materials['companies']}
    extracted = []
    for company in provenance['companies']:
        source = source_root / company['source_report']
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != company['source_sha256']:
            raise ValueError('Source report differs from reviewed provenance: ' + str(source))
        document = Document(source)
        matches = [(n, table) for n, table in enumerate(document.tables)
                   if table.rows and '主要设备名称' in ''.join(c.text for c in table.rows[0].cells)]
        if len(matches) != 1:
            raise ValueError('Expected one equipment table: ' + str(source))
        index, table = matches[0]
        raw_rows = [[c.text.replace('\n', ' ').strip() for c in r.cells] for r in table.rows[1:]]
        rows, warnings, serials = [], [], []
        year = company['source_report_year']
        for physical_row, cells in enumerate(raw_rows, start=2):
            if len(cells) != 6 or not cells[2]:
                raise ValueError('Unexpected equipment row: ' + repr(cells))
            serial, energy, name, raw_quantity, model, original_remark = cells
            serials.append(serial)
            try:
                number = Decimal(raw_quantity)
                if not number.is_finite() or number < 0:
                    raise ValueError('Invalid equipment quantity')
                quantity = int(number) if number == int(number) else float(number)
            except InvalidOperation:
                if raw_quantity not in ('', '/', '-', '—'):
                    raise ValueError('Unrecognized quantity: ' + raw_quantity)
                quantity = None
                warnings.append({'row': physical_row, 'source_serial': serial, 'name': name, 'issue': 'quantity_missing'})
            note = f'{year}年参考'
            if quantity is None:
                note += '；数量未提供'
            remark = '；'.join(v for v in [original_remark if original_remark not in ('', '/') else '', note] if v)
            if len(remark) > 255:
                raise ValueError('Remark exceeds report equipment column')
            rows.append(dict(name=name, category='', quantity=quantity, unit='', model=model,
                             energy_type=energy, remark=remark))
        duplicated = sorted({s for s in serials if serials.count(s) > 1})
        if duplicated:
            warnings.append({'issue': 'duplicate_original_serials_preserved', 'serials': duplicated})
        profile = profiles[company['company_key']]
        profile['profile']['default_equipment_json'] = rows
        company['equipment_defaults'] = dict(table_index=index, table_label='表1.3-1', rows=len(rows),
                                             source_year=year, missing_quantity=sum(r['quantity'] is None for r in rows),
                                             duplicate_original_serials=duplicated, policy='历史设备参考清单，可编辑；缺失数量不补零，不按名称去重')
        company['excluded'] = [v.replace('员工/部门/站点/设备数量及设备型号清单', '员工/部门/站点数量') for v in company['excluded']]
        extracted.append(dict(company_key=company['company_key'], company_name=profile['company_name'],
                              source_report=company['source_report'], source_sha256=digest, source_year=year,
                              table_index=index, raw_rows=raw_rows, equipment=rows, warnings=warnings))
    provenance['equipment_review_date'] = '2026-10-22'
    provenance['policy'] = '稳定文字和图片保留原规则；依用户要求加入历史设备表作为参考默认，注明原报告年度并提示核对；不导入工作量、年度能耗或排放结果。'
    materials_path.write_text(json.dumps(materials, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return dict(schema_version=1, review_date='2026-10-22', companies=extracted)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--defaults-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'defaults')
    args = parser.parse_args()
    data = extract(args.source_root.resolve(), args.defaults_dir.resolve())
    target = Path(__file__).with_name('equipment-defaults.json')
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({c['company_key']: {'rows': len(c['equipment']), 'missing_quantity': sum(r['quantity'] is None for r in c['equipment'])}
                      for c in data['companies']}, ensure_ascii=False))
