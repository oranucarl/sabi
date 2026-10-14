"""Tests for the platform-neutral pieces. Run with: python -m pytest tests"""

from pathlib import Path

from sabi.ai import prompt
from sabi.language import LANGUAGES, PIDGIN, LanguageTracker, looks_like_pidgin, requested_switch
from sabi.learning import pathways
from sabi.learning.journal import DAY, Card, Journal, sm2
from sabi.learning.library import Library
from sabi.platform.macos.screens import Shot
from sabi import intents


def test_parse_point_and_steps():
    raw = "Here is how.\n1. Click File.\n2. Choose Export.\n[POINT:640,40:File menu]\n[TOPIC:mathematics]"
    reply = prompt.parse(raw)
    assert reply.point == (640.0, 40.0, "File menu")
    assert reply.steps == ["Click File.", "Choose Export."]
    assert "[" not in reply.text


def test_visible_holds_back_partial_tags():
    assert prompt.visible("Look here [POI") == "Look here"
    assert prompt.visible("Done. [POINT:1,2:x] More") == "Done.  More"


def test_uncited_markers_are_removed():
    assert prompt.strip_citations("Plants are green [1]. Chlorophyll [1, 2] absorbs light.") == (
        "Plants are green. Chlorophyll absorbs light."
    )


def test_classification_cleanup():
    assert pathways.clean_classification({"subject": "General", "topic": "greeting"}) == ("", "")
    assert pathways.clean_classification({"subject": "Physics", "topic": "Waves"}) == ("Physics", "Waves")
    assert "Quadratic equations" in pathways.classify_prompt("q", "a")


def test_language_rule_is_last_and_reminded():
    system = prompt.build_system(prompt.PromptContext(lang=LANGUAGES[PIDGIN], image_size=(1280, 800)))
    assert system.rstrip().endswith("button names in English.")
    assert prompt.user_turn("what is this", LANGUAGES[PIDGIN]).endswith("(Answer in Nigerian Pidgin.)")
    assert prompt.user_turn("what is this", LANGUAGES["en"]) == "what is this"


def test_shot_maps_image_pixels_to_screen_points():
    shot = Shot("", left=1512, top=0, width=1920, height=1080, image_width=1280, image_height=720)
    assert shot.to_screen(640, 360) == (1512 + 960, 540)
    assert shot.to_screen(5000, -10) == (1512 + 1920, 0)


def test_sm2_progression_and_reset():
    card = Card("Quadratic equations", "Mathematics", 2.5, 0, 0, 0, "")
    card = sm2(card, 5, 0)
    assert card.interval_days == 1
    card = sm2(card, 4, 0)
    assert card.interval_days == 6
    card = sm2(card, 5, 0)
    assert card.interval_days >= 15
    card = sm2(card, 1, 0)
    assert card.reps == 0 and card.interval_days == 1 and card.ease >= 1.3


def test_pidgin_detection_and_switching():
    assert looks_like_pidgin("Abeg wetin dey happen for this formula")
    assert not looks_like_pidgin("What is a quadratic equation")
    assert requested_switch("abeg talk pidgin") == PIDGIN
    assert requested_switch("please explain it in French") == "fr"


def test_language_change_needs_two_turns():
    t = LanguageTracker()
    assert t.update("what is this", "fr").code == "en"
    assert t.update("qu'est-ce que c'est", "fr").code == "fr"


def test_short_commands_need_short_audio():
    assert intents.is_next("Next.", 1.0)
    assert not intents.is_next("Next.", 6.0)
    assert intents.is_pathways("So what should I learn next?")
    assert intents.is_quiz("abeg quiz me")
    assert intents.is_sensitive("Safari", "GTBank Internet Banking")


def test_pathways_suggest_following_syllabus_topics(tmp_path: Path):
    j = Journal(tmp_path / "j.db")
    j.log("Preview", "how do I solve x^2+5x+6=0", "...", "Mathematics", "Quadratic equations", "en", "[]")
    paths = pathways.build(j.mastery())
    assert paths[0].subject == "Mathematics"
    assert paths[0].next_topics[0] == "Variation"
    assert any("jamb" in o["url"] for o in paths[0].opportunities)
    md = pathways.as_markdown(paths)
    assert "Learn next" in md and "https://" in md


def test_catalog_references_resolve():
    cat = pathways.catalog()
    for subject in cat["subjects"].values():
        for r in subject["resources"]:
            assert r in cat["resources"]
        for o in subject["opportunities"]:
            assert o in cat["opportunities"]


def test_library_keyword_search_cites_page(tmp_path: Path):
    notes = tmp_path / "Physics notes.txt"
    notes.write_text("Newton's second law says force equals mass times acceleration. " * 3)
    lib = Library(tmp_path / "l.db", embed=None)
    assert lib.add(notes) >= 1
    hits = lib.search("what is newton's second law about force")
    assert hits and hits[0].title == "Physics notes" and hits[0].number == 1


def test_all_languages_have_voices():
    for lang in LANGUAGES.values():
        assert lang.edge_voice and lang.say_voice
