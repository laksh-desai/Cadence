"""Template store: built-in overrides (with reset) + user-created custom templates.

Built-in outlines can be edited (saved as an override, leaving templates/*.md pristine) and
reset; custom templates are full files the user can create, duplicate, edit, and delete. Both
the forms-layer functions and the HTTP endpoints are exercised. Fully hermetic: OVERRIDES_DIR and
CUSTOM_DIR are redirected to a temp dir so the real templates/ tree is never touched, and the
global FORMS singleton is rebuilt from the pristine defaults in tearDown.

    .venv/Scripts/python.exe -m unittest tests.test_templates -v
"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.generate import forms
from app.ui import server


class _TempTemplatesBase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="cadence_tpl_"))
        self._orig_over, self._orig_custom = forms.OVERRIDES_DIR, forms.CUSTOM_DIR
        forms.OVERRIDES_DIR = self._tmp / "overrides"
        forms.CUSTOM_DIR = self._tmp / "custom"
        forms.reload_forms()  # start from pristine built-ins, no overrides/customs

    def tearDown(self):
        forms.OVERRIDES_DIR, forms.CUSTOM_DIR = self._orig_over, self._orig_custom
        forms.reload_forms()  # restore the process-wide FORMS singleton other tests rely on


class FormsLayerTests(_TempTemplatesBase):
    def test_builtins_present_and_pristine(self):
        self.assertEqual(len(forms.FORMS), len(forms.FORM_ORDER))
        self.assertTrue(forms.is_builtin("initial"))
        self.assertFalse(forms.is_custom("initial"))
        self.assertFalse(forms.is_customized("initial"))

    def test_edit_builtin_creates_override_and_reset_restores(self):
        default_spec = forms.FORMS["followup"].spec
        edited = forms.edit_template("followup", spec="Sections in order: Subjective; Objective.")
        self.assertIn("Subjective; Objective", edited.spec)
        self.assertTrue(forms.is_customized("followup"))
        self.assertTrue((forms.OVERRIDES_DIR / "followup.md").exists())
        # The shipped file is untouched — reload still sees the override, not the default.
        forms.reload_forms()
        self.assertIn("Subjective; Objective", forms.FORMS["followup"].spec)
        # Reset removes the override and restores the pristine outline.
        forms.reset_template("followup")
        self.assertFalse(forms.is_customized("followup"))
        self.assertEqual(forms.FORMS["followup"].spec, default_spec)

    def test_create_custom_template(self):
        f = forms.create_custom_template("Telehealth Check-in", "omit", "Sections in order: Subjective; Plan.")
        self.assertIn(f.id, forms.FORMS)
        self.assertTrue(f.id.startswith("custom-"))
        self.assertFalse(forms.is_builtin(f.id))
        self.assertTrue(forms.is_custom(f.id))
        self.assertEqual(f.mode, "omit")
        self.assertFalse(f.carry)

    def test_custom_is_never_carry_even_when_duplicated_from_carry_form(self):
        # followup carries forward; its copy must not (custom templates are non-carry in v1).
        self.assertTrue(forms.FORMS["followup"].carry)
        dup = forms.duplicate_template("followup")
        self.assertIsNotNone(dup)
        self.assertFalse(dup.carry)
        self.assertTrue(dup.name.endswith("(copy)"))
        # Duplicating carries the guided steps over so the copy keeps a guided walkthrough.
        self.assertEqual(len(dup.steps), len(forms.FORMS["followup"].steps))

    def test_edit_custom_rewrites_file_and_can_rename(self):
        f = forms.create_custom_template("Draft", "require", "Sections in order: A; B.")
        edited = forms.edit_template(f.id, spec="Sections in order: A; B; C.", name="Renamed", mode="omit")
        self.assertEqual(edited.name, "Renamed")
        self.assertEqual(edited.mode, "omit")
        self.assertIn("A; B; C", edited.spec)
        # Still a custom template, no override file created for it.
        self.assertTrue(forms.is_custom(f.id))
        self.assertFalse((forms.OVERRIDES_DIR / f"{f.id}.md").exists())

    def test_delete_custom_and_builtin_guard(self):
        f = forms.create_custom_template("Temp", "require", "Sections in order: A.")
        self.assertTrue(forms.delete_custom_template(f.id))
        self.assertNotIn(f.id, forms.FORMS)
        # A built-in can never be deleted through this path.
        self.assertFalse(forms.delete_custom_template("initial"))
        self.assertIn("initial", forms.FORMS)

    def test_ordered_form_ids_builtins_first_then_custom_alphabetical(self):
        forms.create_custom_template("Bravo", "require", "Sections in order: X.")
        forms.create_custom_template("Alpha", "require", "Sections in order: Y.")
        order = forms.ordered_form_ids()
        self.assertEqual(order[: len(forms.FORM_ORDER)], forms.FORM_ORDER)
        custom_names = [forms.FORMS[i].name for i in order[len(forms.FORM_ORDER):]]
        self.assertEqual(custom_names, ["Alpha", "Bravo"])


class TemplateEndpointTests(_TempTemplatesBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(server.app)  # no lifespan: template routes need no DB/model

    def test_list_forms_carries_spec_and_flags(self):
        r = self.client.get("/api/forms")
        self.assertEqual(r.status_code, 200)
        by_id = {f["id"]: f for f in r.json()}
        self.assertIn("initial_updated", by_id)
        self.assertTrue(by_id["initial_updated"]["spec"])
        self.assertTrue(by_id["initial_updated"]["builtin"])
        self.assertFalse(by_id["initial_updated"]["customized"])

    def test_create_edit_reset_builtin_via_http(self):
        r = self.client.put("/api/forms/followup/template", json={"spec": "Sections in order: S; O."})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["customized"])
        r2 = self.client.post("/api/forms/followup/template/reset")
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["customized"])

    def test_empty_outline_rejected(self):
        self.assertEqual(self.client.put("/api/forms/followup/template", json={"spec": "   "}).status_code, 400)
        self.assertEqual(
            self.client.post("/api/forms", json={"name": "X", "mode": "require", "spec": ""}).status_code, 400
        )

    def test_create_duplicate_delete_custom_via_http(self):
        created = self.client.post("/api/forms", json={"name": "Custom One", "mode": "omit", "spec": "Sections: A."})
        self.assertEqual(created.status_code, 201)
        cid = created.json()["id"]
        self.assertFalse(created.json()["builtin"])

        dup = self.client.post(f"/api/forms/{cid}/duplicate")
        self.assertEqual(dup.status_code, 201)
        self.assertNotEqual(dup.json()["id"], cid)

        # Built-ins cannot be deleted; custom ones can.
        self.assertEqual(self.client.delete("/api/forms/initial").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/forms/{cid}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/forms/{cid}/template").status_code, 404)

    def test_reset_rejected_for_custom(self):
        cid = self.client.post("/api/forms", json={"name": "C", "mode": "require", "spec": "Sections: A."}).json()["id"]
        self.assertEqual(self.client.post(f"/api/forms/{cid}/template/reset").status_code, 400)

    def test_bad_mode_rejected(self):
        self.assertEqual(
            self.client.post("/api/forms", json={"name": "C", "mode": "bogus", "spec": "Sections: A."}).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
