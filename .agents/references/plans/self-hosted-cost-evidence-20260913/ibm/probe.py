import subprocess,json,hashlib
from pathlib import Path
ROOT=Path('/tmp/isaac-selfhost-trials/ibm')
records=[]
def run(name,args,expected=0):
 p=subprocess.run(args,capture_output=True,text=True,timeout=30)
 (ROOT/(name+'.log')).write_text(p.stdout+p.stderr)
 records.append({'name':name,'argv':args,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 if expected is not None:assert p.returncode==expected,(name,p.stderr)
 return p
try:
 run('health',['docker','exec','isaac-cost-ibm-api','curl','--fail','--max-time','10','http://127.0.0.1:4000/health'])
 query={'query':'{ products(filter: {vendorName: "gcp", service: "Compute Engine", region: "us-west1"}) { sku prices { USD unit } } }'}
 p=run('empty-gcp-query',['docker','exec','isaac-cost-ibm-api','curl','--fail','--max-time','10','-H','Content-Type: application/json','--data',json.dumps(query),'http://127.0.0.1:4000/graphql'])
 data=json.loads(p.stdout);assert data=={'data':{'products':[]}},data
 run('external-egress-denied',['docker','exec','isaac-cost-ibm-api','node','-e',"require('https').get('https://pricing.api.infracost.io',()=>process.exit(5)).on('error',()=>process.exit(0)).setTimeout(4000,function(){this.destroy();process.exit(0)})"])
 internal=run('internal-network',['docker','network','inspect','isaac-cost-ibm-net','--format','{{.Internal}}']).stdout.strip();assert internal=='true'
except Exception as e:
 records.append({'probe_error':str(e)})
 raise
finally:
 (ROOT/'probes.json').write_text(json.dumps(records,indent=2))
print(json.dumps({'probes':len(records),'result':'local empty-database API works; no price quote'},indent=2))
