#!/usr/bin/env python3
"""Inventory failed pointers, exact targets and statically recoverable original collection xrefs.

Set XNU_PRELINK_KIT to the pinned kit checkout. All addresses are original
except the explicit output field. Does not emit or modify a kernel image.
ADR(P) xrefs are conservative straight-line evidence; dynamic/aliased accesses
are not claimed complete. Direct B/BL callers of exact authenticated veneers
are collected across all backed executable segments.
"""
import sys,json,bisect,hashlib
from pathlib import Path
# Import the pinned prelink reader without requiring a Python package install.
import os
sys.path.insert(0,os.environ['XNU_PRELINK_KIT'])
from kc_image import Image,scan
from collections import defaultdict
import argparse
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--original',type=Path,required=True)
p.add_argument('--report',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--symbols',type=Path,default=Path(__file__).with_name('m4-prelink-symbols.json'))
options=p.parse_args()
raw=options.original.read_bytes();root=Image(raw);kernel=Image(raw,root.entries['com.apple.kernel'][1]);fixups=root.fixups();rep=json.loads(options.report.read_text())
assert hashlib.sha256(raw).hexdigest()==rep['inputs']['kernelcache_sha256']
slide=int(rep['collection_slide'],0)
reviewed=json.loads(options.symbols.read_text())
identities={row['original']: row for kind in ('functions','data') for row in reviewed[kind]}
targets=defaultdict(dict)
for owner,rows in rep['missing'].items():
 for address,count in rows.items():targets[int(address,16)-slide][owner]=count
members={name:Image(raw,offset) for name,(_,offset) in root.entries.items()}
execs=[];ranges=[]
for name,img in members.items():
 for s in img.segments:
  if s['name']!='__LINKEDIT' and s['size']:ranges.append((s['va'],s['va']+s['size'],name,img))
  if s['name'] in ('__TEXT_EXEC','__TEXT_BOOT_EXEC','__KLD','__LAST') and s['filesize']:execs.append((name,img,s))
def ownerof(a):return next(((name,img) for b,e,name,img in ranges if b<=a<e),('?',root))
refs=defaultdict(list);calls=defaultdict(list)
for name,img,s in execs:
 cc,rr,_=scan(img.read(s['va'],s['filesize']),s['va'])
 for site,target,kind in rr:refs[target].append(dict(module=name,pc=hex(site),kind=kind))
 for site,target,link in cc:calls[target].append(dict(module=name,pc=hex(site),kind='bl' if link else 'b'))
records=[];starts=kernel.function_starts()
for a,owners in sorted(targets.items()):
 section=kernel.section(a);code=section['segment']=='__TEXT_EXEC';sites=[]
 for site,fix in fixups.items():
  if fix[0]!=a:continue
  name,img=ownerof(site);ss=img.section(site)
  sites.append(dict(module=name,site=hex(site),section=(ss['segment']+','+ss['name']) if ss else None,selected_unresolved=name in owners,chain_fields=list(fix[1:]),code_xrefs=refs.get(site,[])))
 for name,count in owners.items():assert sum(s['module']==name for s in sites)==count,(hex(a),name)
 for site_record in sites:
  for x in site_record['code_xrefs']:
   if x['kind'] != 'add': continue
   pc=int(x['pc'],16); im=members[x['module']]
   # Exact authenticated import veneer: ADRP x17; ADD x17; LDR x16,[x17]; BRAA x16,x17.
   import struct
   w=struct.unpack('<4I',im.read(pc-4,16))
   if w[0]&0x9f00001f==0x90000011 and w[1]&0xffc003ff==0x91000231 and w[2:]==(0xf9400230,0xd71f0a11):
    x['authenticated_stub']=hex(pc-4)
    x['direct_callers']=calls.get(pc-4,[])
 record=dict(original=hex(a),output=hex(a+slide),type='function' if code else 'data',section=section,unresolved_owners=owners,pointer_xrefs=sites,direct_calls=calls.get(a,[]),direct_address_xrefs=refs.get(a,[]))
 if code:
  idx=bisect.bisect_right(starts,a)-1;assert starts[idx]==a
  end=starts[idx+1];body=kernel.read(a,end-a)
  record.update(size=end-a,sha256=hashlib.sha256(body).hexdigest(),words=[body[i:i+4].hex() for i in range(0,len(body),4)])
 record['reviewed_identity']=identities.get(hex(a))
 records.append(record)
options.output.write_text(json.dumps(dict(kernelcache_sha256=hashlib.sha256(raw).hexdigest(),failure_report_sha256=hashlib.sha256(options.report.read_bytes()).hexdigest(),reference_count=sum(sum(v.values()) for v in rep['missing'].values()),unique_targets=len(records),targets=records),indent=2))
for r in records:print(r['original'],r['type'],r.get('size'),r['unresolved_owners'],[(x['module'].split('.')[-1],x['site'],x['section'],len(x['code_xrefs'])) for x in r['pointer_xrefs'] if x['selected_unresolved']])
