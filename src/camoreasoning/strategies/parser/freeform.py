"""Free-form questions (judges' own wording) on top of `baseline`. 0 LLM calls, never raises.

Order:
1. `baseline` on the raw text. A template hit ("What effect does X have on Y?") is returned unchanged,
   so template questions parse exactly as in baseline, `template_hit` included. `template_hit` is True
   only in that case.
2. Otherwise normalise (NFKC, smart quotes, zero-width characters, whitespace, trailing ?.!), drop
   polite or evidence-seeking lead-ins ("Can you tell me whether", "Is there evidence that") and a
   leading context clause ("In restored wetlands, ..."), then try the shapes below in order. Matching is
   case-insensitive; spans keep the question's casing.
3. Each span is cleaned: parentheticals go, a cause keeps its last clause and an outcome its first
   (split at , ; :), then trailing habitat/region/time qualifiers ("in restored wetlands", "over time",
   "compared to mowing") and neutral wrappers ("the use of", "we add") are removed only when something
   is left. A qualifier is stripped only when its last word is a context noun (CONTEXT_HEAD), so
   "nitrogen in soil" or "survival on clearcuts" stay whole. A shape is rejected (the next one is
   tried) if a cleaned span has no content word or more than MAX_SPAN_TOKENS, so multi-clause
   questions do not yield clause-long spans.
4. If no shape matches, baseline's own result stands (its " on " split, or no spans).

Shapes (X = cause, Y = outcome):
- "What effect/impact/influence does X have on Y", "What difference does X make to Y"
- "(What is) the effect/impact/influence/consequences of X on/for Y", "the role of X in Y"
- "Does X have an effect on Y", "Does X lead to / result in (more|less|higher|...) Y"
- "Does/Can/Will X help/harm/benefit/increase/reduce/affect/... Y" (also "increase or decrease")
- "Is X good/bad/beneficial/harmful for Y"
- "Is/Are Y affected/influenced/changed/... by X" (passive: sides swap)
- "How does Y respond/react/change to/after X" (sides swap)
- "What happens to Y when/after/if/with X" (sides swap)
- "How does X affect Y" (baseline paraphrases, extended verbs)
- "relationship/link/association between X and Y", "How are X and Y related"
- declarative "X increases Y" (after "whether"/"that" lead-ins too)
- bare "X and Y" / "X vs Y" / "X -> Y" for short inputs without a verb
"""

from __future__ import annotations

import re
import unicodedata

from camoreasoning.components import Context, QuestionParser
from camoreasoning.contracts import ParsedQuestion, Question
from camoreasoning.registry import register
from camoreasoning.strategies.parser.baseline import PARAPHRASES, TEMPLATE, RegexParser
from camoreasoning.text import tokens

MAX_CHARS = 2000  # longer inputs are truncated before the free-form shapes (regex cost stays linear)
BARE_MAX_WORDS = 12  # "X and Y" only for short inputs
MAX_SPAN_TOKENS = 8  # content tokens; class labels have <= 6, longer spans are clauses, not concepts
PARENTHETICAL = re.compile(r"\([^()]*\)?|\[[^\[\]]*\]?")  # "(...)" or an unclosed "(..." to the end

