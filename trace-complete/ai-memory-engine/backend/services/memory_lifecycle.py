"""Confidence is epistemic; activation is recoverable accessibility, never truth."""
import math
from datetime import datetime,timezone
from .. import database as db
LIVE=('CANDIDATE','PROVISIONAL','ACTIVE','ESTABLISHED','DORMANT')
def timestamp(value,fallback):
    try:
        d=datetime.fromisoformat(value);return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError,ValueError):return fallback

def transition(m,state,reason,c=None):
    if m['status']==state:return
    def write(cx):
        db.version(m,reason,cx)
        cx.execute("UPDATE memories SET status=?,retention_class=CASE WHEN ? IN ('STALE','SUPERSEDED','ARCHIVED') THEN 'HISTORICAL' ELSE retention_class END,updated_at=? WHERE id=?",(state,state,db.now(),m['id']))
        cx.execute('INSERT INTO memory_transitions VALUES(?,?,?,?,?,?)',(db.uid(),m['id'],m['status'],state,reason,db.now()))
        cx.execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)',(db.uid(),m['id'],None,'MEMORY_'+('REACTIVATED' if m['status']=='DORMANT' and state=='ACTIVE' else state),reason,db.now()))
    if c:write(c)
    else:
        with db.connect() as cx:write(cx)
    # Callers with a transaction cannot open a second writer here. Retrieval checks
    # live support before using a conclusion, and periodic maintenance cleans it.

def maintain(at=None):
    clock=at or datetime.now(timezone.utc)
    with db.connect() as c:
        for row in c.execute("SELECT * FROM memories WHERE status IN ('CANDIDATE','PROVISIONAL','ACTIVE','ESTABLISHED','DORMANT')").fetchall():
            m=dict(row)
            last=timestamp(m['activation_updated_at'] or m['last_confirmed_at'],clock)
            days=max(0,(clock-last).total_seconds()/86400)
            lifetime=m['expected_lifetime'] or (365 if m['protected'] else 120 if m['memory_layer']=='episodic' else 90 if m['domain']=='general' else 30)
            half=max(7,lifetime*(1+.8*m['importance'])*(1+min(1,math.log1p(m.get('access_count') or 0)/5)))
            activation=max(.02,m['activation']*math.exp(-math.log(2)*days/half))
            age=max(0,(clock-timestamp(m['last_confirmed_at'],clock)).total_seconds()/86400)
            freshness=max(.1,math.exp(-age/max(30,lifetime)))
            c.execute('UPDATE memories SET activation=?,freshness=?,activation_updated_at=? WHERE id=?',(activation,freshness,clock.isoformat(),m['id']))
            if m['expires_at'] and timestamp(m['expires_at'],clock)<clock:
                transition(m,'STALE','Expected applicability elapsed; history retained',c)
            elif activation<.25 and not m['protected'] and m['status'] in ('ACTIVE','ESTABLISHED','PROVISIONAL'):
                transition(m,'DORMANT','Low activation; recoverable on relevant recall',c)

def reinforce(m,conversation_id,c):
    if m['status']=='DORMANT':transition(m,'ACTIVE','Relevant recall reactivated the same memory ID',c)
    # Retrieval is NOT additional factual evidence and does not increase confidence.
    c.execute('UPDATE memories SET activation=MIN(1,MAX(0.60,activation+0.16)),last_accessed_at=?,last_referenced_at=?,activation_updated_at=?,access_count=access_count+1 WHERE id=?',(db.now(),db.now(),db.now(),m['id']))
