#!/usr/bin/env python3
"""Extract region-labelled public page data without executing page JavaScript."""
import re,json
from pathlib import Path
from fetch_docs import Text
ROOT=Path(__file__).resolve().parent

def strings(node):
 if isinstance(node,str):
  p=Text();p.feed(node);yield ' '.join(''.join(p.parts).split())
 elif isinstance(node,list):
  for x in node:yield from strings(x)
 elif isinstance(node,dict):
  for x in node.values():yield from strings(x)

def tables(node,path=()):
 if isinstance(node,list):
  direct=[v for v in node if isinstance(v,str) and v in ['Oregon (us-west1)','Iowa (us-central1)']]
  if direct and len(node)<=5 and isinstance(node[0],list):
   yield {'json_path':list(path),'region_labels':direct,'raw':node,'text_cells':list(strings(node))}
  for i,v in enumerate(node):yield from tables(v,path+(i,))
 elif isinstance(node,dict):
  for k,v in node.items():yield from tables(v,path+(k,))

out=[]
for key in ['accelerator_pricing','disk_pricing','gcs','registry']:
 html=(ROOT/(key+'.html')).read_text()
 for i,s in enumerate(re.findall(r'<script[^>]*>(.*?)</script>',html,re.S)):
  if 'AF_initDataCallback' not in s or 'data:' not in s:continue
  data,end=json.JSONDecoder().raw_decode(s.split('data:',1)[1].lstrip())
  for t in tables(data):
   text=' | '.join(t['text_cells'])
   if (key=='accelerator_pricing' and 'g4-standard-48' in text) or (key=='disk_pricing' and 'Hyperdisk Balanced provisioned space' in text) or key=='gcs':
    t.update(source_key=key,script_index=i)
    out.append(t)
(ROOT/'public_regional_tables.json').write_text(json.dumps(out,indent=2))
for t in out:
 print(t['source_key'],t['region_labels'],t['json_path'])
 cells=t['text_cells']
 if t['source_key']=='accelerator_pricing':
  for machine in ['g4-standard-48','g4-standard-384']:
   for i,c in enumerate(cells):
    if c==machine:print(' | '.join(cells[max(0,i-1):i+12]))
  print('HEADERS:',cells[:25])
 elif t['source_key']=='disk_pricing':
  for i,c in enumerate(cells):
   if c.startswith('Hyperdisk Balanced provisioned'):print(cells[i:i+2])
 else:print(cells[:20])
print('region tables:',len(out))
