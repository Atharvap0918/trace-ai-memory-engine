import json,re,asyncio,logging
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import StreamingResponse,FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from typing import Literal
from . import database as db
from .services import llm_provider as llm, memory_access, memory_retrieval, memory_formation, context_builder, embeddings, memory_lifecycle, episodic_memory, experience_memory, associative_memory, retrieval_diagnostics, answer_evidence
from .services import memory_display

db.init(); experience_memory.backfill(); app=FastAPI(title='AI Memory Engine',docs_url='/api/docs')

@app.on_event('startup')
async def start_memory_maintenance():
    async def worker():
        while True:
            try:
                if llm.settings().get('memory_enabled'):
                    await asyncio.to_thread(associative_memory.maintain)
            except Exception:
                logging.getLogger(__name__).exception('Background memory maintenance failed')
            await asyncio.sleep(300)
    app.state.memory_worker=asyncio.create_task(worker())

@app.on_event('shutdown')
async def stop_memory_maintenance():
    task=getattr(app.state,'memory_worker',None)
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
@app.middleware('http')
async def local_security(request:Request,call_next):
    if request.url.hostname not in ('127.0.0.1','localhost','::1','testserver'):
        return JSONResponse({'detail':'Only localhost requests are allowed.'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        return JSONResponse({'detail':'Cross-origin access is not allowed.'},status_code=403)
    try: response=await call_next(request)
    except Exception: return JSONResponse({'detail':'A local storage or application error occurred. Your existing data is retained.'},status_code=500)
    response.headers['X-Content-Type-Options']='nosniff'; response.headers['Referrer-Policy']='no-referrer'
    return response
class ChatInput(BaseModel):
    user_id:Literal['user_001']='user_001'
    conversation_id:str
    user_message:str=Field(min_length=1,max_length=16000)
    time_zone:str=Field(default='UTC',max_length=80)
class SettingsInput(BaseModel):
    provider:Literal['openai','groq','openrouter','custom']='openai'
    model:str=Field(min_length=1,max_length=150)
    base_url:str=Field(max_length=500)
    api_key:str|None=Field(default=None,max_length=1000)
    clear_api_key:bool=False
    memory_enabled:bool=True
    memory_mode:Literal['OPEN','SELECTIVE','RESTRICTED','ISOLATED']='OPEN'
    top_k:int=Field(ge=1,le=20,default=5)
    threshold:float=Field(ge=0,le=1,default=.28)
    semantic_enabled:bool=False
    embedding_model:str=Field(default='text-embedding-3-small',max_length=150)
class MemoryInput(BaseModel):
    content:str|None=Field(default=None,min_length=1,max_length=2000)
    status:Literal['ACTIVE','DORMANT','ARCHIVED','STALE','CONTESTED','PROVISIONAL']|None=None
    importance:float|None=Field(default=None,ge=0,le=1)
@app.get('/api/settings')
def get_settings(): return {**llm.settings(),'api_key_configured':bool(llm.KEY),'local_semantic':'bundled MiniLM (local, used when available)','semantic_status':'available on request' if llm.settings()['semantic_enabled'] and llm.KEY else 'disabled' if not llm.settings()['semantic_enabled'] else 'API key required'}
@app.post('/api/settings')
def save_settings(body:SettingsInput):
    if not re.match(r'^https?://[^\s]+$',body.base_url): raise HTTPException(422,'Enter a valid provider URL.')
    if body.clear_api_key: llm.set_key('')
    elif body.api_key: llm.set_key(body.api_key)
    s=body.model_dump(exclude={'api_key','clear_api_key'});db.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(s),));embeddings.COLLECTION=None
    return get_settings()
@app.get('/api/conversations')
def conversations(): return db.rows("SELECT * FROM conversations WHERE user_id='user_001' ORDER BY created_at DESC")
@app.post('/api/conversations')
def create_conversation():
    latest=db.one("SELECT domain FROM memories WHERE memory_type='Project' AND status IN ('ACTIVE','ESTABLISHED') ORDER BY updated_at DESC LIMIT 1")
    id=db.uid(); domain=latest['domain'] if latest else 'project:default'; db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',(id,'user_001','New conversation',domain,db.now())); return db.one('SELECT * FROM conversations WHERE id=?',(id,))
