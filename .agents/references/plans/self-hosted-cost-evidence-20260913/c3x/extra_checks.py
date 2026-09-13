from run import run,ROOT
import json,urllib.request,urllib.parse,hashlib
base='docker exec isaac-cost-c3x-cli /c3x estimate --path /trial/azure-fixture --pricing-endpoint http://isaac-cost-c3x-proxy:4001/graphql --no-cache --no-remote-modules --currency USD --format json --region eastus --what-if azurerm_key_vault.public_price_trial.monthly_operations=100000'
p=run(base,30);(ROOT/'actual-azure-quote-explicit-region.json').write_text(p.stdout)
url='https://prices.azure.com/api/retail/prices?'+urllib.parse.urlencode({'$filter':"serviceName eq 'Key Vault' and armRegionName eq 'eastus' and skuName eq 'Standard' and meterName eq 'Operations'"})
try:
 with urllib.request.urlopen(url,timeout=30) as r:raw=r.read();status=r.status
 (ROOT/'azure-public-raw.json').write_bytes(raw)
 (ROOT/'azure-public-provenance.json').write_text(json.dumps({'url':url,'status':status,'sha256':hashlib.sha256(raw).hexdigest(),'authentication':'none','method':'GET'},indent=2))
 print(raw.decode())
except Exception as e: print('Public raw corroboration failed:',str(e))
p=run('docker exec isaac-cost-c3x-api wget -qO- http://localhost:4000/catalog');(ROOT/'served-catalog.json').write_text(p.stdout)
run('docker stop isaac-cost-c3x-api')
p=run(base,45);(ROOT/'endpoint-unavailable-result.txt').write_text(p.stdout)
p=run('docker logs isaac-cost-c3x-proxy');(ROOT/'http-routing.jsonl').write_text(p.stdout)
run('docker start isaac-cost-c3x-api')
