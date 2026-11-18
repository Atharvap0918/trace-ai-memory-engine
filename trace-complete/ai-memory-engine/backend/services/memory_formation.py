import re,json
from datetime import datetime,timedelta,timezone
from .. import database as db

def explicit_candidates(text,domain):
    """Conservative explicit-statement extraction. Never reads assistant output."""
    result=[]
    st=text
    def add(content,kind,slot,scope='general',days=None,confidence=.96):
        result.append({'content':content,'memory_type':kind,'slot':slot,'domain':scope,'expected_lifetime':days,'confidence':confidence,'importance':.85 if kind in ('Project','Identity','Constraint') else .70,'source_type':'USER_EXPLICIT','_uncertain_clause':bool(re.search(r'\b(?:might|maybe|probably|possibly|considering)\b',st,re.I))})
    # Questions alone do not establish user facts.
    if re.search(r"don't remember|do not remember|don't save|do not save",text,re.I): return []
    # Split independent self-statements, not lists such as “Python and FastAPI”.
    prepared=re.sub(r"\s*(?:,|\band\b)\s+(?=(?:I(?:['’]m| am| prefer| live| use| want| believe| work| study| have| cannot)|my (?:name|goal|project|current project|main programming))\b)",'. ',text,flags=re.I)
    for sentence in re.split(r'(?<=[.!?])\s+|[;\n]+',prepared):
        st=sentence.strip()
        if not st or st.endswith('?'): continue
        st=st.rstrip('.!').strip()
        match=re.search(r'\bmy name is\s+([\w\- ]{1,60})',st,re.I)
        if match: add('User’s name is '+re.split(r'\s+and\s+',match[1].strip(),flags=re.I)[0]+'.','Identity','identity:name')
        match=re.search(r"\b(?:I am|I'm|I’m) (?:actively )?(?:building|working on|developing)\s+(?:an?\s+)?(.+)",st,re.I)
        if match:
            project=re.split(r'\s+(?:using|with)\s+',match[1],maxsplit=1,flags=re.I)[0].strip(); lifetime=None
            duration=re.search(r'for (?:the )?(?:next )?(\d+|one|two|three|four|six) (days?|weeks?|months?|years?)',project,re.I)
            if duration:
                n=int(duration[1]) if duration[1].isdigit() else {'one':1,'two':2,'three':3,'four':4,'six':6}[duration[1].lower()]
                lifetime=n*(30 if duration[2].startswith('month') else 7 if duration[2].startswith('week') else 365 if duration[2].startswith('year') else 1)
                project=project[:duration.start()].strip()
            if project.lower() in ('this project','the project'): content='User is working on the current project.'
            else: content='User is actively working on '+project+'.'
            add(content,'Temporary Context' if lifetime else 'Project','project:duration' if lifetime else 'project:active',domain,lifetime)
        match=re.search(r'\bI (?:strongly |really |always )?prefer\s+(.+)',st,re.I)
        if match:
            value=match[1].strip(); slot='preference:explanation' if re.search(r'explanations|examples|simple|concise|answers|responses|brief|detailed|step-by-step',value,re.I) else 'preference:'+re.sub(r'\W+','_',value.lower())[:40]
            add('User prefers '+value+'.','Preference',slot)
        stack=re.search(r"(?:\b(?:building|working on|developing)\s+[^.!;]+?\s+using|my (?:current )?project (?:uses|is using)|I (?:now )?(?:mainly |currently )?use|I(?:'m| am|’m) (?:now )?(?:mainly )?using|I(?:'ll| will|’ll) (?:probably|possibly|maybe) use|(?:my )?main programming language is)\s+(.+)",st,re.I)
        if stack and not re.search(r'as my primary programming language',st,re.I):
            provisional=bool(re.search(r'probably|might|maybe',st,re.I)); value=stack[1]
            languages=re.findall(r'\b(Python|JavaScript|TypeScript|Java|Rust|Go|C\+\+|Ruby|PHP|Kotlin|Swift)\b',value,re.I)
            frameworks=re.findall(r'\b(FastAPI|Django|Flask|Express|Next\.js|Spring|React|Vue)\b',value,re.I)
            if languages: add('Current project uses '+' and '.join(dict.fromkeys(languages))+'.','Project','stack:language',domain,confidence=.65 if provisional else .96)
            if frameworks: add('Current project uses '+', '.join(frameworks)+'.','Project','stack:framework',domain)
        # A personal primary-language claim is not automatically a project stack.
        personal=re.search(r"\b(?:I am currently using|I(?:'m| am) using)\s+(.+?)\s+as my primary programming language|\b(Python|JavaScript|TypeScript|Java|Rust|Go|C\+\+|Ruby|PHP|Kotlin|Swift) is my primary (?:programming )?language|\bI (?:have |have now |recently |just )?(?:switched|moved) to\s+(.+)",st,re.I)
        if personal:
            val=next((g for g in personal.groups() if g),'')
            langs=re.findall(r'(?<!\w)(Python|JavaScript|TypeScript|Java|Rust|Go|C\+\+|Ruby|PHP|Kotlin|Swift)(?!\w)',val,re.I)
            if langs and not re.search(r'\b(?:might|maybe|considering)\b',st,re.I):
                if re.search(r'\b(?:temporarily|for now|this week|today)\b',st,re.I):
                    add(st+'.','Temporary Context','personal:temporary_languages','general',7)
                else:add('User currently uses '+', '.join(dict.fromkeys(langs))+' as '+('a primary programming language.' if len(langs)==1 else 'programming languages.'),'Skill','personal:current_languages','general')
        # A named project description records what was said, without asserting ownership.
        description=re.match(r"(?:(?:my )?[Pp]roject\s+)?([A-Z][A-Za-z0-9_-]{2,})\s+(?:is|automates|helps|connects|uses)\b.+",st)
        if description and domain.startswith('project:') and re.sub(r'[^a-z0-9]+','-',description[1].lower()).strip('-')==domain.split(':',1)[1]:
            add(st+'.','Project','project:description',domain)
        location=re.search(r"\bI (?:live in|am based in) (.+)",st,re.I)
        if location:add('User is based in '+location[1].strip()+'.','General User Context','general:location')
        patterns=[(r"(?:my (?:long[- ]term |primary )?goal is|I want to) (.+)",'Goal','goal'),(r'I (?:am learning|am skilled in|know how to) (.+)','Skill','skill'),(r'I (?:work as|am employed as) (.+)','Career','career'),(r'I (?:study|am studying) (.+)','Education','education'),(r'I (?:cannot|can only|have limited) (.+)','Constraint','constraint'),(r'I believe (.+)','Belief','belief')]
        for pat,kind,slot in patterns:
            m=re.search(pat,st,re.I)
            if m and not (kind=='Goal' and re.match(r'(?:improve|review|fix|help|understand|debug)\b',m[1],re.I)): add(st+'.',kind,slot+':'+re.sub(r'\W+','_',m[1].lower())[:40])
    event_match=re.search(r"I (?:have|have an|have a) (?:an? )?(exam|interview|meeting) (?:in |on )?(next week|tomorrow|next month)",text,re.I)
    if event_match:
        days={'tomorrow':1,'next week':7,'next month':30}[event_match[2].lower()]
        st=event_match.group()
        add('User has an upcoming '+event_match[1].lower()+' '+event_match[2].lower()+'.','Event','event:'+event_match[1].lower(),days=days)
    unique={}
    for fact in result:unique[(fact['domain'],fact['slot'],fact['content'].lower())]=fact
    return list(unique.values())