@app.get('/api/conversations/{id}/messages')
def messages(id:str): return db.rows('SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at',(id,))
@app.delete('/api/conversations/{id}')
def delete_conversation(id:str):
    from .services import local_semantic
    local_semantic.clear_cache()
    with db.connect() as c: retrieval_diagnostics.purge_conversation(id,c)
    db.execute('DELETE FROM experience_candidates WHERE experience_id IN (SELECT id FROM conversation_experiences WHERE conversation_id=?)',(id,));db.execute('DELETE FROM conversation_experiences WHERE conversation_id=?',(id,))
    db.execute('DELETE FROM working_contexts WHERE conversation_id=?',(id,));db.execute('DELETE FROM interaction_candidates WHERE conversation_id=?',(id,));db.execute('DELETE FROM messages WHERE conversation_id=?',(id,));db.execute('DELETE FROM conversations WHERE id=?',(id,));return {'deleted':True,'note':'Persistent memory and provenance are retained.'}
@app.post('/api/chat')
def chat(body:ChatInput):
    conv=db.one("SELECT * FROM conversations WHERE id=? AND user_id='user_001'",(body.conversation_id,))
    if not conv: raise HTTPException(404,'Conversation not found.')
    def stream():
        def packet(stage,**data): return json.dumps({'stage':stage,**data})+'\n'
        def warning(label):
            warnings.append(label)
            try:db.event('PIPELINE_WARNING',label,conversation_id=conv['id'])
            except Exception:pass
        warnings=[]
        try:
            s=llm.settings();history=messages(conv['id'])[-12:];mid=db.uid();text=body.user_message.strip()
            if not text:yield packet('error',message='Enter a message.');return
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?)',(mid,conv['id'],'user',text,db.now()))
            experience_id=None
            try:experience_id=experience_memory.begin(conv['id'],mid,text,conv['domain'],body.time_zone)
            except Exception:warning('Experience capture unavailable; the transcript is retained')
            if conv['title']=='New conversation':db.execute('UPDATE conversations SET title=? WHERE id=?',(text[:50],conv['id']))
            try:access=memory_access.analyze(text,conv,s)
            except Exception:
                warning('Request analysis unavailable; memory skipped safely')
                access={'memory_mode':'ISOLATED','current_domain':conv['domain'],'memory_needed':False,'boundary':memory_access.boundary(text),'allowed_types':[],'requirements':[],'historical':False,'requested_groups':[]}
            db.execute('INSERT INTO memory_access_logs VALUES(?,?,?,?,?,?)',(db.uid(),conv['id'],access['memory_mode'],access['memory_needed'],access['current_domain'],db.now()))
            yield packet('access',message='Memory access evaluated',access=access)
            yield packet('understanding',message='Request decomposed',requirements=access.get('requirements',[]),language=access.get('query_language','en'),intents=access.get('requested_groups',[]))
            # Consolidate old interactions BEFORE retrieval so early reasons survive a short recent window.
            if s['memory_enabled']:
                try:episodic_memory.update(conv['id'],access['current_domain'],text,mid)
                except Exception:warning('Episode consolidation unavailable; other memory remains usable')
            try:approved,decisions,semantic_state=memory_retrieval.retrieve(text,access,s,conv['id'])
            except Exception:
                approved=[];decisions=[];semantic_state='unavailable';warning('Memory retrieval unavailable; responding with recent conversation only')
                requirements=access.get('requirements',[])
                access['coverage']={'covered':0,'total':sum(r['required'] for r in requirements),'missing':[r['label'] for r in requirements if r['required']],'requirements':[{**r,'status':'missing','memory_ids':[]} for r in requirements],'ratio':0}
            yield packet('retrieval',message='Independent requirement searches complete',retrieved=len(approved),semantic_status=semantic_state)
            yield packet('governance',message='Memory governance complete',approved=len(approved),blocked=sum(d['decision']=='BLOCK' for d in decisions),decisions=decisions,semantic_status=semantic_state,coverage=access.get('coverage',{}))
            try:context=context_builder.build(approved,history,text,access)
            except Exception:
                warning('Context assembly unavailable; safe conversation fallback used')
                context=[{'role':'system','content':context_builder.POLICY}]+([] if access.get('boundary') else [{'role':h['role'],'content':h['content']} for h in history if h['role'] in ('user','assistant')])+[{'role':'user','content':text}]
            try:retrieval_diagnostics.record(conv['id'],mid,text,access,decisions,context,semantic_state)
            except Exception:warning('Local retrieval diagnostics unavailable')
            yield packet('context',message='Layered context prepared',context_count=len(approved))
            error=None;response=None;assistant_id=None
            yield packet('provider',message='Contacting provider' if llm.KEY else 'No provider key connected')
            try:response=llm.get_provider().respond(context)
            except llm.ProviderError as e:error=str(e)
            except Exception:error='The provider request failed. Check the model connection and retry.'
            if response:
                response,corrected=answer_evidence.guard(response,answer_evidence.assemble(approved,access))
                if corrected:db.event('ANSWER_CONTRADICTION_GUARDED','Replaced unsupported unknown-stack claim with retrieved evidence',conversation_id=conv['id'])
                assistant_id=db.uid();db.execute('INSERT INTO messages VALUES(?,?,?,?,?)',(assistant_id,conv['id'],'assistant',response,db.now()))
                db.event('RESPONSE_GENERATED','External provider response received',conversation_id=conv['id'])
                for m in approved:db.event('EXPERIENCE_USED' if m.get('memory_layer')=='experience' else 'MEMORY_USED','Included in completed provider request',None if m.get('memory_layer')=='experience' else m['id'],conv['id'])
            formed=[];formation_report={'captured':bool(experience_id),'candidates':0,'long_term':0,'temporary':0,'assistant_derived':0,'updated':0,'rejected':0,'history_only':1}
            if experience_id:
                try:
                    experience_memory.complete(experience_id,response,assistant_id,error,access['current_domain'])
                    formed,formation_report=experience_memory.process(experience_id,access,s)
                except Exception:warning('Memory formation unavailable; captured experience and response are retained')
            if s['memory_enabled']:
                try:episodic_memory.update(conv['id'],access['current_domain'],text,mid)
                except Exception:warning('Episode update unavailable; the response and transcript are retained')
            yield packet('formation',message='Memory update complete' if not warnings else 'Memory update completed with warnings',formed=formed,formation_report=formation_report,warnings=warnings)
            if error:db.execute('INSERT INTO messages VALUES(?,?,?,?,?)',(db.uid(),conv['id'],'notice',error,db.now()))
            yield packet('done',response=response,error=error,access=access,formed=formed,decisions=decisions,coverage=access.get('coverage',{}),formation_report=formation_report,warnings=warnings)
        except Exception:
            yield packet('error',message='The local pipeline could not complete. Check storage and retry; earlier saved data is retained.')
    return StreamingResponse(stream(),media_type='application/x-ndjson',headers={'Cache-Control':'no-store'})
