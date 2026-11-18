"""Decompose the request before independent retrieval. No fixed whole-query top-K."""
import re
from .. import database as db
from .query_v1_compat import legacy_analyze,ALL_TYPES
from .query_understanding import understand
ALL_TYPES=ALL_TYPES+['Plan','Interest','Relationship','Decision','Episodic']
def boundary(text):
    q=text.lower()
    return bool(re.search(r"(?:don['’]?t|do not|never).{0,35}(?:use |access |retrieve )?(?:any |my |the |stored |persistent )?(?:memor(?:y|ies)|past chats|previous conversations)|ignore.{0,20}(?:all |my )?memor|isolated conversation|without (?:any )?memory",q)) or bool(re.search(r'completely new|fresh context',q))

def analyze(text,conversation,s):
    q=text.lower();full=bool(re.search(r"(?:don['’]?t|do not|never|ignore).{0,25}(?:use |access |retrieve )?(?:any |all |my |the |stored |persistent )?memor(?:y|ies)|without (?:any )?memory|isolated conversation",q))
    project_exclusion=bool(re.search(r"completely new project|(?:don['’]?t|do not|ignore).{0,55}(?:previous|old) project|new project.{0,35}(?:ignore|different)",q))
    # Reuse V1 intent patterns but distinguish scoped exclusions from global ones.
    safe_text=text
    if project_exclusion:safe_text=re.sub(r"completely new|don['’]?t|do not|ignore|previous|old",'',text,flags=re.I)
    a=legacy_analyze(safe_text,conversation,s)
    understanding=understand(text)
    a.update(
        original_query=text,
        query_language=understanding["language"],
        normalized_query=understanding["normalized_query"],
        multilingual_intents=understanding["intents"],
    )
    type_map={
        'education':['Education'],'goal':['Goal'],'career':['Career'],
        'project':['Project','Temporary Context'],'preference':['Preference'],
        'name':['Identity'],'location':['General User Context'],
    }
    if not full and not project_exclusion:
        for group in understanding["intents"]:
            if group not in a['requested_groups']:
                a['requested_groups'].append(group)
            a['allowed_types'].extend(type_map.get(group,[]))
    if project_exclusion:
        a.update(memory_mode=s['memory_mode'],current_domain='project:'+conversation['id'],blocked_domains=[conversation['domain']],boundary=True,project_exclusion=True)
        db.execute('UPDATE conversations SET domain=? WHERE id=?',(a['current_domain'],conversation['id']))
    else:a['project_exclusion']=False
    if full or s['memory_mode']=='ISOLATED':a.update(memory_mode='ISOLATED',boundary=True)
    elif not project_exclusion and a['memory_mode']=='ISOLATED':a['memory_mode']=s['memory_mode'];a['boundary']=False
    # Named project descriptions establish a scope, not ownership or intent.
    if not full and not project_exclusion and not text.rstrip().endswith('?'):
        named=re.search(r"(?:^|[.!;]\s+)(?:my )?[Pp]roject\s+([A-Z][A-Za-z0-9_-]+)\s+(?:is|automates|helps|connects|uses)\b|(?:^|[.!;]\s+)([A-Z][A-Za-z0-9_-]{2,})\s+is\s+(?:an? |the )",text)
        if named and (named.group(1) or re.search(r'\b(?:project|app|application|assistant|platform|system|tool|software|product)\b',text,re.I)):
            name=next(x for x in named.groups() if x);domain='project:'+re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')
            a['current_domain']=domain;db.execute('UPDATE conversations SET domain=? WHERE id=?',(domain,conversation['id']))
    # Other contextual domains use the same durable, user-defined scope system.
    context_patterns=[('career',r'(?:i am|i’m|i\x27m) (?:preparing for|working toward) (?:an? )?(.+?interview)'),('learning',r'(?:i am|i’m|i\x27m) learning (.+?)(?:[.!;]|$)'),('travel',r'(?:i am|i’m|i\x27m) planning (?:a )?trip to (.+?)(?:[.!;]|$)')]
    for kind,pattern in context_patterns:
        m=re.search(pattern,q)
        if m and not full and not project_exclusion:
            domain=kind+':'+re.sub(r'[^a-z0-9]+','-',m[1]).strip('-')[:70]
            a['current_domain']=domain;db.execute('UPDATE conversations SET domain=? WHERE id=?',(domain,conversation['id']));break
    if not project_exclusion and not full:
        contexts=db.rows("SELECT * FROM memory_contexts WHERE id!='general' AND state!='ARCHIVED' ORDER BY updated_at DESC")
        matches=[]
        for context in contexts:
            label=context['id'].split(':',1)[-1].replace('-',' ')
            if label and (label in q or context['kind']=='career' and 'interview' in q or context['kind']=='travel' and 'trip' in q):matches.append(context)
        if len(matches)==1:
            a['current_domain']=matches[0]['id'];db.execute('UPDATE conversations SET domain=? WHERE id=?',(a['current_domain'],conversation['id']))
    # The scoped project may be resolved by the actual stored description, not
    # only by repeating its name. Refuse ambiguous or weak matches.
    if s['memory_enabled'] and not full and not project_exclusion and a['memory_mode']=='OPEN' and re.search(r'\b(?:my|our|this)\b',q) and len(q.split())>=5:
        from . import local_semantic
        projects=db.rows("SELECT * FROM memories WHERE memory_type='Project' AND slot IN ('project:active','project:description') AND status IN ('ACTIVE','ESTABLISHED','DORMANT')")
        scores=local_semantic.similarities(text,[(m['id'],m['content']) for m in projects])
        ranked=sorted(((scores.get(m['id'],-1),m) for m in projects),key=lambda x:x[0],reverse=True)
        if ranked and ranked[0][0]>=.38 and (len(ranked)==1 or ranked[0][1]['domain']==ranked[1][1]['domain'] or ranked[0][0]-ranked[1][0]>=.06):
            a['current_domain']=ranked[0][1]['domain'];a['semantic_project_match']={'memory_id':ranked[0][1]['id'],'score':ranked[0][0]}
    a['historical']=a['historical'] or bool(re.search(r'previous (?:goals?|decisions?)|old goals?|used to|original goal|\bpreviously\b|\bdid i previously\b|\bhave my .* changed\b',q))
    groups=a['requested_groups'];types=a['allowed_types']
    if re.search(r'why.{0,45}(?:start|began|begin)|original (?:reason|objective|purpose)|what (?:did|have) (?:we|i) (?:decide|reject)|earlier (?:decision|reason)|recap (?:our|this) (?:conversation|discussion)|forgot.{0,40}(?:why|reason)',q):
        groups.append('episode');types+=['Episodic','Decision'];a['historical']=True
    for group,pat,kinds in [('plan',r'\bmy (?:travel |trip |study )?plans?\b|what am i planning',['Plan']),('interest',r'my interests?|my hobbies|what do i enjoy',['Interest']),('relationship',r'my (?:family|partner|relationships?)',['Relationship']),('context',r'help.{0,20}(?:prepare|interview)|prepare.{0,20}interview|resume.{0,30}(?:project|plan|learning)|continue.{0,20}(?:project|trip)', ['Project','Event','Career','Skill','Constraint','Plan','Temporary Context'])]:
        if re.search(pat,q):groups.append(group);types+=kinds
    if re.search(r'\b(?:improve|continue|review|help with|work on) (?:my |our |this |the |current )?(?:project|app|application)\b',q) and 'project' not in groups:
        groups.append('project');types+=['Project','Temporary Context']
    # Model-based requirement discovery: independent clauses are encoded against
    # schema descriptions; no manually curated synonym table is used.
    semantic_requirements=[]
    if not full and not project_exclusion and not a['profile_summary'] and s['memory_enabled'] and (re.search(r'\b(?:i|my|me|our|we|project)\b',q) or (a['current_domain']!='project:default' and re.search(r'\b(?:in use|using)\b',q))) and ( '?' in q or re.match(r'^(?:what|which|who|where|how|tell me|show me|remind me|describe|summari[sz]e|list|recall)',q)):
        from . import local_semantic
        fragments=re.split(r'\?|,|;|\band\s+(?=(?:what|which|where|who|how)\b)',text,flags=re.I)
        for part in fragments:
            part=part.strip()
            if len(part.split())<3:continue
            predicted=local_semantic.classify(part)
            if not predicted:
                # Strong direct semantic match to an existing, in-scope memory can
                # identify a requirement even when category anchors are weak.
                rows=db.rows("SELECT * FROM memories WHERE user_id='user_001' AND status IN ('ACTIVE','ESTABLISHED','DORMANT') AND source_type IN ('USER_EXPLICIT','USER_CONFIRMED')")
                rows=[m for m in rows if m['domain'] in ('general',a['current_domain']) and (a['memory_mode']!='RESTRICTED' or m['domain']==a['current_domain'])]
                scores=local_semantic.similarities(part,[(m['id'],m['content']) for m in rows])
                matches=sorted(((scores.get(m['id'],-1),m) for m in rows),key=lambda x:x[0],reverse=True)
                if matches and matches[0][0]>=.42 and (len(matches)==1 or matches[0][0]-matches[1][0]>=.10):
                    m=matches[0][1];kind={'Goal':'goal','Education':'education','Identity':'name','Preference':'preference','Interest':'interest','Career':'career','Constraint':'constraint','Project':'project'}.get(m['memory_type'])
                    if m['slot'].startswith('stack:'):kind='stack'
                    if kind:predicted=[(kind,matches[0][0])]
            if not predicted:continue
            best=predicted[0][0]
            if best in groups:continue
            # A second plausible class is retained only if this clause has no
            # existing interpretation; ambiguity is not resolved as a fact.
            choices=predicted if not groups or len(fragments)>1 else predicted[:1]
            for group,score in choices:
                if group not in groups:groups.append(group);semantic_requirements.append({'id':group,'score':score,'clause':part})
        type_map={'goal':['Goal'],'education':['Education'],'project':['Project','Temporary Context'],'stack':['Project','Skill'],'preference':['Preference'],'interest':['Interest'],'career':['Career'],'constraint':['Constraint'],'name':['Identity'],'location':['General User Context'],'experience':['Conversation Experience']}
        for group in groups:types+=type_map.get(group,[])
    a['semantic_requirements']=semantic_requirements
    if a['profile_summary']:types=ALL_TYPES.copy()
    groups=list(dict.fromkeys(groups));a.update(requested_groups=groups,allowed_types=list(dict.fromkeys(types)))
    a['memory_needed']=bool(types) and s['memory_enabled'] and a['memory_mode']!='ISOLATED'
    specs={
        'name':('Name',['Identity'],['identity:name']),
        'location':('Location',['General User Context'],['general:location']),
        'project':('Current project',['Project','Temporary Context'],['project:active','project:duration','project:description']),
        'stack':('Technology stack',['Project','Skill'],['stack:language','stack:framework','personal:current_languages']),
        'preference':('Preferences',['Preference'],[]),
        'explanation_style':('Explanation style',['Preference'],['preference:explanation']),
        'goal':('Goals',['Goal'],[]),'career':('Career',['Career'],[]),'education':('Education',['Education'],[]),
        'skill':('Skills',['Skill'],[]),'constraint':('Constraints',['Constraint'],[]),'belief':('Beliefs',['Belief'],[]),
        'event':('Upcoming events',['Event'],[]),'episode':('Earlier objectives and decisions',['Episodic','Decision'],[]),
        'plan':('Plans',['Plan'],[]),'interest':('Interests',['Interest'],[]),'relationship':('Relationships',['Relationship'],[]),
        'context':('Relevant active context',['Project','Event','Career','Skill','Constraint','Plan','Temporary Context'],[]),
        'history':('Historical project context',['Project','Temporary Context','Episodic'],[])}
    if re.search(r'where (?:am i|will i be) (?:moving|shifting)|my (?:move|relocation)|moving plans?|planned move',q):
        groups.append('transition');types+=['Plan','Event'];specs['transition']=('Planned move',['Plan','Event'],['location:planned'])
    if re.search(r'what (?:did|have) (?:i|we|you) (?:ask|say|discuss|suggest)|earlier (?:message|discussion)|previous conversation|recall.{0,20}discussion',q):
        groups.append('experience');types+=['Conversation Experience'];specs['experience']=('Relevant conversation experiences',['Conversation Experience'],[])
    if re.search(r'my (?:student|university|college)|where (?:do )?i study|what (?:am )?i studying|my (?:course|major|degree|education)',q):
        if 'education' not in groups:groups.append('education')
        types+=['Education']
    if not groups and s['memory_enabled'] and a['memory_mode']!='ISOLATED' and re.match(r'^(?:what|which|where|who|when)\b',q) and re.search(r'\b(?:my|i|me|our)\b',q):
        groups.append('unresolved');specs['unresolved']=('Requested personal fact',[],[])
    a.update(requested_groups=list(dict.fromkeys(groups)),allowed_types=list(dict.fromkeys(types)),memory_needed=bool(types) and s['memory_enabled'] and a['memory_mode']!='ISOLATED')
    selected=list(specs) if a['profile_summary'] else groups
    requirements=[]
    for group in selected:
        if group not in specs:continue
        label,kinds,slots=specs[group]
        # Stack components have separate searches/coverage, not one truncated vector query.
        targets=[('language',['stack:language','personal:current_languages']),('framework',['stack:framework'])] if group=='stack' else [('',slots)]
        for suffix,scoped_slots in targets:
            requirements.append({'id':group+(':'+suffix if suffix else ''),'label':label+(' · '+suffix if suffix else ''),'types':kinds,'slots':scoped_slots,'query':label+' '+suffix+' '+a.get('normalized_query',text),'required':not a['profile_summary'] and group not in ('explanation_style','history','context'),'budget':max(1,s['top_k'])})
    if a['historical'] and re.search(r'\bprogramming\b',q) and re.search(r'\bchanged?\b',q) and not any(r['id'].startswith('stack:') for r in requirements):
        requirements.append({'id':'stack:language','label':'Programming language history','types':['Project','Skill'],'slots':['personal:current_languages','stack:language'],'query':text,'required':True,'budget':max(2,s['top_k'])})
    personal_language_query=bool((re.search(r'\b(?:programming )?languages?\b',q) or (a['historical'] and re.search(r'\bprogramming\b',q)) or re.search(r'\bprimary\b',q)) and not re.search(r'\bproject\b',q) and (bool(re.search(r'\bprimary\b',q)) or not re.search(r'\b(?:stack|framework|technolog)\w*\b',q)))
    if personal_language_query:
        a['personal_language_query']=True
        requirements=[r for r in requirements if r['id']!='stack:framework']
    a['history_only']=bool(a['historical'] and re.search(r'\b(?:previously|previous|formerly|used to|before)\b',q) and not re.search(r'\b(?:changed|change|now|current|both)\b',q))
    if any(r['id']=='project' for r in requirements):
        requirements.append({'id':'project_context','label':'Related project decisions and constraints','types':['Decision','Constraint','Episodic'],'slots':[],'query':text,'required':False,'budget':min(3,max(1,s['top_k']))})
    a['requirements']=requirements;a['multi_fact']=len([r for r in requirements if r['required']])>1
    a['retrieval_strategy']='independent structured + semantic searches; coverage-aware fusion'
    a['retrieval_limit']=40 # Global safety bound only, not the mechanism for recall.
    return a
