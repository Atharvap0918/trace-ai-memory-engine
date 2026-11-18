"""Small, local query-normalization layer for common multilingual memory intents.

The original request is never rewritten for the provider or transcript. This
module adds a searchable English anchor for a conservative set of personal-fact
queries; it is not a general-purpose translator.
"""
import re


_DEVANAGARI = re.compile(r"[\u0900-\u097f]")
_ENGLISH = re.compile(r"[A-Za-z]")

_MARATHI_DEV = re.compile(
    r"\b(?:मी|माझा|माझी|माझे|काय|कोणता|कोणती|कोणत्या|कुठे|शिकत|शिकतो|"
    r"शिकते|आहे|आहेत|करतो|करते|करतोय|मध्?ये|प्रकल्प|करिअर|ध्येय|आवड)\b"
)
_HINDI_DEV = re.compile(
    r"\b(?:मैं|मेरा|मेरी|मेरे|क्या|कौन|कौनसा|कौनसी|कौनसे|कहाँ|कहां|"
    r"पढ़|पढ|पढ़ाई|पढाई|शिक्षा|शैक्षणिक|डिग्री|कोर्स|लक्ष्य|नौकरी|करियर|"
    r"पसंद|परियोजना)\b"
)
_MARATHI_LATIN = re.compile(
    r"\b(?:mi|maza|majha|maji|mazi|kontya|konta|konte|kuthe|madhye|"
    r"shikat|shikto|shikte|kartoy|karतो|ahe|aahe|prakalp|karier|dhye|avड)\b",
    re.I,
)
_HINDI_LATIN = re.compile(
    r"\b(?:mera|meri|mere|main|mein|kya|kaun|kaunsa|kaunsi|kahan|"
    r"padh|padhai|shiksha|lakshya|naukri|pasand|kar raha|kar rahi|"
    r"hoon|hun|hai|batao)\b",
    re.I,
)

_INTENTS = (
    (
        "education",
        re.compile(
            r"\b(?:education|academic|educational background|degree|course|"
            r"student|major|university)\b|"
            r"\b(?:what am i studying|what do i study|my studies|study field|"
            r"studying at (?:a |the )?(?:university|college))\b|"
            r"(?:शिक्षा|शिक्षण|शैक्षणिक|अभ्यासक्रम|अभ्यास|पढ़ाई|पढाई|पढ़|पढ|"
            r"डिग्री|कोर्स|शिकत|शिकतो|शिकते)|"
            r"\b(?:padhai|padh|shikshan|shiksha|abhyas|shikat|shikto|shikte)\b",
            re.I,
        ),
        "What is my academic background, degree, and course of study?",
    ),
    (
        "goal",
        re.compile(r"\b(?:goal|ambition|objective|aspiration)s?\b|(?:लक्ष्य|ध्येय)|\b(?:lakshya|dhye)\b", re.I),
        "What are my goals and long-term ambitions?",
    ),
    (
        "career",
        re.compile(r"\b(?:career|profession|job|occupation)s?\b|(?:करियर|नौकरी|व्यवसाय)|\b(?:karier|naukri)\b", re.I),
        "What is my career and profession?",
    ),
    (
        "project",
        re.compile(r"\b(?:project|app|application|product|system)\b|(?:प्रकल्प|परियोजना|प्रोजेक्ट)|\b(?:prakalp|project)\b", re.I),
        "What project or application am I working on?",
    ),
    (
        "preference",
        re.compile(r"\b(?:prefer(?:ence)?|like|enjoy|favourit[e]?|favorite)\b|(?:पसंद|आवड)|\b(?:pasand|avad)\b", re.I),
        "What are my preferences and what do I like?",
    ),
    (
        "name",
        re.compile(r"\b(?:my name|who am i|identity)\b|(?:मेरा नाम|माझे नाव|माझं नाव)|\b(?:mera naam|maza naav)\b", re.I),
        "What is my name and identity?",
    ),
    (
        "location",
        re.compile(r"\b(?:where do i live|where am i from|my (?:city|location|address))\b|(?:कहाँ|कहां|रहता|रहती|कुठे|राहतो|राहते)|\b(?:kahan|kuthe|rahto|rahte)\b", re.I),
        "Where do I live and what is my location?",
    ),
)

_QUESTION_CUES = re.compile(
    r"\?|^\s*(?:what|which|who|where|when|how|tell me|describe|show me|"
    r"remind me|list|recall)\b|\b(?:kya|kaun|kaunsa|kaunsi|kahan|kontya|"
    r"konta|kuthe|kay|batao)\b|(?:क्या|कौन|कौनसा|कौनसी|कहाँ|कहां|कुठे|"
    r"कोणता|कोणत्या|काय|सांग|बताओ)",
    re.I,
)


def detect_language(text):
    """Return a transparent, approximate language label without external calls."""
    text = str(text or "")
    has_dev = bool(_DEVANAGARI.search(text))
    has_latin = bool(_ENGLISH.search(text))
    mr = len(_MARATHI_DEV.findall(text)) + len(_MARATHI_LATIN.findall(text))
    hi = len(_HINDI_DEV.findall(text)) + len(_HINDI_LATIN.findall(text))
    mixes_english = bool(
        re.search(
            r"\b(?:academic|background|course|degree|education|career|project|"
            r"goal|preference|memory|stack|student)\b",
            text,
            re.I,
        )
    )
    if has_dev:
        if mr and hi:
            base = "hi/mr"
        elif mr > hi:
            base = "mr"
        elif hi:
            base = "hi"
        else:
            base = "hi/mr"
        if has_latin and re.search(r"[A-Za-z]", text) and mixes_english:
            return "Marathi + English" if base == "mr" else "Hindi + English"
        return base
    if mr and hi:
        return "hi/mr-Latn"
    if mr:
        return "Marathi + English" if mixes_english else "mr-Latn"
    if hi:
        return "Hinglish" if mixes_english else "hi-Latn"
    if re.search(r"[\u0900-\u097f]", text):
        return "hi/mr"
    return "en" if has_latin else "und"


def understand(text):
    """Identify common personal-memory intents and attach canonical search text."""
    original = str(text or "")
    language = detect_language(original)
    if not _QUESTION_CUES.search(original):
        return {
            "language": language,
            "normalized_query": original,
            "intents": [],
        }

    found = [(name, anchor) for name, pattern, anchor in _INTENTS if pattern.search(original)]
    # Very short transliterated education questions often omit an English
    # category word (e.g. "Main kya padh raha hoon?").
    if not any(name == "education" for name, _ in found) and re.search(
        r"\b(?:main|mi|kaunsa|kaunsi|konta|kontya|shikat|padh)\b|"
        r"(?:मैं|मी|शिकत|पढ़|पढ)",
        original,
        re.I,
    ):
        found.append(
            ("education", "What is my academic background, degree, and course of study?")
        )
    # Do not create duplicate intent requirements when English logic already
    # recognized the same request.
    intents = list(dict.fromkeys(name for name, _ in found))
    normalized = " ".join(anchor for _, anchor in found) or original
    return {
        "language": language,
        "normalized_query": normalized,
        "intents": intents,
    }