def _episode_slot_parts(m):
    slot=str(m.get('slot') or '')
    if not slot.startswith('episode:'):return None,None
    _,conv,*ctx=slot.split(':',2) if slot.count(':')>=2 else (None,None,'')
    return conv,(ctx[0] if ctx else '')
def _display_with_episode(m,with_details=False):
    """Presentation-only: reads the episodes table, never writes to it."""
    is_episode=str(m.get('memory_layer','')).lower()=='episodic' or str(m.get('memory_type','')).lower() in ('episodic','episode')
    if not is_episode:return memory_display.display_memory(m)
    conv,ctx=_episode_slot_parts(m)
    ep=db.one('SELECT * FROM episodes WHERE conversation_id=? AND context_id=?',(conv,ctx)) if conv else None
    source={}
    if with_details:
        c=db.one('SELECT title,created_at FROM conversations WHERE id=?',(conv,)) if conv else None
        ev=db.rows('SELECT source_type,created_at FROM memory_evidence WHERE memory_id=?',(m['id'],))
        source={'conversation_title':(c or {}).get('title') or 'Untitled conversation','conversation_started':(c or {}).get('created_at'),
                'messages_in_episode':(ep or {}).get('message_count'),'source_messages':len(ev),
                'user_statements':len([e for e in ev if e['source_type']!='ASSISTANT_SUGGESTION']),
                'assistant_statements':len([e for e in ev if e['source_type']=='ASSISTANT_SUGGESTION']),
                'context':humanize_context(ctx),'first_recorded':m.get('created_at'),'last_updated':(ep or {}).get('updated_at') or m.get('updated_at')}
    return memory_display.display_memory(m,(ep or {}).get('items'),source,with_details)
