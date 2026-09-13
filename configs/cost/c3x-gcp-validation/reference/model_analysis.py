#!/usr/bin/env python3
"""Curated accounting reconciliation from actual archive; no heuristic winners."""
from pathlib import Path
from decimal import Decimal as D
import json
ROOT=Path(__file__).resolve().parent
allrows=json.loads((ROOT/'catalog_candidates_uswest_global.json').read_text())
IDS={
 'standard_core':'A36E-7315-8862','standard_ram':'C566-5B7E-28AA','standard_gpu':'73C5-0031-0BF3',
 'dws_defined_duration_core':'3B6F-2FBA-B0C5','dws_defined_duration_ram':'4742-1C3C-6E23','dws_defined_duration_gpu':'1DE7-2C1A-CBEB',
 'hyperdisk_capacity':'E917-4171-722C','hyperdisk_iops':'56CC-5367-43E6','hyperdisk_throughput':'6E3F-6819-5B7A',
 'public_nat_vm_uptime':'32E2-4EFC-EF9F','public_nat_processed':'015F-5732-FFF0','public_nat_ip':'8515-9425-D2CE',
 'gcs_standard_regional':'E5F0-6A5D-7BAD','gcs_regional_class_a':'4DBF-185F-A415','gcs_regional_class_b':'7870-010B-2763',
 'artifact_registry_storage':'8502-299A-ABAF','g4_local_ssd':'FC94-13C6-4468'}
selected={}
for key,id in IDS.items():
 matches=[x for x in allrows if x['skuId']==id]
 assert len(matches)==1,(key,len(matches))
 x=matches[0]
 assert len(x['pricing'])==1,(key,'multiple effective prices: explicit selection needed')
 assert all(t['currencyCode']=='USD' and t['decimal_unit_price'] is not None for t in x['pricing'][0]['tiers'])
 selected[key]=x

def rate(key):
 p=selected[key]['pricing'][0];assert len(p['tiers'])==1
 assert D(str(p['tiers'][0]['startUsageAmount']))==0
 return D(p['tiers'][0]['decimal_unit_price'])
def money(x):return format(x,'f')
def tiercost(key,q):
 ts=selected[key]['pricing'][0]['tiers'];total=D(0);q=D(str(q))
 for i,t in enumerate(ts):
  start=D(str(t['startUsageAmount']));end=D(str(ts[i+1]['startUsageAmount'])) if i+1<len(ts) else q
  total+=max(D(0),min(q,end)-start)*D(t['decimal_unit_price'])
 return total

compute=[]
for model,prefix in [('STANDARD','standard'),('DWS_DEFINED_DURATION_CANDIDATE','dws_defined_duration')]:
 for shape,cpu,ram,gpu in [('g4-standard-48',48,180,1),('g4-standard-384',384,1440,8)]:
  components=[{'resource':k,'quantity_per_vm_hour':q,'skuId':IDS[prefix+'_'+k],'price':money(rate(prefix+'_'+k)),'extended_hourly':money(D(q)*rate(prefix+'_'+k))} for k,q in [('core',cpu),('ram',ram),('gpu',gpu)]]
  total=sum((D(c['extended_hourly']) for c in components),D(0))
  web=D('4.49993' if cpu==48 else '35.99944') if model=='STANDARD' else D('2.25' if cpu==48 else '18')
  compute.append({'machine_type':shape,'region':'us-west1','model':model,'components':components,'catalog_component_sum_hourly':money(total),'catalog_component_sum_730h':money(total*730),'official_web_machine_price_hourly':money(web),'official_web_machine_price_730h':money(web*730),'catalog_minus_public_web_hourly':money(total-web),'assessment':'standard decomposition matches public machine price exactly' if model=='STANDARD' else 'Flex-start public page independently establishes displayed rate. DWS Defined Duration SKU alias is not explicitly defined in retrieved docs; close numeric match is corroboration, not identity proof.'})
anc={
 'hyperdisk_capacity_255GiB_one_catalog_month':money(255*rate('hyperdisk_capacity')),
 'hyperdisk_formula':'255*capacity_rate + max(provisioned_iops-3000,0)*iops_rate + max(provisioned_MiBps-140,0)*throughput_rate per catalog month; prorate by retention',
 'hyperdisk_defaults_formula_only':{'iops':money(D(6)*255+3000),'throughput_MiBps_before_integer_rounding':money(min(D(2400),D('1.5')*255+140)),'excess_iops_cost_one_month':money(D(6)*255*rate('hyperdisk_iops')),'excess_throughput_formula_cost_one_month':money(D('1.5')*255*rate('hyperdisk_throughput')),'total_formula_one_month_not_actual_disk':money(255*rate('hyperdisk_capacity')+D(6)*255*rate('hyperdisk_iops')+D('1.5')*255*rate('hyperdisk_throughput')),'caveat':'Fixture omits provisioned performance. Published defaults exceed included baseline. API/provider boot-disk semantics and integer throughput rounding unverified; do not assert baseline-only disk cost or realized total.'},
 'nat_one_assigned_VM_730h':money(730*rate('public_nat_vm_uptime')),
 'nat_100GiB_processed':money(100*rate('public_nat_processed')),
 'nat_one_external_ip_730h_conditional':money(730*rate('public_nat_ip')),
 'nat_subtotal_if_one_ip_730h_and_100GiB_not_including_egress':money(730*rate('public_nat_vm_uptime')+100*rate('public_nat_processed')+730*rate('public_nat_ip')),
 'gcs_1GiBmo_100A_100B_if_free_tier_unconsumed':money(tiercost('gcs_standard_regional',1)+tiercost('gcs_regional_class_a',100)+tiercost('gcs_regional_class_b',100)),
 'gcs_1GiBmo_100A_100B_if_free_tier_exhausted':money(D('0.02')+100*D('0.000005')+100*D('0.0000004')),
 'artifact_10GiBmo_if_account_allowance_unconsumed':money(tiercost('artifact_registry_storage',10)),
 'artifact_10GiBmo_if_account_allowance_exhausted':money(D(10)*D('0.1')),
 'month_unit_warning':{'catalog_month_seconds':selected['hyperdisk_iops']['pricing'][0]['expression_metadata']['baseUnitConversionFactor'],'catalog_month_hours':money(D(str(selected['hyperdisk_iops']['pricing'][0]['expression_metadata']['baseUnitConversionFactor']))/3600),'public_page_monthly_hourly_toggle_uses_730':True,'do_not_mix':'730 compute hours and one storage billing month are independent assumptions; use Catalog baseUnitConversionFactor for explicitly elapsed seconds; public UI hourly display rounds and uses a different monthly presentation.'}}
fixtures=[]
for p in sorted(Path('/workspaces/IsaacAutomator/configs/cost/fixtures').glob('*/main.tf.json')):
 d=json.loads(p.read_text());v=d['resource']['google_compute_instance']['workstation'];fixtures.append({'path':str(p),'machine_type':v['machine_type'],'scheduling':v['scheduling'],'boot_disk':v['boot_disk'],'gpu':v['guest_accelerator']})
assert len(fixtures)==4
out={'source':'Actual archived Google Catalog pages; 17 explicitly named SKU IDs reviewed, no collision winner','selected_components':selected,'compute_reference':compute,'ancillary_reference':anc,'fixtures':fixtures,'not_an_infrastructure_total':True}
(ROOT/'reference_rates.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'compute_reference':compute,'ancillary_reference':anc,'selected_sku_count':len(selected),'fixture_count':len(fixtures)},indent=2))
