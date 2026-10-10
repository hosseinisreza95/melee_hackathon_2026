"""/ask: natural-language questions answered ONLY from database rows (G3, cahier §16).

Pipeline:
1. `plan()`      deterministic intent(s) + entity resolution (regex over product names, aliases, species, countries,
                 crops and targets through the EPPO alias index, active-substance wording). A multi-part question
                 ("in which countries? and its uses? and its sister products?") yields one main intent + extra intents.
                 Follow-up questions inherit product / countries / species from the conversation `context`.
2. `run_tools()` predefined read-only queries (queries.py). Their rows ARE the evidence (facts).
3. `build_structured()` deterministic, question-shaped answer (headline, useful rows, sections, caveats) in the
                 answer language; always available, no key needed. When nothing is known about a product, the answer
                 says so and explains what the store covers and where to look.
4. LLM phrasing  optional: the model receives the same facts, the deterministic draft and the JSON schema; it may only
                 re-select and re-phrase. The grounding guard rejects any number or country not in the facts.
The LLM therefore never adds a fact.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..config import DISCLAIMER, settings
from ..db.models import Product, ProductAlias, Registration
from ..llm import LLMUnavailable, get_client
from ..parsers.base import norm_name
from . import queries as Q
from .answer_model import SCHEMA as ANSWER_SCHEMA, AnswerItem, AnswerSection, StructuredAnswer

log = logging.getLogger(__name__)

COUNTRY_WORDS = {
    "CA": ["canada", "canadian", "canadien", "canadienne", "canadá", "canadiense"],
    "US": ["usa", "united states", "u.s.", "etats-unis", "états-unis", "etats unis", "american", "américain", "epa", "estados unidos", "eua", "ee.uu", "eeuu", "estadounidense"],
    "FR": ["france", "french", "français", "francais", "française", "anses", "e-phy", "ephy", "frança", "francês", "francia", "francés"],
    "BR": ["brazil", "brésil", "bresil", "brazilian", "brésilien", "agrofit", "brasil", "brasileiro", "brasileño"],
    "DE": ["germany", "allemagne", "german", "allemand", "alemanha", "alemão", "alemania", "alemán"], "BE": ["belgium", "belgique", "bélgica", "belgica"],
    "MX": ["mexico", "mexique", "méxico"], "UY": ["uruguay", "uruguai"], "ES": ["spain", "espagne", "espanha", "españa", "espanol", "español"],
    "IT": ["italy", "italie", "itália", "italia"], "NL": ["netherlands", "pays-bas", "países baixos", "paises baixos", "holanda", "países bajos"],
    "GB": ["united kingdom", "royaume-uni", "uk", "reino unido"], "PL": ["poland", "pologne", "polônia", "polonia", "polish", "polonais"],
}
# first matching intent wins inside a question fragment; a multi-part question yields several intents (see detect_intents)
INTENTS = {
    "help": [r"^\s*(bonjour|salut|bonsoir|hello|hi|hey|olá|ola|hola|buenos d[ií]as|bom dia|good (morning|afternoon|evening))\b[^?]*$", r"que (peux|sais)[- ]tu", r"what can you",
             r"que (podes?|pode|consegue) fazer", r"qué puedes", r"\baide[- ]moi|\baide\b\s*[?!.]?$|^aide\b", r"^help\b|\bhelp me\b|\bhelp\b\s*[?!.]?$", r"\bajuda\b", r"\bayuda\b",
             r"comment (ça|ca) (marche|fonctionne)", r"how (does|do) (this|it|you) work", r"qui es[- ]tu", r"who are you", r"quem é você", r"quién eres",
             r"^\s*(merci|thanks?|thank you|obrigad[oa]|gracias)\b"],
    "sister_product": [r"\bs[oœ]urs?\b", r"\bsister", r"jumeau", r"irmã", r"irmão", r"\bhermanos?\b", r"équivalent", r"equivalent", r"même produit", r"same product", r"candidat"],
    "alternatives": [r"autres? marques?", r"other brands?", r"otras? marcas?", r"outras? marcas?", r"\balternativ", r"\bremplac", r"\bsubstitu", r"à la place", r"instead of", r"en lugar de",
                     r"\bsimilaire", r"\bsimilar\b", r"\bgénérique", r"\bgeneric\b", r"\bpareil", r"\bcomparable"],
    "data_quality": [r"incertain", r"uncertain", r"manquant", r"missing", r"\babsent", r"qualit", r"\bvalid", r"confiance", r"confidence", r"fiab"],
    "expiry": [r"expir", r"échéance", r"echeance", r"renouvel", r"renew", r"fin de validité", r"\bvencem", r"\bvence\b", r"\bcaduc"],
    "source": [r"\bsource", r"preuve", r"evidence", r"d'où", r"provenance", r"citation", r"\burl\b", r"\bfonte\b", r"\bfuente\b"],
    "changes": [r"\bchang", r"nouveaut", r"what's new", r"\bmodif", r"\bdiff\b", r"mudança", r"cambio"],
    "substance_search": [r"mati[eè]re active", r"substance active", r"active (ingredient|substance)", r"ingrediente activo", r"substância ativa", r"substancia activa", r"principio activo",
                         r"\bà base de\b", r"\ba base de\b", r"\bbased on\b"],
    "ingredient_search": [r"contenant", r"contien", r"containing", r"\bcontain", r"\bcontém\b", r"\bcontiene", r"microorganism", r"micro-organisme", r"\bsouche", r"\bstrain", r"\bespèce", r"\bspecies", r"same active",
                          r"même (?:micro|substance|matière)", r"\bcepa\b", r"\bcontendo\b", r"\bcontiene\b", r"\bcon (?:la |el )?(?:bacteria|hongo|microorganismo)"],
    "product_profile": [r"qu'?\s?est[- ]ce que c'?\s?est", r"c'?\s?est quoi", r"what is (this|it|that)\b", r"what'?s (this|it)\b", r"qué es (esto|este|eso|ese)", r"o que é (isto|isso|este)",
                        r"\bdécri[st]", r"\bdescri(be|ba|va)", r"\bprésente[- ]moi", r"\bfiche\b", r"\bprofil\b", r"\bparle[- ]moi", r"tell me about", r"\bquel (type|genre) de produit",
                        r"\bque tipo de produto", r"\bqué tipo de producto"],
    "target_search": [r"\bcontre\b", r"\bagainst\b", r"\bcontra\b", r"pour (lutter|traiter|contrôler|controler)", r"\bmaladies?\b", r"\bdiseases?\b", r"\bdoenças?\b", r"\benfermedad",
                      r"\bravageurs?\b", r"\bpests?\b", r"\bpragas?\b", r"\bplagas?\b", r"\btavelure\b", r"\bmildiou\b", r"\bo[iï]dium\b", r"\bpourriture\b", r"\bbotrytis\b",
                      r"\bsclerotin", r"\bpucerons?\b", r"\baphids?\b", r"\bpulg[oõ]", r"\bfusari", r"\bphytophthora", r"\bpythium", r"\bnématode", r"\bnematod"],
    "use_comparison": [r"\bcompar", r"\busages?\b", r"\buses?\b", r"\busos?\b", r"\bdose", r"\bculture", r"\bcrop", r"\bcultivo", r"\bcultura", r"\bcible", r"\btarget", r"\balvo",
                       r"restriction", r"différence", r"difference", r"\blabel", r"étiquette", r"\bdélai", r"\bdar\b", r"\bphi\b"],
    "registration_lookup": [r"homologu", r"register", r"enregistr", r"autoris", r"approv", r"quels pays", r"which countr", r"\boù\b", r"\bwhere\b", r"\bstatus", r"\bstatut", r"\blicen",
                            r"registrad", r"quais países", r"\bonde\b", r"\bqué países", r"\bdónde\b", r"\bhomologa"],
}
PRODUCT_INTENTS = {"registration_lookup", "use_comparison", "sister_product", "alternatives", "data_quality", "source", "target_search", "product_profile"}
SPECIES_STATIC = ["Coniothyrium minitans", "Clonostachys rosea", "Gliocladium catenulatum", "Metarhizium brunneum", "Metarhizium anisopliae",
                  "Beauveria bassiana", "Trichoderma", "Bacillus", "Streptomyces", "Cordyceps javanica"]
# question words that are not EPPO aliases (fruit / plural / Spanish / Portuguese wording) -> crop concept id
CROP_EXTRA = {"fraise": "strawberry", "fraises": "strawberry", "fresa": "strawberry", "fresas": "strawberry", "frutilla": "strawberry", "morango": "strawberry", "morangos": "strawberry",
              "raisin": "grapevine", "grape": "grapevine", "grapes": "grapevine", "vid": "grapevine", "viñedo": "grapevine", "uva": "grapevine", "uvas": "grapevine", "videira": "grapevine",
              "pomme": "apple", "pommes": "apple", "pommier": "apple", "pommiers": "apple", "manzano": "apple", "manzanos": "apple", "manzana": "apple", "manzanas": "apple",
              "macieira": "apple", "maçã": "apple", "maçãs": "apple", "apples": "apple", "poire": "pear", "poirier": "pear", "peral": "pear", "pera": "pear", "pereira": "pear",
              "pêche": "peach", "pêcher": "peach", "melocotonero": "peach", "durazno": "peach", "pessegueiro": "peach", "cerise": "cherry", "cerisier": "cherry", "cerezo": "cherry",
              "cerejeira": "cherry", "tomates": "tomato", "tomatoes": "tomato", "tomateiro": "tomato", "salade": "lettuce", "salad": "lettuce", "lettuces": "lettuce", "lechuga": "lettuce",
              "alface": "lettuce", "potatoes": "potato", "papa": "potato", "papas": "potato", "patata": "potato", "patatas": "potato", "batata": "potato", "onions": "onion",
              "cebolla": "onion", "cebola": "onion", "carrots": "carrot", "zanahoria": "carrot", "cenoura": "carrot", "cucumbers": "cucumber", "pepino": "cucumber", "pepinos": "cucumber",
              "vigne": "grapevine", "vignes": "grapevine"}
# source wordings that cover a crop (E-Phy groups, French/English/Portuguese crop words) in addition to the concept name
CROP_GROUPS = {"apple": ["pommier", "pomme", "fruits à pépins", "pome fruit", "maçã", "macieira", "manzano"], "pear": ["poirier", "fruits à pépins", "pome fruit", "pereira"],
               "peach": ["pêcher", "fruits à noyau", "stone fruit", "pessegueiro"], "cherry": ["cerisier", "fruits à noyau", "stone fruit", "cerejeira"],
               "grapevine": ["vigne", "raisin", "grape", "videira", "uva", "vid"], "strawberry": ["fraisier", "fraise", "morango", "fresa"], "lettuce": ["laitue", "salades", "alface", "lechuga"],
               "tomato": ["tomate", "tomateiro"], "cucumber": ["concombre", "cucurbitacées à peau comestible", "pepino"], "potato": ["pomme de terre", "batata", "papa", "patata"],
               "onion": ["oignon", "cebola", "cebolla"], "carrot": ["carotte", "cenoura", "zanahoria"], "maize": ["maïs", "corn", "milho"], "wheat": ["blé", "trigo"], "soybean": ["soja", "soy"]}


def crop_terms(crop: str | None) -> list[str]:
    """Wordings accepted for a crop filter: the concept name plus the group / language wordings the sources use."""
    if not crop:
        return []
    return list(dict.fromkeys([crop.lower()] + CROP_GROUPS.get(crop.lower(), [])))


# crop-dependent disease words: wording -> {crop concept id: (EPPO code candidate, display name)}; None = crop unknown
TARGET_HINTS = {
    "tavelure": {"apple": ("VENTIN", "Venturia inaequalis (tavelure du pommier)"), "pear": ("VENTPI", "Venturia pyrina (tavelure du poirier)"), None: (None, "tavelure")},
    "scab": {"apple": ("VENTIN", "Venturia inaequalis (apple scab)"), "pear": ("VENTPI", "Venturia pyrina (pear scab)"), None: (None, "scab")},
    "sarna": {"apple": ("VENTIN", "Venturia inaequalis (sarna da macieira)"), None: (None, "sarna")},
    "moteado": {"apple": ("VENTIN", "Venturia inaequalis (moteado del manzano)"), None: (None, "moteado")},
    "mildiou": {"grapevine": ("PLASVI", "Plasmopara viticola (mildiou de la vigne)"), "potato": ("PHYTIN", "Phytophthora infestans (mildiou de la pomme de terre)"),
                "tomato": ("PHYTIN", "Phytophthora infestans (mildiou de la tomate)"), None: (None, "mildiou")},
    "downy mildew": {"grapevine": ("PLASVI", "Plasmopara viticola (grapevine downy mildew)"), None: (None, "downy mildew")},
    "míldio": {"grapevine": ("PLASVI", "Plasmopara viticola (míldio da videira)"), None: (None, "míldio")},
    "mildiu": {"grapevine": ("PLASVI", "Plasmopara viticola (mildiu de la vid)"), None: (None, "mildiu")},
    "oïdium": {"grapevine": ("UNCINE", "Erysiphe necator (oïdium de la vigne)"), None: (None, "oïdium")},
    "oidium": {"grapevine": ("UNCINE", "Erysiphe necator (oïdium de la vigne)"), None: (None, "oïdium")},
    "powdery mildew": {"grapevine": ("UNCINE", "Erysiphe necator (grapevine powdery mildew)"), None: (None, "powdery mildew")},
    "oídio": {"grapevine": ("UNCINE", "Erysiphe necator (oídio da videira)"), None: (None, "oídio")},
}
PORTFOLIO_RE = re.compile(r"quels? produits?|which products?|what products?|quais produtos|qué productos|cuáles productos|combien de produits|how many products|quantos produtos|cuántos productos|liste des produits|list (?:of |the )?products|produits (?:lallemand|homologu|enregistr|autoris)"
                          r"|lallemand products|produtos (?:lallemand|registrad)|productos (?:lallemand|registrad)|portefeuille|portfolio|tous les produits|all (?:the )?products|todos os produtos|todos los productos")
ALL_COUNTRIES_RE = re.compile(r"quels pays|which countr|quais pa[ií]ses|qué países|dans quels|em quais|en qué|where|où |onde|dónde|partout|everywhere|tous les pays|all countries|todos os pa[ií]ses|todos los países")
NO_ADVICE_RE = re.compile(r"(utilis|use it|usar|utilizar|employ|appliqu|apply).{0,40}(autre|another|other|otro|outra|différent|different)|(autre|another|other|otro|outra).{0,20}(culture|crop|cultivo|cultura)")
LANG_MARKERS = {
    "es": [r"¿", r"¡", r"\bqué\b", r"\bpuedo\b", r"\bcultivo\b", r"\butilizar", r"\bproducto", r"\benfermedad", r"\bplaga", r"\bmanzano", r"\bcuál", r"\bdónde\b", r"\besto\b",
           r"\bpara\b", r"\btambién\b", r"\bmateria activa", r"\bestá registrado\b", r"\bhay\b", r"\bqué es\b", r"\bmarca\b", r"\botro\b", r"\botra\b"],
    "pt": [r"\bvocê\b", r"\bestá\b", r"\bestão\b", r"\bnão\b", r"\bquais\b", r"\bproduto\b", r"\bcultura\b", r"\bdoença", r"\bpraga", r"\bonde\b", r"\btambém\b", r"\bsubstância",
           r"\bregistrado\b", r"\bpaíses\b", r"\bqual\b", r"\bcontra\b", r"\bmarca\b", r"\boutra\b", r"\bprocuro\b", r"\bo que é\b"],
    "fr": [r"\best-il\b", r"\bquels?\b", r"\bquelles?\b", r"\bcontre\b", r"\bhomologu", r"\bproduit", r"\bpays\b", r"\busages?\b", r"\bmati[eè]re\b", r"\bje\b", r"\bcherche\b",
           r"\bpour\b", r"\bdans\b", r"\bautre\b", r"\bmaladie", r"\bavec\b", r"\bqu'est", r"\bc'est\b", r"\bpeut\b", r"\bmarque\b", r"\bet\b", r"\bses\b"],
    "en": [r"\bwhich\b", r"\bwhat\b", r"\bregistered\b", r"\bproduct", r"\bcrop\b", r"\bcountries\b", r"\buses\b", r"\bis\b", r"\bthe\b", r"\bagainst\b", r"\bdisease",
           r"\bfor\b", r"\bcan\b", r"\bwith\b", r"\bbrand", r"\band\b", r"\bits\b", r"\bare\b"],
}


def detect_language(question: str) -> str | None:
    """Language of the question (fr / en / pt / es) when the markers are clear, else None (the UI language is used)."""
    ql = question.lower()
    scores = {lang: sum(1 for p in pats if re.search(p, ql)) for lang, pats in LANG_MARKERS.items()}
    best = max(scores, key=scores.get)
    second = max(v for k, v in scores.items() if k != best)
    return best if scores[best] >= 2 and scores[best] > second else None


def species_in_db(session: Session) -> list[str]:
    """Genus+species present in the store (any product), so questions about any micro-organism resolve, not only the pilots."""
    out = set(SPECIES_STATIC)
    for (ae,) in session.query(Product.active_entity_normalized).filter(Product.active_entity_normalized.isnot(None)):
        w = ae.split()
        if len(w) >= 2 and w[0][:1].isupper() and w[1][:1].islower():
            out.add(f"{w[0]} {w[1]}")
    return sorted(out, key=len, reverse=True)


def crop_in_question(q: str) -> str | None:
    """Crop concept from the question using the EPPO alias index (starter languages + observed and extra wordings) plus CROP_EXTRA."""
    from ..normalize.eppo import _index

    concepts, alias = _index("crop")
    ql = " " + re.sub(r"[^\w\s-]", " ", q.lower()) + " "
    best = None
    for name, cid in list(alias.items()) + list(CROP_EXTRA.items()):
        if len(name) >= 3 and f" {name} " in ql and (best is None or len(name) > len(best[0])):
            best = (name, cid)
    if best:
        c = concepts.get(best[1])
        return c.name_normalized if c else best[1]
    return None


def _crop_word(q: str) -> str | None:
    """The crop wording as it appears in the question (longest matching alias)."""
    from ..normalize.eppo import _index

    _, alias = _index("crop")
    ql = " " + re.sub(r"[^\w\s-]", " ", q.lower()) + " "
    best = None
    for name in list(alias) + list(CROP_EXTRA):
        if len(name) >= 3 and f" {name} " in ql and (best is None or len(name) > len(best)):
            best = name
    return best


def _crop_concept_id(q: str) -> str | None:
    from ..normalize.eppo import _index

    concepts, alias = _index("crop")
    ql = " " + re.sub(r"[^\w\s-]", " ", q.lower()) + " "
    best = None
    for name, cid in list(alias.items()) + list(CROP_EXTRA.items()):
        if len(name) >= 3 and f" {name} " in ql and (best is None or len(name) > len(best[0])):
            best = (name, cid)
    return best[1] if best else None


GENERIC_TARGET_WORDS = {"pourriture", "mildiou", "maladie", "maladies", "disease", "doença", "enfermedad", "champignons", "insectes", "fungus", "fungi", "black", "white", "brown", "downy", "powdery", "grapevine", "tomato"}
TARGET_LEAD = re.compile(r"(?:contre|against|contra|para (?:controlar|combatir|combater)|pour (?:lutter contre|traiter|contrôler|controler)|to control|para)\s+"
                         r"(?:la |le |les |l'|el |los |las |a |o |as |os |the |du |de la |des |do |da |de |d')?([\w'’ \-]{3,48}?)"
                         r"(?=[?.,;:!]|\s+(?:sur|on|en|em|dans|pour|para|in|au|aux|et|and|e|y|de la|du|des|of|do|da)\b|$)")


def target_in_question(q: str, crop_cid: str | None) -> tuple[list[str], str | None, str | None]:
    """(search terms, EPPO code candidate, display name) for the disease / pest named in the question: EPPO pest index (starter,
    observed and extra multilingual aliases) by longest alias; crop-dependent words (tavelure, mildiou…) through TARGET_HINTS;
    else the wording after 'contre / against / contra'."""
    from ..normalize.eppo import _index

    concepts, alias = _index("pest")
    ql = " " + re.sub(r"[^\w\s'’-]", " ", q.lower()) + " "
    best = None
    for name, cid in alias.items():
        if len(name) >= 4 and f" {name} " in ql and (best is None or len(name) > len(best[0])):
            best = (name, cid)
    hint = None
    for word, by_crop in TARGET_HINTS.items():
        if f" {word} " in ql and (hint is None or len(word) > len(hint[0])):
            hint = (word, by_crop)
    if best and (hint is None or len(best[0]) >= len(hint[0])):
        c = concepts[best[1]]
        crop_words = set(_index("crop")[1]) | set(CROP_EXTRA)
        terms = {best[0], c.name_normalized.lower(), (c.scientific_name or "").lower()} | {a for a, cid in alias.items() if cid == best[1]}
        for t in list(terms):
            head = t.split()[0] if t else ""
            if len(head) >= 5 and head not in GENERIC_TARGET_WORDS and head not in crop_words:
                terms.add(head)  # 'tavelure', 'venturia', 'botrytis', 'sarna' - the wording the sources use
        terms = [t for t in terms if t and len(t) >= 4]
        return sorted(terms, key=len, reverse=True), c.eppo_code, c.scientific_name or c.name_normalized
    if hint:
        word, by_crop = hint
        code, name = by_crop.get(crop_cid, by_crop[None])
        return [word], code, name
    m = TARGET_LEAD.search(ql)
    if m:
        w = re.sub(r"\s+", " ", m.group(1)).strip(" '’-")
        if w and w.split()[0] not in ("quel", "quelle", "quels", "which", "what", "qué", "cuál", "qual", "quais"):
            return [w], None, w
    return [], None, None


FLAG_RES = {"expiry": re.compile(r"expir|échéance|echeance|\bvence|caduc|validité|validity"), "holder": re.compile(r"titulaire|\bholder\b|\btitular\b|d[ée]tenteur|registrant"),
            "dose": re.compile(r"\bdos(e|age|is)\b"), "same_product": re.compile(r"même produit|same product|mesmo produto|mismo producto|autre nom|other name|outro nome|otro nombre|\balias\b|synonyme|synonym|sinônimo|sinónimo|nom alternatif|alternate name")}
SUBSTANCE_LEAD = re.compile(r"(?:mati[eè]re active|substance active|active (?:ingredient|substance)|ingrediente activo|substância ativa|substancia activa|principio activo|à base de|a base de|based on|contenant|contiennent|contient|containing|contain|contendo|contém|contiene|contienen)"
                            r"\s*[:=]?\s*(?:la |le |l'|el |la |a |o |the |de |d')?([\w'’ \-]{3,40}?)(?=[?.,;:!)]|\s+(?:sur|on|en|em|dans|pour|para|in|au|aux|et|and|e|y|que|qui|which|that|homolog|registr|autoris)\b|$)")
SUBSTANCE_SYNONYMS = {"captana": "captan", "captane": "captan", "cobre": "cuivre", "copper": "cuivre", "cuivre": "cuivre", "soufre": "sulphur", "azufre": "sulphur", "enxofre": "sulphur", "sulfur": "sulphur"}


def substance_in_question(q: str) -> str | None:
    m = SUBSTANCE_LEAD.search(q.lower())
    if not m:
        return None
    w = re.sub(r"\s+", " ", m.group(1)).strip(" '’-:")
    w = re.sub(r"^(?:du |de la |de l'|des |de |d'|le |la |les |l'|the |of |o |a |os |as |el |los |las |un |une |a |an )+", "", w).strip()
    return w or None


@dataclass
class Plan:
    intent: str
    product_ids: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    species: str | None = None
    crop: str | None = None
    months: int = 12
    unresolved_names: list[str] = field(default_factory=list)
    scope: str = "all"  # country_portfolio: 'lallemand' (holder LALLEMAND/DANSTAR) or 'all'
    inherited: list[str] = field(default_factory=list)  # what a follow-up question took from the conversation context
    extra_intents: list[str] = field(default_factory=list)  # further parts of a multi-part question
    target_terms: list[str] = field(default_factory=list)
    target_code: str | None = None
    target_name: str | None = None
    substance: str | None = None
    crop_cid: str | None = None
    no_advice: bool = False
    flags: list[str] = field(default_factory=list)  # expiry | holder | dose | same_product (what the question focuses on)
    crop_word: str | None = None  # the crop as written in the question (for headlines); `crop` is the concept name used for filtering


# --------------------------------------------------------------------------- 1. plan
def _product_index(session: Session) -> list[tuple[str, str, str]]:
    """(normalized name, product_id, kind) for every commercial name and alias, longest first."""
    idx: list[tuple[str, str, str]] = []
    for p in session.query(Product):
        idx.append((norm_name(p.commercial_name), p.product_id, "name"))
    for a in session.query(ProductAlias):
        idx.append((norm_name(a.alias_name), a.product_id, "alias"))
    # longest first; for the same wording a product's own name wins over another product's alias (PRESTOP WG carries
    # 'LALSTOP G46 WG' as an alternate name, but the question is about LALSTOP G46 WG itself)
    return sorted({i for i in idx if len(i[0]) >= 4}, key=lambda t: (-len(t[0]), t[2] != "name", t[1]))


def _intent_of(fragment: str) -> str | None:
    for name, pats in INTENTS.items():
        if any(re.search(p, fragment) for p in pats):
            return name
    return None


def detect_intents(question: str) -> list[str]:
    """Intents in the order asked: one per question fragment ('… ? … ? …'), duplicates removed."""
    q = question.lower()
    frags = [f.strip() for f in re.split(r"[?!;]+|\.\s+|\bet aussi\b|\band also\b", q) if f.strip()] or [q]
    out: list[str] = []
    for f in frags:
        it = _intent_of(f)
        if it and it not in out:
            out.append(it)
    if not out:
        it = _intent_of(q)
        out = [it] if it else []
    return out


def plan(session: Session, question: str, context: dict | None = None) -> Plan:
    q = question.lower()
    qn = " " + norm_name(question) + " "
    intents = detect_intents(question)
    intent = intents[0] if intents else "registration_lookup"
    countries = [cc for cc, words in COUNTRY_WORDS.items() if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", q) for w in words)]
    countries += [m for m in re.findall(r"\b([A-Z]{2})\b", question) if m in COUNTRY_WORDS and m not in countries]
    pids: list[str] = []
    consumed = qn
    for nname, pid, kind in _product_index(session):
        if f" {nname} " in consumed and pid not in pids:
            pids.append(pid)
            consumed = consumed.replace(f" {nname} ", " ")
            if kind == "name" and len(pids) >= 3:
                break
    species = next((s for s in species_in_db(session) if s.lower() in q), None)
    crop = crop_in_question(question)
    crop_cid = _crop_concept_id(question)
    crop_word = _crop_word(question)
    m = re.search(r"(\d{1,2})\s*(mois|months?|meses)", q)
    months = int(m.group(1)) if m else 12
    substance = substance_in_question(question)
    tterms, tcode, tname = target_in_question(question, crop_cid)
    flags = [k for k, rx in FLAG_RES.items() if rx.search(q)]
    if intent == "substance_search" and not substance and species:
        intent = "ingredient_search"
    if intent == "ingredient_search" and not species and substance and not pids:
        intent = "substance_search"  # 'quels produits contiennent du cuivre' - a substance, not a micro-organism species
    if species and not pids and intent in ("registration_lookup", "use_comparison", "substance_search", "target_search"):
        intent = "ingredient_search"
    if intent == "target_search" and not pids and not tterms:
        intent = "ingredient_search" if species else "target_search"
    if intent == "expiry" and pids:
        intent = "registration_lookup"  # 'quelle est la date d'expiration de X au Canada' - about one product, not the watch list
    unresolved = []
    if not pids and intent in PRODUCT_INTENTS:
        for tok in re.findall(r"\b([A-Z][A-Z0-9]{2,}(?:[ \-][A-Z0-9]{1,6})*)\b", question):  # UPPERCASE tokens look like product names
            if tok not in COUNTRY_WORDS and norm_name(tok) not in {"EPPO", "ANSES", "EPA", "USA", "LPC", "LALLEMAND", "DANSTAR"} and tok not in unresolved:
                unresolved.append(tok)
    scope = "lallemand" if re.search(r"lallemand|danstar", q) else "all"
    if not pids and not species and countries and PORTFOLIO_RE.search(q) and not substance and not (intent == "target_search" and tterms) and intent != "substance_search":
        intent = "country_portfolio"
        unresolved = []
    # follow-up questions ('et en France ?', 'et ses usages ?'): take the subject from the previous turn, deterministically
    inherited: list[str] = []
    ctx = context or {}
    if ctx and not pids and not species and intent not in ("expiry", "changes", "country_portfolio", "help", "substance_search") and not (intent == "target_search" and tterms):
        if ctx.get("productIds"):
            pids = [p for p in ctx["productIds"] if session.get(Product, p)]
            if pids:
                inherited.append("product")
                unresolved = []
                if intent == "ingredient_search":
                    intent = "registration_lookup"
        elif ctx.get("species"):  # previous turn was about a micro-organism: 'and in Canada?' keeps species (and crop)
            species = ctx["species"]
            inherited.append("species")
            if intent in ("registration_lookup", "use_comparison", "ingredient_search"):
                intent = "ingredient_search"
            if not crop and ctx.get("crop"):
                crop = ctx["crop"]
    if inherited and not countries and ctx.get("countries") and not ALL_COUNTRIES_RE.search(q):
        countries = list(ctx["countries"])
        inherited.append("countries")
    extra = [i for i in intents[1:] if i in PRODUCT_INTENTS and i != intent] if pids else []
    return Plan(intent, pids, countries, species, crop, months, unresolved, scope, inherited, extra[:4], tterms, tcode, tname, substance, crop_cid,
                bool(NO_ADVICE_RE.search(q)), flags, crop_word)


# --------------------------------------------------------------------------- 2. tools (the only data access)
def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def run_tools(session: Session, pl: Plan) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Return (facts, evidence, warnings, tools_used). Facts are compact rows the LLM may phrase."""
    facts: list[dict] = []
    evidence: list[dict] = []
    warnings: list[str] = []
    tools: list[str] = []
    if pl.inherited:  # say explicitly what was taken from the conversation
        parts = []
        if "product" in pl.inherited:
            parts.append(", ".join((session.get(Product, p).commercial_name if session.get(Product, p) else p) for p in pl.product_ids))
        if "species" in pl.inherited:
            parts.append(f"{pl.species}" + (f" ({pl.crop})" if pl.crop else ""))
        if "countries" in pl.inherited:
            parts.append(", ".join(pl.countries))
        warnings.append("Context taken from the conversation: " + " · ".join(parts) + ".")
    if pl.no_advice:
        warnings.append("No advice on use: only the official label of the registered product is authoritative; a use on another crop is a regulatory decision, not a data point.")

    def use_matches(u: dict) -> bool:
        ok = True
        if pl.crop:
            cw = ((u.get("cropNormalized") or "") + " | " + (u.get("cropOriginal") or "")).lower()
            ok = any(t in cw for t in crop_terms(pl.crop))
        if ok and pl.target_terms and pl.product_ids:
            tx = ((u.get("targetNormalized") or "") + " " + (u.get("targetOriginal") or "")).lower()
            ok = any(t in tx for t in pl.target_terms) or (pl.target_code and u.get("eppoTargetCode") == pl.target_code)
        return ok

    def add_reg(r: dict, product_name: str | None = None, uses_limit: int = 0):
        uses = r.get("uses", [])
        matched = [u for u in uses if use_matches(u)] if (pl.crop or (pl.target_terms and pl.product_ids)) else uses
        facts.append({"type": "registration", "product": product_name or r["productId"], "country": r["countryCode"],
                      "registrationNumber": r["registrationNumber"], "statusOriginal": r["statusOriginal"], "statusNormalized": r["statusNormalized"],
                      "authority": r["authorityName"], "holder": r["holderOriginal"], "approvalDate": r["approvalDate"], "expirationDate": r["expirationDate"],
                      "usesCount": r["usesCount"], "validationStatus": r["evidence"]["validationStatus"], "sourceId": r["evidence"]["sourceId"],
                      "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": _iso(r["evidence"]["collectedAt"])})
        if (pl.crop or (pl.target_terms and pl.product_ids)) and uses:
            facts[-1]["matchingUsesCount"] = len(matched)
            facts.append({"type": "crop_check", "product": product_name or r["productId"], "country": r["countryCode"], "registrationNumber": r["registrationNumber"],
                          "crop": pl.crop, "target": pl.target_name or (pl.target_terms[0] if pl.target_terms else None), "matchingUses": len(matched), "totalUses": len(uses)})
        evidence.append(r["evidence"])
        for u in matched[:uses_limit]:
            facts.append({"type": "use", "country": r["countryCode"], "registrationNumber": r["registrationNumber"], "crop": u["cropOriginal"],
                          "cropNormalized": u["cropNormalized"], "eppoCropCode": u["eppoCropCode"], "target": u["targetOriginal"],
                          "targetNormalized": u["targetNormalized"], "eppoTargetCode": u.get("eppoTargetCode"), "dose": u["doseValue"], "doseUnit": u["doseUnitOriginal"],
                          "phiDays": u["phiDays"], "maxApplications": u["maxApplications"], "restrictions": (u["restrictionsOriginal"] or "")[:300] or None,
                          "pairing": u["pairing"], "extractionMethod": u["evidence"]["extractionMethod"]})

    def add_sources():
        tools.append("sources")
        for s in Q.store_scope(session):
            if not s.get("registrations") and not s.get("lastCollectedAt"):
                continue  # only the sources actually collected in this store
            facts.append({"type": "source", "sourceId": s["sourceId"], "country": s["countryOrRegion"], "officialName": s["officialName"], "registrations": s["registrations"],
                          "collectedAt": _iso(s["lastCollectedAt"]), "url": s["baseUrl"], "scope": s["scope"]})

    def add_targets(pid: str, pname: str):
        tools.append("targets_of_product")
        for tg in Q.targets_of_product(session, pid, pl.countries or None):
            facts.append({"type": "target", "product": pname, **tg})

    if pl.intent == "help":
        add_sources()
        return facts, evidence, warnings, tools

    if pl.intent == "expiry":
        tools.append("expiring")
        rows = Q.expiring(session, pl.months)
        for r in rows:
            add_reg(r, r["productName"])
            facts[-1]["daysLeft"] = r["daysLeft"]
        if not rows:
            warnings.append(f"No registration with an expiry date within {pl.months} months in the collected sources; BR and US sources give no expiry dates.")
        warnings.append("Expiry dates exist only in CA-PPID and FR-EPHY (withdrawal date); US-EPA-PPLS and BR-AGROFIT do not publish them.")
        return facts, evidence, warnings, tools

    if pl.intent == "changes":
        tools.append("changes")
        for c in Q.changes(session, 50):
            row = {"type": "change", **{k: _iso(v) for k, v in c.items()}}
            reg = session.get(Registration, c.get("entityId")) if c.get("entityType") == "registration" or str(c.get("entityId", "")).startswith("R-") else None
            if reg is not None:
                row["product"] = reg.product.commercial_name
                row["country"] = reg.country_code
                row["registrationNumber"] = reg.registration_number
            facts.append(row)
        if not facts:
            warnings.append("No change detected yet: change detection needs at least two collections of the same source.")
        return facts, evidence, warnings, tools

    if pl.intent == "substance_search" and not pl.product_ids:
        tools.append("search_active_substance")
        x = pl.substance or ""
        key = SUBSTANCE_SYNONYMS.get(x.lower(), x)
        rows = Q.search_active_substance(session, key, pl.countries or None) if key else []
        if not rows and len(key) >= 6:
            rows = Q.search_active_substance(session, key[:5], pl.countries or None)  # stem: 'captana' -> 'capta' -> 'captane (Captan)'
        for r in rows[:40]:
            add_reg(r, r["productName"])
            facts[-1]["activeEntityOriginal"] = r.get("activeEntityOriginal")
        facts.append({"type": "substance_query", "substance": x, "searched": key, "found": len(rows)})
        if not rows:
            facts.append({"type": "actives_available", "items": [{"active": a, "registrations": n} for a, n in Q.active_entities_available(session, pl.countries or None)]})
            warnings.append(f"No product with active substance '{x}' in the collected sources - not proof of absence.")
        if len(rows) > 40:
            warnings.append(f"{len(rows)} registrations match '{x}'; only the first 40 are listed - add a country or a crop to narrow.")
        return facts, evidence, warnings, tools

    if pl.intent == "ingredient_search" or (pl.species and not pl.product_ids):
        tools.append("products_by_active_entity")
        sp = pl.species or ""
        rows = Q.products_by_active_entity(session, sp, pl.crop, pl.countries or None) if sp else []
        for r in rows:
            add_reg(r, r["productName"])
            facts[-1]["activeEntityNormalized"] = r["activeEntityNormalized"]
            facts[-1]["matchingUsesCount"] = r["matchingUsesCount"]
            for u in r["matchingUses"][:3]:
                facts.append({"type": "use", "country": r["countryCode"], "registrationNumber": r["registrationNumber"], "product": r["productName"],
                              "crop": u["cropOriginal"], "cropNormalized": u["cropNormalized"], "target": u["targetOriginal"], "dose": u["doseValue"],
                              "doseUnit": u["doseUnitOriginal"], "pairing": u["pairing"]})
        if not sp:
            warnings.append("No micro-organism species recognised in the question (known species are those present in the store, e.g. " + ", ".join(SPECIES_STATIC[:5]) + ").")
            facts.append({"type": "actives_available", "items": [{"active": a, "registrations": n} for a, n in Q.active_entities_available(session, pl.countries or None)]})
        elif not rows:
            warnings.append(f"No product with '{sp}'" + (f" on crop '{pl.crop}'" if pl.crop else "") + " in the collected sources - not proof of absence.")
        if pl.crop:
            warnings.append("Crop filter applied on normalized and original crop wording; CA/US crop lists are not paired with targets by the source.")
        return facts, evidence, warnings, tools

    if pl.intent == "target_search" and not pl.product_ids:
        tools.append("uses_by_target")
        if not pl.target_terms:
            warnings.append("No disease or pest recognised in the question.")
            facts.append({"type": "targets_available", "crop": pl.crop, "items": [{"target": t, "registrations": n} for t, n in Q.targets_available(session, crop_terms(pl.crop), pl.countries or None)]})
            return facts, evidence, warnings, tools
        rows = Q.uses_by_target(session, pl.target_terms, pl.target_code, crop_terms(pl.crop), pl.countries or None)
        facts.append({"type": "target_id", "wording": pl.target_terms[0], "eppoCode": pl.target_code, "name": pl.target_name, "crop": pl.crop_word or pl.crop, "found": len(rows)})
        for r in rows[:40]:
            add_reg(r, r["productName"])
            facts[-1]["activeEntityOriginal"] = r.get("activeEntityOriginal")
            facts[-1]["matchingUsesCount"] = r["matchingUsesCount"]
            for u in r["matchingUses"][:2]:
                facts.append({"type": "use", "country": r["countryCode"], "registrationNumber": r["registrationNumber"], "product": r["productName"], "crop": u["cropOriginal"],
                              "cropNormalized": u["cropNormalized"], "target": u["targetOriginal"], "targetNormalized": u["targetNormalized"], "eppoTargetCode": u.get("eppoTargetCode"),
                              "dose": u["doseValue"], "doseUnit": u["doseUnitOriginal"], "phiDays": u["phiDays"], "pairing": u["pairing"]})
        if pl.target_code:
            warnings.append(f"EPPO code {pl.target_code} for '{pl.target_name}' is a candidate (to verify against gd.eppo.int).")
        if not rows:
            warnings.append(f"No use against '{pl.target_name or pl.target_terms[0]}'" + (f" on crop '{pl.crop}'" if pl.crop else "") + " in the collected sources - not proof of absence.")
            facts.append({"type": "targets_available", "crop": pl.crop, "items": [{"target": t, "registrations": n} for t, n in Q.targets_available(session, crop_terms(pl.crop), pl.countries or None)]})
        elif len(rows) > 40:
            warnings.append(f"{len(rows)} registrations have a use against '{pl.target_name or pl.target_terms[0]}'; only the first 40 are listed - add a country or a crop to narrow.")
        return facts, evidence, warnings, tools

    if pl.intent == "country_portfolio":
        tools.append("overview")
        ov = Q.overview(session, pl.scope, None, pl.months)
        for c in ov["countries"]:
            cc = c["countryCode"]
            if cc not in pl.countries:
                continue
            regs = c["registrations"]
            name = Q.COUNTRY_NAMES.get(cc, cc)
            for r in regs[:40]:
                facts.append({"type": "registration", "product": r["productName"], "country": cc, "registrationNumber": r["registrationNumber"],
                              "statusOriginal": r["statusOriginal"], "statusNormalized": r["statusNormalized"], "holder": r["holder"],
                              "expirationDate": r["expirationDate"], "usesCount": r["usesCount"], "activeEntityNormalized": r["activeEntityNormalized"],
                              "validationStatus": r["validationStatus"], "sourceId": r["sourceId"], "sourceUrl": r["sourceUrl"],
                              "collectedAt": _iso(r["collectedAt"])})
                evidence.append({"sourceId": r["sourceId"], "sourceUrl": r["sourceUrl"], "collectedAt": r["collectedAt"], "validationStatus": r["validationStatus"]})
            facts.append({"type": "portfolio", "country": cc, "scope": pl.scope, "total": len(regs), "shown": min(len(regs), 40), "coverage": c["coverage"],
                          "sourceId": c["sourceId"], "collectedAt": _iso(c["collectedAt"])})
            if c["coverage"] == "source_not_collected":
                warnings.append(f"{name} ({cc}): no source connected - unknown, not 'not registered'.")
            elif not regs:
                warnings.append(f"{name} ({cc}): no product of scope '{pl.scope}' found in {c['sourceId']} as of {c['collectedAt']:%Y-%m-%d} - this is not proof of no registration.")
            elif len(regs) > 40:
                warnings.append(f"{name} ({cc}): {len(regs)} registrations in scope '{pl.scope}', only the first 40 are listed - narrow the question (e.g. 'Lallemand products').")
        if pl.scope == "lallemand":
            warnings.append("Scope 'Lallemand' = registrations whose holder contains LALLEMAND or DANSTAR in the official source; distributor registrations are not included.")
        if pl.crop:
            warnings.append(f"Crop '{pl.crop}' was not applied to this country listing; ask with a product or a micro-organism to filter by crop.")
        return facts, evidence, warnings, tools

    if not pl.product_ids:
        warnings.append("No known product name recognised in the question" + (f" (unresolved: {', '.join(pl.unresolved_names)})" if pl.unresolved_names else "")
                        + ". Nothing was found in the collected sources; this is not proof of no registration. Try the exact commercial name or an alias.")
        add_sources()
        # a brand we do not know may still name a known active substance ('CAPTAN SC' -> captane): offer what the store has
        for tok in pl.unresolved_names[:2]:
            stem = tok.split()[0].lower()
            if len(stem) >= 5:
                rows = Q.search_active_substance(session, stem[:6], pl.countries or None)
                if rows:
                    tools.append("search_active_substance")
                    facts.append({"type": "substance_query", "substance": tok, "searched": stem[:6], "found": len(rows)})
                    for r in rows[:12]:
                        add_reg(r, r["productName"])
                        facts[-1]["activeEntityOriginal"] = r.get("activeEntityOriginal")
                    break
        return facts, evidence, warnings, tools

    all_intents = [pl.intent] + pl.extra_intents
    uses_limit = 12 if ("use_comparison" in all_intents or pl.crop or "dose" in pl.flags or (pl.target_terms and pl.intent != "target_search")) else 0
    if len(pl.product_ids) >= 2:  # 'are X and Y the same product?' / 'is X another name of Y?': the declared relation between them
        tools.append("aliases_for")
        names = {pid: (session.get(Product, pid).commercial_name if session.get(Product, pid) else pid) for pid in pl.product_ids}
        for pa in pl.product_ids:
            for a in Q.aliases_for(session, pa):
                for pb in pl.product_ids:
                    if pb != pa and norm_name(a["aliasName"]) == norm_name(names[pb]):
                        facts.append({"type": "relation", "product": names[pa], "other": names[pb], "relationship": a["relationshipType"], "reviewStatus": a["reviewStatus"],
                                      "country": a.get("countryCode"), "confidence": a.get("confidence"), "evidence": (a.get("evidence") or "")[:240], "sourceUrl": a.get("sourceRecordUrl")})
        if not [f for f in facts if f["type"] == "relation"]:
            warnings.append("No declared relation between " + " and ".join(names.values()) + " in the collected sources (no alternate name, sister or related-product link).")
    for pid in pl.product_ids:
        p = session.get(Product, pid)
        pname = p.commercial_name if p else pid
        if pl.intent == "sister_product" and not pl.extra_intents and len(pl.product_ids) == 1:
            tools.append("aliases_for")
            for a in Q.aliases_for(session, pid):
                facts.append({"type": "alias", "product": pname, **a})
            warnings.append("Sister-product candidates are hypotheses with a review status; none is a confirmed equivalent unless review_status=validated.")
            for r in Q.registrations_for(session, pid, with_uses=False):
                evidence.append(r["evidence"])
            continue
        if pl.intent == "alternatives":
            tools.append("alternatives_for")
            for a in Q.aliases_for(session, pid):
                facts.append({"type": "alias", "product": pname, **a})
            alts = Q.alternatives_for(session, pid, pl.countries or None)
            for r in alts:
                facts.append({"type": "alternative", "product": pname, "alternative": r["productName"], "country": r["countryCode"], "registrationNumber": r["registrationNumber"],
                              "statusOriginal": r["statusOriginal"], "statusNormalized": r["statusNormalized"], "activeEntityOriginal": r.get("activeEntityOriginal"),
                              "sharedActive": r.get("sharedActive"), "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"],
                              "collectedAt": _iso(r["evidence"]["collectedAt"]), "validationStatus": r["evidence"]["validationStatus"]})
                evidence.append(r["evidence"])
            facts.append({"type": "product", "product": pname, "activeEntityOriginal": p.active_entity_original if p else None,
                          "activeEntityNormalized": p.active_entity_normalized if p else None, "sharedActive": alts[0].get("sharedActive") if alts else None, "alternatives": len(alts)})
            for r in Q.registrations_for(session, pid, with_uses=False):
                evidence.append(r["evidence"])
            warnings.append("Alternatives share the active substance wording only; they are distinct products with their own labels and conditions - not equivalents.")
            continue
        if pl.intent == "data_quality" and not pl.extra_intents:
            tools.append("data_quality")
            dq = Q.data_quality(session, pid)
            for i in dq["registrations"]:
                facts.append({"type": "data_quality", "product": pname, "country": i["countryCode"], "registrationId": i["registrationId"],
                              "validationStatus": i["validationStatus"], "missingOrUncertain": i["missingOrUncertain"], "pairing": i["pairing"]})
                evidence.append(i["evidence"])
            warnings += dq["warnings"]
            continue
        if pl.intent == "target_search":
            add_targets(pid, pname)
            if not [f for f in facts if f["type"] == "target"]:
                warnings.append(f"{pname}: no target (disease / pest) recorded in its uses in the collected sources.")
            if not pl.extra_intents:
                for r in Q.registrations_for(session, pid, with_uses=False):
                    evidence.append(r["evidence"])
                continue
        countries = pl.countries or sorted(Q.COUNTRY_SOURCES)
        tools.append("compare")
        cmp_ = Q.compare(session, pid, countries)
        for r in cmp_["registrations"]:
            add_reg(r, pname, uses_limit)
        for c in cmp_["coverage"]:
            if c["coverage"] != "found":
                facts.append({"type": "coverage", "product": pname, "country": c["countryCode"], "coverage": c["coverage"], "note": c["note"]})
        for rp in cmp_["relatedProducts"]:
            for r in rp["registrations"]:
                facts.append({"type": "related_registration", "product": pname, "relatedProduct": rp["commercialName"], "relationship": rp["relationship"],
                              "reviewStatus": rp["reviewStatus"], "country": r["countryCode"], "registrationNumber": r["registrationNumber"],
                              "statusNormalized": r["statusNormalized"], "statusOriginal": r["statusOriginal"], "sourceId": r["evidence"]["sourceId"],
                              "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": _iso(r["evidence"]["collectedAt"]),
                              "validationStatus": r["evidence"]["validationStatus"]})
                evidence.append(r["evidence"])
        warnings += cmp_["warnings"]
        if pl.intent == "product_profile" or "product_profile" in pl.extra_intents:
            tools.append("product_profile")
            facts.append({"type": "product", "product": pname, "activeEntityOriginal": p.active_entity_original if p else None,
                          "activeEntityNormalized": p.active_entity_normalized if p else None, "strain": p.strain if p else None,
                          "formulation": p.formulation_code if p else None, "aliases": len(Q.aliases_for(session, pid))})
            add_targets(pid, pname)
        for it in pl.extra_intents:
            if it == "sister_product":
                tools.append("aliases_for")
                for a in Q.aliases_for(session, pid):
                    facts.append({"type": "alias", "product": pname, **a})
                warnings.append("Sister-product candidates are hypotheses with a review status; none is a confirmed equivalent unless review_status=validated.")
            elif it == "target_search" and not [f for f in facts if f["type"] == "target" and f.get("product") == pname]:
                add_targets(pid, pname)
            elif it == "data_quality":
                tools.append("data_quality")
                dq = Q.data_quality(session, pid)
                for i in dq["registrations"]:
                    facts.append({"type": "data_quality", "product": pname, "country": i["countryCode"], "registrationId": i["registrationId"],
                                  "validationStatus": i["validationStatus"], "missingOrUncertain": i["missingOrUncertain"], "pairing": i["pairing"]})
                warnings += dq["warnings"]
            elif it == "alternatives":
                tools.append("alternatives_for")
                for r in Q.alternatives_for(session, pid, pl.countries or None):
                    facts.append({"type": "alternative", "product": pname, "alternative": r["productName"], "country": r["countryCode"], "registrationNumber": r["registrationNumber"],
                                  "statusOriginal": r["statusOriginal"], "statusNormalized": r["statusNormalized"], "activeEntityOriginal": r.get("activeEntityOriginal"),
                                  "sharedActive": r.get("sharedActive"), "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"],
                                  "collectedAt": _iso(r["evidence"]["collectedAt"]), "validationStatus": r["evidence"]["validationStatus"]})
                    evidence.append(r["evidence"])
    return facts, evidence, warnings, tools


