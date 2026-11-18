"""Local, bounded trace of observable evidence, not private reasoning."""
import json
from .. import database as db

def record(conversation_id,message_id,query,access,decisions,context,state):
    with db.connect() as c:
        c.execute('INSERT INTO retrieval_diagnostics VALUES(?,?,?,?,?,?,?,?,?,?)',(
            db.uid(),conversation_id,message_id,query,json.dumps(access.get('requirements',[]),ensure_ascii=False),
            json.dumps({'final_decisions':decisions,'candidates':access.get('candidate_diagnostics',[]),'local_semantic_status':access.get('local_semantic_status')},ensure_ascii=False),json.dumps(context,ensure_ascii=False),
            json.dumps(access.get('coverage',{}),ensure_ascii=False),state,db.now()))
        # Keep at most 200 traces per conversation. Delete whole traces, not fragments.
        c.execute('DELETE FROM retrieval_diagnostics WHERE conversation_id=? AND id NOT IN (SELECT id FROM retrieval_diagnostics WHERE conversation_id=? ORDER BY created_at DESC LIMIT 200)',(conversation_id,conversation_id))

def purge_memory(memory_id,c):
    # A memory may appear in rejected decisions as well as the final context.
    c.execute('DELETE FROM retrieval_diagnostics WHERE decisions LIKE ? OR context LIKE ?',('%'+memory_id+'%','%'+memory_id+'%'))
    # Remove the retained candidate representation, while preserving the user's
    # separate conversation transcript unless that conversation is deleted.
    c.execute('DELETE FROM experience_candidates WHERE memory_id=?',(memory_id,))
    for row in c.execute('SELECT id,memory_candidates FROM conversation_experiences WHERE memory_candidates LIKE ?',('%'+memory_id+'%',)).fetchall():
        try:
            candidates=json.loads(row['memory_candidates'])
            if isinstance(candidates,list):
                candidates=[item for item in candidates if not isinstance(item,dict) or item.get('memory_id')!=memory_id]
                c.execute('UPDATE conversation_experiences SET memory_candidates=? WHERE id=?',(json.dumps(candidates,ensure_ascii=False),row['id']))
        except (TypeError,ValueError):pass
    c.execute('DELETE FROM temporal_transitions WHERE memory_id=? OR old_memory_id=?',(memory_id,memory_id))

def purge_conversation(conversation_id,c):
    experience_ids=[x['id'] for x in c.execute('SELECT id FROM conversation_experiences WHERE conversation_id=?',(conversation_id,)).fetchall()]
    c.execute('DELETE FROM retrieval_diagnostics WHERE conversation_id=?',(conversation_id,))
    for eid in experience_ids:c.execute('DELETE FROM retrieval_diagnostics WHERE decisions LIKE ? OR context LIKE ?',('%'+eid+'%','%'+eid+'%'))
