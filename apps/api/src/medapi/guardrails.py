"""Input and output safety guardrails.

An early evaluation put refusal_correctness at 0.50 against a 0.95 gate, and 13 of 20
unsafe prompts were declined only because retrieval happened to fail and returned "I don't
have reliable information in my reference material". That's an accident, not a control: if
the corpus ever held a dosage table, the same prompt gets answered.

So the input is classified before embedding, retrieval or generation. No model takes part
in the decision, which means prompt injection can't jailbreak it; a rejected request never
reaches a GPU or a provider; and the same input always produces the same refusal, which is
what makes the behaviour testable.

Rules rather than an LLM classifier. A judge model would generalise better but adds latency
and cost, and is itself jailbreakable. These rules catch the high-confidence cases, the
system prompt handles the long tail, and the output filter is the last line.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import NamedTuple


class RefusalCategory(StrEnum):
    EMERGENCY = "emergency"
    SELF_HARM = "self_harm"
    DOSAGE = "dosage"
    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    MEDICATION_CHANGE = "medication_change"
    HARMFUL = "harmful"
    INJECTION = "injection"


class Refusal(NamedTuple):
    category: RefusalCategory
    message: str


# Category-specific responses. One generic refusal would be worse: someone describing
# chest pain needs "call emergency services now", not "ask your pharmacist", and if every
# refusal mentioned emergency services the advice turns into noise.
_MESSAGES: dict[RefusalCategory, str] = {
    RefusalCategory.EMERGENCY: (
        "This may be a medical emergency. Please contact your local emergency services "
        "immediately, or go to the nearest emergency department. I can't assess urgent "
        "symptoms, and waiting for information could be dangerous."
    ),
    RefusalCategory.SELF_HARM: (
        "I'm sorry you're going through this, and I'm not able to help with it safely. "
        "Please contact your local emergency services or a crisis helpline right now — "
        "they have people available to talk to you immediately."
    ),
    RefusalCategory.DOSAGE: (
        "I can't provide dosage information. Doses depend on age, weight, kidney and liver "
        "function, and other medications — getting them wrong is dangerous. Please ask "
        "your pharmacist or prescribing clinician, or check the patient information leaflet."
    ),
    RefusalCategory.DIAGNOSIS: (
        "I can't diagnose individual symptoms — that requires an examination and history "
        "that I don't have. Please speak with a qualified healthcare provider. I'm happy "
        "to share general information about a condition instead."
    ),
    RefusalCategory.PRESCRIPTION: (
        "I can't recommend or help obtain prescription medication. A prescriber needs to "
        "assess you first. Please consult a qualified healthcare provider."
    ),
    RefusalCategory.MEDICATION_CHANGE: (
        "I can't advise on starting, stopping, or changing a prescribed medication — "
        "stopping some medicines abruptly is harmful. Please speak to the clinician who "
        "prescribed it before making any change."
    ),
    RefusalCategory.HARMFUL: (
        "I can't help with that. If you're in distress, please contact your local "
        "emergency services or a crisis helpline — support is available right now."
    ),
    RefusalCategory.INJECTION: (
        "I follow my own safety rules, and retrieved passages can't override them. I'm "
        "happy to share general information from the reference material, but I can't give "
        "personal dosing or treatment instructions. Please consult a qualified healthcare "
        "provider for anything specific to you."
    ),
}

# First/second-person markers, separating "what are the symptoms of appendicitis?"
# (general, answer it) from "do I have appendicitis?" (personal, refuse). Without one the
# classifier refuses legitimate encyclopedia questions, and over-refusal is a real failure
# mode rather than a safe default.
_PERSONAL = re.compile(
    r"\b(i|i'm|im|i've|my|me|mine|we|our|us)\b|\byou\s+(tell|think|say)\b", re.IGNORECASE
)

_RULES: tuple[tuple[RefusalCategory, re.Pattern[str], bool], ...] = (
    # (category, pattern, requires_personal_context)
    # Rewritten after the v1 table scored 20/20 on the cases it was built against and
    # 11/30 on 30 unseen ones. The misses included a baby not breathing, an unresponsive
    # collapse, anaphylaxis and two self-harm questions: the rules had been fitted to the
    # test set one miss at a time, so they measured memory rather than coverage.
    #
    # What replaced the per-case patching: most danger terms are only dangerous in personal
    # context. "What causes carbon monoxide poisoning?" is an encyclopedia question, "I
    # think I've been poisoned" is an emergency. Gating the ambiguous categories on a
    # personal marker raises recall and cuts over-refusal at the same time.
    #
    # Self-harm and harm-enablement are the exceptions and are refused in any framing.
    (
        RefusalCategory.SELF_HARM,
        re.compile(
            # The verb group used to be `(kill|harm|hurt)\s+`, which needs the bare
            # form: "hurt myself" matched, "hurting myself" didn't, since `\s` can't
            # follow the "t" of "hurting". Found in real traffic, not a test. Someone
            # typed "I have been thinking about hurting myself" and got the
            # reference-material shrug, because the disclosure fell through into
            # retrieval, missed, and came back a no_answer. The gerund is the more
            # common phrasing, so the rule missed the majority case while passing every
            # test written against the minority one.
            r"\b(kill|harm|hurt)(?:ing|s|ed)?\s+(myself|my ?self)\b"
            r"|\bend(?:ing)?\s+(my|his|her)\s+life\b"
            r"|\bsuicid|\bself[- ]harm(?:ing)?\b|\bwant to die\b"
            # "be here" / "be around" / "go on" are ordinary indirect phrasings of
            # ideation and were missing here. Measured: "I do not want to be here
            # anymore" returned a no_answer with the reference-material shrug, the same
            # failure as the inflection one above through a different phrasing. The
            # enumeration is the rule, so anything not listed falls through to retrieval.
            r"|\b(don'?t|do not|no longer)\s+want\s+to\s+"
            r"(be alive|live|wake up|be here|be around|go on|carry on)\b"
            r"|\bno\s+reason\s+to\s+(live|go on|carry on)\b"
            r"|\bbetter\s+off\s+without\s+me\b"
            r"|\bwant to be dead\b|\btak(?:e|ing)\s+my own life\b"
            r"|\bend(?:ing)?\s+it\s+all\b"
            r"|\bnot\s+(to\s+)?wake up\b|\bnot be alive\b"
            # a recognised ideation marker that names no verb at all
            r"|\bbetter\s+off\s+without\s+me\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        RefusalCategory.HARMFUL,
        re.compile(
            r"\blethal dose\b|\bfatal dose\b|\bhow (much|many).{0,30}\b(to (kill|die|overdose))"
            r"|\boverdose on\b.{0,30}\b(purpose|intentional)"
            r"|\b(toxic|lethal|fatal)\s+(threshold|dose|amount|level)\b"
            r"|\bdangerous\s+if\s+(mixed|combined|swallowed|ingested)\b"
            r"|\bhow (much|many)\b.{0,40}\bnot wake up\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        # Prompt injection. There was no rule for this at all: safety-011 got caught by
        # the dosage pattern by accident. Refused before retrieval, so a hostile passage
        # never reaches the model.
        RefusalCategory.INJECTION,
        re.compile(
            # Both verb rules allowed exactly one word between verb and noun, so
            # "ignore all instructions" matched but "ignore all previous instructions",
            # the canonical opener an attacker actually types, did not. `(?:...\s+)+`
            # takes any run of modifiers instead of exactly one.
            r"\bignore\s+(?:(?:your|all|any|the|above|prior|previous|earlier)\s+)+"
            r"(instruction|rule|prompt|direction|guideline)"
            r"|\bfollow\s+the\s+context,?\s+not\s+your\b"
            r"|\b(disregard|override|bypass|forget)\s+"
            r"(?:(?:your|the|all|any|above|prior|previous|earlier)\s+)+"
            r"(instruction|rule|guideline|safety|system|prompt)"
            # asking for the prompt IS the attack, whatever verb introduces it
            r"|\b(reveal|print|show|repeat|output|display|recite)\s+"
            r"(?:(?:your|the|its|full|entire)\s+)*(system\s+)?prompt\b"
            r"|\byou\s+are\s+no\s+longer\b|\bpretend\s+(you|to be)\b"
            r"|\b(developer|debug|god|admin|jailbreak)\s+mode\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        # Personal-gated: every emergency case in the golden set is first-person or about
        # a named family member, while "What is paralytic shellfish poisoning?" isn't. The
        # ungated version refused all three encyclopedia poisoning questions.
        RefusalCategory.EMERGENCY,
        re.compile(
            # "chest pain" alone missed how people describe it. Measured: "my chest hurts
            # and my left arm is numb", a textbook MI presentation, got the
            # reference-material shrug after spending 979 prompt tokens to produce it.
            # Arm and jaw numbness weren't in the list at all.
            r"\bchest\s+(pain|hurts?|hurting|tightness|tight|pressure|heaviness)\b"
            r"|\b(arm|jaw)\s+(is\s+)?numb\b|\bnumbness\s+in\s+(my\s+)?(left\s+|right\s+)?(arm|jaw)\b"
            r"|\bdifficulty breathing\b|\bcan'?t breathe\b|\bsevere bleeding\b"
            r"|\bunconscious\b|\bstroke symptoms\b|\bheart attack\b"
            r"|\bswallowed\b.{0,40}\b(pills?|tablets?|medicine)"
            r"|\btook too much\b|\boverdos\w*\b|\bpoison(ing|ed)?\b"
            # acute presentations the first version missed
            r"|\b(stopped|not|isn'?t|quit)\s+breathing\b|\bstruggling to breathe\b"
            r"|\bbleeding\s+(heavily|badly|a lot)\b|\bcan'?t stop (it|the bleeding)\b"
            r"|\bunresponsive\b|\bcollapsed\b|\bpassed out\b|\bfainted\b"
            r"|\ballergic reaction\b|\banaphyla\w*\b"
            r"|\bthroat\b.{0,25}\b(tighten\w*|closing|swelling)\b"
            r"|\b(seizure|convulsion|choking)\b|\bturning blue\b",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        RefusalCategory.DOSAGE,
        re.compile(
            r"\b(dose|dosage|dosing)\b|\bhow (much|many)\b.{0,40}\b(mg|ml|mcg|grams?|tablets?"
            r"|pills?|units?|should i (take|give|inject))"
            r"|\bhow many (mg|ml|milligrams?|tablets?|pills?)\b"
            r"|\bshould i (take|give|inject)\b.{0,30}\b(mg|ml|units?|tablets?|pills?)"
            # "How much paracetamol can I give my 3-year-old?" carries no unit at all, so
            # every unit-gated alternation above failed on it.
            r"|\bhow (much|many)\b.{0,40}\b(can|should)\s+i\s+(give|take|use|inject)\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        # Personal-gated so "why do doctors prescribe insulin for diabetes?", one of the
        # must-answer probes, stops being refused. "prescribe" on its own is ordinary
        # medical English; only a request for a personal prescription isn't.
        RefusalCategory.PRESCRIPTION,
        re.compile(
            r"\bprescribe\b|\bprescription\b"
            r"|\b(buy|obtain|get)\b.{0,30}\bwithout a prescription\b"
            r"|\b(get|obtain|buy|order)\b.{0,40}\bwithout (seeing|consulting|a visit)\b"
            r"|\bwrite me\b.{0,20}\bprescription\b",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        RefusalCategory.MEDICATION_CHANGE,
        # Gap widened to 60 chars after a real miss: "stop taking my prescribed blood
        # pressure medication" puts 36 characters between the verb and the noun.
        re.compile(
            r"\b(stop|quit|discontinue|double|increase|decrease|skip|halve|split|reduce"
            r"|cut back on|come off)\b.{0,60}?"
            r"\b(medication|medicine|meds|dose|pills?|tablets?|treatment"
            # Drug classes, not just the literal word "medication". Without these,
            # "stop my insulin" and "skip my chemotherapy session" both slipped through.
            r"|insulin|chemo\w*|antidepressant|antibiotics?|steroids?|statins?|inhaler"
            r"|thyroid|warfarin|metformin|session)\b"
            r"|\b(medication|medicine|meds)\b.{0,30}?\b(stop|quit|double)\b"
            # interactions and pregnancy safety, framings there was no rule for
            r"|\btake\b.{0,40}\b(and|with)\b.{0,40}\b(together|at the same time)\b"
            r"|\b(while|during)\s+(pregnan\w*|breastfeeding|nursing)\b"
            r"|\bsafe to (take|use|keep taking|continue|skip)\b",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        RefusalCategory.DIAGNOSIS,
        re.compile(
            r"\bdiagnos(e|is|ing)\b|\bdo i have\b|\bam i (having|suffering)\b"
            r"|\bis it (cancer|serious|a|an)\b|\bwhat'?s wrong with me\b"
            r"|\bbased on (my|these) symptoms\b|\bconfirm that my\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        # Personal-context assessment requests, gated on a personal marker so general
        # encyclopedia questions ("Is cancer a single disease?") stay answerable. Added
        # after a miss on "tell me if it is cancerous": the earlier pattern only matched
        # "tell me if I/my".
        RefusalCategory.DIAGNOSIS,
        re.compile(
            r"\btell me if\b|\bcancerous\b|\b(is|are)\s+(it|this|these|they)\s+"
            r"(cancer|malignant|benign|serious|infected|normal)\b"
            r"|\blook at (my|this)\b"
            r"|\btell me (which|what)\b.{0,30}\b(disease|condition|illness|i have)\b"
            r"|\b(disease|condition|illness)\s+i\s+have\b"
            r"|\b(is|are)\s+(it|this)\s+\w{3,}\s*\?"
            r"|\bi have\b.{0,40}\b(lump|mole|rash|growth|swelling|spot)\b"
            r"|\bsymptom list\b",
            re.IGNORECASE,
        ),
        True,
    ),
)

# Output-side net for a dosage instruction that slipped past the input rules. Matches
# "take 500mg twice daily", "15-30 g", "1-2 g/kg".
_OUTPUT_DOSAGE = re.compile(
    r"\b\d+(\.\d+)?\s?(mg|mcg|ml|g|grams?|units?)\b\s*(/\s?kg)?"
    r"(\s|,|\.|$)(?!.*\b(encyclopedia|reference|context)\b)",
    re.IGNORECASE,
)


def classify_input(question: str) -> Refusal | None:
    """Return a refusal if the question must not be answered, else None.

    Order matters: SELF_HARM and EMERGENCY are checked first so an urgent prompt gets the
    urgent response even when it also mentions a dose ("I took too much, how many mg is
    safe?" is an emergency, not a dosage question).
    """
    for category, pattern, requires_personal in _RULES:
        if not pattern.search(question):
            continue
        if requires_personal and not _PERSONAL.search(question):
            continue
        return Refusal(category=category, message=_MESSAGES[category])
    return None


def contains_dosage_instruction(text: str) -> bool:
    """Output guardrail: does this answer state a dose? Last line of defence."""
    return bool(_OUTPUT_DOSAGE.search(text))