# --------------------------------------------------------------------------- 3. wording tables (fr / en / pt; es = LLM only)
LBL = {
    "fr": {"sisters": "Hypothèses de produits sœurs (à confirmer) : ", "none": "aucune", "conf": "confiance", "expires": "expire le", "days": "jours", "no": "n°", "uses": "usages",
           "use": "usage", "nodose": "dose non structurée", "nothing": "Aucune donnée trouvée dans les sources collectées pour cette question. Absence de résultat ≠ absence d'homologation.",
           "this_product": "ce produit", "crop_on": " sur {crop}", "to_verify": "à vérifier", "same_active": "même matière active", "scope_cap": "Périmètre des sources : {scope}."},
    "en": {"sisters": "Sister-product hypotheses (to confirm): ", "none": "none", "conf": "confidence", "expires": "expires on", "days": "days", "no": "no.", "uses": "uses",
           "use": "use", "nodose": "dose not in structured source", "nothing": "No data found in the collected sources for this question. No result is not proof of no registration.",
           "this_product": "this product", "crop_on": " on {crop}", "to_verify": "to verify", "same_active": "same active substance", "scope_cap": "Source coverage: {scope}."},
    "pt": {"sisters": "Hipóteses de produtos irmãos (a confirmar): ", "none": "nenhuma", "conf": "confiança", "expires": "expira em", "days": "dias", "no": "nº", "uses": "usos",
           "use": "uso", "nodose": "dose não estruturada na fonte", "nothing": "Nenhum dado encontrado nas fontes coletadas para esta pergunta. Ausência de resultado ≠ ausência de registro.",
           "this_product": "este produto", "crop_on": " em {crop}", "to_verify": "a verificar", "same_active": "mesma substância ativa", "scope_cap": "Cobertura das fontes: {scope}."},
}
CNAME = {"fr": {"CA": "Canada", "US": "États-Unis", "FR": "France", "BR": "Brésil", "DE": "Allemagne", "BE": "Belgique", "MX": "Mexique", "UY": "Uruguay", "ES": "Espagne", "IT": "Italie", "NL": "Pays-Bas", "GB": "Royaume-Uni", "PL": "Pologne"},
         "en": {"CA": "Canada", "US": "United States", "FR": "France", "BR": "Brazil", "DE": "Germany", "BE": "Belgium", "MX": "Mexico", "UY": "Uruguay", "ES": "Spain", "IT": "Italy", "NL": "Netherlands", "GB": "United Kingdom", "PL": "Poland"},
         "pt": {"CA": "Canadá", "US": "Estados Unidos", "FR": "França", "BR": "Brasil", "DE": "Alemanha", "BE": "Bélgica", "MX": "México", "UY": "Uruguai", "ES": "Espanha", "IT": "Itália", "NL": "Países Baixos", "GB": "Reino Unido", "PL": "Polônia"}}
