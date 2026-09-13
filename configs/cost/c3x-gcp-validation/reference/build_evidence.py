#!/usr/bin/env python3
"""Create quote-checked evidence ledger; verify archive hashes and page counts."""
from pathlib import Path
import json,hashlib,gzip,subprocess
from collections import defaultdict
from fetch_docs import ROOT,S,LEDGER
sources=json.loads((ROOT/'sources.json').read_text());bykey={s['key']:s for s in sources}
# Inclusive line ranges in saved, fetched public page text, not paraphrases.
ranges={'g4_specs':[(2669,2678),(2703,2710),(2727,2746),(2751,2758)],'flex':[(1139,1153),(1177,1180)],'disk_pricing':[(270,275)],'hyperdisk':[(1645,1655)],'nat':[(5,28),(70,88)],'gcs':[(195,215),(801,813)],'registry':[(15,30)],'catalog_schema':[(486,488),(522,541)],'dws_current':[(3,12),(116,139)],'accelerator_pricing':[(10,14),(234,251),(294,306),(333,345)],'hyperdisk_balanced':[(1204,1229)],'ai_consumption':[(378,389)]}
evidence=[]
for key,rr in ranges.items():
 src=bykey[key];lines=Path(src['text_path']).read_text().splitlines();quotes=[];id=src['citation_registration'].split(']')[0][1:]
 for start,end in rr:
  text='\n'.join(lines[start-1:end]);quotes.append({'start_line':start,'end_line':end,'text':text})
  subprocess.run(['python3',S,'--ledger',str(LEDGER),'quote',id,'--text',text,'--from',src['text_path']],check=True,capture_output=True)
 evidence.append({**src,'quotes':quotes})
cat=Path('/tmp/isaac-gcp-cost-validation/catalog');manifest=json.loads((cat/'capture-summary.json').read_text());page_evidence=[];last={};counts=defaultdict(int);ids=set()
for p in manifest['pages']:
 raw=gzip.decompress((cat/p['file']).read_bytes());assert hashlib.sha256(raw).hexdigest()==p['sha256'];data=json.loads(raw)
 assert p['records']==len(data.get(p['kind'],[]));last[p['path']]=data.get('nextPageToken','');counts[p['path']]+=p['records']
 ids.update(x['skuId'] for x in data.get('skus',[]));page_evidence.append(p)
assert all(not v for v in last.values());assert len(ids)==35924
selected=json.loads((ROOT/'reference_rates.json').read_text())['selected_components'];services={v['name'].split('/')[1]:v['category']['serviceDisplayName'] for v in selected.values()}
for service,name in services.items():
 url='https://cloudbilling.googleapis.com/v1/services/'+service+'/skus'
 reg=subprocess.check_output(['python3',S,'--ledger',str(LEDGER),'add',url,'--title',name+' captured public Catalog'],text=True).strip();id=reg.split(']')[0][1:]
 ss=[v for v in selected.values() if v['name'].split('/')[1]==service];text='\n'.join(json.dumps(v['raw'],sort_keys=True) for v in ss);path=ROOT/(service+'_selected_raw.txt');path.write_text(text)
 for v in ss:subprocess.run(['python3',S,'--ledger',str(LEDGER),'quote',id,'--text',v['description'],'--from',str(path)],check=True,capture_output=True)
 evidence.append({'key':service,'url':url,'citation_registration':reg,'source':'parent archived unmodified Catalog pages, hash checked','text_path':str(path),'selected_sku_ids':[v['skuId'] for v in ss],'quotes':[{'text':v['description']} for v in ss]})
local_ranges={
 '/tmp/isaac-c3x-oauth-parent/replay/internal/scraper/gcp.go':[(248,282),(308,369),(380,448),(450,473),(525,576),(617,632)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/resources/gcp/google_compute_instance.toml':[(14,19),(35,55),(64,102)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/resources/gcp/google_compute_router_nat.toml':[(5,20)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/resources/gcp/google_storage_bucket.toml':[(5,17)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/resources/gcp/google_artifact_registry_repository.toml':[(5,21)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/internal/pricing/http.go':[(219,252),(272,312)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/internal/pricing/purchaseoption.go':[(8,18)],
 '/tmp/isaac-selfhost-trials/c3x/c3x/internal/expr/functions.go':[(68,78)],
 '/workspaces/IsaacAutomator/configs/cost/infracost-usage.example.yml':[(1,18)]}
locals=[]
for filename,rr in local_ranges.items():
 p=Path(filename);raw=p.read_bytes();lines=raw.decode().splitlines();locals.append({'path':filename,'sha256':hashlib.sha256(raw).hexdigest(),'extracts':[{'start_line':a,'end_line':b,'text':'\n'.join(lines[a-1:b])} for a,b in rr]})
out={'public_sources':evidence,'local_source_evidence':locals,'archive_verification':{'unique_skus':len(ids),'all_pages_sha256_matched':True,'all_manifest_record_counts_matched':True,'all_service_pagination_terminated':True,'counts_by_api_path':dict(counts),'pages':page_evidence},'public_regional_tables_file':'public_regional_tables.json','notes':['Default rendered region is Iowa; Oregon values were extracted from explicitly Oregon-labelled embedded JSON tables, with raw paths and rows preserved.','DWS search returned no usable text; no source explicitly equating the Catalog phrase DWS Defined Duration to Flex-start was retrieved.']}
(ROOT/'source_evidence.json').write_text(json.dumps(out,indent=2));print(json.dumps({'verified_unique_catalog_skus':len(ids),'registered_sources':[e['citation_registration'] for e in evidence],'local_evidence_files':len(locals)},indent=2))
