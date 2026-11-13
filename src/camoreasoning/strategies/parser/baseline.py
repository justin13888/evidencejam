"""Regex split of "What effect does X have on Y?" plus common paraphrases."""

from __future__ import annotations

import re

from camoreasoning.components import Context, QuestionParser
from camoreasoning.contracts import ParsedQuestion, Question
from camoreasoning.registry import register

TEMPLATE = re.compile(r"^what (?:is the )?effects? (?:does|do|did) (?P<c>.+?) (?:have|has) on (?P<o>.+?)[?.!]*$", re.I)
PARAPHRASES = [
    re.compile(r"^what (?:is|are) the effects? of (?P<c>.+?) on (?P<o>.+?)[?.!]*$", re.I),
    re.compile(r"^how (?:does|do|did) (?P<c>.+?) (?:affect|influence|change|impact) (?P<o>.+?)[?.!]*$", re.I),
    re.compile(
        r"^(?:does|do|did|can) (?P<c>.+?) (?:affect|increase|decrease|reduce|change|influence) "
        r"(?P<o>.+?)[?.!]*$",
        re.I,
    ),  # fmt: skip
    re.compile(r"^(?:the )?effects? of (?P<c>.+?) on (?P<o>.+?)[?.!]*$", re.I),
]


@register("parser", "baseline")
class RegexParser(QuestionParser):
    def parse(self, question: Question, ctx: Context) -> ParsedQuestion:
        text = " ".join((question.text or "").replace("’", "'").split())
        if m := TEMPLATE.match(text):
            return ParsedQuestion(question, m["c"].strip(), m["o"].strip(), True)
        for rx in PARAPHRASES:
            if m := rx.match(text):
                return ParsedQuestion(question, m["c"].strip(), m["o"].strip(), False)
        if " on " in text:
            c, o = text.rsplit(" on ", 1)
            return ParsedQuestion(question, c.strip() or None, o.strip(" ?.!") or None, False)
        return ParsedQuestion(question, None, None, False)