HEAD = {
    "fr": {"lookup": "{product} : {n} enregistrement(s) trouvé(s) dans les sources officielles collectées pour {countries}.",
           "lookup_nf": "Non trouvé dans la source officielle de : {countries} (≠ non homologué).", "lookup_ns": "Aucune source connectée pour : {countries}.",
           "lookup_none": "{product} : aucun enregistrement dans les sources collectées (non trouvé : {nf} ; source non connectée : {ns}). Ce n'est pas une preuve d'absence d'homologation.",
           "compare": "{product} : usages comparés pour {countries} ({n} usages au total).", "sisters": "{product} : {n} produit(s) lié(s) ou sœur(s), dont {nc} confirmé(s) par LPC ; le reste est une hypothèse à confirmer.",
           "sisters_caveat": "Les candidats sont des hypothèses tant qu'un relecteur ne les a pas validés.", "quality": "{product} : {n} enregistrement(s) ; champs manquants ou incertains listés par pays.",
           "expiry": "{n} autorisation(s) active(s) expirent dans les {m} prochains mois (sources avec date : Canada, France).", "changes": "{n} changement(s) détecté(s) entre deux collectes.",
           "ingredient": "{species}{crop} : {n} enregistrement(s) dans {nc} pays.",
           "cov_not_found_in_source": "non trouvé dans la source officielle collectée — pas une preuve d'absence", "cov_source_not_collected": "aucune source officielle connectée — inconnu",
           "pf": "{country} : {n} enregistrement(s){scope} dans {source} (collecte du {date}).", "pf_none": "{country} : aucun enregistrement{scope} dans {source} (collecte du {date}) — pas une preuve d'absence.",
           "pf_nosrc": "{country} : aucune source officielle connectée — inconnu.", "pf_more": "{more} autre(s) enregistrement(s) non affiché(s) ; précisez la question (ex. « produits Lallemand »).",
           "scope_lallemand": " de titulaire Lallemand/Danstar",
           "help": "Je suis l'assistant de veille réglementaire Lallemand Plant Care. Je réponds uniquement à partir des sources officielles collectées ({sources}) : homologations par pays, usages autorisés (culture, cible, dose), produits sœurs ou liés, alternatives à même matière active, échéances, changements, qualité des données, recherche par matière active ou par cible. Posez votre question en français, anglais, portugais ou espagnol.",
           "help_caveat": "Je ne donne aucun conseil d'utilisation : seules les étiquettes et sources officielles font foi, après validation Regulatory Affairs.",
           "unknown": "Je n'ai aucune donnée sur « {names} » dans les sources collectées. Couverture actuelle : {scope}. Pour ce produit, consultez la source officielle du pays concerné (liens ci-dessous) ; je peux aussi chercher par matière active, par culture ou par cible (maladie, ravageur).",
           "unknown_active": " En revanche, {n} produit(s) dont la matière active contient « {stem} » figurent dans les sources ({countries}) : voir le tableau.",
           "scope_fr_all": "France : tous les produits autorisés (E-Phy, {n})", "scope_lal": "{country} : produits Lallemand Plant Care et produits liés ({n})", "scope_br": "Brésil : produits microbiens de l'extrait AGROFIT ({n})",
           "substance": "{n} produit(s) dont la matière active contient « {x} » dans les sources collectées ({countries}).",
           "substance_none": "Aucun produit avec la matière active « {x} » dans les sources collectées — ce n'est pas une preuve d'absence. Matières actives les plus présentes : {actives}.",
           "target": "{n} produit(s) avec un usage contre {name}{code}{crop} dans les sources collectées ({countries}).",
           "target_none": "Aucun usage contre {name}{code}{crop} dans les sources collectées — ce n'est pas une preuve d'absence. Cibles les plus fréquentes{crop} : {targets}.",
           "target_unknown": "Je n'ai pas reconnu de maladie ou de ravageur dans la question. Précisez la cible (ex. « tavelure du pommier », « pucerons ») et, si utile, la culture et le pays. Cibles fréquentes dans les sources : {targets}.",
           "targets_of": "{product} : {n} cible(s) distincte(s) dans ses usages autorisés ({countries}).", "targets_none": "{product} : aucune cible (maladie, ravageur) enregistrée dans ses usages des sources collectées.",
           "profile": "{product} — matière active : {active}{formulation}{holder}. Enregistrements trouvés : {found} ; non trouvé dans la source de : {nf}.",
           "alternatives": "{product} : {n} autre(s) produit(s) avec la même matière active ({active}) dans les sources collectées ({countries}) — produits distincts, avec leur propre étiquette ; {nr} produit(s) lié(s) ou sœur(s) déclaré(s).",
           "alternatives_none": "{product} : aucun autre produit avec la même matière active ({active}) dans les sources collectées ({countries}) ; {nr} produit(s) lié(s) ou sœur(s) déclaré(s).",
           "sec_use_comparison": "Usages autorisés", "sec_sister_product": "Produits sœurs et liés", "sec_target_search": "Cibles (maladies, ravageurs)", "sec_data_quality": "Champs incertains",
           "sec_registration_lookup": "Homologations", "sec_alternatives": "Alternatives (même matière active)", "sec_product_profile": "Fiche produit", "sec_source": "Sources",
           "eppo_code": " (EPPO {code}, à vérifier)",
           "relation": "{a} et {b} : produits distincts — relation déclarée « {rel} » ({review}{country}) : {evidence}", "relation_alt": "{b} est un nom alternatif de {a}{country} ({review}) : {evidence}",
           "relation_none": "{a} et {b} : aucune relation déclarée dans les sources collectées (ni nom alternatif, ni produit sœur ou lié) ; ce sont des enregistrements distincts.",
           "holder_of": "{product} : titulaire {rows}.", "expiry_of": "{product} : {rows}.", "exp_none": "pas de date d'expiration dans la source",
           "crop_check": "{product}{crop} : {rows}.", "crop_yes": "{cc} n° {num} : {n} usage(s) sur {crop}", "crop_no": "{cc} n° {num} : aucun usage sur {crop} dans la source",
           "two_products": "{rows}"},
    "en": {"lookup": "{product}: {n} registration(s) found in the collected official sources for {countries}.",
           "lookup_nf": "Not found in the official source of: {countries} (≠ not registered).", "lookup_ns": "No source connected for: {countries}.",
           "lookup_none": "{product}: no registration in the collected sources (not found: {nf}; source not connected: {ns}). This is not proof of no registration.",
           "compare": "{product}: uses compared for {countries} ({n} uses in total).", "sisters": "{product}: {n} related or sister product(s), {nc} confirmed by LPC; the rest are hypotheses to confirm.",
           "sisters_caveat": "Candidates remain hypotheses until a reviewer validates them.", "quality": "{product}: {n} registration(s); missing or uncertain fields listed per country.",
           "expiry": "{n} active authorisation(s) expire within the next {m} months (sources with dates: Canada, France).", "changes": "{n} change(s) detected between two collections.",
           "ingredient": "{species}{crop}: {n} registration(s) in {nc} countries.",
           "cov_not_found_in_source": "not found in the collected official source — not proof of absence", "cov_source_not_collected": "no official source connected — unknown",
           "pf": "{country}: {n} registration(s){scope} in {source} (collected {date}).", "pf_none": "{country}: no registration{scope} in {source} (collected {date}) — not proof of absence.",
           "pf_nosrc": "{country}: no official source connected — unknown.", "pf_more": "{more} more registration(s) not shown; narrow the question (e.g. 'Lallemand products').",
           "scope_lallemand": " held by Lallemand/Danstar",
           "help": "I am the Lallemand Plant Care regulatory-watch assistant. I answer only from the collected official sources ({sources}): registrations by country, authorised uses (crop, target, dose), sister or related products, alternatives with the same active substance, expiries, changes, data quality, search by active substance or by target. Ask in French, English, Portuguese or Spanish.",
           "help_caveat": "I give no advice on use: only official labels and sources are authoritative, after Regulatory Affairs validation.",
           "unknown": "I have no data on '{names}' in the collected sources. Current coverage: {scope}. For this product, check the official source of the country concerned (links below); I can also search by active substance, crop or target (disease, pest).",
           "unknown_active": " However, {n} product(s) whose active substance contains '{stem}' are in the sources ({countries}): see the table.",
           "scope_fr_all": "France: every authorised product (E-Phy, {n})", "scope_lal": "{country}: Lallemand Plant Care products and related products ({n})", "scope_br": "Brazil: microbial products of the AGROFIT extract ({n})",
           "substance": "{n} product(s) whose active substance contains '{x}' in the collected sources ({countries}).",
           "substance_none": "No product with the active substance '{x}' in the collected sources — not proof of absence. Most frequent active substances: {actives}.",
           "target": "{n} product(s) with a use against {name}{code}{crop} in the collected sources ({countries}).",
           "target_none": "No use against {name}{code}{crop} in the collected sources — not proof of absence. Most frequent targets{crop}: {targets}.",
           "target_unknown": "I did not recognise a disease or pest in the question. Name the target (e.g. 'apple scab', 'aphids') and, if useful, the crop and the country. Frequent targets in the sources: {targets}.",
           "targets_of": "{product}: {n} distinct target(s) in its authorised uses ({countries}).", "targets_none": "{product}: no target (disease, pest) recorded in its uses in the collected sources.",
           "profile": "{product} — active substance: {active}{formulation}{holder}. Registrations found: {found}; not found in the source of: {nf}.",
           "alternatives": "{product}: {n} other product(s) with the same active substance ({active}) in the collected sources ({countries}) — distinct products with their own labels; {nr} declared related or sister product(s).",
           "alternatives_none": "{product}: no other product with the same active substance ({active}) in the collected sources ({countries}); {nr} declared related or sister product(s).",
           "sec_use_comparison": "Authorised uses", "sec_sister_product": "Sister and related products", "sec_target_search": "Targets (diseases, pests)", "sec_data_quality": "Uncertain fields",
           "sec_registration_lookup": "Registrations", "sec_alternatives": "Alternatives (same active substance)", "sec_product_profile": "Product profile", "sec_source": "Sources",
           "eppo_code": " (EPPO {code}, to verify)",
           "relation": "{a} and {b}: distinct products — declared relation '{rel}' ({review}{country}): {evidence}", "relation_alt": "{b} is an alternate name of {a}{country} ({review}): {evidence}",
           "relation_none": "{a} and {b}: no declared relation in the collected sources (no alternate name, sister or related-product link); they are distinct registrations.",
           "holder_of": "{product}: holder {rows}.", "expiry_of": "{product}: {rows}.", "exp_none": "no expiry date in the source",
           "crop_check": "{product}{crop}: {rows}.", "crop_yes": "{cc} no. {num}: {n} use(s) on {crop}", "crop_no": "{cc} no. {num}: no use on {crop} in the source",
           "two_products": "{rows}"},
    "pt": {"lookup": "{product}: {n} registro(s) encontrado(s) nas fontes oficiais coletadas para {countries}.",
           "lookup_nf": "Não encontrado na fonte oficial de: {countries} (≠ não registrado).", "lookup_ns": "Nenhuma fonte conectada para: {countries}.",
           "lookup_none": "{product}: nenhum registro nas fontes coletadas (não encontrado: {nf}; fonte não conectada: {ns}). Isto não prova ausência de registro.",
           "compare": "{product}: usos comparados para {countries} ({n} usos no total).", "sisters": "{product}: {n} produto(s) relacionado(s) ou irmão(s), {nc} confirmado(s) pela LPC; o restante são hipóteses a confirmar.",
           "sisters_caveat": "Os candidatos permanecem hipóteses até que um revisor os valide.", "quality": "{product}: {n} registro(s); campos ausentes ou incertos listados por país.",
           "expiry": "{n} autorização(ões) ativa(s) vencem nos próximos {m} meses (fontes com data: Canadá, França).", "changes": "{n} mudança(s) detectada(s) entre duas coletas.",
           "ingredient": "{species}{crop}: {n} registro(s) em {nc} países.",
           "cov_not_found_in_source": "não encontrado na fonte oficial coletada — não prova ausência", "cov_source_not_collected": "nenhuma fonte oficial conectada — desconhecido",
           "pf": "{country}: {n} registro(s){scope} em {source} (coleta de {date}).", "pf_none": "{country}: nenhum registro{scope} em {source} (coleta de {date}) — não prova ausência.",
           "pf_nosrc": "{country}: nenhuma fonte oficial conectada — desconhecido.", "pf_more": "{more} outro(s) registro(s) não exibido(s); restrinja a pergunta (ex. « produtos Lallemand »).",
           "scope_lallemand": " de titular Lallemand/Danstar",
           "help": "Sou o assistente de vigilância regulatória da Lallemand Plant Care. Respondo apenas a partir das fontes oficiais coletadas ({sources}): registros por país, usos autorizados (cultura, alvo, dose), produtos irmãos ou relacionados, alternativas com a mesma substância ativa, vencimentos, mudanças, qualidade dos dados, busca por substância ativa ou por alvo. Pergunte em francês, inglês, português ou espanhol.",
           "help_caveat": "Não dou conselhos de uso: apenas os rótulos e fontes oficiais fazem fé, após validação pelo Regulatory Affairs.",
           "unknown": "Não tenho dados sobre « {names} » nas fontes coletadas. Cobertura atual: {scope}. Para este produto, consulte a fonte oficial do país (links abaixo); também posso buscar por substância ativa, cultura ou alvo (doença, praga).",
           "unknown_active": " Por outro lado, {n} produto(s) cuja substância ativa contém « {stem} » estão nas fontes ({countries}): veja a tabela.",
           "scope_fr_all": "França: todos os produtos autorizados (E-Phy, {n})", "scope_lal": "{country}: produtos Lallemand Plant Care e relacionados ({n})", "scope_br": "Brasil: produtos microbianos do extrato AGROFIT ({n})",
           "substance": "{n} produto(s) cuja substância ativa contém « {x} » nas fontes coletadas ({countries}).",
           "substance_none": "Nenhum produto com a substância ativa « {x} » nas fontes coletadas — não prova ausência. Substâncias ativas mais presentes: {actives}.",
           "target": "{n} produto(s) com um uso contra {name}{code}{crop} nas fontes coletadas ({countries}).",
           "target_none": "Nenhum uso contra {name}{code}{crop} nas fontes coletadas — não prova ausência. Alvos mais frequentes{crop}: {targets}.",
           "target_unknown": "Não reconheci uma doença ou praga na pergunta. Indique o alvo (ex. « sarna da macieira », « pulgões ») e, se útil, a cultura e o país. Alvos frequentes nas fontes: {targets}.",
           "targets_of": "{product}: {n} alvo(s) distinto(s) nos seus usos autorizados ({countries}).", "targets_none": "{product}: nenhum alvo (doença, praga) registrado nos seus usos nas fontes coletadas.",
           "profile": "{product} — substância ativa: {active}{formulation}{holder}. Registros encontrados: {found}; não encontrado na fonte de: {nf}.",
           "alternatives": "{product}: {n} outro(s) produto(s) com a mesma substância ativa ({active}) nas fontes coletadas ({countries}) — produtos distintos, com rótulo próprio; {nr} produto(s) relacionado(s) ou irmão(s) declarado(s).",
           "alternatives_none": "{product}: nenhum outro produto com a mesma substância ativa ({active}) nas fontes coletadas ({countries}); {nr} produto(s) relacionado(s) ou irmão(s) declarado(s).",
           "sec_use_comparison": "Usos autorizados", "sec_sister_product": "Produtos irmãos e relacionados", "sec_target_search": "Alvos (doenças, pragas)", "sec_data_quality": "Campos incertos",
           "sec_registration_lookup": "Registros", "sec_alternatives": "Alternativas (mesma substância ativa)", "sec_product_profile": "Ficha do produto", "sec_source": "Fontes",
           "eppo_code": " (EPPO {code}, a verificar)",
           "relation": "{a} e {b}: produtos distintos — relação declarada « {rel} » ({review}{country}): {evidence}", "relation_alt": "{b} é um nome alternativo de {a}{country} ({review}): {evidence}",
           "relation_none": "{a} e {b}: nenhuma relação declarada nas fontes coletadas (nem nome alternativo, nem produto irmão ou relacionado); são registros distintos.",
           "holder_of": "{product}: titular {rows}.", "expiry_of": "{product}: {rows}.", "exp_none": "sem data de vencimento na fonte",
           "crop_check": "{product}{crop}: {rows}.", "crop_yes": "{cc} nº {num}: {n} uso(s) em {crop}", "crop_no": "{cc} nº {num}: nenhum uso em {crop} na fonte",
           "two_products": "{rows}"},
}
PROFILE_WORDS = {"fr": (", formulation {f}", ", titulaire {h}"), "en": (", formulation {f}", ", holder {h}"), "pt": (", formulação {f}", ", titular {h}")}

