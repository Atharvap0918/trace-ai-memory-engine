"""Experience capture is unconditional; retention and influence are separate phases."""
import json,re
from .. import database as db
from . import memory_formation,experience_analyzer,retention_policy,memory_lifecycle

def begin(conversation_id,message_id,text,context,time_zone='UTC'):
    existing=db.one('SELECT id FROM conversation_experiences WHERE message_id=?',(message_id,))
    if existing:return existing['id']
    id=db.uid()
    db.execute('INSERT INTO conversation_experiences (id,user_id,conversation_id,message_id,user_message,timestamp,current_context,source_information) VALUES(?,?,?,?,?,?,?,?)',(id,'user_001',conversation_id,message_id,text,db.now(),context,json.dumps({'user':'USER_EXPLICIT','time_zone':time_zone})))
    db.event('EXPERIENCE_CAPTURED','Conversation interaction captured before retention analysis',conversation_id=conversation_id)
    return id

def complete(id,response=None,assistant_id=None,provider_error=None,context=None):
    e=db.one('SELECT * FROM conversation_experiences WHERE id=?',(id,));source=json.loads(e['source_information']);source.update(assistant='EXTERNAL_LLM' if response else None,assistant_message_id=assistant_id)
    db.execute('UPDATE conversation_experiences SET assistant_response=?,assistant_message_id=?,error=?,current_context=?,source_information=? WHERE id=?',(response,assistant_id,provider_error,context or e['current_context'],json.dumps(source),id))

def source_evidence(memory_id,conversation_id,ids):
    for mid in ids:
        m=db.one("SELECT * FROM messages WHERE id=? AND role='user' AND conversation_id=?",(mid,conversation_id))
        if not m or db.one('SELECT id FROM memory_evidence WHERE memory_id=? AND message_id=?',(memory_id,mid)):continue
        db.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),memory_id,conversation_id,mid,m['content'],'USER_EXPLICIT',m['created_at']))
    count=db.one('SELECT COUNT(*) AS n FROM memory_evidence WHERE memory_id=? AND source_type NOT IN (\'ASSISTANT_SUGGESTION\',\'SOURCE_LINKED_SUMMARY\')',(memory_id,))['n']
    db.execute('UPDATE memories SET evidence_count=MAX(evidence_count,?) WHERE id=?',(count,memory_id))