def humanize_context(ctx):
    v=str(ctx or '').split(':',1)[-1].replace('-',' ').strip()
    return v[:1].upper()+v[1:] if v else 'General'
@app.get('/api/memories')
def memories():
    memory_lifecycle.maintain()
    rows=db.rows("SELECT * FROM memories WHERE user_id='user_001' AND status!='DELETED' ORDER BY updated_at DESC")
    return [_display_with_episode(m) for m in rows]
@app.get('/api/memories/export')
def export_memories():
    rows=db.rows("SELECT * FROM memories WHERE user_id='user_001' AND status!='DELETED' ORDER BY created_at")
    return {
        'format':'trace-memory-export-v1',
        'exported_at':db.now(),
        'memories':rows,
        'evidence':db.rows("SELECT e.* FROM memory_evidence e JOIN memories m ON m.id=e.memory_id WHERE m.user_id='user_001' AND m.status!='DELETED' ORDER BY e.created_at"),
        'versions':db.rows("SELECT v.* FROM memory_versions v JOIN memories m ON m.id=v.memory_id WHERE m.user_id='user_001' AND m.status!='DELETED' ORDER BY v.created_at"),
        'relationships':db.rows("SELECT r.* FROM memory_relationships r JOIN memories a ON a.id=r.source_id JOIN memories b ON b.id=r.target_id WHERE a.user_id='user_001' AND b.user_id='user_001' AND a.status!='DELETED' AND b.status!='DELETED'"),
    }
@app.get('/api/memories/{id}')
def detail(id:str):
    m=db.one('SELECT * FROM memories WHERE id=?',(id,))
    if not m or m['status']=='DELETED': raise HTTPException(404,'Memory not found.')
    versions=db.rows('SELECT * FROM memory_versions WHERE memory_id=? ORDER BY created_at DESC',(id,))
    for version in versions:
        try:snapshot=json.loads(version.get('snapshot') or '{}')
        except (TypeError,ValueError):snapshot={}
        version['display_content']=memory_display.clean_text(snapshot.get('content',''),m.get('memory_type',''),m.get('source_type',''),m.get('memory_layer',''))
    evidence=db.rows('SELECT * FROM memory_evidence WHERE memory_id=? ORDER BY created_at DESC',(id,))
    for item in evidence:item['display_statement']=memory_display.clean_text(item.get('statement',''))
    return {**_display_with_episode(m,True),'versions':versions,'evidence':evidence,'usage':db.rows('SELECT * FROM memory_usage_logs WHERE memory_id=? ORDER BY created_at DESC LIMIT 30',(id,))}
