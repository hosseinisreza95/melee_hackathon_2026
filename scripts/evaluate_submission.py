#!/usr/bin/env python3
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
score=0; notes=[]; answers=d.get('answers',[]); evidence=[e for a in answers for e in a.get('evidence',[])]
if answers: score+=10
else: notes.append('No answers')
if evidence and all(e.get('source_id') and e.get('source_url') and e.get('collected_at') and e.get('validation_status') for e in evidence): score+=20
else: notes.append('Traceability incomplete')
if answers and all(a.get('disclaimer') for a in answers): score+=10
else: notes.append('Disclaimer missing')
if answers and all('warnings' in a for a in answers): score+=10
else: notes.append('Warnings missing')
i=d.get('m365_integration',{})
if i.get('mechanism') and i.get('documentation_url'): score+=15
else: notes.append('M365 integration missing')
if 'known_limitations' in d: score+=5
else: notes.append('Known limitations missing')
print(json.dumps({'automatic_score':score,'automatic_max':70,'notes':notes},ensure_ascii=False,indent=2))
