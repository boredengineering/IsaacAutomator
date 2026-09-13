#!/usr/bin/env python3
"""Read archived Google public Catalog pages only. No network, no chosen winner.
All matching variants retain raw fields, decimal string prices, geographic tags,
all tiers/effective times and source page identity. Candidate tags are SEARCH
labels, never billing eligibility judgments. No estimate or zero substitution.
"""
import argparse, gzip, json, re, hashlib
from pathlib import Path
from decimal import Decimal
from collections import Counter

def decode(data):return json.loads(data,parse_float=Decimal)
def plain(x):
 if isinstance(x,Decimal):return str(x)
 if isinstance(x,list):return [plain(v) for v in x]
 if isinstance(x,dict):return {k:plain(v) for k,v in x.items()}
 return x

def scan_skus(node):
 if isinstance(node,dict):
  if 'skuId' in node and ('pricingInfo' in node or 'category' in node):yield node
  else:
   for v in node.values():yield from scan_skus(v)
 elif isinstance(node,list):
  for v in node:yield from scan_skus(v)

def tags(sku):
 desc=sku.get('description','');cat=sku.get('category',{});txt=desc+' '+json.dumps(cat)
 tests={'g4_rtx':r'\bg4\b|rtx|6000|blackwell','flex_dws':r'flex[ -]?start|\bdws\b|dynamic workload',
 'hyperdisk':r'hyperdisk','nat':r'\bnat\b','external_ip':r'ip.*(address|usage|charge)|external.*ip',
 'gcs':r'cloud storage|google cloud storage','registry':r'artifact registry|container registry'}
 return [name for name,pat in tests.items() if re.search(pat,txt,re.I)]

def extract(sku):
 regions=sku.get('serviceRegions',[])
 geo='exact_us-west1' if 'us-west1' in regions else ('global_candidate' if 'global' in regions else ('unresolved_geography' if not regions else 'other_regions'))
 pricing=[]
 for pi in sku.get('pricingInfo',[]):
  pe=pi.get('pricingExpression',{})
  rates=[]
  for t in pe.get('tieredRates',[]):
   money=t.get('unitPrice');value=None;status='missing_money'
   if isinstance(money,dict):
    # Protobuf JSON omits zero-valued scalars. A present Money message
    # with omitted units/nanos therefore encodes zero; absent Money does not.
    try:value=format(Decimal(str(money.get('units','0')))+Decimal(str(money.get('nanos',0)))/Decimal(1000000000),'f');status='decoded_protobuf_money'
    except Exception:status='invalid_money'
   rates.append({'startUsageAmount':plain(t.get('startUsageAmount')),'startUsageAmount_omitted_defaults_to_zero':'startUsageAmount' not in t,'decimal_unit_price':value,'price_status':status,'currencyCode':None if money is None else money.get('currencyCode'),'raw':plain(t)})
  pricing.append({'effectiveTime':pi.get('effectiveTime'),'summary':pi.get('summary'),'aggregationInfo':plain(pi.get('aggregationInfo')),'currencyConversionRate':plain(pi.get('currencyConversionRate')),'expression_metadata':plain({k:v for k,v in pe.items() if k!='tieredRates'}),'tiers':rates,'raw':plain(pi)})
 return {'skuId':sku.get('skuId'),'name':sku.get('name'),'description':sku.get('description'),'category':sku.get('category'),'serviceRegions':regions,'geoTaxonomy':sku.get('geoTaxonomy'),'geographic_candidate_class':geo,'search_tags':tags(sku),'pricing':pricing,'raw':plain(sku)}

def run(directory,output):
 files=sorted(Path(directory).glob('*.json.gz'));out={};seen=0;pages=[]
 for path in files:
  raw=gzip.decompress(path.read_bytes());data=decode(raw);skus=list(scan_skus(data));seen+=len(skus)
  pages.append({'path':str(path),'raw_sha256':hashlib.sha256(raw).hexdigest(),'sku_records':len(skus)})
  for s in skus:
   if not tags(s):continue
   e=extract(s);variant=hashlib.sha256(json.dumps(plain(s),sort_keys=True).encode()).hexdigest()
   key=(s.get('name') or s.get('skuId'),variant)
   if key not in out:out[key]={**e,'raw_variant_sha256':variant,'source_pages':[]}
   out[key]['source_pages'].append(str(path))
 entries=sorted(out.values(),key=lambda e:(e['geographic_candidate_class'],str(e['name']),e['raw_variant_sha256']))
 relevant=[e for e in entries if e['geographic_candidate_class']!='other_regions']
 summary={'input_page_count':len(files),'sku_records_seen':seen,'unique_candidate_sku_ids':len({x['skuId'] for x in entries}),'candidate_variants':len(entries),'uswest_global_unresolved_variants':len(relevant),'candidate_geography_counts':dict(Counter(e['geographic_candidate_class'] for e in entries)),'tags_all':dict(Counter(t for e in entries for t in e['search_tags'])),'pages':pages,'caveats':['Search candidates, not asserted eligible rates; no winner selected.','Other-region records retained for explicit comparison, not merged.','Global/empty region candidates require applicability check.','All service page capture completion must be checked against parent manifest.','Raw decimal-valued JSON numbers are retained as decimal strings; original bytes remain in source gzip.']}
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 for name,obj in [('catalog_candidates_all_regions.json',entries),('catalog_candidates_uswest_global.json',relevant),('catalog_extract_summary.json',summary)]: (output/name).write_text(json.dumps(obj,indent=2))
 print(json.dumps({k:v for k,v in summary.items() if k!='pages'},indent=2))
 if not files:raise SystemExit('No pages found: no rate or total is implied.')
if __name__=='__main__':
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('catalog');a.add_argument('--output',default=str(Path(__file__).resolve().parent));args=a.parse_args();run(args.catalog,args.output)