@app.patch('/api/memories/{id}')
def patch(id:str,body:MemoryInput):
    m=detail(id);db.version({k:v for k,v in m.items() if k not in ('versions','evidence','usage')},'User edit')
    changes=body.model_dump(exclude_none=True)
    if not changes: return m
    if body.content is not None:
        from .services import local_semantic
        local_semantic.clear_cache()
    if body.content is not None or (body.status is not None and body.status not in ('ACTIVE','DORMANT')): associative_memory.invalidate_source(id)
    changes['updated_at']=db.now()
    if body.content is not None:
        from .services.entity_extraction import extract
        changes['entities']=json.dumps(extract(body.content,m['domain'],m['slot']),ensure_ascii=False)
        changes.update(source_type='USER_CONFIRMED',last_confirmed_at=db.now(),confidence=.99,evidence_count=m['evidence_count']+1,activation=max(.65,m['activation']),activation_updated_at=db.now())
    with db.connect() as c:
        c.execute('UPDATE memories SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',list(changes.values())+[id])
        if body.content is not None:c.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),id,None,None,body.content,'USER_CONFIRMED',db.now()))
    if body.status and body.status!=m['status']:
        db.execute('INSERT INTO memory_transitions VALUES(?,?,?,?,?,?)',(db.uid(),id,m['status'],body.status,'Manual state change',db.now()))
        db.event('MEMORY_'+('REACTIVATED' if body.status=='ACTIVE' else body.status),'Manual state change',id)
    if body.content is not None or body.status is not None: associative_memory.refresh_associations([id])
    db.event('MEMORY_UPDATED','Manual user edit',id);return detail(id)
@app.delete('/api/memories/{id}')
def delete_memory(id:str):
    detail(id)
    from .services import local_semantic
    local_semantic.clear_cache()
    derived_cleared=associative_memory.invalidate_source(id,delete=True)
    with db.connect() as c:
        retrieval_diagnostics.purge_memory(id,c)
        for table in ('memory_versions','memory_evidence','memory_usage_logs'): c.execute('DELETE FROM '+table+' WHERE memory_id=?',(id,))
        c.execute('DELETE FROM memory_relationships WHERE source_id=? OR target_id=?',(id,id)); c.execute("UPDATE memories SET status='DELETED',content='',entities='[]',confidence=0,activation=0,importance=0,updated_at=? WHERE id=?",(db.now(),id))
        c.execute('INSERT INTO memory_transitions VALUES(?,?,?,?,?,?)',(db.uid(),id,'USER_DELETE','DELETED','User explicitly deleted content and provenance',db.now()))
        c.execute("UPDATE memory_events SET detail='Deleted content' WHERE memory_id=?",(id,))
        c.execute("DELETE FROM episodes WHERE conversation_id IN (SELECT conversation_id FROM memories WHERE id=? AND memory_layer='episodic')",(id,))
    cleared=embeddings.remove(id) and derived_cleared;db.event('MEMORY_DELETED','User deleted structured memory'+(' and semantic vectors' if cleared else '; semantic deletion failed'),id);return {'deleted':True,'warning':None if cleared else 'Structured memory deleted, but the semantic index could not be cleared. Stop the app and remove data/chroma to clear retained vectors.'}
@app.get('/api/retrieval-diagnostics/{conversation_id}')
def diagnostics(conversation_id:str,limit:int=20):
    limit=max(1,min(200,limit))
    return db.rows('SELECT * FROM retrieval_diagnostics WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?',(conversation_id,limit))