def process(id,access,settings):
    e=db.one('SELECT * FROM conversation_experiences WHERE id=?',(id,))
    if e['processing_status'] in ('PROCESSED','HISTORY_ONLY','MEMORY_DISABLED'):return [],json.loads(e['formation_report'])
    if not settings['memory_enabled']:
        report={'experience_id':id,'captured':True,'candidates':0,'long_term':0,'temporary':0,'assistant_derived':0,'updated':0,'rejected':0,'history_only':1}
        db.execute("UPDATE conversation_experiences SET processing_status='MEMORY_DISABLED',formation_report=? WHERE id=?",(json.dumps(report),id));return [],report
    domain=access['current_domain'];source=json.loads(e['source_information']);text=e['user_message']
    if access.get('boundary'):
        source['context_boundary']={'current_context':domain,'excluded_contexts':access.get('blocked_domains',[]),'mode':access['memory_mode']}
        db.execute('UPDATE conversation_experiences SET source_information=? WHERE id=?',(json.dumps(source),id))
    base=memory_formation.candidates(text,domain,enhance=False)
    cs=experience_analyzer.enrich(text,domain,base,e['conversation_id'],e['message_id'],e['timestamp'],source.get('time_zone','UTC'))
    if access.get('boundary'):
        cs.append({'content':'Explicit context boundary: earlier project/conversation context is excluded for this scope.','memory_type':'Temporary Context','slot':'boundary:'+domain,'domain':domain,'expected_lifetime':90,'confidence':.99,'importance':1,'source_type':'USER_EXPLICIT','memory_layer':'contextual','protected':0,'memory_category':'CONTEXT_BOUNDARY','retention_class':'MEDIUM_TERM'})
    entities,topics=experience_analyzer.describe(text,e['assistant_response'],cs)
    db.execute("UPDATE conversation_experiences SET entities=?,topics=?,memory_candidates=?,processing_status='ANALYZED' WHERE id=?",(json.dumps(entities),json.dumps(topics),json.dumps(cs),id))
    # Candidate capture happens before deciding which candidates become distilled memory.
    for x in cs:
        cat,ret=retention_policy.classify(x)
        db.execute('INSERT OR IGNORE INTO experience_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(db.uid(),id,'user',x['content'],x['memory_type'],cat,ret,'CANDIDATE','Captured before retention',None,x['expected_lifetime'],e['message_id'],db.now()))
    try:
        formed=memory_formation.interaction(text,e['assistant_response'],domain,e['conversation_id'],e['message_id'],e['assistant_message_id'],candidates_override=cs)
        for item in formed:
            m=db.one('SELECT * FROM memories WHERE id=?',(item['id'],))
            x=next((x for x in cs if x['slot']==m['slot'] and x['domain']==m['domain']),m)
            cat,ret=retention_policy.classify(x)
            if m['source_type']=='USER_CONFIRMED' and m['memory_type']=='Project':cat='USER_CONFIRMED_DECISION'
            db.execute('UPDATE memories SET memory_category=?,retention_class=?,valid_from=?,experience_id=? WHERE id=?',(cat,ret,x.get('valid_from'),id,m['id']))
            db.execute('INSERT OR IGNORE INTO experience_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(db.uid(),id,'user',m['content'],m['memory_type'],cat,ret,m['status'],'Retained with source evidence',m['id'],m['expected_lifetime'],e['message_id'],db.now()))
            db.execute("UPDATE experience_candidates SET status=?,memory_id=?,reason='Retained with source evidence' WHERE experience_id=? AND role='user' AND content=?",(m['status'],m['id'],id,m['content']))
            source_evidence(m['id'],e['conversation_id'],x.get('source_message_ids',[]))
            transition=x.get('temporal_transition')
            if transition and not db.one('SELECT id FROM temporal_transitions WHERE memory_id=?',(m['id'],)):
                db.execute("UPDATE temporal_transitions SET status='SUPERSEDED',updated_at=? WHERE status='PLANNED' AND memory_id IN (SELECT id FROM memories WHERE status='SUPERSEDED')",(db.now(),))
                db.execute('INSERT INTO temporal_transitions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(db.uid(),id,m['id'],transition['old_memory_id'],transition['from_state'],transition['to_state'],transition['effective_at'],'PLANNED','general',None,db.now(),db.now()))
                if transition['old_memory_id']:db.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),m['id'],transition['old_memory_id'],'planned_update'))
            if x.get('confirmed_location'):
                for tr in db.rows("SELECT * FROM temporal_transitions WHERE status='PLANNED' AND lower(to_state)=lower(?)",(x['confirmed_location'],)):
                    db.execute("UPDATE temporal_transitions SET status='CONFIRMED',confirmed_by=?,updated_at=? WHERE id=?",(e['message_id'],db.now(),tr['id']))
                    plan=db.one('SELECT * FROM memories WHERE id=?',(tr['memory_id'],))
                    if plan and plan['status'] not in ('DELETED','ARCHIVED'):memory_lifecycle.transition(plan,'SUPERSEDED','Move confirmed; current residence now updated')
                    db.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),m['id'],tr['memory_id'],'confirms_transition'))
        if re.search(r"(?:not moving|cancel(?:led)? (?:the |my )?move|decided not to move)",text,re.I):
            for tr in db.rows("SELECT * FROM temporal_transitions WHERE status='PLANNED' AND context='general'"):
                m=db.one('SELECT * FROM memories WHERE id=?',(tr['memory_id'],))
                if m:memory_lifecycle.transition(m,'ARCHIVED','User cancelled the planned move')
                db.execute("UPDATE temporal_transitions SET status='CANCELLED',updated_at=? WHERE id=?",(db.now(),tr['id']))
        # Store proposals in experiences, NEVER promote an assistant statement to a profile fact.
        proposals=db.rows('SELECT * FROM interaction_candidates WHERE message_id=? AND role=\'assistant\'',(e['assistant_message_id'] or '',))
        for p in proposals:
            entities.append({'type':'Assistant Suggestion','value':p['content'],'source':'ASSISTANT'})
            db.execute('INSERT OR IGNORE INTO experience_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(db.uid(),id,'assistant',p['content'],'Assistant Suggestion','ASSISTANT_SUGGESTION','SHORT_TERM',p['status'],'User acceptance required',None,30,p['message_id'],db.now()))
        for accepted in db.rows("SELECT * FROM interaction_candidates WHERE accepted_by=?",(e['message_id'],)):
            db.execute("UPDATE experience_candidates SET status='ACTIVE',reason='Explicit user confirmation; linked in accepting experience' WHERE role='assistant' AND source_message_id=?",(accepted['message_id'],))
        # Education relations link actual memory rows; no invented university nodes.
        who=db.one("SELECT id FROM memories WHERE slot='identity:name' AND status='ACTIVE' ORDER BY updated_at DESC LIMIT 1")
        if who:
            for m in db.rows("SELECT id FROM memories WHERE slot='education:institution' AND status='ACTIVE'"):
                db.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),who['id'],m['id'],'studies_at'))
        cand=db.rows('SELECT * FROM experience_candidates WHERE experience_id=?',(id,))
        # One candidate per retained information item, not duplicate capture/promote rows.
        report={'experience_id':id,'captured':True,'candidates':len(cand),'long_term':sum(x['role']=='user' and x['memory_id'] is not None and x['retention_class']=='LONG_TERM' for x in cand),'temporary':sum(x['role']=='user' and x['memory_id'] is not None and x['retention_class'] in ('SHORT_TERM','MEDIUM_TERM') for x in cand),'assistant_derived':sum(x['role']=='assistant' for x in cand),'updated':sum(x['action']=='MEMORY_UPDATED' for x in formed),'rejected':sum(x['status']=='REJECTED' for x in cand),'history_only':int(not cand)}
        retention='LONG_TERM' if report['long_term'] else 'MEDIUM_TERM' if any(x['retention_class']=='MEDIUM_TERM' for x in cand) else 'SHORT_TERM' if cand else 'EPHEMERAL'
        db.execute('UPDATE conversation_experiences SET memory_candidates=?,entities=? WHERE id=?',(json.dumps(cand),json.dumps(entities),id))
        event_type='CONTEXT_BOUNDARY' if access.get('boundary') else 'TEMPORAL_TRANSITION' if any(x.get('temporal_transition') for x in cs) else 'PROFILE_UPDATE' if report['long_term'] else 'TEMPORARY_EVENT' if report['temporary'] else 'ASSISTANT_SUGGESTION' if proposals else 'CONVERSATION'
        summary=text[:600]+(' | Assistant proposal (unconfirmed): '+e['assistant_response'][:400] if proposals else '')
        db.execute('UPDATE conversation_experiences SET event_type=?,importance=?,expected_lifetime=?,retention_class=?,processing_status=?,summary=?,formation_report=? WHERE id=?',(event_type,max([x.get('importance',.3) for x in cs] or [.3]),max([x.get('expected_lifetime') or 0 for x in cs] or [0]) or None,retention,'PROCESSED' if cand else 'HISTORY_ONLY',summary,json.dumps(report),id))
        db.event('EXPERIENCE_PROCESSED',f"{report['candidates']} candidates; {report['long_term']} long-term; {report['temporary']} temporary; {report['assistant_derived']} assistant-derived; {report['history_only']} history-only",conversation_id=e['conversation_id'])
        return formed,report
    except Exception:
        db.execute("UPDATE conversation_experiences SET processing_status='PROCESSING_FAILED' WHERE id=?",(id,));raise