# English warning templates (API contract, tests) -> French / Portuguese wording for the caveats shown to the reader.
WARN_I18N: list[tuple[re.Pattern, dict[str, str]]] = [
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): not found in (?P<src>\S+) as of (?P<date>\d{4}-\d\d-\d\d) - this is not proof of no registration\.$"),
     {"fr": "{name} ({cc}) : non trouvé dans {src} au {date} — ce n'est pas une preuve d'absence d'homologation.",
      "pt": "{name} ({cc}): não encontrado em {src} em {date} — isto não prova ausência de registro."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): no source connected - unknown, not 'not registered'\.$"),
     {"fr": "{name} ({cc}) : aucune source connectée — inconnu, pas « non homologué ».", "pt": "{name} ({cc}): nenhuma fonte conectada — desconhecido, não « não registrado »."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): no registration of this product, but related product '(?P<rel>.+?)' \((?P<type>[a-z_]+), (?P<review>[a-z_]+)\) has n° (?P<num>\S+) - a distinct product, not an equivalent\.$"),
     {"fr": "{name} ({cc}) : pas d'enregistrement de ce produit, mais le produit lié « {rel} » ({type}, {review}) porte le n° {num} — produit distinct, pas un équivalent.",
      "pt": "{name} ({cc}): nenhum registro deste produto, mas o produto relacionado « {rel} » ({type}, {review}) tem o nº {num} — produto distinto, não equivalente."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): dose is not in the structured source; only the official label PDF states it\.$"),
     {"fr": "{cc} {num} : la dose n'est pas dans la source structurée ; seule l'étiquette officielle (PDF) l'indique.",
      "pt": "{cc} {num}: a dose não está na fonte estruturada; apenas o rótulo oficial (PDF) a indica."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): the source lists crops and targets as two independent lists; crop-target pairs are not asserted by the source\.$"),
     {"fr": "{cc} {num} : la source liste cultures et cibles comme deux listes indépendantes ; les couples culture-cible ne sont pas affirmés par la source.",
      "pt": "{cc} {num}: a fonte lista culturas e alvos como duas listas independentes; os pares cultura-alvo não são afirmados pela fonte."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): some uses were extracted from the label PDF by an AI model \(extraction_method=llm_pdf\) and are not yet validated\.$"),
     {"fr": "{cc} {num} : certains usages ont été extraits de l'étiquette PDF par un modèle d'IA (extraction_method=llm_pdf) et ne sont pas encore validés.",
      "pt": "{cc} {num}: alguns usos foram extraídos do rótulo PDF por um modelo de IA (extraction_method=llm_pdf) e ainda não foram validados."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): automatically extracted, not yet validated by Regulatory Affairs\.$"),
     {"fr": "{cc} {num} : extraction automatique, non encore validée par Regulatory Affairs.", "pt": "{cc} {num}: extração automática, ainda não validada pelo Regulatory Affairs."}),
    (re.compile(r"^No known product name recognised in the question(?P<unres> \(unresolved: .+?\))?\. Nothing was found in the collected sources; this is not proof of no registration\. Try the exact commercial name or an alias\.$"),
     {"fr": "Aucun nom de produit connu reconnu dans la question{unres}. Rien n'a été trouvé dans les sources collectées ; ce n'est pas une preuve d'absence d'homologation. Essayez le nom commercial exact ou un alias.",
      "pt": "Nenhum nome de produto conhecido reconhecido na pergunta{unres}. Nada foi encontrado nas fontes coletadas; isto não prova ausência de registro. Tente o nome comercial exato ou um alias."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): no product of scope '(?P<scope>\w+)' found in (?P<src>\S+) as of (?P<date>\d{4}-\d\d-\d\d) - this is not proof of no registration\.$"),
     {"fr": "{name} ({cc}) : aucun produit du périmètre « {scope} » dans {src} au {date} — ce n'est pas une preuve d'absence d'homologation.",
      "pt": "{name} ({cc}): nenhum produto do escopo « {scope} » em {src} em {date} — isto não prova ausência de registro."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): (?P<n>\d+) registrations in scope '(?P<scope>\w+)', only the first 40 are listed - narrow the question \(e\.g\. 'Lallemand products'\)\.$"),
     {"fr": "{name} ({cc}) : {n} enregistrements dans le périmètre « {scope} », seuls les 40 premiers sont listés — précisez la question (ex. « produits Lallemand »).",
      "pt": "{name} ({cc}): {n} registros no escopo « {scope} », apenas os 40 primeiros são listados — restrinja a pergunta (ex. « produtos Lallemand »)."}),
    (re.compile(r"^Scope 'Lallemand' = registrations whose holder contains LALLEMAND or DANSTAR in the official source; distributor registrations are not included\.$"),
     {"fr": "Périmètre « Lallemand » = enregistrements dont le titulaire contient LALLEMAND ou DANSTAR dans la source officielle ; les enregistrements de distributeurs ne sont pas inclus.",
      "pt": "Escopo « Lallemand » = registros cujo titular contém LALLEMAND ou DANSTAR na fonte oficial; registros de distribuidores não estão incluídos."}),
    (re.compile(r"^Crop '(?P<crop>.+?)' was not applied to this country listing; ask with a product or a micro-organism to filter by crop\.$"),
     {"fr": "La culture « {crop} » n'a pas été appliquée à cette liste par pays ; posez la question avec un produit ou un micro-organisme pour filtrer par culture.",
      "pt": "A cultura « {crop} » não foi aplicada a esta lista por país; pergunte com um produto ou um microrganismo para filtrar por cultura."}),
    (re.compile(r"^Context taken from the conversation: (?P<what>.+)\.$"),
     {"fr": "Contexte repris de la conversation : {what}.", "pt": "Contexto retomado da conversa: {what}."}),
    (re.compile(r"^Sister-product candidates are hypotheses with a review status; none is a confirmed equivalent unless review_status=validated\.$"),
     {"fr": "Les candidats « produit sœur » sont des hypothèses avec un statut de revue ; aucun n'est un équivalent confirmé sauf review_status=validated.",
      "pt": "Os candidatos a « produto irmão » são hipóteses com um estado de revisão; nenhum é equivalente confirmado salvo review_status=validated."}),
    (re.compile(r"^No registration with an expiry date within (?P<m>\d+) months in the collected sources; BR and US sources give no expiry dates\.$"),
     {"fr": "Aucun enregistrement avec une date d'expiration dans les {m} mois dans les sources collectées ; les sources BR et US ne donnent pas de date d'expiration.",
      "pt": "Nenhum registro com data de vencimento nos próximos {m} meses nas fontes coletadas; as fontes BR e US não informam datas de vencimento."}),
    (re.compile(r"^Expiry dates exist only in CA-PPID and FR-EPHY \(withdrawal date\); US-EPA-PPLS and BR-AGROFIT do not publish them\.$"),
     {"fr": "Les dates d'expiration n'existent que dans CA-PPID et FR-EPHY (date de retrait) ; US-EPA-PPLS et BR-AGROFIT ne les publient pas.",
      "pt": "As datas de vencimento existem apenas em CA-PPID e FR-EPHY (data de retirada); US-EPA-PPLS e BR-AGROFIT não as publicam."}),
    (re.compile(r"^No change detected yet: change detection needs at least two collections of the same source\.$"),
     {"fr": "Aucun changement détecté pour l'instant : la détection nécessite au moins deux collectes de la même source.",
      "pt": "Nenhuma mudança detectada ainda: a detecção exige pelo menos duas coletas da mesma fonte."}),
    (re.compile(r"^No micro-organism species recognised in the question \(known species are those present in the store, e\.g\. (?P<ex>.+?)\)\.$"),
     {"fr": "Aucune espèce de micro-organisme reconnue dans la question (espèces connues : celles présentes dans la base, ex. {ex}).",
      "pt": "Nenhuma espécie de microrganismo reconhecida na pergunta (espécies conhecidas: as presentes na base, ex. {ex})."}),
    (re.compile(r"^No product with '(?P<sp>.+?)'(?P<crop> on crop '.+?')? in the collected sources - not proof of absence\.$"),
     {"fr": "Aucun produit avec « {sp} »{crop} dans les sources collectées — pas une preuve d'absence.",
      "pt": "Nenhum produto com « {sp} »{crop} nas fontes coletadas — não prova ausência."}),
    (re.compile(r"^Crop filter applied on normalized and original crop wording; CA/US crop lists are not paired with targets by the source\.$"),
     {"fr": "Filtre culture appliqué sur le libellé normalisé et original ; les listes de cultures CA/US ne sont pas appariées aux cibles par la source.",
      "pt": "Filtro de cultura aplicado ao texto normalizado e original; as listas de culturas CA/US não são pareadas com os alvos pela fonte."}),
    (re.compile(r"^AI phrasing rejected by the grounding guard \((?P<why>.+)\); deterministic answer shown instead\.$"),
     {"fr": "Formulation IA rejetée par le garde-fou d'ancrage ({why}) ; réponse déterministe affichée.",
      "pt": "Formulação da IA rejeitada pela proteção de fundamentação ({why}); resposta determinística exibida."}),
    (re.compile(r"^AI provider unavailable \((?P<kind>.+)\); deterministic answer shown, built from the same facts\.$"),
     {"fr": "Fournisseur d'IA indisponible ({kind}) ; réponse déterministe affichée, construite à partir des mêmes faits.",
      "pt": "Provedor de IA indisponível ({kind}); resposta determinística exibida, construída a partir dos mesmos fatos."}),
    (re.compile(r"^No advice on use: only the official label of the registered product is authoritative; a use on another crop is a regulatory decision, not a data point\.$"),
     {"fr": "Aucun conseil d'utilisation : seule l'étiquette officielle du produit homologué fait foi ; un usage sur une autre culture est une décision réglementaire, pas une donnée.",
      "pt": "Nenhum conselho de uso: apenas o rótulo oficial do produto registrado faz fé; um uso em outra cultura é uma decisão regulatória, não um dado."}),
    (re.compile(r"^No product with active substance '(?P<x>.+?)' in the collected sources - not proof of absence\.$"),
     {"fr": "Aucun produit avec la matière active « {x} » dans les sources collectées — pas une preuve d'absence.",
      "pt": "Nenhum produto com a substância ativa « {x} » nas fontes coletadas — não prova ausência."}),
    (re.compile(r"^(?P<n>\d+) registrations match '(?P<x>.+?)'; only the first 40 are listed - add a country or a crop to narrow\.$"),
     {"fr": "{n} enregistrements correspondent à « {x} » ; seuls les 40 premiers sont listés — ajoutez un pays ou une culture pour affiner.",
      "pt": "{n} registros correspondem a « {x} »; apenas os 40 primeiros são listados — acrescente um país ou uma cultura para restringir."}),
    (re.compile(r"^No disease or pest recognised in the question\.$"),
     {"fr": "Aucune maladie ni ravageur reconnu dans la question.", "pt": "Nenhuma doença ou praga reconhecida na pergunta."}),
    (re.compile(r"^EPPO code (?P<code>\S+) for '(?P<name>.+?)' is a candidate \(to verify against gd\.eppo\.int\)\.$"),
     {"fr": "Le code EPPO {code} pour « {name} » est un candidat (à vérifier sur gd.eppo.int).", "pt": "O código EPPO {code} para « {name} » é um candidato (a verificar em gd.eppo.int)."}),
    (re.compile(r"^No use against '(?P<x>.+?)'(?P<crop> on crop '.+?')? in the collected sources - not proof of absence\.$"),
     {"fr": "Aucun usage contre « {x} »{crop} dans les sources collectées — pas une preuve d'absence.",
      "pt": "Nenhum uso contra « {x} »{crop} nas fontes coletadas — não prova ausência."}),
    (re.compile(r"^(?P<n>\d+) registrations have a use against '(?P<x>.+?)'; only the first 40 are listed - add a country or a crop to narrow\.$"),
     {"fr": "{n} enregistrements ont un usage contre « {x} » ; seuls les 40 premiers sont listés — ajoutez un pays ou une culture pour affiner.",
      "pt": "{n} registros têm um uso contra « {x} »; apenas os 40 primeiros são listados — acrescente um país ou uma cultura para restringir."}),
    (re.compile(r"^(?P<p>.+?): no target \(disease / pest\) recorded in its uses in the collected sources\.$"),
     {"fr": "{p} : aucune cible (maladie / ravageur) enregistrée dans ses usages des sources collectées.", "pt": "{p}: nenhum alvo (doença / praga) registrado nos seus usos nas fontes coletadas."}),
    (re.compile(r"^No declared relation between (?P<names>.+?) in the collected sources \(no alternate name, sister or related-product link\)\.$"),
     {"fr": "Aucune relation déclarée entre {names} dans les sources collectées (ni nom alternatif, ni produit sœur ou lié).",
      "pt": "Nenhuma relação declarada entre {names} nas fontes coletadas (nem nome alternativo, nem produto irmão ou relacionado)."}),
    (re.compile(r"^Alternatives share the active substance wording only; they are distinct products with their own labels and conditions - not equivalents\.$"),
     {"fr": "Les alternatives partagent seulement le libellé de la matière active ; ce sont des produits distincts, avec leur propre étiquette et leurs conditions — pas des équivalents.",
      "pt": "As alternativas partilham apenas o texto da substância ativa; são produtos distintos, com rótulo e condições próprios — não equivalentes."}),
]


