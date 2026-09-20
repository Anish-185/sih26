"""Multilingual assistant layer — English, Hindi, Telugu.

    user query (any language)
        -> detect / honour the requested language
        -> rewrite known product and BIS terms into their canonical English
        -> the EXISTING deterministic SearchEngine, unchanged
        -> the SAME verified BIS records
        -> the grounded answer, written in the user's language

MetrIQ's multilingual assistant changes the LANGUAGE OF INTERACTION, not the
source of truth. The knowledge base stays canonical English and is never
translated, copied or re-indexed; standard numbers, record ids, document names
and source URLs stay exactly as stored. The model explains retrieved evidence in
the user's language — it never decides which standard applies.

Why a rewrite layer is needed at all: ``app/retrieval/text.normalize`` strips
every non-ASCII character, so a pure Hindi or Telugu query reaches retrieval as
an empty string and abstains. Rewriting known terms to canonical English BEFORE
retrieval fixes that without touching the retrieval engine, its scoring, or the
knowledge base. A query whose terms are not in the alias table simply reaches
retrieval as it does today — and abstains if there is no evidence, rather than
being guessed at.

The alias table is deliberately small: it covers products and BIS terms that are
actually in the verified knowledge base. It is not a dictionary, and it is not a
transliteration engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EN = "en"
HI = "hi"
TE = "te"
AUTO = "auto"

SUPPORTED: tuple[str, ...] = (EN, HI, TE)
ACCEPTED: tuple[str, ...] = (AUTO,) + SUPPORTED
DEFAULT = EN

LANGUAGE_NAMES = {EN: "English", HI: "Hindi", TE: "Telugu"}
ENDONYMS = {EN: "English", HI: "हिन्दी", TE: "తెలుగు"}

# Script blocks. Devanagari also has an extended block; Telugu does not.
_SCRIPTS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    (HI, ((0x0900, 0x097F), (0xA8E0, 0xA8FF))),   # Devanagari, Devanagari Extended
    (TE, ((0x0C00, 0x0C7F),)),                     # Telugu
)


def script_counts(text: str) -> dict[str, int]:
    """How many characters of each supported script the text contains."""
    counts = {HI: 0, TE: 0}
    for char in text or "":
        point = ord(char)
        for language, ranges in _SCRIPTS:
            if any(low <= point <= high for low, high in ranges):
                counts[language] += 1
                break
    return counts


def detect(text: str) -> str:
    """Deterministic script detection. No model, no network, no dependency.

    Mixed text is handled conservatively: any real run of Devanagari or Telugu
    wins, because a user who writes in their own script wants an answer in it,
    even when the product name stays in English ("Electric kettle కి ఏ standard?").
    Otherwise English.
    """
    counts = script_counts(text)
    if counts[HI] == counts[TE] == 0:
        return EN
    # A stray character (a symbol pasted in, a single matra) is not a language.
    winner = HI if counts[HI] >= counts[TE] else TE
    return winner if counts[winner] >= 2 else EN


def resolve(text: str, requested: str | None = None) -> str:
    """The language to answer in. An explicit choice always wins over detection."""
    choice = (requested or AUTO).strip().lower()
    if choice in SUPPORTED:
        return choice
    if choice and choice not in ACCEPTED:
        # An unknown code is not an error and is never guessed at: fall back to
        # detection, exactly as "auto" would.
        return detect(text)
    return detect(text)


# --------------------------------------------------------------- alias table
#
# canonical English term -> the Hindi, Telugu and romanized ways users write it.
# The canonical term on the left MUST retrieve something from the verified
# knowledge base; tests assert that, so a concept cannot drift into a term the
# knowledge base has no record for.
#
# Kept small on purpose. Only add an alias when it is a real name for the SAME
# product, in the spirit of the knowledge base's own keyword policy — never a
# category guess.

ALIASES: dict[str, tuple[str, ...]] = {
    # --- BIS vocabulary ---
    "standard": ("मानक", "मानकों", "स्टैंडर्ड", "ప్రమాణం", "ప్రమాణాలు", "స్టాండర్డ్"),
    "certification": ("प्रमाणन", "प्रमाणीकरण", "प्रमाण पत्र", "ధృవీకరణ", "సర్టిఫికేషన్", "ధృవపత్రం"),
    "isi mark": ("आईएसआई मार्क", "ఐఎస్ఐ మార్క్"),
    "licence": ("लाइसेंस", "लायसेंस", "లైసెన్స్"),
    "hallmarking": ("हॉलमार्किंग", "हालमार्किंग", "हॉलमार्क", "హాల్‌మార్కింగ్", "హాల్‌మార్క్"),
    "laboratory": ("प्रयोगशाला", "प्रयोगशालाओं", "ప్రయోగశాల", "ప్రయోగశాలలు"),
    "testing": ("परीक्षण", "जांच", "పరీక్ష", "పరీక్షలు"),
    # --- products that exist in the verified knowledge base ---
    "electric kettle": ("इलेक्ट्रिक केतली", "बिजली की केतली", "केतली",
                        "ఎలక్ట్రిక్ కెటిల్", "ఎలక్ట్రిక్ కేటిల్", "కెటిల్", "కేటిల్"),
    "led bulb": ("एलईडी बल्ब", "एलईडी लैंप", "बल्ब", "ఎల్ఈడీ బల్బ్", "ఎల్ఈడీ లైట్", "బల్బ్"),
    "cement": ("सीमेंट", "सिमेंट", "సిమెంట్"),
    "mobile phone": ("मोबाइल फोन", "मोबाइल फ़ोन", "मोबाइल", "మొబైల్ ఫోన్", "మొబైల్"),
    "laptop": ("लैपटॉप", "ల్యాప్‌టాప్"),
    "power bank": ("पावर बैंक", "పవర్ బ్యాంక్"),
    "television": ("टेलीविजन", "टेलीविज़न", "టెలివిజన్"),
    "lpg cylinder": ("एलपीजी सिलेंडर", "गैस सिलेंडर", "सिलेंडर",
                     "ఎల్పీజీ సిలిండర్", "గ్యాస్ సిలిండర్", "సిలిండర్"),
    "packaged drinking water": ("पैकेज्ड पेयजल", "बोतलबंद पानी", "पीने का पानी",
                                "ప్యాకేజ్డ్ తాగునీరు", "తాగునీరు", "బాటిల్ నీరు"),
    "gold": ("सोना", "स्वर्ण", "सोने", "బంగారం", "బంగారు"),
    "silver": ("चांदी", "चाँदी", "వెండి"),
    "reinforcement bar": ("सरिया", "स्टील बार", "इस्पात छड़", "స్టీల్ కడ్డీ", "ఇనుప కడ్డీ"),
    "clinical thermometer": ("थर्मामीटर", "థర్మామీటర్"),
    "room heater": ("रूम हीटर", "कमरा हीटर", "రూమ్ హీటర్"),
    "rice cooker": ("राइस कुकर", "चावल कुकर", "రైస్ కుక్కర్"),
    "induction stove": ("इंडक्शन चूल्हा", "इंडक्शन स्टोव", "ఇండక్షన్ స్టవ్"),
    "microwave oven": ("माइक्रोवेव ओवन", "माइक्रोवेव", "మైక్రోవేవ్ ఓవెన్", "మైక్రోవేవ్"),
    "electric iron": ("इलेक्ट्रिक इस्त्री", "प्रेस", "इस्त्री", "ఇస్త్రీ పెట్టె", "ఐరన్ బాక్స్"),
    "immersion water heater": ("इमर्शन हीटर", "पानी गरम करने की रॉड", "గీజర్", "ఇమ్మర్షన్ హీటర్"),
    "vacuum flask": ("थर्मस", "वैक्यूम फ्लास्क", "ఫ్లాస్క్", "థర్మాస్"),
    "feeding bottle": ("फीडिंग बोतल", "दूध की बोतल", "ఫీడింగ్ బాటిల్", "పాల సీసా"),
    "tyre": ("टायर", "टयर", "టైర్"),
    "battery": ("बैटरी", "बैट्री", "బ్యాటరీ"),
    "circuit breaker": ("सर्किट ब्रेकर", "सर्किट ब्रेकर एमसीबी", "సర్క్యూట్ బ్రేకర్"),
    "electric motor": ("इलेक्ट्रिक मोटर", "मोटर", "ఎలక్ట్రిక్ మోటార్", "మోటార్"),
}

# Romanized Hindi / Telugu question words. They are not product terms and carry
# no retrieval signal, but the retrieval engine does not know them, so they
# dilute query-term coverage and drag a Hinglish query's confidence down. They
# are dropped from the RETRIEVAL text only — the user's question is untouched.
# None of these is a term in the knowledge base (tested).
FILLER: frozenset[str] = frozenset({
    # Hindi
    "ke", "liye", "kaunsa", "kaun", "kya", "kyaa", "hai", "hain", "ka", "ki",
    "ko", "kis", "mein", "mera", "meri", "aur", "kaise", "kyun", "kyu",
    "batao", "bataye", "bataiye", "chahiye", "hota", "hoti", "jaruri", "zaruri",
    "nahi", "nahin", "iska", "uska", "yeh", "koi", "lagta", "lagu",
    # Telugu
    "ku", "emi", "edi", "ela", "enti", "ento", "cheppandi", "kosam", "undi",
    "unnayi", "vartistundi", "kaavali", "kavali", "gurinchi", "gaani", "ide",
})


@dataclass(frozen=True)
class Normalized:
    """A query rewritten for retrieval only. The user's question is never changed."""

    query: str                                  # what retrieval should see
    original: str
    concepts: list[str] = field(default_factory=list)   # canonical terms matched
    dropped: list[str] = field(default_factory=list)    # filler words removed

    @property
    def changed(self) -> bool:
        return bool(self.concepts or self.dropped)


