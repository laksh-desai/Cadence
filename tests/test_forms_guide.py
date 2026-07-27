"""Tests for the per-form guided-dictation walkthrough.

Each template (templates/*.md) carries a `steps:` list in its frontmatter — an
ordered, section-by-section walkthrough (label + concrete example + optional flag)
that the UI's Guided dictation mode reads so the clinician doesn't have to have
every form memorized. Two things must stay true and are easy to break by accident:

  1. Every form actually has a usable walkthrough (a template edit that drops or
     malforms the list would silently leave that note type with no guided mode).
  2. The walkthrough is a DICTATION AID ONLY — it must never leak into the
     generation prompt, or it would start steering (and potentially contaminating)
     the model's output. `build_prompt` uses `form.spec`, never `form.steps`; this
     locks that in.

Pure functions -- no DB, no model, no server lifespan.

    .venv/Scripts/python.exe -m unittest tests.test_forms_guide -v
"""

import asyncio
import unittest

from app.generate.forms import FORM_ORDER, load_forms
from app.generate.prompt import PatientContext, build_prompt, render_prior_block
from app.ui.schemas import FormOut


FORMS = load_forms()


class StepMetadataTests(unittest.TestCase):
    def test_every_form_has_a_walkthrough(self):
        for fid in FORM_ORDER:
            with self.subTest(form=fid):
                steps = FORMS[fid].steps
                self.assertTrue(steps, f"{fid} has no guided steps")
                self.assertGreaterEqual(len(steps), 2, f"{fid} walkthrough is suspiciously short")

    def test_steps_are_clean(self):
        for fid in FORM_ORDER:
            for i, step in enumerate(FORMS[fid].steps):
                with self.subTest(form=fid, step=i):
                    self.assertIsInstance(step.label, str)
                    self.assertIsInstance(step.example, str)
                    self.assertIsInstance(step.optional, bool)
                    self.assertEqual(step.label, step.label.strip(), "label has stray whitespace")
                    self.assertEqual(step.example, step.example.strip(), "example has stray whitespace")
                    self.assertTrue(4 <= len(step.label) <= 120, f"label length off: {step.label!r}")
                    self.assertTrue(10 <= len(step.example) <= 240, f"example length off: {step.example!r}")

    def test_steps_default_to_empty_tuple_when_absent(self):
        # FormSpec defaults steps to () -- a form missing the key must degrade to no
        # guided mode, not raise, so the UI simply hides the Guided toggle.
        from app.generate.forms import FormSpec
        bare = FormSpec(id="x", name="X", mode="omit", carry=False, spec="body")
        self.assertEqual(bare.steps, ())


class StepsDoNotLeakIntoPromptTests(unittest.TestCase):
    """The load-bearing safety test: walkthrough text must not reach the model."""

    def _prompt_for(self, fid):
        form = FORMS[fid]
        prior_block = render_prior_block(form, None, False)
        ctx = PatientContext(name="Test Patient", sub="condition")
        return build_prompt(form, ctx, "did some therapy today", prior_block, None)

    def test_no_step_text_appears_in_any_prompt(self):
        for fid in FORM_ORDER:
            prompt = self._prompt_for(fid)
            for step in FORMS[fid].steps:
                with self.subTest(form=fid, label=step.label):
                    self.assertNotIn(step.example, prompt, f"step example leaked into {fid} prompt")

    def test_prompt_still_contains_the_real_spec(self):
        # Sanity check the negative test above isn't passing just because the prompt
        # is empty/broken: the actual note structure must still be present.
        for fid in FORM_ORDER:
            prompt = self._prompt_for(fid)
            with self.subTest(form=fid):
                self.assertIn(FORMS[fid].spec[:40], prompt)


class StepsReachApiTests(unittest.TestCase):
    def test_list_forms_serializes_steps(self):
        # Call the endpoint coroutine directly -- it only reads the FORMS singleton,
        # so no app lifespan / MedASR / DB startup is needed.
        from app.ui.server import list_forms

        forms = asyncio.run(list_forms())
        self.assertEqual(len(forms), len(FORM_ORDER))
        for f in forms:
            with self.subTest(form=f.id):
                self.assertIsInstance(f, FormOut)
                self.assertEqual(len(f.steps), len(FORMS[f.id].steps))
                self.assertTrue(f.steps)
                for out, src in zip(f.steps, FORMS[f.id].steps):
                    self.assertEqual(out.label, src.label)
                    self.assertEqual(out.example, src.example)
                    self.assertEqual(out.optional, src.optional)

    def test_formout_steps_survive_json_roundtrip(self):
        from app.ui.schemas import FormStep

        f = FORMS["followup"]
        out = FormOut(
            id=f.id, name=f.name, mode=f.mode, carry=f.carry,
            steps=[FormStep(label=s.label, example=s.example, optional=s.optional) for s in f.steps],
        )
        dumped = out.model_dump()
        self.assertIn("steps", dumped)
        self.assertEqual(len(dumped["steps"]), len(f.steps))
        self.assertEqual(dumped["steps"][0]["label"], f.steps[0].label)


if __name__ == "__main__":
    unittest.main()