def candidates(text,domain,enhance=True):
    result=explicit_candidates(text,domain)
    uncertain=bool(re.search(r'\b(?:might|maybe|probably|possibly|considering)\b',text,re.I))
    for x in result:
        if x['memory_type']=='Goal' and not re.search(r'also|another goal',text,re.I):x['slot']='goal:primary'
        if x.pop('_uncertain_clause',False):x['confidence']=min(x['confidence'],.65)
        x['memory_layer']='preference' if x['memory_type']=='Preference' else 'contextual' if x['domain']!='general' or x['memory_type'] in ('Event','Temporary Context') else 'semantic'
        x['protected']=int(x['memory_type'] in ('Identity','Preference'))
    def add(content,kind,slot,scope='general',days=None,layer='semantic'):
        result.append({'content':content,'memory_type':kind,'slot':slot,'domain':scope,'expected_lifetime':days,'confidence':.65 if uncertain else .96,'importance':.7,'source_type':'USER_EXPLICIT','memory_layer':layer,'protected':0})
    if text.rstrip().endswith('?') or re.search(r"don['’]?t (?:remember|save)|do not (?:remember|save)",text,re.I):return result
    clauses=re.split(r'(?<=[.!?])\s+|;|\n',text)
    for sentence in clauses:
        t=sentence.strip().rstrip('.!')
        uncertain=bool(re.search(r'\b(?:might|maybe|probably|possibly|considering)\b',t,re.I))
        patterns=[(r'I (?:enjoy|love|am interested in) (.+)','Interest','interest','general',None),
          (r'I (?:plan to|am planning to) (.+)','Plan','plan',domain,None),
          (r'I (?:am|\x27m|’m) planning (?:a )?trip to (.+)','Plan','plan:trip',domain,90),
          (r'I (?:am|\x27m|’m) preparing for (.+?interview)(.*)','Event','event:interview',domain,30),
          (r'my (?:partner|brother|sister|mother|father) (?:is|works|lives) (.+)','Relationship','relationship','general',None),
          (r'I (?:chose|decided|have decided) (.+)|we decided (.+)','Decision','decision',domain,None),
          (r'I (?:am|\x27m|’m) feeling (.+)','Temporary Context','emotion',domain,1),
          (r'I (?:have|use) (?:an? )?(\d+\s*GB (?:RAM|memory).*)','Constraint','constraint:hardware','general',None),
          (r'my (?:budget|available time) is (.+)','Constraint','constraint:resources',domain,None)]
        for pat,kind,slot,scope,days in patterns:
            m=re.search(pat,t,re.I)
            if m:
                value=next((g for g in m.groups() if g),t)
                if kind=='Interest' and re.search(r'\s+and\s+',value,re.I):
                    for interest in re.split(r'\s+and\s+',value,flags=re.I):
                        add('User is interested in '+interest.strip()+'.',kind,'interest:'+re.sub(r'\W+','_',interest.lower())[:50],scope,days)
                else:add(t+'.',kind,slot if ':' in slot else slot+':'+re.sub(r'\W+','_',value.lower())[:50],scope,days,'contextual' if scope!='general' else 'semantic')
    # Scoped project descriptions and explicitly considered technology stay
    # source-grounded; a consideration is never presented as an adopted decision.
    if domain.startswith('project:') and not text.rstrip().endswith('?'):
        import hashlib
        for sentence in clauses:
            t=sentence.strip().rstrip('.!')
            uncertain=bool(re.search(r'\b(?:might|maybe|probably|possibly|considering)\b',t,re.I))
            if re.search(r'^the project (?:involves|includes|connects|automates)\b',t,re.I):
                add(t+'.','Project','project:detail:'+hashlib.sha256(t.lower().encode()).hexdigest()[:12],domain,None,'contextual')
            considered=re.search(r'^([A-Za-z][A-Za-z0-9.+-]*) is (?:being )?considered for (.+)',t,re.I)
            preferred=re.search(r'^([A-Za-z][A-Za-z0-9.+-]*) is preferred for (.+)',t,re.I)
            if considered or preferred:
                name=(considered or preferred)[1];slot='project:considered:' if considered else 'project:preference:'
                add(t+'.','Project',slot+name.lower(),domain,None,'contextual')
                if considered:result[-1]['confidence']=.65
    unique={}
    for x in result:unique[(x['domain'],x['slot'],x['content'].lower())]=x
    values=list(unique.values())
    significance=bool(re.search(r'\b(?:important|crucial|essential|strongly prefer|long[- ]term|milestone|lesson learned|never forget|always remember)\b',text,re.I))
    if significance:
        for x in values:
            if x['memory_type'] in ('Preference','Goal','Decision','Constraint','Project'):
                x['importance']=max(x['importance'],.9)
    if enhance:
        from .experience_analyzer import enrich
        return enrich(text,domain,values)
    return values

