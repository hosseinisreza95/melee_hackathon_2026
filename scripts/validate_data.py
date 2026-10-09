#!/usr/bin/env python3
from pathlib import Path
import csv,re,sys
from datetime import datetime
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
REQ={'data/products.csv':['product_id','commercial_name','is_synthetic','validation_status'],'data/product_aliases.csv':['alias_id','product_id','alias_name','relationship_type','review_status','is_synthetic'],'data/registrations.csv':['registration_id','product_id','country_code','source_id','source_record_url','collected_at','validation_status','is_synthetic'],'data/uses.csv':['use_id','registration_id','validation_status','is_synthetic'],'data/source_registry.csv':['source_id','official_name','country_or_region','base_url','access_method','manual_validation_required']}
errors=[]
def rows(name):
    with (ROOT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
for name,cols in REQ.items():
    rs=rows(name); present=set(rs[0]) if rs else set()
    for col in cols:
        if col not in present: errors.append(f'{name}: missing {col}')
    for n,r in enumerate(rs,2):
        for col in cols:
            if col!='base_url' and not r.get(col,'').strip(): errors.append(f'{name}:{n}: empty {col}')
        if r.get('country_code') and not re.fullmatch(r'[A-Z]{2}',r['country_code']):errors.append(f'{name}:{n}: country_code')
        for k in ('source_record_url','base_url'):
            if r.get(k) and urlparse(r[k]).scheme not in ('http','https'):errors.append(f'{name}:{n}: URL {k}')
        if r.get('collected_at'):
            try:datetime.fromisoformat(r['collected_at'].replace('Z','+00:00'))
            except ValueError:errors.append(f'{name}:{n}: collected_at')
products={r['product_id'] for r in rows('data/products.csv')}; sources={r['source_id'] for r in rows('data/source_registry.csv')}; regs={r['registration_id'] for r in rows('data/registrations.csv')}
for n,r in enumerate(rows('data/registrations.csv'),2):
    if r['product_id'] not in products: errors.append(f'registrations:{n}: product FK')
    if r['source_id'] not in sources: errors.append(f'registrations:{n}: source FK')
for n,r in enumerate(rows('data/uses.csv'),2):
    if r['registration_id'] not in regs: errors.append(f'uses:{n}: registration FK')
if errors:
    print('VALIDATION FAILED'); print('\n'.join('- '+x for x in errors)); sys.exit(1)
print('VALIDATION PASSED')