def localize_warning(w: str, lang: str) -> str:
    """French/Portuguese wording of a known English warning; unknown wording is returned unchanged."""
    if lang == "en":
        return w
    for rx, tpl in WARN_I18N:
        m = rx.match(w)
        if m and lang in tpl:
            gd = {k: (v or "") for k, v in m.groupdict().items()}
            if gd.get("cc") in CNAME.get(lang, {}) and "name" in gd:
                gd["name"] = CNAME[lang][gd["cc"]]  # country name in the reader's language
            if gd.get("crop", "").startswith(" on crop "):
                gd["crop"] = {"fr": " sur la culture « {c} »", "pt": " na cultura « {c} »"}[lang].format(c=gd["crop"][10:-1])
            return tpl[lang].format(**gd)
    return w


CAVEAT_KEYS = ("Context taken", "not proof", "dose is not", "two independent lists", "AI model", "hypotheses", "no source connected", "only the first", "Scope 'Lallemand'",
               "was not applied", "No advice", "EPPO code", "No disease", "Alternatives share", "no target", "No declared relation")


def scope_summary(session: Session, lang: str, sources: list[dict]) -> str:
    H = HEAD.get(lang, HEAD["en"])
    CN = CNAME.get(lang, CNAME["en"])
    parts = []
    for s in sources:
        cc = s.get("country")
        n = s.get("registrations", 0)
        if s["sourceId"] == "FR-EPHY" and settings.fr_ephy_scope == "all":
            parts.append(H["scope_fr_all"].format(n=n))
        elif s["sourceId"] == "BR-AGROFIT":
            parts.append(H["scope_br"].format(n=n))
        else:
            parts.append(H["scope_lal"].format(country=CN.get(cc, cc), n=n))
    return " ; ".join(parts)