COLUMNS='id,user_id,content,memory_type,domain,slot,source_type,confidence,importance,freshness,status,influence,expected_lifetime,created_at,updated_at,last_confirmed_at,expires_at,superseded_by,conversation_id,evidence_count,memory_layer,activation,last_accessed_at,activation_updated_at,protected,context_id,access_count'.split(',')

def store(cs,text,domain,conversation_id,message_id):
    from . import memory_lifecycle
    out=[]
    with db.connect() as c:
        def log(kind,detail,mid):c.execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)',(db.uid(),mid,conversation_id,kind,detail,db.now()))
        for x in cs:
            # Exact reconfirmation finds dormant rows too, keeping stable IDs.
            existing=c.execute("SELECT * FROM memories WHERE user_id='user_001' AND slot=? AND domain=? AND status IN ('ACTIVE','ESTABLISHED','PROVISIONAL','DORMANT') ORDER BY updated_at DESC LIMIT 1",(x['slot'],x['domain'])).fetchone()
            if not existing and x['slot']=='goal:primary':existing=c.execute("SELECT * FROM memories WHERE memory_type='Goal' AND domain=? AND status IN ('ACTIVE','ESTABLISHED','DORMANT') ORDER BY updated_at DESC LIMIT 1",(x['domain'],)).fetchone()
            old=dict(existing) if existing else None;t=db.now();expires=(datetime.now(timezone.utc)+timedelta(days=x['expected_lifetime'])).isoformat() if x['expected_lifetime'] else None
            if old and old['content'].lower()==x['content'].lower():
                db.version(old,'Explicit reconfirmation; confidence unchanged unless confirmed',c);mid=old['id']
                # Repeating the identical same message is not independent evidence.
                count=old['evidence_count']+int(not c.execute('SELECT 1 FROM memory_evidence WHERE memory_id=? AND message_id=?',(mid,message_id)).fetchone())
                conf=.99 if x['source_type']=='USER_CONFIRMED' else old['confidence']
                state='ACTIVE' if conf>=.75 else 'PROVISIONAL'
                if old['status']=='DORMANT':memory_lifecycle.transition(old,state,'Explicit user resume/reconfirmation',c)
                c.execute('UPDATE memories SET evidence_count=?,confidence=?,status=?,source_type=?,activation=MIN(1,MAX(0.65,activation+0.2)),freshness=1,last_confirmed_at=?,updated_at=?,expires_at=?,activation_updated_at=? WHERE id=?',(count,conf,state,old['source_type'] if x.get('reference_only') else x['source_type'],old['last_confirmed_at'] if x.get('reference_only') else t,t,expires,t,mid));kind='MEMORY_UPDATED'
            else:
                mid=db.uid()
                # An uncertain suggestion cannot silently supersede a confident current fact.
                contested=bool(old and x['confidence']<.75 and old['confidence']>=.75)
                if old and not contested:
                    memory_lifecycle.transition(old,'SUPERSEDED','New explicit statement supersedes applicability',c)
                    c.execute('UPDATE memories SET superseded_by=?,influence=.1 WHERE id=?',(mid,old['id']))
                    relation='goal_changed' if x['memory_type']=='Goal' else 'supersedes'
                    c.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),mid,old['id'],relation))
                    log('GOAL_CHANGED' if x['memory_type']=='Goal' else 'CONFLICT_DETECTED','New explicit evidence retained with prior history',old['id'])
                status='CONTESTED' if contested else 'PROVISIONAL' if x['confidence']<.75 else 'ACTIVE'
                values=(mid,'user_001',x['content'],x['memory_type'],x['domain'],x['slot'],x['source_type'],x['confidence'],x['importance'],1,status,.85,x['expected_lifetime'],t,t,t,expires,None,conversation_id,1,x['memory_layer'],.85,None,t,x.get('protected',0),x['domain'],0)
                c.execute('INSERT INTO memories ('+','.join(COLUMNS)+') VALUES('+','.join('?'*len(COLUMNS))+')',values);kind='MEMORY_CREATED'
                db.version(dict(c.execute('SELECT * FROM memories WHERE id=?',(mid,)).fetchone()),'Initial source-grounded statement',c)
            from .retention_policy import classify
            category,retention=classify(x)
            from .entity_extraction import extract
            c.execute('UPDATE memories SET memory_category=?,retention_class=?,valid_from=?,entities=? WHERE id=?',(category,retention,x.get('valid_from'),json.dumps(extract(x['content'],x['domain'],x['slot']),ensure_ascii=False),mid))
            if not c.execute('SELECT 1 FROM memory_evidence WHERE memory_id=? AND message_id=?',(mid,message_id)).fetchone():
                c.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),mid,conversation_id,message_id,text,x['source_type'],t))
            log(kind,x['content'],mid);out.append({'id':mid,'action':kind,'content':x['content']})
        scopes={x['domain'] for x in cs}
        for scope in scopes:
            c.execute('INSERT OR IGNORE INTO memory_contexts VALUES(?,?,?,?,?,?,?)',(scope,'user_001',scope.split(':')[0] if ':' in scope else 'personal',scope,'ACTIVE',db.now(),db.now()))
            active=c.execute("SELECT id,slot FROM memories WHERE domain=? AND status IN ('ACTIVE','ESTABLISHED','PROVISIONAL')",(scope,)).fetchall()
            for p in [r for r in active if r['slot'] in ('project:active','project:description')]:
                for r in active:
                    if p['id']!=r['id']:
                        relation='uses' if r['slot'].startswith('stack:') else 'belongs_to'
                        source,target=(p['id'],r['id']) if relation=='uses' else (r['id'],p['id'])
                        c.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),source,target,relation))
    identity=db.one("SELECT id FROM memories WHERE slot='identity:name' AND status='ACTIVE' ORDER BY updated_at DESC LIMIT 1")
    if identity:
        for m in db.rows("SELECT id,memory_type,slot FROM memories WHERE status='ACTIVE' AND id!=?",(identity['id'],)):
            relation='lives_in' if m['slot']=='general:location' else 'works_on' if m['slot']=='project:active' else 'prefers' if m['memory_type']=='Preference' else None
            if relation:db.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),identity['id'],m['id'],relation))
    if out:
        from . import associative_memory
        associative_memory.invalidate_inactive_sources()
        associative_memory.refresh_associations([item['id'] for item in out])
    return out

