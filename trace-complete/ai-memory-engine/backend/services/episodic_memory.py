"""Deterministic, source-linked consolidation; no fabricated model summaries."""
import json,re
from .. import database as db
from .memory_formation import store

def update(conversation_id,domain,text,message_id):
    if db.one("SELECT id FROM memories WHERE slot=? AND status='DELETED'",('episode:'+conversation_id+':'+domain,)):return None
    # Experiences are the primary consolidation source. Legacy transcript fallback prevents gaps.
    experiences=db.rows('SELECT * FROM conversation_experiences WHERE conversation_id=? ORDER BY timestamp',(conversation_id,))
    keyed={}
    for e in experiences:
        keyed[e['message_id']]={'id':e['message_id'],'role':'user','content':e['user_message'],'created_at':e['timestamp'],'experience_id':e['id']}
        if e['assistant_message_id'] and e['assistant_response']:
            keyed[e['assistant_message_id']]={'id':e['assistant_message_id'],'role':'assistant','content':e['assistant_response'],'created_at':e['timestamp'],'experience_id':e['id']}
    for m in db.rows('SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at',(conversation_id,)):
        if m['id'] not in keyed:keyed[m['id']]={**m,'experience_id':None}
    messages=sorted(keyed.values(),key=lambda m:m['created_at'])
    working=[{'role':m['role'],'content':m['content'][:2000]} for m in messages[-8:] if m['role'] in ('user','assistant')]
    intent='recall' if '?' in text else 'planning' if re.search(r'plan|goal|want',text,re.I) else 'conversation'
    db.execute('INSERT OR REPLACE INTO working_contexts VALUES(?,?,?,?,?,?)',(conversation_id,domain,intent,text[:200],json.dumps(working),db.now()))
    # Segment explicit fresh-context boundaries; prior episodes stay in their prior scope.
    from .memory_access import boundary
    cuts=[i for i,m in enumerate(messages) if m['role']=='user' and boundary(m['content'])]
    if cuts:messages=messages[cuts[-1]:]
    # Working context stays conversation-local, not a duplicated semantic fact.
    marks=[]
    for m in messages:
        if m['role']=='user':
            t=m['content']
            if re.search(r'^(?:what|why|tell|show|list|recap|summari[sz]e|how|where)\b',t,re.I):continue
            if re.search(r'original (?:reason|objective)|why.{0,30}(?:start|began)|forgot.{0,20}why',t,re.I):continue
            category='objective' if re.search(r"(?:start(?:ed|ing)? (?:this )?conversation|objective|my goal (?:is|was|to)|my purpose|i (?:am|'m) building|i want|i need help|i am here|i came here)",t,re.I) else 'rejected_alternative' if re.search(r'reject|not use|ruled out|instead|don[’\x27]t want',t,re.I) else 'decision' if re.search(r'decided|chose|agreed|let[’\x27]s|cancelled|changed.*(?:goal|direction)',t,re.I) else 'constraint' if re.search(r'cannot|budget|limited|deadline|because',t,re.I) else 'unresolved_question' if t.endswith('?') and re.search(r'should|which|choose',t,re.I) else None
        else:category='assistant_proposal' if m['role']=='assistant' and re.search(r'i suggest|you could|i recommend|consider|^use\b',m['content'],re.I) else None
        if category:marks.append({'kind':category,'role':m['role'],'text':m['content'][:1000],'message_id':m['id'],'created_at':m['created_at'],'experience_id':m.get('experience_id')})
    if not marks:return None
    meaningful=any(m['kind'] in ('decision','rejected_alternative','constraint') or re.search(r'start(?:ed|ing)?.{0,30}conversation|because|objective|purpose|i need help',m['text'],re.I) for m in marks if m['role']=='user')
    recall=bool(re.search(r'forgot.{0,20}why|original (?:reason|objective)|why.{0,25}start',text,re.I))
    if not meaningful and len(messages)<12 and not recall:return None
    # Always retain earliest objectives plus recent outcomes; full transcript remains in messages.
    objectives=[m for m in marks if m['kind']=='objective'][:4]
    picked=objectives+[m for m in marks[-24:] if m not in objectives]
    lines=[];size=0
    for m in picked:
        line=f"{m['kind']} ({m['role']}; message {m['message_id']}): {m['text']}"
        if size+len(line)>5500:break
        lines.append(line);size+=len(line)
    summary='Meaningful episode from this conversation:\n'+'\n'.join(lines)
    prior=db.one('SELECT * FROM episodes WHERE conversation_id=? AND context_id=?',(conversation_id,domain))
    eid=prior['id'] if prior else db.uid()
    db.execute('INSERT OR REPLACE INTO episodes VALUES(?,?,?,?,?,?,?)',(eid,conversation_id,domain,summary,json.dumps(picked),len(messages),db.now()))
    if prior and prior['summary']==summary:return eid
    # Episode uses a stable memory ID and history; unlike user facts, revisions do not contradict it.
    existing=db.one("SELECT * FROM memories WHERE slot=? AND status!='DELETED'",('episode:'+conversation_id+':'+domain,))
    if existing:
        db.version(existing,'Episodic consolidation revision')
        db.execute('UPDATE memories SET content=?,updated_at=?,activation=MIN(1,activation+.05) WHERE id=?',(summary,db.now(),existing['id']))
        mid=existing['id']
    else:
        x={'content':summary,'memory_type':'Episodic','slot':'episode:'+conversation_id+':'+domain,'domain':domain,'expected_lifetime':None,'confidence':.95,'importance':.85,'source_type':'SOURCE_LINKED_SUMMARY','memory_layer':'episodic','protected':1}
        mid=store([x],text,domain,conversation_id,message_id)[0]['id']
    current_experience=db.one('SELECT id FROM conversation_experiences WHERE message_id=?',(message_id,))
    if current_experience:db.execute('UPDATE memories SET experience_id=? WHERE id=?',(current_experience['id'],mid))
    for item in picked:
        if not db.one('SELECT 1 AS ok FROM memory_evidence WHERE memory_id=? AND message_id=?',(mid,item['message_id'])):
            db.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),mid,conversation_id,item['message_id'],item['text'],'ASSISTANT_SUGGESTION' if item['role']=='assistant' else 'USER_EXPLICIT',item['created_at']))
    db.event('EPISODE_CONSOLIDATED','Source-linked objectives, decisions and alternatives retained',mid,conversation_id)
    return eid
