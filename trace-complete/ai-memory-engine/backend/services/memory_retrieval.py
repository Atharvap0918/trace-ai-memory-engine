"""Independent requirement retrieval, fusion, governance and measured coverage."""
import re,math,json
from .. import database as db
from . import embeddings,memory_lifecycle
STOP={'what','which','where','how','is','are','am','do','does','i','my','me','the','a','an','and','of','to','user','current','tell','please','about','using','use','name','location'}
def tokens(s):return set(re.findall(r'\w+',s.lower()))-STOP

def intent_match(m,access):
    return max((structured(m,r,access) for r in access.get('requirements',[])),default=0)

def structured(m,r,a):
    if m['memory_type'] not in r['types'] and not (m.get('memory_category')=='USER_CONFIRMED_DECISION' and 'Decision' in r['types']):return 0
    if r['slots']:return .98 if m['slot'] in r['slots'] else 0
    if r['id']=='episode':return .96 if m['conversation_id']==a.get('conversation_id') else 0
    if r['id']=='project_context':return .80 if m['domain']==a.get('current_domain') and m['domain'].startswith('project:') else 0
    if r['id']=='explanation_style':return .78
    return .93

def scope_allowed(m,a):
    if a['memory_mode']=='ISOLATED' or not a['memory_needed']:return False
    if m['source_type'] in ('ASSISTANT_SUGGESTION','LLM_INFERENCE') or m['status'] in ('ARCHIVED','DELETED','CANDIDATE'):return False
    if a['memory_mode']=='RESTRICTED':return m['domain']==a['current_domain']
    if m['domain']=='general' or m['domain']==a['current_domain']:return True
    if a.get('project_exclusion') and m['domain'].startswith('project:'):return False
    if a.get('project_exclusion'):return False
    if m['memory_layer']=='episodic':return m['conversation_id']==a.get('conversation_id') or a.get('historical',False)
    return a.get('historical',False) and m['domain'] not in a.get('blocked_domains',[])

