"""Build clearly marked synthetic acceptance artifacts with the production renderer."""
import json
import sys
import os
from pathlib import Path
from test_period_contract import fixture
from carbon_report_agent.models import ReportInput
from carbon_report_agent.pipeline import generate_report_docx, convert_report_docx_to_pdf

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
cases=[('jiliang_3months','2025-03-01','2025-05-31','机辆分公司','机辆分公司三个月测试模板'),
       ('yuanping_17months','2024-01-01','2025-05-31','原平分公司',('原平分公司Mixed能源统计测试模板ABC'*12)[:200]),
       ('suning_leapmonth','2024-02-01','2024-02-29','肃宁分公司','肃宁分公司闰年二月测试模板'),
       ('suning_year_200cjk','2025-01-01','2025-12-31','肃宁分公司',('核算模板中文长名称测试'*20)[:200])]
for name,start,end,company,template in cases:
    if len(sys.argv) > 2 and name != sys.argv[2]:
        continue
    data=fixture(start,end,template)
    data['metadata']['entity_name']=company+'渲染测试主体'
    data['entity_profile']['short_name']=company+'测试'
    data['metadata']['compiler']='合成测试编制单位'+('长名称测试单位'*10 if '17months' in name or '200cjk' in name else '')
    data['metadata']['approver']='合成测试批准';data['metadata']['reviewer']='合成测试审核'
    # Local synthetic logo, never read or export private company images.
    from PIL import Image,ImageDraw
    logo=out/'synthetic_logo.png'
    im=Image.new('RGB',(440,120),'white');ImageDraw.Draw(im).text((20,30),'CARBON RENDER TEST',fill='black');im.save(logo)
    os.environ['CARBON_REPORT_JOB_ASSETS_DIR']=str(out.resolve())
    data['images']=[dict(role='cover_logo',url='/job-assets/synthetic_logo.png',caption='合成测试Logo')]
    if 'leapmonth' in name:
        data['prior_year']=dict(report_year=2023,report_month=2,period_start='2023-02-01',period_end='2023-02-28',source_label='手工填报测试',total_emissions_tco2=50)
        data['prior_month']=dict(report_year=2024,report_month=1,period_start='2024-01-01',period_end='2024-01-31',source_label='手工填报测试',total_emissions_tco2=60)
    report=ReportInput.model_validate(data)
    (out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    path=generate_report_docx(report,out/(name+'.docx'),llm_enabled=False)
    convert_report_docx_to_pdf(path,out/(name+'.pdf'))
    print(name, 'Word and PDF generated', flush=True)
