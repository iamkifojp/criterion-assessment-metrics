"""
Enhanced MYP Arts - Criterion D (Evaluating) transition rubrics.

Transcribed from the Art Department "Enhanced MYP Transition Framework"
(enhanced_myp_arts_rubrics.pdf). The framework tracks weekly inquiry across
three creative dimensions and is split into two grade phases:

    "7-8"  -> Grades 7 & 8  (MYP Year 2 & 3)
    "9-10" -> Grades 9 & 10 (MYP Year 4 & 5)

Each phase maps a band range ("0", "1-2", "3-4", "5-6", "7-8") to "I can"
statements under three dimensions:

    "Critique & Analyze"  (Responding to Inquiry Questions)
    "Reflect on Growth"   (Tracking Studio & Process Work)
    "Connect to Audience" (Intent, Meaning & Context)

The dashboard uses :func:`rubric_options` to populate the Criterion D feedback
dropdown with statements matching a student's target grade phase.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

DIMENSIONS = ("Critique & Analyze", "Reflect on Growth", "Connect to Audience")
BANDS = ("0", "1-2", "3-4", "5-6", "7-8")

# phase -> band -> dimension -> [statements]
RUBRIC_D: Dict[str, Dict[str, Dict[str, List[str]]]] = {
    "7-8": {
        "0": {
            "Critique & Analyze": [
                "I have not yet provided evidence of an answer to the weekly inquiry question.",
            ],
            "Reflect on Growth": [
                "I have not yet documented or reflected on my studio work this week.",
            ],
            "Connect to Audience": [
                "I have not yet shared thoughts about the meaning or impact of the artwork.",
            ],
        },
        "1-2": {
            "Critique & Analyze": [
                "I can state a basic, factual answer to our weekly inquiry question.",
                "I can identify simple creative choices or elements in an artwork using everyday words.",
            ],
            "Reflect on Growth": [
                "I can list the physical steps I completed during my studio practice this week.",
                "I can point out one clear success or one obvious difficulty I ran into.",
            ],
            "Connect to Audience": [
                "I can state what my artwork (or the artist's work) is explicitly showing.",
                "I can express a simple personal like or dislike toward the final piece.",
            ],
        },
        "3-4": {
            "Critique & Analyze": [
                "I can outline a clear answer to the inquiry question with some supporting details.",
                "I can describe how specific art techniques or elements are used, starting to use correct art terms.",
            ],
            "Reflect on Growth": [
                "I can describe how my studio skills or artistic ideas developed over the week.",
                "I can identify a piece of feedback or a mistake and show where I tried to change my work.",
            ],
            "Connect to Audience": [
                "I can explain a basic connection between the artistic choices made and the intended meaning.",
                "I can describe how an audience might feel or what they might think when looking at the work.",
            ],
        },
        "5-6": {
            "Critique & Analyze": [
                "I can explain my answer to the inquiry question clearly, using examples from the studio or research.",
                "I can analyze how specific elements, styles, or visual cultures shape an artwork, using accurate art vocabulary.",
            ],
            "Reflect on Growth": [
                "I can reflect on my design process, explaining the reasons behind my creative decisions.",
                "I can evaluate my artistic progress this week and identify realistic next steps to improve my work.",
            ],
            "Connect to Audience": [
                "I can explain how effectively an artwork communicates its main idea or mood to an audience.",
                "I can describe how the artwork links to its wider time period, culture, or historical context.",
            ],
        },
        "7-8": {
            "Critique & Analyze": [
                "I can discuss the weekly inquiry question thoroughly, offering insightful connections and distinct viewpoints.",
                "I can critique an artwork accurately, naturally blending advanced design and art theories into my analysis.",
            ],
            "Reflect on Growth": [
                "I can critically reflect on my creative path, detailing exactly how challenges transformed my initial ideas.",
                "I can synthesize my self-reflections and peer feedback to construct clear, ambitious goals for my future practice.",
            ],
            "Connect to Audience": [
                "I can appraise how successfully an artwork conveys complex ideas, looking at it from multiple perspectives.",
                "I can justify my personal interpretation of an artwork with solid, well-reasoned artistic arguments.",
            ],
        },
    },
    "9-10": {
        "0": {
            "Critique & Analyze": [
                "I have not yet provided evidence of an analytical answer to the inquiry question.",
            ],
            "Reflect on Growth": [
                "I have not yet critically evaluated my creative choices or studio progress.",
            ],
            "Connect to Audience": [
                "I have not yet examined the communication of intent or external context.",
            ],
        },
        "1-2": {
            "Critique & Analyze": [
                "I can outline a basic response to the weekly inquiry question with minimal explanation.",
                "I can identify and name prominent visual elements or design strategies using fundamental art terms.",
            ],
            "Reflect on Growth": [
                "I can describe the progression of my studio work and identify the baseline skills used this week.",
                "I can state where I encountered operational obstacles or milestones in my production.",
            ],
            "Connect to Audience": [
                "I can identify the central theme or intended message of my artwork or the reference artwork.",
                "I can recognize that an audience may interpret a piece of art based on its apparent visual cues.",
            ],
        },
        "3-4": {
            "Critique & Analyze": [
                "I can explain my response to the inquiry question, supporting it with relevant observations from my work.",
                "I can describe how specific media, techniques, and formal elements are integrated to build a visual effect.",
            ],
            "Reflect on Growth": [
                "I can explain how my technical abilities and creative ideas developed through active studio experimentation.",
                "I can explain how specific feedback or technical limitations directly altered my planned workflow.",
            ],
            "Connect to Audience": [
                "I can analyze how specific creative mechanisms, styles, or compositions are designed to express an intent.",
                "I can describe how a viewer's background might influence their emotional or intellectual response to the work.",
            ],
        },
        "5-6": {
            "Critique & Analyze": [
                "I can analyze the inquiry question deeply, supporting my arguments with coherent, structured artistic evidence.",
                "I can critically analyze how artistic choices, formal elements, and historical or cultural contexts intersect in an artwork.",
            ],
            "Reflect on Growth": [
                "I can evaluate the effectiveness of my own choices, explaining how my studio practices align with my concept.",
                "I can critically evaluate my technical development, identifying clear, actionable paths to refine my skills.",
            ],
            "Connect to Audience": [
                "I can analyze how successfully an artwork communicates nuances to a targeted audience.",
                "I can evaluate the relationship between an artwork and its broader historical, social, political, or cultural environments.",
            ],
        },
        "7-8": {
            "Critique & Analyze": [
                "I can synthesize an insightful response to the inquiry question, demonstrating deep critical thinking and conceptual awareness.",
                "I can provide a sophisticated critique of an artwork, seamlessly utilizing high-level formal art terminology and concepts.",
            ],
            "Reflect on Growth": [
                "I can critically analyze my own creative evolution, justifying major conceptual shifts across my portfolio over time.",
                "I can synthesize self-appraisal, peer critique, and expert feedback to map out innovative, self-directed future studio projects.",
            ],
            "Connect to Audience": [
                "I can appraise and deconstruct how an artwork functions and communicates complex meaning from multiple ideological standpoints.",
                "I can justify a complex interpretation of an artwork, supporting it with sophisticated, cross-referenced aesthetic arguments.",
            ],
        },
    },
}

# MYP year (from the unit plan) -> rubric phase.
_YEAR_TO_PHASE = {
    "1": "7-8", "2": "7-8", "3": "7-8",
    "4": "9-10", "5": "9-10",
    "7": "7-8", "8": "7-8", "9": "9-10", "10": "9-10",
}


def phase_for_year(myp_year) -> str:
    """Map an MYP year (or grade) to a rubric phase; defaults to '7-8'."""
    if myp_year is None:
        return "7-8"
    return _YEAR_TO_PHASE.get(str(myp_year).strip(), "7-8")


def band_label(value: int) -> str:
    """Map a 0-8 band score to its rubric band range label."""
    if value <= 0:
        return "0"
    if value <= 2:
        return "1-2"
    if value <= 4:
        return "3-4"
    if value <= 6:
        return "5-6"
    return "7-8"


def rubric_options(phase: str) -> List[Tuple[str, str]]:
    """Return (label, statement) pairs for a phase, grouped by band/dimension.

    The label is a compact menu caption such as
    "[5-6 - Reflect] I can reflect on my design process...".
    """
    phase = phase if phase in RUBRIC_D else "7-8"
    options: List[Tuple[str, str]] = []
    short = {
        "Critique & Analyze": "Critique",
        "Reflect on Growth": "Reflect",
        "Connect to Audience": "Connect",
    }
    for band in BANDS:
        for dim in DIMENSIONS:
            for stmt in RUBRIC_D[phase][band][dim]:
                label = f"[{band} - {short[dim]}] {stmt}"
                options.append((label, stmt))
    return options