def retrieve(text,access,s,conversation_id):
    access['conversation_id']=conversation_id
    memory_lifecycle.maintain()
    memories=db.rows("SELECT * FROM memories WHERE user_id='user_001' AND status!='DELETED' ORDER BY updated_at DESC")
    decisions={};merged={};requirements=access.get('requirements',[]);semantic_states=[];candidate_diagnostics=[]
    # A supported conclusion ceases to be current as soon as any source changes.
    supported={r['source_id'] for r in db.rows("SELECT r.source_id FROM memory_relationships r JOIN memories m ON m.id=r.target_id WHERE r.relation='supported_by' AND m.status NOT IN ('ACTIVE','ESTABLISHED','DORMANT')")}
    eligible=[m for m in memories if scope_allowed(m,access) and not (m['source_type']=='SUPPORTED_CONCLUSION' and m['id'] in supported)]
    # Recorded graph edges contribute related context only within the same allowed scope.
    edges=db.rows('SELECT source_id,target_id,relation FROM memory_relationships')
    for req in requirements if access['memory_needed'] else []:
        pool=[m for m in eligible if (m['memory_type'] in req['types'] or m.get('memory_category')=='USER_CONFIRMED_DECISION' and 'Decision' in req['types']) and (not req['slots'] or m['slot'] in req['slots'])]
        if req['id']=='stack:language' and access.get('personal_language_query') and any(m['slot']=='personal:current_languages' for m in pool):
            pool=[m for m in pool if m['slot']=='personal:current_languages']
        try:sem,state=embeddings.search(req['query'],pool,min(12,max(3,req['budget']))) if pool else ({},'not needed')
        except Exception:sem,state={},'unavailable'
        from . import local_semantic
        semantic_query=access.get('normalized_query') or text
        local=local_semantic.similarities(semantic_query,[(m['id'],m['content']) for m in pool]) if pool else {}
        semantic_states.append(state);lex=tokens(req['query']);scored=[]
        for m in pool:
            st=structured(m,req,access);words=tokens(m['content']);overlap=len(lex&words)/max(1,math.sqrt(len(lex)*len(words)))
            # Episodes from other chats must match substance, not simply "episode" type.
            if req['id']=='episode' and m['conversation_id']!=conversation_id:st=0
            local_score=local.get(m['id']);external_score=sem.get(m['id'])
            try:entities=json.loads(m.get('entities') or '[]')
            except (TypeError,ValueError):entities=[]
            entity_matches=[e['value'] for e in entities if e.get('value') and re.search(r'(?<!\w)'+re.escape(e['value'])+r'(?!\w)',text,re.I)]
            entity_score=.80 if entity_matches else 0
            # Exact schema slots and explicit category questions are distinct
            # signals, not claims of semantic similarity.
            category_score=st*.65 if not req['slots'] else st*.80
            relevance=max(category_score,local_score or 0,external_score or 0,overlap,entity_score)
            if not req['slots'] and local_score is not None and local_score<.16 and overlap<.05 and not access.get('profile_summary') and not access.get('multi_fact') and req['id'] not in ('context','episode','project_context','explanation_style'):
                relevance=0
            inferred=next((x for x in access.get('semantic_requirements',[]) if x['id']==req['id'].split(':')[0]),None)
            # Weakly classified, topical requests require independent content
            # evidence; category membership alone is not a match.
            if inferred and req['id'] in ('education','career','project') and inferred['score']<.58 and not (tokens(text)&words) and (local_score is None or local_score<.40) and not entity_score:
                relevance=0
            if req['id']=='project_context' and (m['domain']!=access.get('current_domain') or not m['domain'].startswith('project:')):relevance=0
            if req['id']=='explanation_style' and m['slot']!='preference:explanation':relevance=0
            old=m['status'] in ('STALE','SUPERSEDED','CONTESTED')
            authority=1 if m['source_type'] in ('USER_EXPLICIT','USER_CONFIRMED') else .7 if m['memory_layer']=='episodic' else .55
            base=.38*m['confidence']+.18*m['importance']+.16*m['freshness']+.16*m['activation']+.12*authority
            # Strong exact-match recall remains possible even after accessibility decay.
            influence=relevance*base*(.30 if old else .72 if m['status']=='PROVISIONAL' else 1)
            history_only=access.get('history_only') and req['id'].startswith('stack:')
            choice='LIMIT' if old and access['historical'] and relevance>=.45 else 'BLOCK' if old or history_only else 'USE' if influence>=s['threshold'] and relevance>=.3 else 'BLOCK'
            reason='Historical evidence only; not a current fact' if choice=='LIMIT' else 'Requirement matched; source, applicability and activation checked' if choice=='USE' else 'Below relevance/influence threshold or non-current state'
            dscore={'memory_id':m['id'],'content':m['content'],'category':m.get('memory_category'),'slot':m['slot'],'requirement':req['id'],'semantic_similarity':local_score,'provider_similarity':external_score,'lexical_score':round(overlap,4),'entity_score':entity_score,'matched_entities':entity_matches,'structured_score':round(category_score,4),'ranking_score':round(influence,4),'temporal_validity':m['status'],'source_type':m['source_type'],'methods':[x for x,used in [('local_semantic',local_score is not None),('provider_semantic',external_score is not None),('lexical',overlap>0),('entity',entity_score>0),('structured',st>0)] if used]}
            scored.append((choice!='BLOCK',influence,local_score or 0,m,relevance,choice,reason,dscore))
        scored.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
        chosen=0
        # Full profile / contextual requests can include several independent fact slots.
        budget=max(req['budget'],6 if req['id'] in ('context','preference','goal','skill','constraint','education') else 1)
        for rank,(_,inf,_,m,rel,choice,reason,dscore) in enumerate(scored,1):
            if choice!='BLOCK' and chosen>=budget:choice='BLOCK';reason='Per-requirement relevance budget reached'
            if choice!='BLOCK':
                chosen+=1
                item=merged.setdefault(m['id'],{**m,'influence':round(inf,3),'decision':choice,'matched_requirements':[]})
                item['matched_requirements'].append(req['id']);item['influence']=max(item['influence'],round(inf,3))
            dscore.update(rank=rank,decision=choice,reason=reason);candidate_diagnostics.append(dscore)
            prior=decisions.get(m['id'])
            d={**dscore,'decision':choice,'relevance':round(rel,3),'impact':round(rel,3),'influence':round(inf,3) if choice!='BLOCK' else 0,'reason':reason}
            if not prior or (choice!='BLOCK' and (prior['decision']=='BLOCK' or d['influence']>prior['influence'])):decisions[m['id']]=d
    # Bounded spreading activation: use existing project edges and conservative
    # shared-entity edges. Edges suggest possible association, never a new fact.
    if any(r['id'] in ('project','context') for r in requirements) and not access.get('project_exclusion'):
        by_id={m['id']:m for m in eligible}; visited=set(merged); frontier=set(merged); candidates=[]
        for depth in (1,2):
            next_frontier=set()
            for e in edges:
                relation=e['relation']
                if not (relation in ('uses','belongs_to','project context') or relation.startswith('associated_entity:')):continue
                for a,b in ((e['source_id'],e['target_id']),(e['target_id'],e['source_id'])):
                    if a not in frontier or b in visited or b not in by_id:continue
                    m=by_id[b]
                    if m['status'] not in ('ACTIVE','ESTABLISHED','DORMANT','PROVISIONAL') or m['source_type']=='SUPPORTED_CONCLUSION':continue
                    if m['memory_type'] not in ('Project','Skill','Decision','Constraint','Goal','Plan'):continue
                    next_frontier.add(b)
                    relevance=.78 if depth==1 else .63
                    score=relevance*(.42*m['confidence']+.22*m['importance']+.20*m['activation']+.16*m['freshness'])*(.8 if m['status']=='PROVISIONAL' else 1)
                    if score>=s['threshold']:
                        candidates.append((score,m,relation,depth))
            visited.update(next_frontier);frontier=next_frontier
            if not frontier:break
        for inf,m,relation,depth in sorted(candidates,key=lambda x:x[0],reverse=True)[:3]:
            if m['id'] in merged:continue
            merged[m['id']]={**m,'influence':round(inf,3),'decision':'USE','matched_requirements':['project_relationship'],'association_note':'Possible association via recorded graph edge; not a claim of user intent. Provisional items remain unconfirmed.','association_relation':relation}
            decisions[m['id']]={'memory_id':m['id'],'content':m['content'],'decision':'USE','relevance':.78 if depth==1 else .63,'impact':.78 if depth==1 else .63,'influence':round(inf,3),'reason':'Possible association via recorded '+relation+' edge; scope and relevance checked','requirement':'project_relationship','category':m.get('memory_category'),'temporal_validity':m['status'],'source_type':m['source_type'],'methods':['association'],'ranking_score':round(inf,3)}
    approved=[];chars=0
    # Reserve one best candidate for every requirement before additional matches.
    ordered=[]
    for r in requirements:
        matches=[m for m in merged.values() if r['id'] in m['matched_requirements']]
        if matches:ordered.append(max(matches,key=lambda m:m['influence']))
    ordered+=sorted(merged.values(),key=lambda m:m['influence'],reverse=True)
    seen=set()
    for m in ordered:
        if m['id'] in seen:continue
        seen.add(m['id'])
        if len(approved)>=40 or chars+len(m['content'])>24000:
            decisions[m['id']].update(decision='BLOCK',influence=0,reason='Global context safety bound reached');continue
        approved.append(m);chars+=len(m['content'])
    from . import experience_memory
    for e in experience_memory.search(text,access,conversation_id):
        # Episodic summaries already cover this recall; avoid redundant experience injection.
        if e['matched_requirements']==['episode'] and any('episode' in m['matched_requirements'] for m in approved):continue
        if len(approved)>=40 or chars+len(e['content'])>24000:continue
        approved.append(e);chars+=len(e['content'])
        decisions[e['id']]={'memory_id':e['id'],'experience_id':e['experience_record_id'],'content':e['content'],'decision':'LIMIT','relevance':round(e['relevance'],3),'impact':round(e['relevance'],3),'influence':e['influence'],'reason':'Relevant captured experience; quoted history, not an asserted user fact'}
    for m in memories:
        if m['id'] not in decisions and (access['memory_needed'] or access['boundary']):
            if not access['memory_needed'] or access['memory_mode']=='ISOLATED':why='Memory access disabled or isolated'
            elif m['status'] in ('ARCHIVED','DELETED','CANDIDATE'):why='Excluded lifecycle state'
            elif m['source_type'] in ('ASSISTANT_SUGGESTION','LLM_INFERENCE'):why='Unconfirmed or inferred source excluded'
            elif m['source_type']=='SUPPORTED_CONCLUSION' and m['id'] in supported:why='Source conclusion invalidated'
            elif not scope_allowed(m,access):why='Outside allowed context or project scope'
            else:why='No matching requested category or slot'
            decisions[m['id']]={'memory_id':m['id'],'content':m['content'],'decision':'BLOCK','relevance':0,'impact':0,'influence':0,'reason':why,'category':m.get('memory_category'),'temporal_validity':m['status'],'source_type':m['source_type'],'methods':[]}
    access['candidate_diagnostics']=candidate_diagnostics
    coverage=[]
    for r in requirements:
        matches=[m['id'] for m in approved if r['id'] in m['matched_requirements']]
        coverage.append({'id':r['id'],'label':r['label'],'required':r['required'],'status':'covered' if matches else 'missing','memory_ids':matches})
    required=[r for r in coverage if r['required']];covered=sum(r['status']=='covered' for r in required)
    access['coverage']={'covered':covered,'total':len(required),'requirements':coverage,'missing':[r['label'] for r in required if r['status']=='missing'],'ratio':covered/len(required) if required else None}
    with db.connect() as c:
        for d in decisions.values():
            if d.get('experience_id'):
                c.execute('INSERT INTO experience_usage_logs VALUES(?,?,?,?,?,?,?,?)',(db.uid(),d['experience_id'],conversation_id,d['decision'],d['relevance'],d['influence'],d['reason'],db.now()))
                c.execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)',(db.uid(),None,conversation_id,'EXPERIENCE_RETRIEVED',d['reason'],db.now()))
                continue
            c.execute('INSERT INTO memory_usage_logs VALUES(?,?,?,?,?,?,?,?,?)',(db.uid(),d['memory_id'],conversation_id,d['decision'],d['relevance'],d['impact'],d['influence'],d['reason'],db.now()))
            c.execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)',(db.uid(),d['memory_id'],conversation_id,'MEMORY_BLOCKED' if d['decision']=='BLOCK' else 'MEMORY_RETRIEVED',d['reason'],db.now()))
        for m in approved:
            if m['decision']=='USE':memory_lifecycle.reinforce(m,conversation_id,c)
    access['local_semantic_status']='available' if any(d.get('semantic_similarity') is not None for d in candidate_diagnostics) else 'not used or unavailable'
    state='local_only' if 'unavailable' in semantic_states and access['local_semantic_status']=='available' else 'unavailable' if 'unavailable' in semantic_states else 'disabled' if not s['semantic_enabled'] else 'available' if eligible else 'not needed'
    return approved,list(decisions.values()),state
