import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402


class BuildTest(unittest.TestCase):
    def setUp(self):
        resources, layout, templates = build.load()
        self.resources = copy.deepcopy(resources)
        self.layout = copy.deepcopy(layout)
        self.templates = dict(templates)

    def errors(self):
        return build.validate(self.resources, self.layout, self.templates)

    def resource(self, rid):
        return next(r for r in self.resources if r["id"] == rid)

    def assertError(self, fragment):
        errors = self.errors()
        self.assertTrue(any(fragment in e for e in errors), f"{fragment!r} not in {errors}")

    def test_repository_data_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_generated_guides_are_up_to_date(self):
        for locale, filename in build.OUTPUTS.items():
            expected = build.render(locale, self.resources, self.layout, self.templates)
            self.assertEqual(
                (ROOT / filename).read_text(encoding="utf-8"),
                expected,
                f"{filename} is stale; run python3 tools/build.py",
            )

    def test_missing_translation_is_rejected(self):
        del self.resource("asl-lex")["pt-BR"]
        self.assertError("missing pt-BR name")

    def test_untranslated_description_is_rejected(self):
        resource = self.resource("asl-lex")
        resource["pt-BR"]["description"] = resource["en"]["description"]
        self.assertError("identical to en")

    def test_resource_must_appear_in_every_guide(self):
        self.layout["pt-BR"][1]["subsections"][2]["ids"].remove("openasl")
        self.assertError("'openasl' is missing from this guide")

    def test_resource_cannot_be_listed_twice(self):
        self.layout["en"][0]["subsections"][0]["ids"].append("asl-connect")
        self.assertError("listed 2 times")

    def test_unknown_resource_id_is_rejected(self):
        self.layout["en"][0]["subsections"][0]["ids"].append("nope")
        self.assertError("unknown resource id 'nope'")

    def test_todo_placeholder_is_rejected_but_not_the_word_todos(self):
        resource = self.resource("asl-lex")
        resource["en"]["description"] = "TODO write this"
        self.assertError("contains TODO")
        resource["en"]["description"] = "Comunicação para TODOS"
        self.assertEqual(self.errors(), [])

    def test_http_url_needs_explicit_exception(self):
        resource = self.resource("asl-lex")
        resource["url"] = "http://asl-lex.org/"
        self.assertError("use https://")

    def test_duplicate_url_is_rejected(self):
        self.resource("openasl")["url"] = self.resource("asl-lex")["url"]
        self.assertError("duplicate url")

    def test_sign_language_must_be_named(self):
        self.resource("asl-lex")["languages"] = []
        self.assertError("name the sign language(s)")

    def test_unknown_language_code_is_rejected(self):
        self.resource("asl-lex")["languages"] = ["sgn"]
        self.assertError("unknown language code")

    def test_maintainer_is_required(self):
        self.resource("asl-lex")["maintainer"] = " "
        self.assertError("maintainer is required")

    def test_translation_tool_must_state_direction_and_output(self):
        self.resource("wikilibras")["translation"] = {"direction": "", "output": "magic"}
        self.assertError("must state their direction")
        self.assertError("translation output must be one of")

    def test_translation_tool_needs_limitations_note(self):
        libras = next(s for s in self.layout["en"] if s["title"] == "Libras resources")
        software = next(sub for sub in libras["subsections"] if "vlibras-suite" in sub["ids"])
        del software["after"]
        self.assertError("has no limitations note")

    def test_templates_must_keep_structure_in_sync(self):
        self.templates["pt-BR"] = self.templates["pt-BR"].replace(
            "- Evidências de qualidade", "- Evidências de qualidade\n- Extra item"
        )
        self.assertError("bullet count")

    def test_template_needs_placeholders(self):
        self.templates["en"] = self.templates["en"].replace("<!-- resources -->", "")
        self.assertError("exactly one <!-- resources -->")

    def test_slug_matches_github_anchors(self):
        self.assertEqual(build.slug("Learning and teaching"), "learning-and-teaching")
        self.assertEqual(build.slug("Ferramentas gerais de pesquisa"), "ferramentas-gerais-de-pesquisa")


if __name__ == "__main__":
    unittest.main()
