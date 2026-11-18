"""Optional real semantic retrieval, using API embeddings and persistent Chroma.
No hash vectors, fabricated similarity, or hidden model downloads.
"""
from .. import database as db
from . import llm_provider as llm
COLLECTION=None
LAST_ERROR=None
def collection():
    global COLLECTION
    if COLLECTION is None:
        import chromadb
        from chromadb.config import Settings
        client=chromadb.PersistentClient(path=str(db.ROOT/'data'/'chroma'),settings=Settings(anonymized_telemetry=False))
        # Model-specific collection keeps incompatible vector dimensions separate.
        import hashlib
        name='memory_'+hashlib.sha256((llm.settings()['embedding_model']+llm.settings()['base_url']).encode()).hexdigest()[:12]
        COLLECTION=client.get_or_create_collection(name,embedding_function=None)
    return COLLECTION
def vectors(texts):
    s=llm.settings()
    if not llm.KEY: raise ValueError('API key required for semantic retrieval')
    data=llm.api_json(s['base_url'].rstrip('/')+'/embeddings',{'model':s['embedding_model'],'input':texts},llm.KEY)
    return [x['embedding'] for x in sorted(data['data'],key=lambda x:x['index'])]
def search(query,memories,k):
    global LAST_ERROR
    if not llm.settings()['semantic_enabled']: return {},'disabled'
    try:
        col=collection()
        if not memories: return {},'ready'
        existing=col.get(ids=[m['id'] for m in memories],include=['documents'])
        docs=dict(zip(existing['ids'],existing['documents']))
        changed=[m for m in memories if docs.get(m['id'])!=m['content']]
        if changed: col.upsert(ids=[m['id'] for m in changed],documents=[m['content'] for m in changed],embeddings=vectors([m['content'] for m in changed]),metadatas=[{'memory_id':m['id']} for m in changed])
        result=col.query(query_embeddings=vectors([query]),n_results=min(k,len(memories)),where={'memory_id':{'$in':[m['id'] for m in memories]}},include=['distances'])
        allowed={m['id'] for m in memories}
        scores={i:max(0,1-float(d)/2) for i,d in zip(result['ids'][0],result['distances'][0]) if i in allowed}
        LAST_ERROR=None; return scores,'ready'
    except Exception:
        LAST_ERROR='Semantic retrieval unavailable. Structured retrieval was used.'
        return {},'unavailable'
def remove(id):
    path=db.ROOT/'data'/'chroma'
    if not path.exists(): return True
    try:
        import chromadb
        from chromadb.config import Settings
        client=chromadb.PersistentClient(path=str(path),settings=Settings(anonymized_telemetry=False))
        for item in client.list_collections():
            name=item if isinstance(item,str) else item.name
            client.get_collection(name,embedding_function=None).delete(ids=[id])
        return True
    except Exception: return False
