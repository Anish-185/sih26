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


# MetrIQ's own sentence when the explanation provider is unreachable and /ask
# falls back to rendering the retrieved records itself (Phase 1, Part C). Hard-
# coded per language for the same reason as INSUFFICIENT and WITHHELD: MetrIQ is
# speaking about its own evidence, and must be able to do so with no model
# running at all. The records themselves stay in their stored English — the
# knowledge base is never translated.
EVIDENCE_ONLY = {
    EN: ("An AI explanation is not available right now, so MetrIQ is showing the "
         "verified BIS records it retrieved for this question, exactly as they are "
         "stored. Nothing below was written by a language model."),
    HI: ("इस समय AI व्याख्या उपलब्ध नहीं है, इसलिए MetrIQ ने इस प्रश्न के लिए जो सत्यापित "
         "BIS रिकॉर्ड प्राप्त किए, उन्हें जैसा संग्रहीत है वैसा ही दिखाया जा रहा है। नीचे दिया गया "
         "कुछ भी किसी भाषा मॉडल द्वारा नहीं लिखा गया है।"),
    TE: ("ప్రస్తుతం AI వివరణ అందుబాటులో లేదు, అందువల్ల ఈ ప్రశ్నకు MetrIQ పొందిన ధృవీకరించిన "
         "BIS రికార్డులను నిల్వ ఉన్న రూపంలోనే చూపిస్తోంది. కింద ఉన్నది ఏదీ భాషా నమూనా "
         "(language model) రాసినది కాదు."),
}


def evidence_only(language: str) -> str:
    return EVIDENCE_ONLY.get(language, EVIDENCE_ONLY[EN])


# MetrIQ's own sentences for an informative abstention (Phase 3). Hard-coded per
# language for the same reason as INSUFFICIENT, EMPTY_QUESTION and WITHHELD:
# MetrIQ is speaking about its OWN coverage, not about BIS, and must be able to do
# so with no model running.
#
# Every sentence is a claim about what MetrIQ holds and what its search did. None
# of them is a claim about the product, and none of them says an Indian Standard
# does not exist for it — those are different statements, and conflating them
# would be a fabrication. The numbers are substituted from the knowledge base by
# app/boundary.py, never typed here.
#
# NOTE on "{product} is not on those lists": it is deliberately NOT said. MetrIQ
# cannot tell at runtime whether a product is genuinely absent from BIS's listings
# or merely listed under wording the query did not match — "refrigerator" retrieves
# nothing although BIS lists "Household Refrigerating Appliances", and "solar
# panel" retrieves solar water heating although BIS lists "Photovoltaic (PV)
# modules". So the boundary states BOTH possibilities and resolves neither.

