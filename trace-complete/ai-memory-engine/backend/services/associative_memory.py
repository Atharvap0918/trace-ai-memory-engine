"""Conservative graph associations and source-linked, non-destructive consolidation.

An entity edge is a possible association, not a statement about causation or user intent.
No embeddings or model output are treated as factual evidence.
"""
import hashlib,re
from .. import database as db

LIVE=('ACTIVE','ESTABLISHED','DORMANT')
TECH=re.compile(r'(?<![\w])(?:Python|JavaScript|TypeScript|FastAPI|Django|Flask|React|Vue|Java|Rust|Kotlin|Swift|Ruby|PHP|C\+\+)(?![\w])',re.I)

def entities(m):
    return {x.lower() for x in TECH.findall(m['content'])}

def refresh_associations(ids=None):
    """Link independently recorded memories sharing a named technology.

    Rebuild only our own edges so edits, supersession, and deletes do not leave
    stale links. No association implies a relationship was explicitly stated.
    """
    rows=db.rows("SELECT * FROM memories WHERE user_id='user_001' AND status IN ('ACTIVE','ESTABLISHED','DORMANT') AND source_type IN ('USER_EXPLICIT','USER_CONFIRMED','USER_REFERENCE') AND memory_type IN ('Skill','Project','Decision','Constraint','Goal','Plan')")
    with db.connect() as c:
        if ids:
            for mid in set(ids):
                c.execute("DELETE FROM memory_relationships WHERE relation LIKE 'associated_entity:%' AND (source_id=? OR target_id=?)",(mid,mid))
        else:c.execute("DELETE FROM memory_relationships WHERE relation LIKE 'associated_entity:%'")
        # Inverted entity index avoids comparing unrelated pairs. Limit neighbours
        # per entity/scope so a popular technology cannot create a quadratic graph.
        buckets={}
        for m in rows:
            for entity in entities(m):buckets.setdefault(entity,{}).setdefault(m['domain'],[]).append(m)
        for entity,domains in buckets.items():
            for group in domains.values():group.sort(key=lambda m:m['updated_at'] or '',reverse=True)
            for domain,group in domains.items():
                for a in group:
                    if ids and a['id'] not in ids:continue
                    neighbours=group[:25]+([] if domain=='general' else domains.get('general',[])[:25])
                    if domain=='general':
                        for other,scoped in domains.items():
                            if other!='general':neighbours+=scoped[:25]
                    for b in neighbours:
                        if a['id']==b['id']:continue
                        source,target=sorted((a['id'],b['id']))
                        c.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),source,target,'associated_entity:'+entity))

