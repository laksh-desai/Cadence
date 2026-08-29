"""Tests for the over-long-dictation condensing scaffolding (app/generate/chunked.py, rule 16).

The deterministic parts (token estimate, sentence-boundary chunking, the budget decision) are tested
directly; the two-pass orchestration is tested with a stub generator so no real model is needed.
The load-bearing guarantee: a normal-length dictation is returned UNCHANGED with no model call, so
condensing never touches the normal path.

    .venv/Scripts/python.exe -m unittest tests.test_chunked -v
"""

import asyncio
import unittest

from app.generate import chunked


class _StubGen:
    """Async prompt -> text stub standing in for the Ollama condense call."""

    def __init__(self, fn):
        self.calls = []
        self.fn = fn

    async def __call__(self, prompt):
        self.calls.append(prompt)
        return self.fn(prompt)


class EstimateTests(unittest.TestCase):
    def test_estimate_is_chars_over_four(self):
        self.assertEqual(chunked.estimate_tokens("a" * 40), 10)

    def test_estimate_handles_empty_and_none(self):
        self.assertEqual(chunked.estimate_tokens(""), 0)
        self.assertEqual(chunked.estimate_tokens(None), 0)


class SplitTests(unittest.TestCase):
    def test_empty_is_no_chunks(self):
        self.assertEqual(chunked.split_into_chunks(""), [])

    def test_single_sentence_one_chunk(self):
        self.assertEqual(chunked.split_into_chunks("One sentence here."), ["One sentence here."])

    def test_splits_at_sentence_boundaries_by_budget(self):
        text = "Aaaa bbbb cccc dddd. Eeee ffff gggg hhhh. Iiii jjjj kkkk llll."
        chunks = chunked.split_into_chunks(text, max_chunk_tokens=5)  # ~5 tokens per sentence
        self.assertEqual(len(chunks), 3)
        self.assertEqual(" ".join(chunks), text)  # no content lost or reordered

    def test_oversized_single_sentence_kept_whole(self):
        big = ("word " * 100).strip() + "."  # one sentence far over the limit
        chunks = chunked.split_into_chunks(big, max_chunk_tokens=5)
        self.assertEqual(chunks, [big])  # never cut mid-clause


class FitDictationTests(unittest.TestCase):
    # An overhead that leaves a 2-token budget, so anything longer than ~8 chars condenses.
    TINY_BUDGET_OVERHEAD = chunked.NUM_CTX - chunked.NUM_PREDICT - 2

    def test_short_dictation_unchanged_and_no_model_call(self):
        gen = _StubGen(lambda p: "SHOULD-NOT-BE-CALLED")
        text, condensed, over = asyncio.run(chunked.fit_dictation("Short note.", 0, gen))
        self.assertEqual(text, "Short note.")
        self.assertFalse(condensed)
        self.assertFalse(over)
        self.assertEqual(gen.calls, [])  # the normal path makes no extra call

    def test_long_dictation_is_condensed(self):
        gen = _StubGen(lambda p: "CONDENSED")
        long = "Sentence one is here. Sentence two is here. Sentence three is here."
        text, condensed, over = asyncio.run(chunked.fit_dictation(long, self.TINY_BUDGET_OVERHEAD, gen, enabled=True))
        self.assertTrue(condensed)
        self.assertGreaterEqual(len(gen.calls), 1)
        self.assertIn("CONDENSED", text)

    def test_condense_prompt_carries_the_chunk_text(self):
        gen = _StubGen(lambda p: "ok")
        asyncio.run(chunked.fit_dictation("Patient walked a long way today and more.", self.TINY_BUDGET_OVERHEAD, gen, enabled=True))
        self.assertIn("Patient walked a long way today", gen.calls[0])

    def test_still_over_true_when_condense_does_not_shrink_enough(self):
        gen = _StubGen(lambda p: "x" * 400)  # condensed output still large
        _, condensed, over = asyncio.run(chunked.fit_dictation("a" * 400, self.TINY_BUDGET_OVERHEAD, gen, enabled=True))
        self.assertTrue(condensed)
        self.assertTrue(over)

    def test_still_over_false_when_condense_shrinks_below_budget(self):
        gen = _StubGen(lambda p: "tiny")
        _, condensed, over = asyncio.run(chunked.fit_dictation("a" * 400 + ".", self.TINY_BUDGET_OVERHEAD, gen, enabled=True))
        self.assertTrue(condensed)
        self.assertFalse(over)

    def test_over_budget_is_NOT_condensed_by_default(self):
        """The default changed after the A/B (CLAUDE.md rule 16): condensing lost to plain
        truncation 18/78 vs 59/78, and its second attempt FABRICATED — five specific dictated
        goals came back as five generic invented ones, which no verification layer can catch
        because the note ends up with fewer values rather than invented ones. Truncation loses
        the tail VISIBLY and cannot invent, so it is the better failure."""
        gen = _StubGen(lambda p: "SHOULD-NOT-BE-CALLED")
        long = "Sentence one is here. Sentence two is here. Sentence three is here."
        text, condensed, over = asyncio.run(chunked.fit_dictation(long, self.TINY_BUDGET_OVERHEAD, gen))
        self.assertEqual(text, long, "the raw dictation must be passed through untouched")
        self.assertFalse(condensed)
        self.assertTrue(over, "still_over must be True so the caller warns the clinician")
        self.assertEqual(gen.calls, [], "no second model call may run on clinical content")

    def test_empty_condense_falls_back_to_raw_dictation(self):
        # Model returns nothing for every chunk -> must NOT feed an empty dictation to generation.
        gen = _StubGen(lambda p: "")
        text, condensed, over = asyncio.run(chunked.fit_dictation("A long dictation here.", self.TINY_BUDGET_OVERHEAD, gen, enabled=True))
        self.assertEqual(text, "A long dictation here.")  # fell back to the raw dictation
        self.assertTrue(condensed)                         # still flagged so the clinician is warned
        self.assertTrue(over)


if __name__ == "__main__":
    unittest.main()