BOUNDARY = {
    EN: {
        "heading": "Why MetrIQ did not answer this",
        "covers": ("MetrIQ's verified data covers {standards} Indian Standards that BIS lists "
                   "under compulsory certification — {scheme_i} from the Scheme I (ISI Mark) "
                   "listing and {scheme_ii} from the Scheme II (Compulsory Registration Scheme) "
                   "listing, transcribed from BIS's own pages and covering {products} listed "
                   "products, and {other} from other official BIS pages — plus "
                   "{legal_metrology} Legal Metrology packaged-commodity rule records."),
        "not_found": ("No standard in that verified data was matched to \u201c{product}\u201d."),
        "two_reasons": ("That can mean one of two things, and MetrIQ cannot tell which: the "
                        "product is not on the two BIS listing pages this data was built from, "
                        "or it is listed there under different wording from the words you used. "
                        "It does NOT mean that no Indian Standard exists for this product."),
        "why_boundary": ("BIS notifies roughly {notified} products under compulsory certification. "
                         "About {outside} of them sit in Quality Control Orders that BIS does not "
                         "publish on those two pages, so they are outside this dataset."),
        "where_next": "Search BIS's Know Your Standards by product name:",
        "weak_heading": "A weak match was retrieved",
        "weak_body": ("MetrIQ found the record below by a partial word match only. It is shown as "
                      "evidence of what the search did, NOT as an answer, and MetrIQ is not "
                      "putting it forward as the standard for this product."),
    },
    HI: {
        "heading": "MetrIQ ने इसका उत्तर क्यों नहीं दिया",
        "covers": ("MetrIQ के सत्यापित डेटा में BIS द्वारा अनिवार्य प्रमाणन के अंतर्गत सूचीबद्ध "
                   "{standards} भारतीय मानक हैं — {scheme_i} स्कीम I (ISI मार्क) सूची से और "
                   "{scheme_ii} स्कीम II (अनिवार्य पंजीकरण योजना) सूची से, जो BIS के अपने पृष्ठों से "
                   "लिए गए हैं और {products} सूचीबद्ध उत्पादों को कवर करते हैं — तथा {other} अन्य आधिकारिक "
                   "BIS पृष्ठों से; साथ ही {legal_metrology} लीगल मेट्रोलॉजी पैकेज्ड-कमोडिटी नियम रिकॉर्ड।"),
        "not_found": ("उस सत्यापित डेटा में “{product}” से मेल खाता कोई मानक नहीं मिला।"),
        "two_reasons": ("इसका अर्थ दो में से कुछ भी हो सकता है, और MetrIQ यह तय नहीं कर सकता कि कौन सा: "
                        "या तो यह उत्पाद उन दो BIS सूची-पृष्ठों पर नहीं है जिनसे यह डेटा बना है, या वह वहाँ "
                        "आपके उपयोग किए गए शब्दों से भिन्न शब्दों में सूचीबद्ध है। इसका यह अर्थ नहीं है कि "
                        "इस उत्पाद के लिए कोई भारतीय मानक मौजूद नहीं है।"),
        "why_boundary": ("BIS लगभग {notified} उत्पादों को अनिवार्य प्रमाणन के अंतर्गत अधिसूचित करता है। "
                         "इनमें से लगभग {outside} ऐसे गुणवत्ता नियंत्रण आदेशों (QCO) में हैं जिन्हें BIS उन "
                         "दो पृष्ठों पर प्रकाशित नहीं करता, इसलिए वे इस डेटासेट के बाहर हैं।"),
        "where_next": "उत्पाद के नाम से BIS की Know Your Standards में खोजें:",
        "weak_heading": "एक कमज़ोर मिलान मिला",
        "weak_body": ("MetrIQ को नीचे दिया गया रिकॉर्ड केवल आंशिक शब्द-मिलान से मिला। यह केवल यह दिखाने "
                      "के लिए है कि खोज ने क्या किया, उत्तर के रूप में नहीं — MetrIQ इसे इस उत्पाद के मानक "
                      "के रूप में प्रस्तुत नहीं कर रहा है।"),
    },
    TE: {
        "heading": "MetrIQ దీనికి ఎందుకు సమాధానం ఇవ్వలేదు",
        "covers": ("MetrIQ ధృవీకరించిన డేటాలో BIS తప్పనిసరి ధృవీకరణ కింద జాబితా చేసిన "
                   "{standards} భారతీయ ప్రమాణాలు ఉన్నాయి — {scheme_i} స్కీమ్ I (ISI మార్క్) "
                   "జాబితా నుండి, {scheme_ii} స్కీమ్ II (తప్పనిసరి నమోదు పథకం) జాబితా నుండి, "
                   "BIS సొంత పేజీల నుండి తీసుకున్నవి, {products} జాబితా చేసిన ఉత్పత్తులను "
                   "కవర్ చేస్తాయి — మరో {other} ఇతర అధికారిక BIS పేజీల నుండి, అదనంగా "
                   "{legal_metrology} లీగల్ మెట్రాలజీ ప్యాకేజ్డ్-కమోడిటీ "
                   "నియమ రికార్డులు."),
        "not_found": ("ఆ ధృవీకరించిన డేటాలో “{product}”కి సరిపోలిన ప్రమాణం ఏదీ దొరకలేదు."),
        "two_reasons": ("దీనికి రెండు అర్థాలు ఉండవచ్చు, వాటిలో ఏది అన్నది MetrIQ నిర్ధారించలేదు: ఈ ఉత్పత్తి "
                        "ఈ డేటా తయారైన రెండు BIS జాబితా పేజీలలో లేదు, లేదా మీరు వాడిన పదాలకు భిన్నమైన "
                        "పదాలతో అక్కడ జాబితా చేయబడి ఉంది. ఈ ఉత్పత్తికి భారతీయ ప్రమాణం లేదని దీని "
                        "అర్థం కాదు."),
        "why_boundary": ("BIS సుమారు {notified} ఉత్పత్తులను తప్పనిసరి ధృవీకరణ కింద నోటిఫై చేస్తుంది. "
                         "వాటిలో సుమారు {outside} ఉత్పత్తులు BIS ఆ రెండు పేజీలలో ప్రచురించని నాణ్యతా "
                         "నియంత్రణ ఉత్తర్వుల (QCO) పరిధిలో ఉన్నాయి, కాబట్టి అవి ఈ డేటాసెట్ వెలుపల ఉన్నాయి."),
        "where_next": "ఉత్పత్తి పేరుతో BIS Know Your Standards లో వెతకండి:",
        "weak_heading": "బలహీనమైన సరిపోలిక దొరికింది",
        "weak_body": ("కింది రికార్డు MetrIQ కు పాక్షిక పద-సరిపోలిక ద్వారా మాత్రమే దొరికింది. ఇది శోధన ఏమి "
                      "చేసిందో చూపడానికే తప్ప సమాధానంగా కాదు — MetrIQ దీనిని ఈ ఉత్పత్తికి ప్రమాణంగా "
                      "ముందుకు తీసుకురావడం లేదు."),
    },
}


def boundary(language: str) -> dict:
    """MetrIQ's own abstention sentences in the requested language."""
    return BOUNDARY.get(language, BOUNDARY[EN])


def withheld(language: str) -> str:
    return WITHHELD.get(language, WITHHELD[EN])


def insufficient(language: str) -> str:
    return INSUFFICIENT.get(language, INSUFFICIENT[EN])


def empty_question(language: str) -> str:
    return EMPTY_QUESTION.get(language, EMPTY_QUESTION[EN])