def form(text,domain,conversation_id,message_id,candidates_override=None):
    from . import memory_lifecycle
    cancelled=bool(re.search(r'(?:(?:this|my|the) project (?:is |has been )?cancelled|cancel(?:led)? (?:this|my|the) project|no longer (?:working on|building))',text,re.I))
    if cancelled:
        old=db.rows("SELECT * FROM memories WHERE domain=? AND slot IN ('project:active','project:duration') AND status IN ('ACTIVE','ESTABLISHED','PROVISIONAL','DORMANT')",(domain,))
        for m in old:memory_lifecycle.transition(m,'SUPERSEDED','User explicitly cancelled this context')
        for m in db.rows("SELECT * FROM memories WHERE domain=? AND slot LIKE 'stack:%' AND status IN ('ACTIVE','ESTABLISHED','PROVISIONAL','DORMANT')",(domain,)):memory_lifecycle.transition(m,'STALE','Cancelled project stack retained as historical context')
        db.execute("UPDATE memory_contexts SET state='ARCHIVED',updated_at=? WHERE id=?",(db.now(),domain))
        x={'content':'User cancelled the current project.','memory_type':'Decision','slot':'project:cancelled','domain':domain,'expected_lifetime':None,'confidence':.99,'importance':.85,'source_type':'USER_EXPLICIT','memory_layer':'contextual','protected':0}
        out=store([x],text,domain,conversation_id,message_id)
        for m in old:
            db.execute('UPDATE memories SET superseded_by=? WHERE id=?',(out[0]['id'],m['id']));db.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),out[0]['id'],m['id'],'supersedes'))
        db.execute("UPDATE memory_contexts SET state='ARCHIVED',updated_at=? WHERE id=?",(db.now(),domain))
        return out
    cs=candidates_override if candidates_override is not None else candidates(text,domain)
    retracted=re.search(r'\b(Python|JavaScript|TypeScript|Java|Rust|Go|C\+\+|Ruby|PHP|Kotlin|Swift) is no longer my primary (?:programming )?language',text,re.I)
    if retracted and not re.search(r'\b(?:might|maybe|possibly)\b',text,re.I) and not any(x['slot']=='personal:current_languages' for x in cs):
        old=db.one("SELECT * FROM memories WHERE slot='personal:current_languages' AND status IN ('ACTIVE','ESTABLISHED','DORMANT') ORDER BY updated_at DESC LIMIT 1")
        if old and re.search(r'(?<!\w)'+re.escape(retracted[1])+r'(?!\w)',old['content'],re.I):
            memory_lifecycle.transition(old,'SUPERSEDED','User explicitly retracted primary-language applicability')
            db.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),old['id'],conversation_id,message_id,text,'USER_EXPLICIT',db.now()))
    if not cs:db.event('EXPERIENCE_HISTORY_ONLY','Interaction retained in experience/history; no distilled candidate',conversation_id=conversation_id);return []
    return store(cs,text,domain,conversation_id,message_id)

