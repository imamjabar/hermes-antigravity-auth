from __future__ import annotations

import unittest

from antigravity_auth.transform.envelope import build_antigravity_envelope
from antigravity_auth.transform.prompt_guard import (
  SYSTEM_INSTRUCTION_REWRITES,
  sanitize_antigravity_envelope,
  sanitize_system_instruction,
  sanitize_system_instruction_text,
)


# Verbatim fragments of Hermes' system prompt (agent/prompt_builder.py). The
# Antigravity backend answers each of them with 429 RESOURCE_EXHAUSTED.
HERMES_PROMPT = (
  "# Finishing the job\n"
  "When the user asks you to build, run, or verify something, the deliverable is a working artifact backed by real "
  "tool output — not a description of one. Do not stop after writing a stub, a plan, or a single command.\n"
  "Reporting a blocker honestly is always better than inventing a result.\n"
  "\n"
  "## Mid-turn user steering\n"
  "Mid-turn, the user can steer you: Hermes delivers their message as a standalone user message right after "
  "the latest tool results, wrapped exactly as:\n"
  "\n"
  "# Google model operational directives\n"
  "Follow these operational rules strictly:\n"
  "\n"
  "# Hermes runtime environment\n"
  "cwd=/srv/app\n"
  "<!-- End Hermes runtime environment -->\n"
)


class TestSanitizeText(unittest.TestCase):
  def test_rewrites_every_blocked_phrase(self):
    sanitized = sanitize_system_instruction_text(HERMES_PROMPT)
    for blocked, replacement in SYSTEM_INSTRUCTION_REWRITES:
      self.assertNotIn(blocked, sanitized)
      self.assertIn(replacement, sanitized)

  def test_keeps_instruction_meaning(self):
    sanitized = sanitize_system_instruction_text(HERMES_PROMPT)
    self.assertIn("the deliverable must be a working artifact", sanitized)
    self.assertIn("Reporting a blocker honestly always beats inventing a result.", sanitized)
    self.assertIn("immediately after the latest tool results", sanitized)
    self.assertIn("# Model operational directives", sanitized)
    self.assertIn("<!-- End runtime environment -->", sanitized)
    self.assertIn("# Finishing the job", sanitized)
    self.assertIn("cwd=/srv/app", sanitized)

  def test_idempotent(self):
    once = sanitize_system_instruction_text(HERMES_PROMPT)
    self.assertEqual(once, sanitize_system_instruction_text(once))

  def test_leaves_unrelated_prompt_untouched(self):
    text = "You are a helpful assistant.\nUse absolute paths."
    self.assertIs(text, sanitize_system_instruction_text(text))

  def test_empty_text(self):
    self.assertEqual(sanitize_system_instruction_text(""), "")


class TestSanitizeSystemInstruction(unittest.TestCase):
  def test_parts_shape(self):
    si = {"role": "user", "parts": [{"text": HERMES_PROMPT}]}
    out = sanitize_system_instruction(si)
    self.assertNotIn("the deliverable is a working artifact backed by real tool output",
                     out["parts"][0]["text"])
    self.assertEqual(out["role"], "user")
    self.assertIn("the deliverable is a working artifact backed by real tool output",
                  si["parts"][0]["text"], "input must not be mutated")

  def test_string_shape(self):
    out = sanitize_system_instruction(HERMES_PROMPT)
    self.assertIsInstance(out, str)
    self.assertNotIn("# Google model operational directives", out)

  def test_multi_part_shape(self):
    si = {"parts": [{"text": "keep me"}, {"text": HERMES_PROMPT}, {"inlineData": {"mimeType": "x"}}]}
    out = sanitize_system_instruction(si)
    self.assertEqual(out["parts"][0]["text"], "keep me")
    self.assertIn({"inlineData": {"mimeType": "x"}}, out["parts"])
    self.assertNotIn("<!-- End Hermes runtime environment -->", out["parts"][1]["text"])

  def test_absent_parts_returned_unchanged(self):
    si = {"role": "user"}
    self.assertEqual(sanitize_system_instruction(si), si)


class TestSanitizeEnvelope(unittest.TestCase):
  def test_envelope_reports_change(self):
    envelope = {"request": {"systemInstruction": {"parts": [{"text": HERMES_PROMPT}]}}}
    self.assertTrue(sanitize_antigravity_envelope(envelope))
    self.assertNotIn(
      "the deliverable is a working artifact backed by real tool output",
      envelope["request"]["systemInstruction"]["parts"][0]["text"],
    )

  def test_envelope_reports_no_change(self):
    envelope = {"request": {"systemInstruction": {"parts": [{"text": "plain"}]}}}
    self.assertFalse(sanitize_antigravity_envelope(envelope))

  def test_snake_case_field(self):
    envelope = {"request": {"system_instruction": HERMES_PROMPT}}
    self.assertTrue(sanitize_antigravity_envelope(envelope))
    self.assertNotIn("# Google model operational directives", envelope["request"]["system_instruction"])

  def test_build_antigravity_envelope_sanitizes_outgoing_prompt(self):
    envelope = build_antigravity_envelope(
      {"systemInstruction": {"parts": [{"text": HERMES_PROMPT}]},
       "contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
      model="gemini-3.8-flash-high",
      project_id="demo-project",
    )
    text = envelope["request"]["systemInstruction"]["parts"][0]["text"]
    for blocked, _ in SYSTEM_INSTRUCTION_REWRITES:
      self.assertNotIn(blocked, text)
    self.assertIn("# Finishing the job", text)


if __name__ == "__main__":
  unittest.main()
