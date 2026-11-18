"""Structured answer evidence and a narrow, auditable contradiction guard."""
import re

def assemble(approved,access):
    result=[]
    for req in access.get('requirements',[]):
        matched=[m for m in approved if req['id'] in m.get('matched_requirements',[])]
        current=[m for m in matched if m.get('decision')=='USE' and m.get('status') not in ('SUPERSEDED','STALE','CONTESTED','PROVISIONAL')]
        tentative=[m for m in matched if m.get('decision')=='USE' and m.get('status') in ('PROVISIONAL','CONTESTED')]
        historical=[m for m in matched if m.get('decision')=='LIMIT' or m.get('status') in ('SUPERSEDED','STALE')]
        by_slot={}
        for m in current:by_slot.setdefault((m.get('domain'),m.get('slot')),[]).append(m)
        conflicts=[{'domain':key[0],'slot':key[1],'memory_ids':[x['id'] for x in values]} for key,values in by_slot.items() if len({x['content'].lower() for x in values})>1]
        def item(m):return {'id':m['id'],'content':m['content'],'status':m['status'],'source':m['source_type'],'category':m.get('memory_category'),'conversation_id':m.get('conversation_id'),'confidence':m.get('confidence'),'domain':m.get('domain'),'slot':m.get('slot')}
        result.append({'id':req['id'],'label':req['label'],'required':req['required'],'current':[item(m) for m in current],'historical':[item(m) for m in historical],'tentative':[item(m) for m in tentative],'conflicts':conflicts,'missing':not bool(current or historical or tentative)})
    return result

def guard(response,plan):
    """Catch a narrow contradictory 'unknown stack' claim, not general entailment."""
    if not response:return response,False
    covered={x['id'] for x in plan if x['current']}
    stack=covered & {'stack:language','stack:framework'}
    if not stack:return response,False
    unknown=r"(?:don['’]t know|do not know|doesn['’]t know|cannot determine|can['’]t determine|not sure|no (?:information|details)|unknown|not (?:provided|known))"
    segments=re.split(r'(?<=[.!?])\s+|\n',response)
    contradiction=False
    for segment in segments:
        if not re.search(unknown,segment,re.I):continue
        general=bool(re.search(r'\b(?:stack|technolog(?:y|ies)|development tools)\b',segment,re.I))
        language=bool(re.search(r'\b(?:language|languages)\b',segment,re.I)) and 'stack:language' in stack
        framework=bool(re.search(r'\bframeworks?\b',segment,re.I)) and 'stack:framework' in stack
        if general or language or framework:contradiction=True;break
    if not contradiction:return response,False
    lines=[];seen=set()
    for entry in plan:
        if not entry['required']:continue
        for m in entry['current']+entry['tentative']+entry['historical']:
            if m['id'] not in seen:
                prefix='Earlier: ' if m in entry['historical'] else 'Tentative: ' if m in entry['tentative'] else ''
                lines.append('- '+prefix+m['content']);seen.add(m['id'])
        if entry['missing']:lines.append('- '+entry['label']+': not established in the available memory.')
    return ('Here is what the available memory supports:\n'+'\n'.join(lines) if lines else response),bool(lines)