# --------------------------------------------------------------------------- 4. structured answer (always available)
def build_structured(pl: Plan, facts: list[dict], warnings: list[str], language: str) -> StructuredAnswer:
    """Compact, question-shaped answer from the facts: one headline, only the relevant rows, sections for the other parts of a
    multi-part question, short caveats."""
    lang = (language or "fr").lower()[:2]
    if lang not in LBL:
        lang = "en"
    L, H, CN = LBL[lang], HEAD[lang], CNAME[lang]
    regs = [f for f in facts if f["type"] == "registration"]
    cov = [f for f in facts if f["type"] == "coverage"]
    rel = [f for f in facts if f["type"] == "related_registration"]
    items: list[AnswerItem] = []
    sections: list[AnswerSection] = []
    caveats: list[str] = []
    name = regs[0]["product"] if regs else (cov[0]["product"] if cov else None)
    found = sorted({f["country"] for f in regs})
    countries_txt = ", ".join(found) or "—"

    def item_from_reg(f, detail=None):
        return AnswerItem(country=f["country"], product=f.get("product"), registrationNumber=f.get("registrationNumber"), status=f.get("statusNormalized"),
                          statusOriginal=f.get("statusOriginal"), expiry=f.get("expirationDate"), detail=detail, sourceId=f.get("sourceId"),
                          collectedAt=(f.get("collectedAt") or "")[:10] or None, url=f.get("sourceUrl") if pl.intent == "source" else None)

    def source_items():
        return [AnswerItem(country=s.get("country"), product=s["sourceId"], detail=s.get("scope"), collectedAt=(s.get("collectedAt") or "")[:10] or None,
                           registrationNumber=None, status=None, url=s.get("url")) for s in facts if s["type"] == "source"]

    def use_items(reg_facts, max_rows=12):
        out = []
        short = lambda x, n=38: (x or "")[:n] + ("…" if x and len(x) > n else "")  # noqa: E731
        for f in reg_facts[:max_rows]:
            uses = [u for u in facts if u["type"] == "use" and u.get("registrationNumber") == f["registrationNumber"] and (u.get("target") or "").strip().upper() not in ("NO PEST", "")]
            nodose_all = bool(uses) and all(u.get("dose") is None for u in uses)
            det = "; ".join(f"{short(u.get('crop'))} → {short(u.get('target'), 30)}" + (f", {u['dose']} {u['doseUnit']}" if u.get("dose") is not None else "") for u in uses[:3])
            det = (det + (f" … +{len(uses) - 3}" if len(uses) > 3 else "") + (f" · {L['nodose']}" if nodose_all else "")) or None
            out.append(item_from_reg(f, detail=det))
        return out

    def alias_items():
        al = [f for f in facts if f["type"] == "alias"]
        cands = [a for a in al if a["relationshipType"] in ("sister_product_candidate", "related_formulation", "confirmed_sister_product", "related_product")]
        return cands, [AnswerItem(product=a["aliasName"], country=a.get("countryCode"), relationship=f"{a['relationshipType']} · {a['reviewStatus']} · {L['conf']} {a['confidence']}",
                                  detail=(a.get("evidence") or "")[:160] or None, sourceId=None) for a in cands[:12]]

    def target_items(pname=None):
        tg = [f for f in facts if f["type"] == "target" and (pname is None or f.get("product") == pname)]
        return tg, [AnswerItem(country=f["country"], product=f.get("product"), registrationNumber=f.get("registrationNumber"),
                               detail=(f["target"] + (f" (EPPO {f['eppoTargetCode']})" if f.get("eppoTargetCode") else "") + (" — " + ", ".join(f["crops"]) if f.get("crops") else "") + f" · {f['uses']} {L['uses']}")[:160])
                    for f in tg[:12]]

    def lookup_headline():
        not_found = sorted({c["country"] for c in cov if c["coverage"] == "not_found_in_source"})
        no_src = sorted({c["country"] for c in cov if c["coverage"] == "source_not_collected"})
        if regs:
            h = H["lookup"].format(product=name or "", countries=", ".join(found), n=len(regs))
            if not_found:
                h += " " + H["lookup_nf"].format(countries=", ".join(not_found))
            if no_src:
                h += " " + H["lookup_ns"].format(countries=", ".join(no_src))
            return h
        if cov:
            return H["lookup_none"].format(product=name or "", nf=", ".join(not_found) or "—", ns=", ".join(no_src) or "—")
        return L["nothing"]

    def coverage_items():
        return [AnswerItem(country=c["country"], product=c.get("product"), status=c["coverage"], detail=H["cov_" + c["coverage"]], sourceId=None) for c in cov]

    def related_items():
        return [AnswerItem(country=r["country"], product=r["relatedProduct"], registrationNumber=r.get("registrationNumber"), status=r.get("statusNormalized"),
                           statusOriginal=r.get("statusOriginal"), relationship=f"{r['relationship']} · {r['reviewStatus']}", sourceId=r.get("sourceId"),
                           collectedAt=(r.get("collectedAt") or "")[:10]) for r in rel[:6]]

    srcs = [f for f in facts if f["type"] == "source"]
    rels = [f for f in facts if f["type"] == "relation"]
    checks = [f for f in facts if f["type"] == "crop_check"]

    def relation_headline():
        r = rels[0]
        country = f", {r['country']}" if r.get("country") else ""
        if r["relationship"] == "alternate_name":
            return H["relation_alt"].format(a=r["product"], b=r["other"], country=country, review=r["reviewStatus"], evidence=r.get("evidence") or "")
        return H["relation"].format(a=r["product"], b=r["other"], rel=r["relationship"], review=r["reviewStatus"], country=country, evidence=r.get("evidence") or "")

    def focus_headline(default: str) -> str:
        """Headline for a question that focuses on the holder, the expiry date or a crop of a known product."""
        if rels and ("same_product" in pl.flags or pl.intent in ("sister_product", "registration_lookup", "product_profile")):
            return relation_headline()
        if len(pl.product_ids) >= 2 and not rels and "same_product" in pl.flags:
            names = [f["product"] for f in regs]
            return H["relation_none"].format(a=names[0] if names else pl.product_ids[0], b=next((n for n in names if n != (names[0] if names else None)), pl.product_ids[-1]))
        if "holder" in pl.flags and regs:
            return H["holder_of"].format(product=name or "", rows="; ".join(f"{f['country']} {L['no']} {f['registrationNumber']}: {f.get('holder') or '—'}" for f in regs[:6]))
        if "expiry" in pl.flags and regs:
            return H["expiry_of"].format(product=name or "", rows="; ".join(f"{f['country']} {L['no']} {f['registrationNumber']} " + (f"{L['expires']} {f['expirationDate']}" if f.get("expirationDate") else L["exp_none"]) for f in regs[:6]))
        if checks and pl.crop:
            cw = pl.crop_word or pl.crop
            parts = []
            for c in checks[:6]:
                part = (H["crop_yes"] if c["matchingUses"] else H["crop_no"]).format(cc=c["country"], num=c["registrationNumber"], n=c["matchingUses"], crop=cw)
                uses = [u for u in facts if u["type"] == "use" and u.get("registrationNumber") == c["registrationNumber"]]
                if uses and c["matchingUses"] <= 3:
                    part += " (" + "; ".join(f"{u.get('crop')} → {u.get('target')}" + (f", {u['dose']} {u['doseUnit']}" if u.get("dose") is not None else f" · {L['nodose']}") for u in uses[:3]) + ")"
                parts.append(part)
            return H["crop_check"].format(product=name or "", crop="", rows="; ".join(parts)) + (" " + default if cov else "")
        return default

    if pl.intent == "help":
        headline = H["help"].format(sources=", ".join(s["sourceId"] for s in srcs) or "CA-PPID, US-EPA-PPLS, FR-EPHY, BR-AGROFIT")
        items = source_items()
        caveats.append(H["help_caveat"])
    elif not pl.product_ids and pl.intent in PRODUCT_INTENTS and pl.intent not in ("target_search",):  # unknown product: say so, explain the coverage, point to the sources
        sq = next((f for f in facts if f["type"] == "substance_query"), None)
        names = ", ".join(pl.unresolved_names) or L["this_product"]
        headline = H["unknown"].format(names=names, scope=scope_summary(None, lang, srcs))
        if sq and regs:
            headline += H["unknown_active"].format(n=sq["found"], stem=sq["searched"], countries=countries_txt)
            items = [item_from_reg(f, detail=f.get("activeEntityOriginal")) for f in regs[:12]]
            sections.append(AnswerSection(title=H["sec_source"], items=source_items()))
        else:
            items = source_items()
    elif pl.intent == "substance_search":
        sq = next((f for f in facts if f["type"] == "substance_query"), {"substance": pl.substance or "", "found": len(regs)})
        if regs:
            headline = H["substance"].format(n=sq["found"], x=sq["substance"], countries=countries_txt)
            items = [item_from_reg(f, detail=f.get("activeEntityOriginal")) for f in regs[:12]]
        else:
            av = next((f for f in facts if f["type"] == "actives_available"), {"items": []})
            headline = H["substance_none"].format(x=sq["substance"], actives=", ".join(f"{a['active']} ({a['registrations']})" for a in av["items"][:8]) or "—")
    elif pl.intent == "target_search" and not pl.product_ids:
        tid = next((f for f in facts if f["type"] == "target_id"), None)
        tav = next((f for f in facts if f["type"] == "targets_available"), {"items": []})
        targets_txt = ", ".join(f"{a['target']} ({a['registrations']})" for a in tav["items"][:8]) or "—"
        if not tid:
            headline = H["target_unknown"].format(targets=targets_txt)
        else:
            code = H["eppo_code"].format(code=tid["eppoCode"]) if tid.get("eppoCode") else ""
            crop_txt = L["crop_on"].format(crop=tid["crop"]) if tid.get("crop") else ""
            if regs:
                headline = H["target"].format(n=tid["found"], name=tid.get("name") or tid["wording"], code=code, crop=crop_txt, countries=countries_txt)
                items = use_items(regs)
            else:
                headline = H["target_none"].format(name=tid.get("name") or tid["wording"], code=code, crop=crop_txt, targets=targets_txt)
    elif pl.intent == "sister_product":
        cands, items = alias_items()
        al = [f for f in facts if f["type"] == "alias"]
        n_conf = sum(1 for a in cands if a["reviewStatus"] == "validated")
        headline = focus_headline(H["sisters"].format(product=al[0]["product"] if al else (name or ""), n=len(cands), nc=n_conf))
        if not rels:
            caveats.append(H["sisters_caveat"])
        if len(pl.product_ids) >= 2:
            items = [item_from_reg(f, detail=f"{f.get('usesCount')} {L['uses']}" if f.get("usesCount") is not None else None) for f in regs[:12]] + items
    elif pl.intent == "alternatives":
        alts = [f for f in facts if f["type"] == "alternative"]
        prod = next((f for f in facts if f["type"] == "product"), {})
        cands, rel_items = alias_items()
        pname = prod.get("product") or (alts[0]["product"] if alts else "")
        active = prod.get("sharedActive") or prod.get("activeEntityNormalized") or prod.get("activeEntityOriginal") or "—"
        ctx_countries = ", ".join(pl.countries) if pl.countries else ", ".join(sorted({a["country"] for a in alts})) or "—"
        headline = (H["alternatives"] if alts else H["alternatives_none"]).format(product=pname, n=len(alts), active=active, countries=ctx_countries, nr=len(cands))
        items = [AnswerItem(country=a["country"], product=a["alternative"], registrationNumber=a.get("registrationNumber"), status=a.get("statusNormalized"), statusOriginal=a.get("statusOriginal"),
                            relationship=L["same_active"], detail=(a.get("activeEntityOriginal") or "")[:120] or None, sourceId=a.get("sourceId"), collectedAt=(a.get("collectedAt") or "")[:10])
                 for a in alts[:12]]
        if rel_items:
            sections.append(AnswerSection(title=H["sec_sister_product"], items=rel_items))
    elif pl.intent == "data_quality":
        dq = [f for f in facts if f["type"] == "data_quality"]
        for f in dq:
            items.append(AnswerItem(country=f["country"], product=f.get("product"), registrationNumber=f["registrationId"].split("-", 2)[-1], status=f["validationStatus"],
                                    detail=", ".join(f["missingOrUncertain"]) or "—"))
        headline = H["quality"].format(product=dq[0]["product"] if dq else "", n=len(dq))
    elif pl.intent == "expiry":
        for f in regs[:12]:
            items.append(item_from_reg(f, detail=f"{f.get('daysLeft')} {L['days']}" if f.get("daysLeft") is not None else None))
        headline = H["expiry"].format(n=len(regs), m=pl.months)
    elif pl.intent == "changes":
        ch = [f for f in facts if f["type"] == "change"]
        for f in ch[:12]:
            items.append(AnswerItem(registrationNumber=f.get("entityId"), detail=f"{f.get('field')}: {f.get('oldValue')} → {f.get('newValue')}", collectedAt=(f.get("detectedAt") or "")[:10]))
        headline = H["changes"].format(n=len(ch))
    elif pl.intent == "country_portfolio":
        scope_txt = H["scope_lallemand"] if pl.scope == "lallemand" else ""
        for f in regs[:12]:
            items.append(item_from_reg(f, detail=f.get("activeEntityNormalized") or f.get("holder")))
        parts = []
        for f in [x for x in facts if x["type"] == "portfolio"]:
            cn = CN.get(f["country"], f["country"])
            if f["coverage"] == "source_not_collected":
                parts.append(H["pf_nosrc"].format(country=cn))
            elif f["total"] == 0:
                parts.append(H["pf_none"].format(country=cn, scope=scope_txt, source=f.get("sourceId"), date=(f.get("collectedAt") or "")[:10]))
            else:
                parts.append(H["pf"].format(country=cn, n=f["total"], scope=scope_txt, source=f.get("sourceId"), date=(f.get("collectedAt") or "")[:10]))
                if f["total"] > 12:
                    caveats.append(H["pf_more"].format(more=f["total"] - 12))
        headline = " ".join(parts) or L["nothing"]
    elif pl.intent == "ingredient_search":
        for f in regs[:12]:
            uses = [u for u in facts if u["type"] == "use" and u.get("registrationNumber") == f["registrationNumber"]]
            det = "; ".join(f"{u.get('crop')} → {u.get('target')}" + (f", {u['dose']} {u['doseUnit']}" if u.get("dose") is not None else "") for u in uses[:2]) or None
            items.append(item_from_reg(f, detail=det))
        if pl.species:
            headline = H["ingredient"].format(species=pl.species or "", crop=f" · {pl.crop}" if pl.crop else "", n=len(regs), nc=len({f["country"] for f in regs}))
        else:
            av = next((f for f in facts if f["type"] == "actives_available"), {"items": []})
            headline = H["substance_none"].format(x=pl.substance or "?", actives=", ".join(f"{a['active']} ({a['registrations']})" for a in av["items"][:8]) or "—")
    elif pl.intent == "product_profile":
        prod = next((f for f in facts if f["type"] == "product"), {})
        fw, hw = PROFILE_WORDS[lang]
        holder = next((f.get("holder") for f in regs if f.get("holder")), None)
        not_found = sorted({c["country"] for c in cov if c["coverage"] == "not_found_in_source"})
        headline = H["profile"].format(product=name or prod.get("product") or "", active=prod.get("activeEntityNormalized") or prod.get("activeEntityOriginal") or "—",
                                       formulation=fw.format(f=prod["formulation"]) if prod.get("formulation") else "", holder=hw.format(h=holder) if holder else "",
                                       found=", ".join(f"{f['country']} {L['no']} {f['registrationNumber']} ({f['statusNormalized']})" for f in regs[:6]) or "—", nf=", ".join(not_found) or "—")
        items = [item_from_reg(f, detail=f"{f.get('usesCount')} {L['uses']}" if f.get("usesCount") is not None else None) for f in regs[:12]] + coverage_items()
        tg, titems = target_items()
        if titems:
            sections.append(AnswerSection(title=H["sec_target_search"], items=titems))
    elif pl.intent == "target_search":  # with a product: its targets
        tg, items = target_items()
        headline = (H["targets_of"].format(product=name or (tg[0]["product"] if tg else ""), n=len({(f['country'], f['target']) for f in tg}), countries=", ".join(sorted({f["country"] for f in tg})) or "—")
                    if tg else H["targets_none"].format(product=name or (pl.product_ids[0] if pl.product_ids else "")))
    else:  # registration_lookup, use_comparison, source
        show_uses = pl.intent == "use_comparison" or bool(pl.crop) or "dose" in pl.flags
        items = use_items(regs) if show_uses else [item_from_reg(f, detail=(f.get("holder") if "holder" in pl.flags else (f"{f.get('usesCount')} {L['uses']}" if f.get("usesCount") is not None else None))) for f in regs[:12]]
        items += coverage_items() + related_items()
        if len({f["product"] for f in regs}) >= 2:  # two products compared: one clause per product, plus their declared relation
            by_p: dict[str, list] = {}
            for f in regs:
                by_p.setdefault(f["product"], []).append(f)
            headline = " ".join(H["lookup"].format(product=p, countries=", ".join(sorted({f['country'] for f in fs})), n=len(fs)) for p, fs in by_p.items())
            if rels:
                headline += " " + relation_headline()
        else:
            headline = lookup_headline()
            if pl.intent == "use_comparison" and regs:
                headline = H["compare"].format(product=name or "", countries=", ".join(found), n=sum(f.get("usesCount") or 0 for f in regs))
        headline = focus_headline(headline)
    # further parts of a multi-part question
    for it in pl.extra_intents:
        if it == "use_comparison":
            sections.append(AnswerSection(title=H["sec_use_comparison"], text=H["compare"].format(product=name or "", countries=", ".join(found), n=sum(f.get("usesCount") or 0 for f in regs)) if regs else None,
                                          items=use_items(regs)))
        elif it == "sister_product":
            cands, sitems = alias_items()
            sections.append(AnswerSection(title=H["sec_sister_product"], text=H["sisters"].format(product=name or "", n=len(cands), nc=sum(1 for a in cands if a["reviewStatus"] == "validated")), items=sitems))
            caveats.append(H["sisters_caveat"])
        elif it == "target_search":
            tg, titems = target_items()
            sections.append(AnswerSection(title=H["sec_target_search"], text=(H["targets_of"].format(product=name or "", n=len({(f['country'], f['target']) for f in tg}), countries=", ".join(sorted({f["country"] for f in tg})) or "—")
                                                                               if tg else H["targets_none"].format(product=name or "")), items=titems))
        elif it == "data_quality":
            dq = [f for f in facts if f["type"] == "data_quality"]
            sections.append(AnswerSection(title=H["sec_data_quality"], text=H["quality"].format(product=name or "", n=len(dq)),
                                          items=[AnswerItem(country=f["country"], registrationNumber=f["registrationId"].split("-", 2)[-1], status=f["validationStatus"], detail=", ".join(f["missingOrUncertain"]) or "—") for f in dq[:12]]))
        elif it == "alternatives":
            alts = [f for f in facts if f["type"] == "alternative"]
            sections.append(AnswerSection(title=H["sec_alternatives"], text=None, items=[AnswerItem(country=a["country"], product=a["alternative"], registrationNumber=a.get("registrationNumber"), status=a.get("statusNormalized"),
                                                                                                    relationship=L["same_active"], detail=(a.get("activeEntityOriginal") or "")[:120] or None) for a in alts[:12]]))
        elif it == "product_profile":
            prod = next((f for f in facts if f["type"] == "product"), {})
            sections.append(AnswerSection(title=H["sec_product_profile"], text=f"{name}: {prod.get('activeEntityNormalized') or prod.get('activeEntityOriginal') or '—'}" + (f", {prod['formulation']}" if prod.get("formulation") else "")))
    for w in warnings:
        if len(caveats) >= 4:
            break
        if rels and "not found in" in w:
            continue  # a relation question: per-country coverage of each product is noise here
        if any(k in w for k in CAVEAT_KEYS):
            lw = localize_warning(w, lang)
            if lw not in caveats:
                caveats.append(lw)
    return StructuredAnswer(headline=headline, items=items[:12], sections=sections[:4], caveats=caveats[:4])


