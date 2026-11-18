"""Source-grounded experience analysis; persistent retention is a separate decision.
No assistant text is used as evidence for user profile extraction.
"""
import re
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from .. import database as db
from . import retention_policy

def timepoint(word,stamp=None,time_zone='UTC'):
    try:zone=ZoneInfo(time_zone)
    except (ValueError,ZoneInfoNotFoundError):zone=timezone.utc
    clock=datetime.fromisoformat(stamp or db.now()).astimezone(zone)
    days=1 if word.lower()=='tomorrow' else 7 if 'week' in word.lower() else 30 if 'month' in word.lower() else 0
    return (clock+timedelta(days=days)).replace(hour=0,minute=0,second=0,microsecond=0).isoformat()

def enrich(text,domain,base,conversation_id=None,message_id=None,stamp=None,time_zone='UTC'):
    result=list(base);clean=text.strip().replace('’',"'")
    if re.search(r"\b(?:don't|do not) (?:save|remember)\b",clean,re.I):return []
    def add(content,kind,slot,scope='general',days=None,category=None,retention=None,**metadata):
        x={'content':content,'memory_type':kind,'slot':slot,'domain':scope,'expected_lifetime':days,'confidence':.96,'importance':.85 if kind in ('Education','Event') else .8,'source_type':'USER_EXPLICIT','memory_layer':'contextual' if days or kind in ('Plan','Event','Temporary Context') or scope!='general' else 'semantic','protected':int(kind in ('Identity','Preference','Education'))}
        if category:x['memory_category']=category
        if retention:x['retention_class']=retention
        x.update(metadata);result.append(x)
    clauses=re.split(r'(?<=[.!?])\s+|;|\n|\s+and\s+(?=I\b|my\b)',clean,flags=re.I)
    for t in clauses:
        t=t.strip().rstrip('.!')
        if not t or t.endswith('?'):continue
        student=re.search(r"\bI(?: am|'m) (?:an? )?(.+?) student(?:\s+at\s+(.+))?$",t,re.I)
        study=re.search(r"\bI(?: am|'m) studying (.+?)(?:\s+at\s+(.+))?$",t,re.I)
        found=student or study
        if found:
            subject=found[1].strip();subject='Computer Science' if subject.lower() in ('cs','computer science') else subject
            # Canonical course slot lets differently phrased supporting statements reinforce it.
            prior=db.one("SELECT content FROM memories WHERE slot='education:subject' AND status IN ('ACTIVE','ESTABLISHED','DORMANT')")
            content='User is a '+subject+' student.' if student else prior['content'] if prior and subject.lower() in prior['content'].lower() else 'User studies '+subject+'.'
            add(content,'Education','education:subject')
            school=found[2]
            if school:
                city=None
                loc=re.search(r'(?:\s+in\s+([A-Z][\w -]+)|\s+(Pune|Mumbai|Delhi|Bangalore|Chennai))$',school,re.I)
                if loc:city=(loc[1] or loc[2]).strip();school=school[:loc.start()].strip()
                add('User studies at '+school+'.','Education','education:institution')
                if city:add('User studies in '+city+'.','Education','education:location')
        institute=re.search(r"\bI (?:study|am enrolled) at (.+)",t,re.I)
        if institute:add('User studies at '+institute[1].strip()+'.','Education','education:institution')
        # Preserve only explicitly stated milestones and lessons as user text;
        # emotion alone is not evidence of a lasting preference or goal.
        significant=re.search(r"\b(?:we|i|my project) (?:reached|completed|achieved) (?:an? |the )?(?:important |major )?milestone\b|\b(?:i learned|we learned|lesson learned)\b.{3,}",t,re.I)
        if significant and not re.search(r"\b(?:maybe|might|possibly)\b",t,re.I):
            import hashlib
            slot='decision:experience:'+hashlib.sha256(t.lower().encode()).hexdigest()[:16]
            add(t+'.','Decision',slot,domain,importance=.9)
        # No residence assumption is made from a university's campus city.
        event=re.search(r"\bI (?:have|am preparing for|'m preparing for) (?:an? |my )?((?:technical |backend |job )?(?:interview|exam|meeting))(?:\s+(?:on |in )?(tomorrow|next week|next month))?",t,re.I)
        if event:
            label=event[1].strip().lower();when=event[2];kind=label.split()[-1]
            result=[x for x in result if x['slot']!='event:'+kind]
            add('User has '+('a ' if label.startswith(('technical','backend','job','meeting')) else 'an ')+label+(' '+when if when else ' coming up')+'.','Event','event:'+kind,scope=domain if domain.startswith('career:') else 'general',days=3 if when=='tomorrow' else 14 if when=='next week' else 40 if when else 30,category='TEMPORARY_CONTEXT',retention='SHORT_TERM' if when in ('tomorrow','next week') else 'MEDIUM_TERM',valid_from=timepoint(when,stamp,time_zone) if when else None)
        pending=re.search(r"\bI(?: am|'m) preparing for (?:something important|something)",t,re.I)
        if pending:add(t+'.','Temporary Context','working:preparation',domain,7,'WORKING_CONTEXT','SHORT_TERM')
        move=re.search(r"\bI(?: am|'m) (?:moving|shifting)(?: from (.+?))? to (.+?)(?: (tomorrow|next week|next month))?$",t,re.I)
        if move:
            origin,destination,when=move.groups();old=db.one("SELECT * FROM memories WHERE slot='general:location' AND status IN ('ACTIVE','ESTABLISHED','DORMANT') ORDER BY updated_at DESC LIMIT 1")
            origin=origin or (re.sub(r'^User (?:is based|lives) in |\.$','',old['content']) if old else None)
            when=when or 'next week'
            add('User plans to move'+(' from '+origin if origin else '')+' to '+destination+' '+when+'.','Plan','location:planned',days=30,category='EVENT',retention='MEDIUM_TERM',confidence=.96,temporal_transition={'from_state':origin,'to_state':destination,'effective_at':timepoint(when,stamp,time_zone),'old_memory_id':old['id'] if old else None},valid_from=timepoint(when,stamp,time_zone))
        confirmed=re.search(r"\bI(?: have|'ve) (?:moved|shifted) to (.+)|\bI(?: am|'m) now living in (.+)",t,re.I)
        if confirmed:
            city=next(g for g in confirmed.groups() if g).strip()
            add('User is based in '+city+'.','General User Context','general:location',confirmed_location=city,source_type='USER_CONFIRMED',confidence=.99)
        semester=re.search(r"\bI(?: am|'m) working on (.+?) (?:this semester|for this semester)$",t,re.I)
        if semester:
            result=[x for x in result if not x['slot'].startswith('project:')]
            add('User is actively working on '+semester[1]+'.','Project','project:active',domain,120,'PROJECT_CONTEXT','MEDIUM_TERM')
    # Resolve only user-authored recent experiences from the same context, never a guessed assistant assertion.
    recent=[]
    if conversation_id:
        recent=db.rows("SELECT * FROM conversation_experiences WHERE conversation_id=? AND current_context=? AND message_id!=? ORDER BY timestamp DESC LIMIT 6",(conversation_id,domain,message_id or ''))
    if re.search(r"^(?:it'?s|it is) (?:my |a |an )?(?:technical |backend |job )?interview[.!]?$",clean,re.I):
        context=next((e for e in recent if re.search(r'preparing|interview',e['user_message'],re.I)),None)
        if context:
            label='technical interview' if 'technical' in clean.lower() else 'interview'
            add('User has a '+label+' coming up.','Event','event:interview',days=30,category='TEMPORARY_CONTEXT',retention='MEDIUM_TERM',source_message_ids=[context['message_id']])
    if re.search(r"^(?:it'?s|it is) (tomorrow|next week)[.!]?$",clean,re.I):
        event=db.one("SELECT * FROM memories WHERE memory_type='Event' AND conversation_id=? AND status IN ('ACTIVE','PROVISIONAL','DORMANT') ORDER BY updated_at DESC LIMIT 1",(conversation_id,)) if conversation_id else None
        if event and recent:
            when='tomorrow' if 'tomorrow' in clean.lower() else 'next week'
            content=re.sub(r' coming up\.| (?:tomorrow|next week)\.$','',event['content'])+' '+when+'.'
            add(content,'Event',event['slot'],event['domain'],3 if when=='tomorrow' else 14,'TEMPORARY_CONTEXT','SHORT_TERM',valid_from=timepoint(when,stamp,time_zone),source_message_ids=[e['message_id'] for e in recent if re.search(r'interview|preparing',e['user_message'],re.I)][:3])
    if re.search(r'\bmy CS classes\b',clean,re.I):
        old=db.one("SELECT * FROM memories WHERE slot='education:subject' AND content LIKE '%Computer Science%' AND status IN ('ACTIVE','ESTABLISHED','DORMANT')")
        if old:add(old['content'],'Education',old['slot'],reference_only=True,source_type='USER_REFERENCE',confidence=old['confidence'])
    # More precise education records replace a legacy broad course candidate, not other independent facts.
    if any(x['slot']=='education:subject' for x in result):result=[x for x in result if x['memory_type']!='Education' or x['slot'].startswith('education:subject') or x['slot'] in ('education:institution','education:location')]
    unique={}
    for x in result:
        category,retention=retention_policy.classify(x);x.update(memory_category=category,retention_class=retention)
        unique[(x['domain'],x['slot'])]=x
    return list(unique.values())

def describe(text,response,candidates):
    entities=[]
    for x in candidates:
        if x['memory_type'] in ('Identity','Education','General User Context','Project','Event','Plan'):entities.append({'type':x['memory_type'],'value':x['content'],'source':'USER'})
    topics=list(dict.fromkeys(x['memory_type'] for x in candidates))
    if not topics:
        words=re.findall(r'\b[A-Za-z][A-Za-z.+]{2,}\b',text)
        topics=list(dict.fromkeys(w.lower() for w in words if w.lower() not in {'what','the','tell','please','can','you','today','this'}))[:8]
    return entities,topics