def consolidate():
    """Consolidate exact recurring user statements from separate conversations.

    Conservative by design: no paraphrase equivalence or behavioral inference.
    Source memories and evidence remain intact. Tombstoned summaries are not rebuilt.
    """
    sources=db.rows("SELECT * FROM memories WHERE user_id='user_001' AND status IN ('ACTIVE','ESTABLISHED','DORMANT') AND source_type IN ('USER_EXPLICIT','USER_CONFIRMED') AND memory_type IN ('Preference','Goal','Decision','Constraint') AND expires_at IS NULL ORDER BY created_at")
    groups={}
    for m in sources:
        key=(m['domain'],m['memory_type'],re.sub(r'\s+',' ',m['content'].strip().lower()))
        groups.setdefault(key,[]).append(m)
    count=0
    for key,items in groups.items():
        ev=[]
        for m in items:
            ev += db.rows("SELECT * FROM memory_evidence WHERE memory_id=? AND source_type IN ('USER_EXPLICIT','USER_CONFIRMED') AND message_id IS NOT NULL",(m['id'],))
        ev=list({e['message_id']:e for e in ev}.values())
        if len(ev)<2 or len({e['conversation_id'] for e in ev if e['conversation_id']})<2:continue
        signature=hashlib.sha256(('|'.join(key)).encode()).hexdigest()[:24];slot='consolidated:'+signature
        existing=db.one('SELECT * FROM memories WHERE slot=?',(slot,))
        if existing and (existing['status'] in ('DELETED','ARCHIVED') or existing['source_type']!='SUPPORTED_CONCLUSION'):continue
        if existing and existing['status'] in ('STALE','SUPERSEDED'):continue
        source=items[0]; now=db.now();mid=existing['id'] if existing else db.uid()
        with db.connect() as c:
            if not existing:
                from .memory_formation import COLUMNS
                values=(mid,'user_001','Repeatedly recorded across conversations: '+source['content'],source['memory_type'],source['domain'],slot,'SUPPORTED_CONCLUSION',min(m['confidence'] for m in items),max(m['importance'] for m in items),1,'ACTIVE',.85,None,now,now,now,None,None,source['conversation_id'],len(ev),source['memory_layer'],.85,None,now,source['protected'],source['domain'],0)
                c.execute('INSERT INTO memories ('+','.join(COLUMNS)+') VALUES('+','.join('?'*len(COLUMNS))+')',values)
                c.execute('UPDATE memories SET memory_category=?,retention_class=?,entities=? WHERE id=?',(source['memory_category'],'LONG_TERM',source.get('entities','[]'),mid))
                db.version(dict(c.execute('SELECT * FROM memories WHERE id=?',(mid,)).fetchone()),'Source-linked repeated statement consolidation',c)
                c.execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)',(db.uid(),mid,None,'MEMORY_CONSOLIDATED','Repeated explicit statements; original evidence retained',now));count+=1
            for m in items:c.execute('INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?,?)',(db.uid(),mid,m['id'],'supported_by'))
            for e in ev:
                if not c.execute('SELECT 1 FROM memory_evidence WHERE memory_id=? AND message_id=?',(mid,e['message_id'])).fetchone():
                    c.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?,?)',(db.uid(),mid,e['conversation_id'],e['message_id'],e['statement'],e['source_type'],e['created_at']))
            c.execute('UPDATE memories SET evidence_count=? WHERE id=?',(len(ev),mid))
    return count

def invalidate_source(mid,delete=False):
    """A changed/deleted source must not leave a usable derived claim behind."""
    derived=db.rows("SELECT m.* FROM memories m JOIN memory_relationships r ON r.source_id=m.id WHERE r.target_id=? AND r.relation='supported_by' AND m.source_type='SUPPORTED_CONCLUSION' AND m.status!='DELETED'",(mid,))
    from . import memory_lifecycle
    vectors_cleared=True
    for m in derived:
        if delete:
            with db.connect() as c:
                from . import retrieval_diagnostics
                retrieval_diagnostics.purge_memory(m['id'],c)
                c.execute("UPDATE memories SET status='DELETED',content='',entities='[]',activation=0,confidence=0,importance=0,updated_at=? WHERE id=?",(db.now(),m['id']))
                for table in ('memory_versions','memory_evidence','memory_usage_logs'):c.execute('DELETE FROM '+table+' WHERE memory_id=?',(m['id'],))
                c.execute('DELETE FROM memory_relationships WHERE source_id=? OR target_id=?',(m['id'],m['id']))
                c.execute("UPDATE memory_events SET detail='Deleted derived content' WHERE memory_id=?",(m['id'],))
            from . import embeddings
            vectors_cleared=embeddings.remove(m['id']) and vectors_cleared
        elif m['status'] not in ('STALE','ARCHIVED','SUPERSEDED'):
            memory_lifecycle.transition(m,'STALE','Source changed; derived conclusion requires re-evaluation')
    return vectors_cleared

def invalidate_inactive_sources():
    for r in db.rows("SELECT DISTINCT r.target_id FROM memory_relationships r JOIN memories m ON m.id=r.target_id JOIN memories d ON d.id=r.source_id WHERE r.relation='supported_by' AND m.status NOT IN ('ACTIVE','ESTABLISHED','DORMANT') AND d.status IN ('ACTIVE','ESTABLISHED','DORMANT') AND d.source_type='SUPPORTED_CONCLUSION'"):
        invalidate_source(r['target_id'])

def maintain():
    from . import memory_lifecycle
    memory_lifecycle.maintain();invalidate_inactive_sources();refresh_associations();return consolidate()