# --------------------------------------------------------------------------- 5. LLM phrasing + guard
SYSTEM = """You are the conversational assistant of a regulatory-watch tool for plant protection products, used by Regulatory Affairs at Lallemand Plant Care.
You receive the QUESTION, FACTS (rows from official sources, already filtered), WARNINGS and a DRAFT built deterministically (same JSON shape).
Return a JSON object matching the schema (headline, items, sections, caveats), written in the requested language.
Rules:
- headline: answer the question directly, naturally and briefly (one to three sentences), as a knowledgeable colleague would. No row dump.
- items: ONLY the rows that support the headline, with ONLY the fields that matter for this question. Keep product names, numbers, dates, statuses, doses and URLs exactly as in FACTS. Max 12.
- sections: for a multi-part question, one section per further part in the order asked (title + one or two sentences + rows). Otherwise leave empty.
- caveats: at most 4 short sentences from WARNINGS the reader must know (not proof of absence, dose not in structured source, hypothesis, no advice on use, EPPO code to verify).
- If FACTS contain 'source' rows and no registration for the product asked: say clearly that the store has no data on that product, what the store covers (use the 'scope' of each source), and which official source to check (keep the URLs); offer what you CAN do (search by active substance, crop or target). Never guess a registration.
- If FACTS contain 'actives_available' or 'targets_available': say nothing was found and list a few of those as what the store knows.
- A 'target_id' row names the disease/pest the question is about (with an EPPO code candidate when known): state it ("tavelure du pommier = Venturia inaequalis, EPPO VENTIN, à vérifier").
- Never add a country, product, number, date, dose, URL or status that is not in FACTS. Never give advice on how to use a product or whether it may be used on another crop: say that only the official label is authoritative and report the registered uses you have.
- Related or sister candidates are hypotheses unless their review status is 'validated'; alternatives share only the active substance and are distinct products.
- CONVERSATION (earlier turns) is given for wording only: never reuse a number, product or country from it unless it is in FACTS.
- For a greeting or a 'what can you do' question, answer warmly in two or three sentences and give two example questions."""


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d\-/.,]*\d|\d", text))