def backfill():
    """Existing transcripts gain experience records without replaying formation or replacing memories."""
    conversations=db.rows('SELECT * FROM conversations')
    for c in conversations:
        messages=db.rows('SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at',(c['id'],))
        for i,m in enumerate(messages):
            if m['role']!='user' or db.one('SELECT id FROM conversation_experiences WHERE message_id=?',(m['id'],)):continue
            response=next((x for x in messages[i+1:] if x['role'] in ('user','assistant')),None)
            if response and response['role']=='user':response=None
            db.execute('INSERT INTO conversation_experiences (id,user_id,conversation_id,message_id,assistant_message_id,user_message,assistant_response,timestamp,current_context,source_information,processing_status,summary) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(db.uid(),'user_001',c['id'],m['id'],response['id'] if response else None,m['content'],response['content'] if response else None,m['created_at'],c['domain'],json.dumps({'user':'USER_EXPLICIT','assistant':'EXTERNAL_LLM' if response else None,'migrated':True}),'LEGACY_HISTORY',m['content'][:600]))

def search(text,access,conversation_id):
    """Bounded, query-specific source experiences; NEVER inject complete history."""
    from .memory_retrieval import tokens
    if not access['memory_needed'] or access['memory_mode']=='ISOLATED':return []
    reqs=[r for r in access.get('requirements',[]) if r['id'] in ('experience','episode')]
    if not reqs:return []
    records=db.rows("SELECT * FROM conversation_experiences WHERE user_id='user_001' AND processing_status IN ('PROCESSED','HISTORY_ONLY','LEGACY_HISTORY','MEMORY_DISABLED') ORDER BY timestamp DESC LIMIT 500")
    ranked=[];q=tokens(text)
    for e in records:
        if access['memory_mode']=='RESTRICTED' and e['current_context']!=access['current_domain']:continue
        if e['current_context'] not in ('general',access['current_domain']) and e['conversation_id']!=conversation_id:
            if not access.get('historical') or access.get('project_exclusion'):continue
        if access.get('boundary') and e['current_context']!=access['current_domain']:continue
        body=e['user_message'];words=tokens(body);rel=len(q&words)/max(1,len(q))
        objective=bool(re.search(r'start(?:ed|ing)?.{0,25}conversation|original objective|i need help|i want',body,re.I))
        if any(r['id']=='episode' for r in reqs) and e['conversation_id']==conversation_id and objective:rel=max(.92,rel)
        if rel<.25:continue
        quoted={'user_statement':body[:900],'assistant_response':e['assistant_response'][:700] if e['assistant_response'] else None,'assistant_is_not_user_fact':True,'timestamp':e['timestamp'],'experience_id':e['id'],'message_id':e['message_id']}
        ranked.append((rel,e,quoted))
    ranked.sort(key=lambda x:x[0],reverse=True)
    output=[]
    for rel,e,quoted in ranked[:3]:
        output.append({'id':'experience:'+e['id'],'experience_record_id':e['id'],'user_id':e['user_id'],'content':json.dumps(quoted,ensure_ascii=False),'memory_type':'Conversation Experience','memory_layer':'experience','domain':e['current_context'],'conversation_id':e['conversation_id'],'slot':'experience:'+e['message_id'],'source_type':'SOURCE_LINKED_EXPERIENCE','confidence':1.,'importance':e['importance'],'activation':.5,'freshness':.5,'status':'HISTORICAL','influence':round(min(.4,.4*rel),3),'decision':'LIMIT','matched_requirements':[r['id'] for r in reqs],'retention_class':e['retention_class'],'relevance':rel})
    return output
