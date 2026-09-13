from run import run,ROOT
import json,subprocess,hashlib,datetime

def output(cmd):return subprocess.check_output(cmd,shell=True,cwd=ROOT,text=True).strip()
receipt={'trial':'C3X + c3x-pricing-api','result':'SELF_HOSTED_REAL_AZURE_QUOTE_VERIFIED; G4_REJECTED','completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'workspace':str(ROOT),'sources':{},'production_patches':[],'test_harness_additions':['c3x-pricing-api/internal/scraper/trial_import_test.go: calls unchanged upstream scrapeService(Key Vault) and UpsertProducts; avoids full multi-service scrape','audit-proxy.go: transparent HTTP recorder forwarding unchanged requests to real API, no pricing logic'],'synthetic_prices_used':False,'terraform_executed':False,'cloud_provisioning':False,'existing_credentials_used':False,'initial_tool_error':'Bare python unavailable; used python3. First bind-mount build could not see files on remote daemon; switched to docker cp.'}
for name in ['c3x','c3x-pricing-api']:
 p=ROOT/name
 receipt['sources'][name]={'url':'https://github.com/c3xdev/'+name,'sha':output('git -C '+str(p)+' rev-parse HEAD'),'license':'Apache-2.0','license_sha256':hashlib.sha256((p/'LICENSE').read_bytes()).hexdigest(),'status':output('git -C '+str(p)+' status --short')}
receipt['binary_sha256']={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['c3x-cli','pricing-api']}
receipt['configuration']={'pricing_endpoint':'http://isaac-cost-c3x-api:4000/graphql','audited_endpoint':'http://isaac-cost-c3x-proxy:4001/graphql','catalog_rule':'cmd/c3x/catalog_client.go:35-42 derives /catalog from pricing endpoint ending /graphql; no second setting needed','catalog_failure_behavior':'Remote -> cached bundle -> embedded snapshot (not remote SaaS fallback)','price_chain':'No-cache HTTPSource; no --offline used; USD avoids external FX; --no-remote-modules','database':'PostgreSQL16, trust auth only on isolated internal network, tmpfs data, no published ports','public_import_url':'https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Key%20Vault%27','import_scope':'one service using production scraper via test harness; not complete cloud catalog','gcp_blocker':'GCP_API_KEY required; runtime scrape --vendor gcp exits1 without key'}
products=json.loads((ROOT/'azure-key-vault-products.json').read_text())
quote=json.loads((ROOT/'actual-azure-quote-explicit-region.json').read_text())
receipt['actual_quote']={'accepted':True,'vendor':'azure','service':'Key Vault','region':'eastus','catalog_products_imported':len(products),'monthly_operations':100000,'unit':'10K operations','unit_price_usd':quote['costs'][0]['line_items'][0]['unit_rate'],'monthly_usd':quote['project_total'],'quote_file':'actual-azure-quote-explicit-region.json','public_provenance':json.loads((ROOT/'azure-public-provenance.json').read_text()),'note':'Original Azure fixture location was not consumed as region; first run silently fell back from us-east-1 to eastus. Accepted re-run explicitly sets --region eastus.'}
orig=json.loads((ROOT/'fixture-results.json').read_text());derived=json.loads((ROOT/'derived-fixture-results.json').read_text())
assert len(orig)==len(derived)==4
for item in derived:
 d=json.loads((ROOT/item['output_file']).read_text());vm=next(c for c in d['costs'] if c['kind']=='google_compute_instance')
 item.update({'accepted':False,'project_total_reported':d['project_total'],'instance_subtotal_reported':vm['monthly_subtotal'],'line_items':vm['line_items'],'reason':'Missing GCP prices are silently zero with price_source live; only static NAT charge remains'})
receipt['fixtures']={'original_json':orig,'original_result':'all four exit1: no .tf files found','derived_hcl':derived,'derivation':'convert_and_test.py preserves JSON attributes and nested resource blocks in separate generated HCL copies; no edits to original repository fixtures'}
receipt['g4_findings']=['Machine synthesis whitelist internal/scraper/gcp.go:385-452 contains n1,n2,e2,n2d,c2,c2d,t2d,t2a; no g4','Flex scheduling ignored: audited Flex fixture queries OnDemand','RTX PRO 6000 falls through catalog GPU expression to Nvidia Tesla T4 GPU running in Americas','hyperdisk-balanced falls through catalog disk expression to Storage PD Capacity','HTTPSource silently retries missing regional prices in reference region: gcp us-central1, azure eastus, aws us-east-1','Unknown machine and missing G4 return exit0, zero VM subtotal, price_source live; FAIL-CLOSED REQUIREMENT FAILED; no accepted G4 quote']
routing=[json.loads(s) for s in (ROOT/'http-routing.jsonl').read_text().splitlines() if s.startswith('{')]
receipt['network_proof']={'docker_network_internal':True,'cli_external_dns_test':'pricing.c3x.dev bad address, exit1','cli_external_ip_test':'1.1.1.1 Network unreachable, exit1','recorded_requests':len(routing),'all_forwarded_to_local_api':all(r['forward_to']=='http://isaac-cost-c3x-api:4000' for r in routing),'catalog_get_observed':any(r['path']=='/catalog' for r in routing),'log':'http-routing.jsonl','api_unavailable_test':'Stopped actual pricing API; Azure estimate fails at local proxy502; no fallback quote','egress_only':'build dependencies and completed import container had egress; API/CLI/proxy/DB internal only'}
catalog=json.loads((ROOT/'served-catalog.json').read_text());receipt['served_catalog']={k:catalog[k] for k in ['schema_version','hash','count']}
records=[json.loads(x) for x in (ROOT/'commands.jsonl').read_text().splitlines()]
receipt['commands']=records
names=['isaac-cost-c3x-build','isaac-cost-c3x-db','isaac-cost-c3x-api','isaac-cost-c3x-import','isaac-cost-c3x-cli','isaac-cost-c3x-proxy']
receipt['runtime']=[]
for n in names:
 info=json.loads(output('docker inspect '+n))[0]
 receipt['runtime'].append({'name':n,'id':info['Id'],'image_id':info['Image'],'labels':info['Config'].get('Labels'),'cpu_limit':info['HostConfig']['NanoCpus'],'memory_limit':info['HostConfig']['Memory'],'networks':list(info['NetworkSettings']['Networks']),'mounts':info['Mounts'],'port_bindings':info['HostConfig']['PortBindings']})
receipt['cleanup']={'commands':[]}
try:
 for cmd in ['docker rm -f '+ ' '.join(names),'docker network rm isaac-cost-c3x-internal isaac-cost-c3x-import-egress','docker image rm isaac-cost-c3x-built:trial isaac-cost-c3x-go:trial isaac-cost-c3x-postgres:trial']:
  p=run(cmd,60);receipt['cleanup']['commands'].append({'command':cmd,'exit_code':p.returncode,'output':p.stdout})
 # Public base tags pulled by this trial: only remove if no other container uses their image.
 for tag in ['golang:1.26-alpine','postgres:16-alpine']:
  foreign=output('docker ps -aq --filter ancestor='+tag)
  if foreign:receipt['cleanup'].setdefault('shared_base_tags_retained',[]).append({'tag':tag,'reason':'in use by another container; preserved'})
  else:
   p=run('docker image rm '+tag,60);receipt['cleanup']['commands'].append({'command':'docker image rm '+tag,'exit_code':p.returncode,'output':p.stdout})
finally:
 remaining={}
 for kind,cmd in {'containers':'docker ps -a --format "{{.Names}}"','networks':'docker network ls --format "{{.Name}}"','volumes':'docker volume ls --format "{{.Name}}"','image_tags':'docker image ls --format "{{.Repository}}:{{.Tag}}"'}.items():
  remaining[kind]=[s for s in output(cmd).splitlines() if s.startswith('isaac-cost-c3x-')]
 receipt['cleanup']['remaining_prefixed_resources']=remaining
 receipt['cleanup']['verified_absent']=not any(remaining.values())
 receipt['commands']=[json.loads(x) for x in (ROOT/'commands.jsonl').read_text().splitlines()]
 (ROOT/'receipt.json').write_text(json.dumps(receipt,indent=2))
 print(json.dumps({'receipt':str(ROOT/'receipt.json'),'result':receipt['result'],'actual_quote':receipt['actual_quote'],'cleanup':receipt['cleanup']},indent=2))