_QUOTES = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": None,
        "”": None,
        "„": None,
        "‟": None,
        '"': None,
        "`": "'",
        "´": "'",
        "–": "-",
        "—": "-",
    }
)
_INVISIBLE = re.compile(r"[​-‏⁠-⁤﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


AUX = r"(?:does|do|did|can|could|would|will|might|may|should|is|are|was|were|has|have)"
# Base, 3rd-person and past forms of effect verbs (one alternation, longest first where prefixes clash).
_VERB_STEMS = (
    "increase",
    "decrease",
    "reduce",
    "improve",
    "affect",
    "influence",
    "change",
    "impact",
    "alter",
    "harm",
    "help",
    "benefit",
    "boost",
    "lower",
    "raise",
    "promote",
    "suppress",
    "enhance",
    "limit",
    "damage",
    "hurt",
    "favour",
    "favor",
    "impair",
    "support",
    "inhibit",
    "stimulate",
    "restore",
    "degrade",
    "shape",
    "modify",
    "drive",
    "control",
    "accelerate",
    "slow",
    "speed up",
    "maintain",
    "diminish",
    "elevate",
    "deplete",
)


def _forms(stem: str) -> list[str]:
    head, _, tail = stem.partition(" ")
    tail = f" {tail}" if tail else ""
    if head.endswith("e"):
        forms = [head, head + "s", head + "d"]
    elif head.endswith("y") and head != "slow":
        forms = [head, head[:-1] + "ies", head[:-1] + "ied"]
    else:
        forms = [head, head + "s", head + "ed"]
    if head == "speed":
        forms = ["speed", "speeds", "sped"]
    return [f + tail for f in forms]


VERBS = "(?:" + "|".join(sorted({f for s in _VERB_STEMS for f in _forms(s)}, key=len, reverse=True)) + ")"
VERB_PHRASE = (
    rf"(?:(?:help|helps|helped) (?:to )?)?{VERBS}(?: or {VERBS})?"
    r"|(?:lead|leads|led|result|results|resulted|contribute|contributes|contributed) (?:to|in)"
    r"|(?:matter|matters) (?:for|to)|(?:make|makes|made) (?:a|any) difference (?:to|for|in)"
    r"|(?:cause|causes|caused)"
)
AMOUNT = (
    r"(?:(?:more|less|higher|lower|greater|fewer|increased|decreased|reduced|improved|better|worse|bigger|"
    r"smaller|larger|faster|slower|elevated|enhanced|lowered|raised|declining|increasing|decreasing) )?"
)
PASSIVE = (
    r"(?:affected|influenced|changed|altered|impacted|driven|controlled|determined|reduced|increased|decreased|"
    r"improved|harmed|helped|benefited|benefitted|enhanced|suppressed|promoted|limited|damaged|hurt|shaped|"
    r"favou?red|impaired|boosted|lowered|raised|inhibited|stimulated|modified|related|linked|tied)"
)
EFFECT_NOUN = r"(?:effects?|impacts?|influences?|consequences?|outcomes?|results?)"
NOT_A_SUBJECT = (
    r"(?:what|which|who|whom|whose|when|where|why|how|after|before|while|if|for|in|and|but|or|does|do|did|is|are"
    r"|can|could|would|will|should)\b"
)

# In priority order. Groups are named, so shapes that name the outcome first need no swap.
SHAPES: list[re.Pattern] = [
    _rx(
        r"^(?:what|which) (?:kinds? of |sorts? of )?(?:effects?|impacts?|influences?|consequences?)"
        r" (?:does|do|did|can|could|would|will|might|may|has|have) (?P<c>.+?)"
        r" (?:have|has|had) (?:had )?(?:on|for|upon) (?P<o>.+)$"
    ),
    _rx(
        r"^(?:what|how much) difference (?:does|do|did|can|could|would|will|might|may) (?P<c>.+?)"
        r" (?:make|makes|made) (?:to|for|in|on) (?P<o>.+)$"
    ),
    _rx(
        r"^(?:(?:what|how) (?:is|are|was|were) |what's |what're |(?:is|are) there (?:an? |any )?|describe |"
        rf"explain |summari[sz]e )?(?:the |an? |any )?(?:overall |net |main |likely )?{EFFECT_NOUN} of"
        r" (?P<c>.+?) (?:on|for|upon) (?P<o>.+)$"
    ),
    _rx(r"^(?:(?:what|how) (?:is|are) |what's )?(?:the )?role of (?P<c>.+?) (?:in|for|on) (?P<o>.+)$"),
    _rx(
        rf"^{AUX} (?P<c>.+?) (?:have|has|had) (?:an? |any |some |no )?(?:positive |negative |significant |"
        rf"measurable |real |direct )?{EFFECT_NOUN} (?:on|for|upon) (?P<o>.+)$"
    ),
    _rx(rf"^(?:how|why) (?:is|are|was|were) (?P<o>.+?) {PASSIVE} (?:by|to|with) (?P<c>.+)$"),
    _rx(
        rf"^(?:is|are|was|were|can|could|will|would|might|may) (?:be )?(?P<o>.+?) (?:be )?{PASSIVE}"
        r" (?:by|to|with) (?P<c>.+)$"
    ),
    _rx(
        r"^how (?:does|do|did|will|would|might|can) (?P<o>.+?) (?:respond|react|change|vary|differ|recover|"
        r"fare|cope) (?:to|after|with|following|under|in response to|when exposed to) (?P<c>.+)$"
    ),
    _rx(
        r"^what (?:happens|happened|will happen|would happen|changes) (?:to|in|with) (?P<o>.+?)"
        r" (?:when|after|if|once|with|under|following|during) (?P<c>.+)$"
    ),
    _rx(rf"^{AUX} (?P<c>.+?) (?:{VERB_PHRASE}) {AMOUNT}(?P<o>.+)$"),
    _rx(
        rf"^(?:how|in what ways?) (?:does|do|did|can|could|would|will|might|may) (?P<c>.+?) (?:{VERB_PHRASE})"
        rf" {AMOUNT}(?P<o>.+)$"
    ),
    _rx(
        r"^(?:is|are|was|were) (?P<c>.+?) (?:good|bad|beneficial|harmful|helpful|detrimental|useful|"
        r"effective|important|positive|negative) (?:for|to|on) (?P<o>.+)$"
    ),
    *PARAPHRASES,
    _rx(
        r"^(?:what(?:'s| is| are)? |is there |are there |describe |explain |show )?(?:an? |the |any )?"
        r"(?:relationships?|links?|associations?|connections?|correlations?|interactions?|evidence)"
        r" (?:between|linking|connecting) (?P<c>.+?) (?:and|with|to) (?P<o>.+)$"
    ),
    _rx(
        r"^how (?:is|are|was|were) (?P<c>.+?) (?:and|with) (?P<o>.+?) (?:related|linked|connected|"
        r"associated)$"
    ),
    # declarative "X increases Y": single clause only, not a wh-question or a subordinate clause
    _rx(rf"^(?!{NOT_A_SUBJECT})(?P<c>[^,;()]+?) (?:{VERB_PHRASE}) {AMOUNT}(?P<o>[^,;()]+)$"),
]
BARE = _rx(rf"^(?!{NOT_A_SUBJECT})(?P<c>[^,;()]+?) (?:and|vs\.?|versus|->|→|=>|on) (?P<o>[^,;()]+)$")

LEAD_INS = [
    _rx(r"^(?:hi|hello|hey|ok(?:ay)?|so|well|please|quick question)\b[,:!]?\s+"),
    _rx(
        r"^(?:(?:can|could|would|will) you (?:please )?|please )?(?:tell me|explain|show me|say|find out|"
        r"check|let me know)(?: about)?\s+"
    ),
    _rx(
        r"^(?:i(?:'m| am) (?:wondering|curious|interested)(?: about)?|i (?:want|would like|'d like|need)"
        r" to know|i wonder|do you know|does the graph (?:show|say)|what does the graph say about)\s+"
    ),
    _rx(
        r"^(?:is there|are there|do you have|what is the|what's the) (?:any )?(?:evidence|data|research|"
        r"proof|support) (?:that|whether|if|for whether)\s+"
    ),
    _rx(
        r"^(?:do|does|did) (?:studies|research|the data|the graph|the evidence|the literature|papers)"
        r" (?:show|suggest|find|indicate|say) (?:that|whether|if)\s+"
    ),
    _rx(
        r"^(?:how much|to what (?:extent|degree)|how (?:strongly|exactly|far|quickly|fast)|by how much)"
        rf"\s+(?={AUX}\s)"
    ),
    _rx(r"^(?:whether|if|that)\s+"),
]
LEAD_CONTEXT = _rx(r"^(?:in|for|within|across|among|on|at|under|throughout) [^,]{1,80},\s*(?=\S)")
TRAIL_CONTEXT = _rx(r",\s*(?:in|for|within|across|among|on|at|under|throughout|over|during) [^,]{1,80}$")

PREP = r"(?:in|within|across|at|on|for|among|under|over|during|after|following|throughout|from|of)"
CONTEXT_HEAD = (
    r"(?:forests?|woodlands?|wetlands?|peatlands?|bogs?|fens?|marsh(?:es)?|swamps?|grasslands?|prairies?|"
    r"meadows?|savann?ahs?|tundra|sites?|plots?|stands?|areas?|regions?|landscapes?|ecosystems?|habitats?|"
    r"watersheds?|catchments?|streams?|rivers?|lakes?|ponds?|canada|ontario|quebec|québec|alberta|manitoba|"
    r"saskatchewan|columbia|scotia|brunswick|labrador|newfoundland|yukon|nunavut|territories|north|boreal|"
    r"field|lab|laboratory|greenhouses?|experiments?|studies|study|trials?|plantations?|years?|decades?|"
    r"seasons?|term|run|time|practice|projects?|zones?|ecozones?|ecoregions?|biomes?|systems?|conditions?)"
)
TRAIL_QUALIFIERS = [
    _rx(rf"\s+{PREP}\s+(?:(?!(?:of|in|on|and|or|to|with|by)\b)[\w'&/-]+\s+){{0,3}}{CONTEXT_HEAD}$"),
    _rx(r"\s+(?:compared (?:to|with)|relative to|versus|vs\.?|instead of|rather than) .+$"),
    _rx(
        r"\s+(?:or not|at all|over time|long[- ]term|short[- ]term|significantly|much|a lot|overall|"
        r"in general|generally|really|anymore|in practice)$"
    ),
]
LEAD_WRAPPERS = [
    _rx(r"^(?:we|you|they|people|managers|land managers|practitioners|restorationists|one)\s+"),
    _rx(
        r"^(?:add|adding|added|apply|applying|applied|use|using|used|do|doing|implement|implementing|"
        r"introduce|introducing|carry out|carrying out|perform|performing|conduct|conducting)\s+(?=\S)"
    ),
    _rx(r"^(?:the )?(?:use|application|implementation|practice) of\s+"),
    _rx(r"^(?:the|a|an|any|some)\s+(?=\S)"),
    _rx(r"^(?:more|less|higher|lower|greater|fewer|increased|decreased|reduced)\s+(?=\S)"),
]
TRAIL_WRAPPERS = _rx(
    r"\s+(?:is|are|was|were|gets|get) (?:used|applied|added|done|implemented|carried out|performed|conducted)$"
)


def normalise(text: str) -> str:
    """NFKC, ASCII apostrophes and dashes, no double quotes, invisible or control characters, single spaces."""
    t = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    t = _CONTROL.sub(" ", _INVISIBLE.sub("", t))
    t = " ".join(t.split())
    return t.strip(" ?.!;:,\"'")


def _strip_lead_ins(t: str) -> str:
    for _ in range(4):
        before = t
        for rx in LEAD_INS:
            t = rx.sub("", t, count=1)
        t = LEAD_CONTEXT.sub("", t, count=1)
        if t == before:
            break
    return t


def clean_span(span: str | None, cause: bool) -> str | None:
    """Trim punctuation, parentheticals, trailing context qualifiers and neutral wrappers. A cause keeps
    its last clause, an outcome its first. None if nothing with a word in it is left, or if the span is
    too long to be one concept (MAX_SPAN_TOKENS)."""
    if span is None:
        return None
    s = PARENTHETICAL.sub(" ", span)
    clauses = [c for c in re.split(r"[,;:]", s) if re.search(r"\w", c)]
    if not clauses:
        return None
    s = " ".join((clauses[-1] if cause else clauses[0]).split()).strip(" ?.!\"'[]")
    for _ in range(3):
        before = s
        for rx in TRAIL_QUALIFIERS:
            cut = rx.sub("", s, count=1).strip(" ,")
            if cut and cut != s and re.search(r"\w", cut):
                s = cut
        if cause:
            cut = TRAIL_WRAPPERS.sub("", s, count=1)
            if cut.strip():
                s = cut
        for rx in LEAD_WRAPPERS:
            cut = rx.sub("", s, count=1)
            if cut.strip() and re.search(r"\w", cut):
                s = cut
        if s == before:
            break
    s = s.strip(" ?.!;:,\"'()[]")
    return s if tokens(s) and len(tokens(s)) <= MAX_SPAN_TOKENS else None


def _match(body: str) -> tuple[str, str] | None:
    """First shape whose cleaned spans both carry content words."""
    shapes = [TEMPLATE, *SHAPES] + ([BARE] if len(body.split()) <= BARE_MAX_WORDS else [])
    for rx in shapes:
        if (m := rx.match(body)) and (c := clean_span(m["c"], True)) and (o := clean_span(m["o"], False)):
            return c, o
    return None


def parse_spans(text: str) -> tuple[str | None, str | None] | None:
    """Free-form shapes only (no baseline fallback). None if no shape matches."""
    t = normalise(text)[:MAX_CHARS]
    if not t:
        return None
    candidates = [t]
    body = _strip_lead_ins(t)
    if body != t:
        candidates.insert(0, body)
    for b in list(candidates):
        trimmed = TRAIL_CONTEXT.sub("", b, count=1)
        if trimmed != b and trimmed:
            candidates.append(trimmed)
    for b in candidates:
        if hit := _match(b):
            return hit
    return None


@register("parser", "freeform")
class FreeformParser(QuestionParser):
    def __init__(self):
        self._base = RegexParser()

    def parse(self, question: Question, ctx: Context) -> ParsedQuestion:
        base = self._base.parse(question, ctx)
        if base.template_hit:
            return base
        spans = parse_spans(question.text or "")
        if spans is None:
            return base
        return ParsedQuestion(question, spans[0], spans[1], False)