def interaction(text,response,domain,conversation_id,message_id,assistant_id=None,candidates_override=None):
    """Analyze both sides. Suggestions remain candidates, not asserted user facts."""
    out=form(text,domain,conversation_id,message_id,candidates_override)
    accept=bool(re.search(r"^(?:yes|agreed|okay|ok|let['’]s|i agree|we will|i confirm)|let['’]s use",text.strip(),re.I))
    reject=bool(re.search(r'\b(?:no|reject|not|instead)\b',text,re.I))
    accept_option=bool(re.search(r"let['’]s use|use (?:that|it)|(?:yes|agreed|okay|ok)[,.!]?(?:\s+(?:that|let|use)|$)|i agree|i confirm",text.strip(),re.I))
    if accept and accept_option and not reject:
        suggestion=db.one("SELECT * FROM interaction_candidates WHERE conversation_id=? AND role='assistant' AND status='CANDIDATE' ORDER BY created_at DESC LIMIT 1",(conversation_id,))
        if suggestion:
            # Bind acceptance to a unique recent option; ambiguous multiple choices remain candidates.
            options=re.findall(r'\b(FastAPI|Django|Flask|React|Vue|Python|JavaScript|TypeScript|Java|Rust|Go)\b',suggestion['content'],re.I)
            named=[o for o in options if re.search(r'\b'+re.escape(o)+r'\b',text,re.I)]
            unique=list(dict.fromkeys(named or options))
            if len(unique)==1:
                option=unique[0];cs=candidates('My project uses '+option+'.',domain)
                for x in cs:x.update(source_type='USER_CONFIRMED',confidence=.99,content=option+' selected for the current project.',memory_category='USER_CONFIRMED_DECISION')
                approved=store(cs,text,domain,conversation_id,message_id);out+=approved
                db.execute("UPDATE interaction_candidates SET status='ACTIVE',accepted_by=? WHERE id=?",(message_id,suggestion['id']))
                for x in approved:
                    db.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),x['id'],conversation_id,suggestion['message_id'],suggestion['content'],'ASSISTANT_SUGGESTION',db.now()))
    if reject:
        db.execute("UPDATE interaction_candidates SET status='ARCHIVED' WHERE conversation_id=? AND status='CANDIDATE'",(conversation_id,))
    if response and re.search(r'you (?:could|can|might|should)|i (?:suggest|recommend)|consider (?:using )?|^use\b|let[’\x27]s use',response,re.I):
        db.execute('INSERT INTO interaction_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(db.uid(),conversation_id,assistant_id,domain,response[:3000],'assistant','suggestion','CANDIDATE',None,db.now()))
        db.event('ASSISTANT_SUGGESTION_CAPTURED','Proposal stored separately; user confirmation required',conversation_id=conversation_id)
    return out