@app.get('/api/memory-stats')
def stats():
    ms=memories();active=sum(m['status'] in ('ACTIVE','ESTABLISHED','PROVISIONAL') for m in ms)
    duplicates=db.rows("SELECT lower(trim(content)) AS normalized,count(*) AS n FROM memories WHERE user_id='user_001' AND status!='DELETED' AND trim(content)!='' GROUP BY lower(trim(content)) HAVING count(*)>1")
    return {'total':len(ms),'active':active,'temporary':sum(bool(m['expires_at']) and m['status'] in ('ACTIVE','ESTABLISHED','PROVISIONAL') for m in ms),'stale':sum(m['status']=='STALE' for m in ms),'conflicts':sum(m['status']=='CONTESTED' for m in ms),'superseded':sum(m['status']=='SUPERSEDED' for m in ms),'blocked':db.one("SELECT COUNT(*) AS n FROM memory_usage_logs WHERE decision='BLOCK'")['n'],'used':db.one("SELECT COUNT(*) AS n FROM memory_events WHERE event_type='MEMORY_USED'")['n'],'total_experiences':db.one('SELECT COUNT(*) AS n FROM conversation_experiences')['n'],'long_term':sum(m['retention_class']=='LONG_TERM' for m in ms),'episodic':sum(m['memory_layer']=='episodic' for m in ms),'project_memories':sum(m['memory_category']=='PROJECT_CONTEXT' for m in ms),'short_term':sum(m['retention_class']=='SHORT_TERM' for m in ms),'medium_term':sum(m['retention_class']=='MEDIUM_TERM' for m in ms),'working_contexts':db.one('SELECT COUNT(*) AS n FROM working_contexts')['n'],'dormant':sum(m['status']=='DORMANT' for m in ms),'duplicate_candidates':sum(x['n'] for x in duplicates),'without_evidence':sum((m.get('evidence_count') or 0)<1 for m in ms),'layers':{k:sum(m['memory_layer']==k for m in ms) for k in ('semantic','contextual','preference','episodic')},'categories':{t:sum(m['memory_type']==t for m in ms) for t in set(m['memory_type'] for m in ms)}}
@app.get('/api/experiences')
def experiences(conversation_id:str|None=None,limit:int=50):
    limit=max(1,min(200,limit))
    return db.rows('SELECT * FROM conversation_experiences '+('WHERE conversation_id=? ' if conversation_id else '')+'ORDER BY timestamp DESC LIMIT ?',((conversation_id,limit) if conversation_id else (limit,)))
@app.get('/api/experiences/{id}')
def experience_detail(id:str):
    e=db.one('SELECT * FROM conversation_experiences WHERE id=?',(id,))
    if not e:raise HTTPException(404,'Experience not found.')
    return {**e,'candidates':db.rows('SELECT * FROM experience_candidates WHERE experience_id=?',(id,))}
@app.get('/api/memory-activity')
def activity(): return db.rows('SELECT * FROM memory_events ORDER BY created_at DESC LIMIT 100')
@app.get('/api/memory-graph')
def graph():
    ms=memories(); ids={m['id'] for m in ms}
    def readable_relation(value):
        known={'uses':'Uses','works_on':'Works on','works on':'Works on','belongs_to':'Belongs to','belongs to':'Belongs to','prefers':'Prefers','related_to':'Related to','supersedes':'Supersedes','supported_by':'Supported by'}
        if value in known:return known[value]
        if value.startswith('associated_entity:'):
            return 'Possible link · '+value.split(':',1)[1]
        return str(value).replace('_',' ').strip().capitalize()
    nodes=[]
    for m in ms:
        nodes.append({'data':{'id':m['id'],'label':m.get('display_label') or memory_display.short_label(m),'type':m['memory_type'],'category':m['memory_type'],'memory_class':m.get('memory_category') or 'SEMANTIC_MEMORY','status':m['status'],'domain':m.get('domain') or 'general'}})
    edges=[{'data':{'id':r['id'],'source':r['source_id'],'target':r['target_id'],'label':r['relation'],'display_label':readable_relation(r['relation']),'relation_type':r['relation']}} for r in db.rows('SELECT * FROM memory_relationships') if r['source_id'] in ids and r['target_id'] in ids]
    return {'nodes':nodes,'edges':edges}
@app.get('/api/health')
def health(): return {'status':'ok','provider_connected':bool(llm.KEY),'database':'SQLite','semantic_enabled':llm.settings()['semantic_enabled'],'version':'2.2','memory_pipeline':'capture first / retention second / governed influence'}
app.mount('/assets',StaticFiles(directory=db.ROOT/'frontend'),name='assets')
@app.get('/')
@app.get('/dashboard')
@app.get('/settings')
@app.get('/graph')
def index(): return FileResponse(db.ROOT/'frontend'/'index.html')
