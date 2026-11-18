"""Local pretrained sentence embeddings; no user text leaves the machine.

Uses Chroma's existing Apache-2.0 MiniLM ONNX integration, with a bundled,
SHA-256 verified model archive. No synthetic or hand-built vectors are used.
"""
import hashlib, shutil, threading
from functools import lru_cache
from .. import database as db
_lock=threading.RLock()
_model=None
_failure=None

def model():
    global _model,_failure
    with _lock:
        if _model is not None:return _model
        if _failure:raise RuntimeError(_failure)
        try:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            path=ONNXMiniLM_L6_V2.DOWNLOAD_PATH
            bundle=db.ROOT/'models'/'minilm-onnx.tar.gz'
            required=('config.json','model.onnx','special_tokens_map.json','tokenizer_config.json','tokenizer.json','vocab.txt')
            if not all((path/'onnx'/name).is_file() for name in required):
                if not bundle.is_file():raise RuntimeError('Bundled local semantic model is unavailable')
                if hashlib.sha256(bundle.read_bytes()).hexdigest()!=ONNXMiniLM_L6_V2._MODEL_SHA256:raise RuntimeError('Bundled semantic model checksum failed')
                path.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(bundle,path/'onnx.tar.gz')
            _model=ONNXMiniLM_L6_V2(preferred_providers=['CPUExecutionProvider'])
            return _model
        except Exception as e:
            _failure=str(e);raise

@lru_cache(maxsize=4096)
def vector(text):
    with _lock:return tuple(float(x) for x in model()([text[:3000]])[0])

def clear_cache():
    # Cached keys may contain user text; clear them on user-requested deletion.
    with _lock:vector.cache_clear()

def similarities(query,items):
    """Cosine similarity on normalized local MiniLM embeddings."""
    if not items:return {}
    try:
        q=vector(query)
        return {key:round(sum(a*b for a,b in zip(q,vector(text))),4) for key,text in items}
    except Exception:return {}

# One canonical description per schema category, not a synonym dictionary.
# The encoder supplies paraphrase relationships; anchors can be audited.
ANCHORS={
 'name':'What is my name?',
 'location':'Where do I live?',
 'goal':'What is my long-term goal and ambition?',
 'education':'What am I studying for my education?',
 'project':'What project am I working on?',
 'stack':'What technology, programming languages and frameworks does my project use?',
 'preference':'What are my personal preferences?',
 'interest':'What are my interests?',
 'career':'What is my work and career?',
 'constraint':'What are my constraints?',
 'experience':'What was discussed previously in a conversation?',
}
def classify(question):
    scores=similarities(question,list(ANCHORS.items()))
    if not scores:return []
    best=max(scores.values());out=[]
    for name,score in sorted(scores.items(),key=lambda x:x[1],reverse=True):
        if score>=max(.36,.70 if name in ('name','location') else .36) and score>=best-.09:out.append((name,score))
        if len(out)==2:break
    return out