# Longest alias first, so "इलेक्ट्रिक केतली" wins over "केतली".
_ALIAS_ORDER: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((alias, canonical) for canonical, aliases in ALIASES.items() for alias in aliases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)
_WORD = re.compile(r"[A-Za-z]+")


def normalize_query(text: str) -> Normalized:
    """Rewrite known non-English terms into canonical English, for RETRIEVAL only.

    Deterministic and order-independent in effect: aliases are applied
    longest-first, so a longer phrase is never broken up by a shorter one
    inside it. A term that is not in the table is left exactly as it is.
    """
    original = text or ""
    working = original
    concepts: list[str] = []

    for alias, canonical in _ALIAS_ORDER:
        if alias in working:
            working = working.replace(alias, f" {canonical} ")
            if canonical not in concepts:
                concepts.append(canonical)

    # Drop romanized filler words (Hinglish / Tanglish), whole words only.
    dropped: list[str] = []

    def keep(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.lower() in FILLER:
            if word.lower() not in dropped:
                dropped.append(word.lower())
            return " "
        return word

    working = _WORD.sub(keep, working)
    working = re.sub(r"\s+", " ", working).strip()

    # Never hand retrieval an empty string when the original had content: an
    # untranslatable query must reach retrieval and abstain on the evidence,
    # not be silently turned into nothing.
    if not working:
        working = original
    return Normalized(query=working, original=original, concepts=concepts, dropped=dropped)


# ------------------------------------------------------------ prompt + copy

_INSTRUCTION = """
LANGUAGE OF THE ANSWER: {name}.
Write the whole answer in {name}, in natural {name} prose.
Reproduce these EXACTLY as they appear in the evidence, never translated,
transliterated or reformatted: Indian Standard numbers (for example
IS 367:1993), scheme names, rule and requirement ids, record ids, HUIDs,
document names and source URLs. You may give a short gloss of a document title
in {name} beside the original title, never instead of it.
Translating the evidence does not make it stronger: the same limits apply in
every language. If the supplied evidence does not answer the question, say so in
{name} and stop.
"""


def instruction(language: str) -> str:
    """The language clause appended to an existing grounded system prompt.

    English adds nothing, so existing English behaviour is byte-for-byte what it
    was before this milestone.
    """
    if language == EN or language not in LANGUAGE_NAMES:
        return ""
    return _INSTRUCTION.format(name=LANGUAGE_NAMES[language])


def apply(system_prompt: str, language: str) -> str:
    """``system_prompt`` with the language clause appended (unchanged for English)."""
    clause = instruction(language)
    return f"{system_prompt.rstrip()}\n{clause}" if clause else system_prompt


# MetrIQ's own abstention sentence, in each supported language. This is the one
# place translated text is hard-coded, because it is MetrIQ speaking about its
# own evidence, not a claim about BIS — and it must be available when no model
# runs at all.
INSUFFICIENT = {
    EN: ("I couldn't find sufficient information in the available "
         "BIS knowledge base to answer this reliably."),
    HI: ("उपलब्ध BIS ज्ञान-आधार में इस प्रश्न का विश्वसनीय उत्तर देने के लिए "
         "पर्याप्त सत्यापित जानकारी नहीं मिली।"),
    TE: ("అందుబాటులో ఉన్న BIS విజ్ఞాన నిధిలో ఈ ప్రశ్నకు నమ్మదగిన సమాధానం "
         "ఇవ్వడానికి సరిపడా ధృవీకరించిన సమాచారం దొరకలేదు."),
}

EMPTY_QUESTION = {
    EN: "Please provide a question about BIS standards or BIS information.",
    HI: "कृपया BIS मानकों या BIS जानकारी से संबंधित कोई प्रश्न पूछें।",
    TE: "దయచేసి BIS ప్రమాణాలు లేదా BIS సమాచారం గురించి ఒక ప్రశ్న అడగండి.",
}


# MetrIQ's own sentence when it REJECTS a generated explanation (Milestone 20).
# Hard-coded per language for the same reason as INSUFFICIENT: MetrIQ is speaking
# about its own verification, and must be able to do so with no model running.
WITHHELD = {
    EN: ("MetrIQ checked the generated explanation against its own evidence and rejected it. "
         "The deterministic result and the evidence on this page are unchanged."),
    HI: ("MetrIQ ने उत्पन्न व्याख्या को अपने साक्ष्य के विरुद्ध जाँचा और उसे अस्वीकार कर दिया। "
         "निर्धारित (deterministic) परिणाम और इस पृष्ठ के साक्ष्य अपरिवर्तित हैं।"),
    TE: ("MetrIQ తయారైన వివరణను తన సాక్ష్యంతో సరిపోల్చి దానిని తిరస్కరించింది. "
         "నిర్ధారిత (deterministic) ఫలితం మరియు ఈ పేజీలోని సాక్ష్యం మారలేదు."),
}


def withheld(language: str) -> str:
    return WITHHELD.get(language, WITHHELD[EN])


def insufficient(language: str) -> str:
    return INSUFFICIENT.get(language, INSUFFICIENT[EN])


def empty_question(language: str) -> str:
    return EMPTY_QUESTION.get(language, EMPTY_QUESTION[EN])
