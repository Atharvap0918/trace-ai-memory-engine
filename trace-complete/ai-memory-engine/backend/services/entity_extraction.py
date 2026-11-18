"""Extract only verbatim, recognizable entities; never infer ownership."""
import re
TECH=re.compile(r'(?<![\w])(?:Python|JavaScript|TypeScript|FastAPI|Django|Flask|Express|Next\.js|Spring|React|Vue|Java|Rust|Go|C\+\+|Ruby|PHP|Kotlin|Swift)(?![\w])',re.I)
FRAMEWORKS={'fastapi','django','flask','express','next.js','spring','react','vue'}
def extract(content,domain='',slot=''):
    result=[]
    def add(kind,value):
        if value and not any(x['type']==kind and x['value'].lower()==value.lower() for x in result):result.append({'type':kind,'value':value})
    for m in TECH.finditer(content):add('framework' if m.group().lower() in FRAMEWORKS else 'programming_language',m.group())
    if slot=='identity:name':
        m=re.search(r'name is (.+?)(?:[.]|$)',content,re.I)
        if m:add('person_name',m[1])
    if slot=='education:subject':
        m=re.search(r'(?:a |studies )(.+?)(?: student|[.]|$)',content,re.I)
        if m:add('academic_subject',m[1])
    if domain.startswith('project:') and slot.startswith('project:'):
        name=domain.split(':',1)[1].replace('-',' ')
        match=re.search(r'\b'+re.escape(name)+r'\b',content,re.I)
        if match:add('project',match.group())
    return result
