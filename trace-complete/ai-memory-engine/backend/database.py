import sqlite3, json, uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'memory.db'
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return uuid.uuid4().hex
@contextmanager
def connect():
    c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def init():
    DB.parent.mkdir(exist_ok=True)
    with connect() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY);
        INSERT OR IGNORE INTO users VALUES('user_001');
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,user_id TEXT,title TEXT,domain TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,conversation_id TEXT,role TEXT,content TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,user_id TEXT,content TEXT,memory_type TEXT,domain TEXT,slot TEXT,source_type TEXT,confidence REAL,importance REAL,freshness REAL,status TEXT,influence REAL,expected_lifetime INTEGER,created_at TEXT,updated_at TEXT,last_confirmed_at TEXT,expires_at TEXT,superseded_by TEXT,conversation_id TEXT,evidence_count INTEGER);
        CREATE TABLE IF NOT EXISTS memory_versions(id TEXT PRIMARY KEY,memory_id TEXT,snapshot TEXT,reason TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS memory_evidence(id TEXT PRIMARY KEY,memory_id TEXT,conversation_id TEXT,message_id TEXT,statement TEXT,source_type TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS memory_events(id TEXT PRIMARY KEY,memory_id TEXT,conversation_id TEXT,event_type TEXT,detail TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS memory_relationships(id TEXT PRIMARY KEY,source_id TEXT,target_id TEXT,relation TEXT,UNIQUE(source_id,target_id,relation));
        CREATE TABLE IF NOT EXISTS memory_access_logs(id TEXT PRIMARY KEY,conversation_id TEXT,mode TEXT,needed INTEGER,domain TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS memory_usage_logs(id TEXT PRIMARY KEY,memory_id TEXT,conversation_id TEXT,decision TEXT,relevance REAL,impact REAL,influence REAL,reason TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT);
        ''')
        defaults={'provider':'openai','model':'gpt-4o-mini','base_url':'https://api.openai.com/v1','memory_enabled':True,'memory_mode':'OPEN','top_k':5,'threshold':0.28,'semantic_enabled':False,'embedding_model':'text-embedding-3-small'}
        c.execute('INSERT OR IGNORE INTO settings VALUES(1,?)',(json.dumps(defaults),))

def rows(sql,args=()):
    with connect() as c: return [dict(x) for x in c.execute(sql,args).fetchall()]
def one(sql,args=()):
    r=rows(sql,args); return r[0] if r else None
def execute(sql,args=()):
    with connect() as c: c.execute(sql,args)
def event(kind,detail='',memory_id=None,conversation_id=None):
    execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)',(uid(),memory_id,conversation_id,kind,detail,now()))
def version(m,reason,c=None):
    args=(uid(),m['id'],json.dumps(m),reason,now())
    if c: c.execute('INSERT INTO memory_versions VALUES(?,?,?,?,?)',args)
    else: execute('INSERT INTO memory_versions VALUES(?,?,?,?,?)',args)
def expire():
    for m in rows("SELECT * FROM memories WHERE expires_at IS NOT NULL AND expires_at < ? AND status IN ('ACTIVE','ESTABLISHED','PROVISIONAL')",(now(),)):
        version(m,'Lifetime elapsed'); execute("UPDATE memories SET status='STALE', influence=0.1, freshness=0.1, updated_at=? WHERE id=?",(now(),m['id'])); event('MEMORY_EXPIRED','Expected lifetime elapsed',m['id'])

# V2 is additive: old rows, IDs, snapshots and source evidence survive migration.
def migrate():
    columns={r['name'] for r in rows('PRAGMA table_info(memories)')}
    additions={'memory_layer':"TEXT DEFAULT 'semantic'",'activation':'REAL DEFAULT 0.85',
        'last_accessed_at':'TEXT','activation_updated_at':'TEXT','protected':'INTEGER DEFAULT 0',
        'context_id':'TEXT','access_count':'INTEGER DEFAULT 0'}
    missing={k:v for k,v in additions.items() if k not in columns}
    if missing and DB.exists():
        backup=DB.with_suffix('.pre-v2.bak')
        if not backup.exists():
            source=sqlite3.connect(DB);target=sqlite3.connect(backup)
            try:source.backup(target)
            finally:source.close();target.close()
    with connect() as c:
        for name,definition in missing.items(): c.execute('ALTER TABLE memories ADD COLUMN '+name+' '+definition)
        c.executescript('''
        CREATE TABLE IF NOT EXISTS memory_contexts(id TEXT PRIMARY KEY,user_id TEXT,kind TEXT,label TEXT,state TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS working_contexts(conversation_id TEXT PRIMARY KEY,context_id TEXT,intent TEXT,topic TEXT,recent_context TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS interaction_candidates(id TEXT PRIMARY KEY,conversation_id TEXT,message_id TEXT,context_id TEXT,content TEXT,role TEXT,kind TEXT,status TEXT,accepted_by TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY,conversation_id TEXT,context_id TEXT,summary TEXT,items TEXT,message_count INTEGER,updated_at TEXT,UNIQUE(conversation_id,context_id));
        CREATE TABLE IF NOT EXISTS memory_transitions(id TEXT PRIMARY KEY,memory_id TEXT,from_state TEXT,to_state TEXT,reason TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT);
        CREATE INDEX IF NOT EXISTS memory_scope_slot ON memories(user_id,domain,slot,status);
        CREATE INDEX IF NOT EXISTS memory_updated ON memories(updated_at);
        CREATE INDEX IF NOT EXISTS message_conversation ON messages(conversation_id,created_at);
        CREATE INDEX IF NOT EXISTS evidence_memory ON memory_evidence(memory_id,message_id);
        CREATE INDEX IF NOT EXISTS events_created ON memory_events(created_at);
        ''')
        if missing:
            c.execute("UPDATE memories SET activation_updated_at=COALESCE(last_confirmed_at,updated_at,created_at),context_id=domain,memory_layer=CASE WHEN memory_type='Preference' THEN 'preference' WHEN domain!='general' OR memory_type IN ('Event','Temporary Context') THEN 'contextual' ELSE 'semantic' END,protected=CASE WHEN memory_type IN ('Identity','Preference') THEN 1 ELSE 0 END")
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(2,?)',(now(),))

_original_init=init
def init():
    _original_init()
    migrate()

# Capture-first upgrade. Additional tables/columns only; no memories or history wiped.
def migrate_experiences():
    columns={r['name'] for r in rows('PRAGMA table_info(memories)')}
    additions={'memory_category':"TEXT DEFAULT 'SEMANTIC_MEMORY'",'retention_class':"TEXT DEFAULT 'LONG_TERM'",'valid_from':'TEXT','last_referenced_at':'TEXT','experience_id':'TEXT'}
    missing={k:v for k,v in additions.items() if k not in columns}
    if missing and DB.exists():
        backup=DB.with_suffix('.pre-experience.bak')
        if not backup.exists():
            source=sqlite3.connect(DB);target=sqlite3.connect(backup)
            try:source.backup(target)
            finally:source.close();target.close()
    with connect() as c:
        for name,definition in missing.items():c.execute('ALTER TABLE memories ADD COLUMN '+name+' '+definition)
        c.executescript('''
        CREATE TABLE IF NOT EXISTS conversation_experiences(
          id TEXT PRIMARY KEY,user_id TEXT NOT NULL,conversation_id TEXT NOT NULL,message_id TEXT UNIQUE NOT NULL,
          assistant_message_id TEXT,user_message TEXT NOT NULL,assistant_response TEXT,timestamp TEXT NOT NULL,
          current_context TEXT,entities TEXT DEFAULT '[]',topics TEXT DEFAULT '[]',memory_candidates TEXT DEFAULT '[]',
          source_information TEXT DEFAULT '{}',event_type TEXT DEFAULT 'CONVERSATION',importance REAL DEFAULT .3,
          expected_lifetime INTEGER,retention_class TEXT DEFAULT 'EPHEMERAL',processing_status TEXT DEFAULT 'CAPTURED',
          summary TEXT DEFAULT '',formation_report TEXT DEFAULT '{}',error TEXT);
        CREATE TABLE IF NOT EXISTS experience_candidates(
          id TEXT PRIMARY KEY,experience_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,memory_type TEXT,
          memory_category TEXT,retention_class TEXT,status TEXT,reason TEXT,memory_id TEXT,expected_lifetime INTEGER,
          source_message_id TEXT,created_at TEXT,UNIQUE(experience_id,role,content,memory_category));
        CREATE TABLE IF NOT EXISTS temporal_transitions(
          id TEXT PRIMARY KEY,experience_id TEXT,memory_id TEXT,old_memory_id TEXT,from_state TEXT,to_state TEXT,
          effective_at TEXT,status TEXT,context TEXT,confirmed_by TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS experience_usage_logs(
          id TEXT PRIMARY KEY,experience_id TEXT,conversation_id TEXT,decision TEXT,relevance REAL,influence REAL,
          reason TEXT,created_at TEXT);
        CREATE INDEX IF NOT EXISTS experience_conversation_time ON conversation_experiences(conversation_id,timestamp);
        CREATE INDEX IF NOT EXISTS experience_scope ON conversation_experiences(current_context,processing_status);
        CREATE INDEX IF NOT EXISTS candidate_experience ON experience_candidates(experience_id);
        CREATE INDEX IF NOT EXISTS transition_status ON temporal_transitions(status);
        ''')
        if missing:
            from .services.retention_policy import classify
            for r in c.execute('SELECT * FROM memories').fetchall():
                m=dict(r);category,retention=classify(m)
                if m['status'] in ('SUPERSEDED','STALE','ARCHIVED'):retention='HISTORICAL'
                c.execute('UPDATE memories SET memory_category=?,retention_class=?,last_referenced_at=last_accessed_at WHERE id=?',(category,retention,m['id']))
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(3,?)',(now(),))

_v2_init=init
def init():
    _v2_init()
    migrate_experiences()

# Reliability diagnostics are additive and contain local user data. They are
# deleted along with their conversation, or when a referenced memory is deleted.
def migrate_reliability():
    exists=one("SELECT name FROM sqlite_master WHERE type='table' AND name='retrieval_diagnostics'")
    columns={r['name'] for r in rows('PRAGMA table_info(memories)')}
    needs_entities='entities' not in columns
    if (not exists or needs_entities) and DB.exists():
        backup=DB.with_suffix('.pre-reliability.bak')
        if not backup.exists():
            source=sqlite3.connect(DB);target=sqlite3.connect(backup)
            try:source.backup(target)
            finally:source.close();target.close()
    with connect() as c:
        if needs_entities:
            c.execute("ALTER TABLE memories ADD COLUMN entities TEXT DEFAULT '[]'")
            from .services.entity_extraction import extract
            for row in c.execute("SELECT id,content,domain,slot FROM memories WHERE status!='DELETED'").fetchall():
                c.execute('UPDATE memories SET entities=? WHERE id=?',(json.dumps(extract(row['content'],row['domain'] or '',row['slot'] or ''),ensure_ascii=False),row['id']))
        c.executescript('''
        CREATE TABLE IF NOT EXISTS retrieval_diagnostics(
          id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,message_id TEXT NOT NULL,
          query TEXT NOT NULL,requirements TEXT NOT NULL,decisions TEXT NOT NULL,
          context TEXT NOT NULL,coverage TEXT NOT NULL,semantic_status TEXT,
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS retrieval_diagnostics_conversation ON retrieval_diagnostics(conversation_id,created_at);
        ''')
        c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(4,?)',(now(),))

_experience_init=init
def init():
    _experience_init();migrate_reliability()
