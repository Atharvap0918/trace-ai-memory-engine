"""Retention class is not query relevance or response influence."""
CATEGORY={'Identity':'SEMANTIC_MEMORY','General User Context':'SEMANTIC_MEMORY','Education':'SEMANTIC_MEMORY','Career':'SEMANTIC_MEMORY','Skill':'SEMANTIC_MEMORY','Belief':'SEMANTIC_MEMORY','Preference':'PREFERENCE','Goal':'GOAL','Plan':'PLAN','Decision':'DECISION','Event':'EVENT','Constraint':'CONSTRAINT','Project':'PROJECT_CONTEXT','Temporary Context':'TEMPORARY_CONTEXT','Episodic':'EPISODIC_MEMORY','Interest':'SEMANTIC_MEMORY','Relationship':'SEMANTIC_MEMORY'}
def classify(candidate):
    kind=candidate.get('memory_type','Temporary Context');days=candidate.get('expected_lifetime')
    category=candidate.get('memory_category') or CATEGORY.get(kind,'WORKING_CONTEXT')
    if candidate.get('source_type')=='USER_CONFIRMED':category='USER_CONFIRMED_DECISION' if kind in ('Project','Decision') else category
    retention=candidate.get('retention_class') or ('SHORT_TERM' if days and days<=14 else 'MEDIUM_TERM' if days and days<=180 else 'LONG_TERM')
    return category,retention
