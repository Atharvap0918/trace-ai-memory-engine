"""Analyze every request before retrieval; collect all explicit retrieval intents.
A compound question can request several fact groups. Exclusions still take priority.
"""
import re
from .. import database as db
ALL_TYPES=['Identity','Preference','Goal','Project','Skill','Career','Education','Constraint','Belief','Event','Temporary Context','General User Context']
def boundary(text):
    return bool(re.search(r"(?:don['’]?t|do not|never).{0,30}(?:memory|previous|old project)|ignore.{0,25}(?:previous|memory)|completely new|fresh context",text.lower()))
def legacy_analyze(text,conversation,s):
    q=text.lower();mode=s['memory_mode'];domain=conversation['domain'];types=[];groups=[]
    isolated=boundary(text)
    restricted=bool(re.search(r'only.{0,35}(?:current project|this project)|use only',q))
    if isolated:
        mode='ISOLATED';domain='project:'+conversation['id'];db.execute('UPDATE conversations SET domain=? WHERE id=?',(domain,conversation['id']))
    elif restricted:mode='RESTRICTED'
    else:
        named=re.search(r"(?:i am|i'm|i’m) (?:building|developing|working on) (?:an? )?(.+?)(?:[.!;]| using | with | for |\s+and\s+(?:i\b|my\b)|$)",q)
        if named and named[1].strip() not in ('this project','the project'):
            domain='project:'+re.sub(r'[^a-z0-9]+','-',named[1].strip()).strip('-')[:70]
            db.execute('UPDATE conversations SET domain=? WHERE id=?',(domain,conversation['id']))
    personal=bool(re.search(r'\b(my|me|i|our)\b',q))
    summary=bool(re.search(r'(?:what|everything).{0,28}(?:remember|know).{0,20}(?:about me|of me)|(?:summari[sz]e|recap|review).{0,25}(?:my profile|about me|my context)|who am i|(?:what|all).{0,25}(?:information|facts|details).{0,25}about me|(?:list|show|review).{0,25}my (?:memories|profile)',q))
    def intent(name,pattern,kinds):
        if re.search(pattern,q):groups.append(name);types.extend(kinds)
    intent('name',r'\bmy (?:name|identity)\b',['Identity'])
    if personal:
        intent('location',r'where (?:do )?i (?:live|reside)|where i (?:live|am based)|where am i based|where am i from|\b(?:location|city|address)\b|my (?:location|city)|(?:location|city).{0,15}\bmy\b',['General User Context'])
        intent('project',r'\b(?:my|current|this|our) (?:project|stack)|what project|am i (?:working|building)|\bproject\b',['Project','Temporary Context','Constraint','Skill'])
        intent('stack',r'\bstack\b|programming languages?|frameworks?|currently (?:using|use)|language am i|which language',['Project'])
        intent('preference',r'\bpreferences?\b|what do i prefer|how (?:do )?i (?:like|prefer)|my explanation style',['Preference'])
        intent('goal',r'\bgoals?\b|my objectives?|my ambitions?',['Goal'])
        intent('career',r'\bcareer\b|my (?:job|role)|what (?:do )?i do for (?:a )?living|my profession',['Career'])
        intent('education',r'\beducation\b|what (?:am )?i studying|where (?:do )?i study|my degree',['Education'])
        intent('skill',r'\bskills?\b|what (?:am )?i learning|my abilities',['Skill'])
        intent('constraint',r'\bconstraints?\b|my limitations?|my budget|my hardware',['Constraint'])
        intent('belief',r'\bbeliefs?\b|what do i believe',['Belief'])
        intent('event',r'\b(?:exam|interview|meeting|events?)\b|my upcoming',['Event'])
    technical=bool(re.search(r'explain|technical|programming|python|code|backend|implement|learning|machine learning',q))
    if re.search(r'backend|implement',q) and 'project' not in groups:
        groups.append('project');types.extend(['Project','Temporary Context','Constraint','Skill'])
    if technical:
        types.append('Preference')
        if 'preference' not in groups:groups.append('explanation_style')
    if summary:types=ALL_TYPES.copy();groups=['profile']
    historical=bool(re.search(r'previously|historical|used to|past project|previous project',q))
    if historical:types.extend(['Project','Skill']);groups.append('history')
    groups=list(dict.fromkeys(groups));types=list(dict.fromkeys(types))
    if mode=='OPEN' and types==['Preference']:mode='SELECTIVE'
    multi=summary or len([g for g in groups if g not in ('explanation_style','history')])>1
    # Top-K remains the baseline. Compound recall grows enough to cover multiple
    # requested facts, with explicit upper bounds rather than a blind DB dump.
    limit=min(40,max(s['top_k'],32 if summary else len(groups)*4 if multi else 8 if 'stack' in groups else s['top_k']))
    return {'memory_mode':mode,'current_domain':domain,'allowed_types':types,'requested_groups':groups,'profile_summary':summary,'multi_fact':multi,'retrieval_limit':limit,'blocked_domains':['previous_project'] if isolated else [],'memory_needed':bool(types) and s['memory_enabled'] and mode!='ISOLATED','historical':historical,'boundary':isolated}