def guard(llm_text: str, facts: list[dict], warnings: list[str]) -> tuple[bool, str | None]:
    """Reject any LLM answer containing a number or country code not present in the facts/warnings."""
    allowed = _numbers(json.dumps(facts, ensure_ascii=False, default=str) + " " + " ".join(warnings))
    for n in _numbers(llm_text):
        if n not in allowed and not re.fullmatch(r"\d{1,2}", n):  # small counts (e.g. '3 countries') are tolerated
            return False, f"unsupported number '{n}' in model text"
    ccs = set(re.findall(r"\b([A-Z]{2})\b", llm_text)) & set(Q.COUNTRY_SOURCES) | set(re.findall(r"\b(DE|BE|MX|UY|ES|IT|NL|GB|PL)\b", llm_text))
    fact_ccs = {f.get("country") for f in facts if f.get("country")} | set(re.findall(r"\(([A-Z]{2})\)", " ".join(warnings)))
    for cc in ccs - fact_ccs:
        if cc in COUNTRY_WORDS:
            return False, f"country {cc} not in facts"
    return True, None


def ask(session: Session, question: str, language: str = "fr", context: dict | None = None, history: list[dict] | None = None) -> dict:
    pl = plan(session, question, context)
    facts, evidence, warnings, tools = run_tools(session, pl)
    detected = detect_language(question)
    answer_lang = detected or (language or "fr").lower()[:2]
    det_lang = answer_lang if answer_lang in LBL else (language if (language or "")[:2] in LBL else "en")
    structured = build_structured(pl, facts, warnings, det_lang)
    text = structured.to_text(det_lang)
    model = None
    if settings.ai_enabled and (facts or pl.intent == "help"):
        try:
            client = get_client()
            conv = "".join(f"- {h.get('role')}: {str(h.get('content') or '')[:300]}\n" for h in (history or [])[-6:] if isinstance(h, dict))
            user = ((f"CONVERSATION (earlier turns, wording only):\n{conv}\n" if conv else "")
                    + f"QUESTION (answer language: {answer_lang}): {question}\n\nFACTS (JSON rows):\n{json.dumps(facts[:60], ensure_ascii=False, default=str)}\n\n"
                    f"WARNINGS:\n- " + "\n- ".join(warnings[:12]) + f"\n\nDRAFT (same shape; improve selection and wording, never content):\n{structured.model_dump_json()}")
            data = client.chat_json(SYSTEM, user, schema=ANSWER_SCHEMA, max_tokens=1600)
            cand = StructuredAnswer.model_validate(data)
            cand.items = cand.items[:12]
            cand.sections = cand.sections[:4]
            cand.caveats = cand.caveats[:4]
            ok, why = guard(cand.to_text(det_lang), facts, warnings)
            if ok and cand.headline.strip():
                structured, text, model = cand, cand.to_text(det_lang), client.model
            else:
                warnings.append(f"AI phrasing rejected by the grounding guard ({why}); deterministic answer shown instead.")
        except (LLMUnavailable, ValueError) as e:
            kind = str(e).split(":", 1)[0].strip() or "error"
            warnings.append(f"AI provider unavailable ({kind}); deterministic answer shown, built from the same facts.")
    # dedupe evidence by (source url, snapshot)
    seen = set()
    ev = []
    for e in evidence:
        k = (e["sourceUrl"], e.get("snapshotId"))
        if k not in seen:
            seen.add(k)
            ev.append(e)
    return {"answer": text, "evidence": ev[:50], "warnings": list(dict.fromkeys(warnings)), "disclaimer": DISCLAIMER,
            "facts": facts[:200], "intent": pl.intent, "toolsUsed": list(dict.fromkeys(tools)), "model": model,
            "structured": structured.model_dump(), "warningsLocalized": [localize_warning(w, det_lang) for w in dict.fromkeys(warnings)],
            "context": {"productIds": pl.product_ids, "countries": pl.countries, "species": pl.species, "crop": pl.crop, "intent": pl.intent},
            "language": answer_lang, "extraIntents": pl.extra_intents}
