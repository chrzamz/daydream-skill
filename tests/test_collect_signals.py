"""Synthetic-only fixtures: never inspect actual accounts, chats, or notes."""

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / "skills/daydream/scripts/collect_signals.py"
SPEC = importlib.util.spec_from_file_location("collect_signals", SCRIPT)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
NOW = datetime(2030, 6, 30, tzinfo=timezone.utc)
RECENT = "2030-06-29T12:00:00Z"


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_jsonl(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                        encoding="utf-8")
        return path

    def write_text(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_collect(self, kind, path, **kwargs):
        return collector.collect([(kind, path)], now=NOW, **kwargs)

    def claude(self, text, **extra):
        return dict({"type": "user", "sessionId": "synthetic-session",
                     "timestamp": RECENT, "message": {"role": "user", "content": text}}, **extra)

    def codex(self, text, stamp=RECENT, variant="response", role="user"):
        if variant == "response":
            return {"type": "response_item", "timestamp": stamp,
                    "payload": {"type": "message", "role": role,
                                "content": [{"type": "input_text", "text": text}]}}
        return {"type": "event_msg", "timestamp": stamp,
                "payload": {"type": "user_message" if role == "user" else "agent_message",
                            "message": text}}

    def generic(self, text, **extra):
        return dict({"role": "user", "timestamp": RECENT, "text": text}, **extra)

    def test_claude_keeps_real_text_and_ignores_tool_results_meta_and_sidechains(self):
        path = self.write_jsonl("chat.jsonl", [
            self.claude("A real idea", uuid="human-one"),
            self.claude([{"type": "tool_result", "content": "not a human idea"}]),
            self.claude([{"type": "text", "text": "Another idea"},
                         {"type": "image", "source": {"data": "not text"}}]),
            self.claude("a subagent request", isSidechain=True),
            self.claude("injected context", isMeta=True),
            self.claude("internal dispatch", origin={"kind": "agent"}),
            self.claude("This session is being continued from a previous conversation. Summary..."),
            {"type": "progress", "message": "progress"},
        ])
        report = self.run_collect("claude", path)
        self.assertEqual({r["text"] for r in report["records"]}, {"A real idea", "Another idea"})
        self.assertTrue(all(r["locator"].endswith((":1", ":3")) for r in report["records"]))

    def test_mixed_context_blocks_preserve_human_text(self):
        text = ("<environment_context>workspace metadata</environment_context>\n"
                "I want a playful way to connect ideas.\n"
                "<system-reminder>generated instructions</system-reminder>")
        path = self.write_jsonl("mixed.jsonl", [self.codex(text), self.claude([
            {"type": "text", "text": "<system-reminder>injected</system-reminder>"},
            {"type": "text", "text": "Keep this actual question."},
        ])])
        codex = self.run_collect("codex", path)
        claude = self.run_collect("claude", path)
        self.assertEqual(codex["records"][0]["text"], "I want a playful way to connect ideas.")
        self.assertEqual(claude["records"][0]["text"], "Keep this actual question.")

    def test_agents_header_and_environment_only_records_are_empty(self):
        path = self.write_jsonl("context.jsonl", [self.codex(
            "# AGENTS.md instructions for /synthetic\n<INSTRUCTIONS>rules</INSTRUCTIONS>\n"
            "<environment_context>context</environment_context>"
        ), self.codex("An actual idea", stamp="2030-06-29T12:01:00Z")])
        self.assertEqual([r["text"] for r in self.run_collect("codex", path)["records"]],
                         ["An actual idea"])

    def test_codex_mirrors_are_deduplicated_without_removing_later_real_repetition(self):
        path = self.write_jsonl("rollout.jsonl", [
            {"type": "session_meta", "payload": {"id": "synthetic-session", "source": "cli"}},
            self.codex("Continue", variant="event"),
            self.codex("Continue", stamp="2030-06-29T12:00:00.500Z"),
            self.codex("Continue", stamp="2030-06-29T13:00:00Z", variant="event"),
            self.codex("Continue", stamp="2030-06-29T13:00:00.500Z"),
        ])
        report = self.run_collect("codex", path)
        self.assertEqual(len(report["records"]), 2)
        self.assertEqual(report["summary"]["counts"]["duplicate_records_skipped"], 2)

    def test_identical_records_without_ids_are_deduplicated(self):
        path = self.write_jsonl("export.jsonl", [self.generic("same"), self.generic("same")])
        self.assertEqual(len(self.run_collect("json", path)["records"]), 1)

    def test_codex_subagent_session_is_excluded(self):
        path = self.write_jsonl("subagent.jsonl", [
            {"type": "session_meta", "payload": {"source": {"subagent": {"thread_spawn": {}}}}},
            self.codex("Agent-generated task"),
        ])
        self.assertEqual(self.run_collect("codex", path)["records"], [])

    def test_assistant_opt_in_preserves_status_evidence(self):
        path = self.write_jsonl("status.jsonl", [self.generic("Cancelled this idea", role="assistant",
                                                           id="result", status="cancelled")])
        self.assertEqual(self.run_collect("json", path)["records"], [])
        record = self.run_collect("json", path, include_assistant=True)["records"][0]
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(record["role"], "assistant")

    def test_source_role_from_optional_export_is_preserved(self):
        path = self.write_text("apple-export.json", json.dumps({"records": [
            self.generic("A source idea", role="source", status="pending")
        ], "summary": {"synthetic": True}}))
        record = self.run_collect("json", path)["records"][0]
        self.assertEqual(record["role"], "source")
        self.assertEqual(record["status"], "pending")

    def test_assistant_codex_event_and_response_mirrors(self):
        path = self.write_jsonl("assistant.jsonl", [
            self.codex("Completed the draft", role="assistant", variant="event"),
            self.codex("Completed the draft", role="assistant"),
        ])
        self.assertEqual(len(self.run_collect("codex", path, include_assistant=True)["records"]), 1)

    def test_message_date_not_file_mtime_controls_recency(self):
        path = self.write_jsonl("old.jsonl", [self.generic("old idea", timestamp="2020-01-01T00:00:00Z")])
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
        self.assertEqual(self.run_collect("json", path)["records"], [])
        self.assertEqual(len(self.run_collect("json", path, days=0)["records"]), 1)

    def test_undated_and_invalid_dates_require_days_zero(self):
        path = self.write_jsonl("undated.jsonl", [self.generic("unknown", timestamp=None),
                                                self.generic("invalid", timestamp="not a date")])
        self.assertEqual(self.run_collect("json", path)["records"], [])
        records = self.run_collect("json", path, days=0)["records"]
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["timestamp"] is None for r in records))

    def test_timezone_and_epoch_timestamps(self):
        path = self.write_jsonl("dates.jsonl", [
            self.generic("offset", timestamp="2030-06-29T20:00:00+08:00"),
            self.generic("epoch", timestamp=1908964800000),
        ])
        records = self.run_collect("json", path, days=0)["records"]
        self.assertEqual(next(r for r in records if r["text"] == "offset")["timestamp"], RECENT)
        self.assertTrue(all(r["timestamp"].endswith("Z") for r in records))

    def test_limit_is_applied_after_latest_selection_and_id_dedup(self):
        path = self.write_jsonl("unordered.jsonl", [
            self.generic("old a", id="a", timestamp="2030-06-20T00:00:00Z"),
            self.generic("middle b", id="b", timestamp="2030-06-25T00:00:00Z"),
            self.generic("new a", id="a", timestamp="2030-06-29T00:00:00Z"),
            self.generic("older c", id="c", timestamp="2030-06-21T00:00:00Z"),
        ])
        records = self.run_collect("json", path, limit=2)["records"]
        self.assertEqual([r["text"] for r in records], ["new a", "middle b"])

    def test_markdown_uses_explicit_edit_time_without_claiming_message_time(self):
        path = self.write_text("idea.md", "# A little idea\nConnect two hobbies.")
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
        record = self.run_collect("markdown", path)["records"][0]
        self.assertEqual(record["role"], "source")
        self.assertIsNone(record["timestamp"])
        self.assertEqual(record["modified_at"], "2030-06-30T00:00:00Z")
        os.utime(path, (0, 0))
        self.assertEqual(self.run_collect("markdown", path)["records"], [])

    def test_secret_checks_before_truncation_drop_whole_record(self):
        synthetic_token = "sk-proj-" + "A1" * 20
        path = self.write_jsonl("safe-title.jsonl", [
            self.generic("Harmless beginning " * 200 + synthetic_token),
            self.generic("Allowed idea"),
        ])
        report = self.run_collect("json", path, max_chars=7)
        self.assertEqual([r["text"] for r in report["records"]], ["Allowed"])
        self.assertNotIn(synthetic_token, json.dumps(report))

    def test_multiline_credentials_and_common_tokens_are_rejected(self):
        examples = [
            "password:\nfictional-sensitive-value",
            "api_key =\nfictional-sensitive-value",
            "AppSecret\nfictional-sensitive-value",
            "密码：\n虚构测试内容",
            "密钥\n虚构测试内容",
            "API Key is fictional-sensitive-value",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic\n-----END OPENSSH PRIVATE KEY-----",
            "ghp_" + "a" * 36,
            "github_pat_" + "b" * 30,
            "glpat-" + "c" * 20,
            "xoxb-" + "1" * 24,
            "AKIA" + "Z" * 16,
            "Bearer " + "d" * 30,
            "https://synthetic:fictional-sensitive-value@example.invalid",
        ]
        for text in examples:
            with self.subTest(example=text.splitlines()[0][:25]):
                self.assertTrue(collector.contains_secret(text))
        self.assertFalse(collector.contains_secret("How could a password manager feel simpler?"))

    def test_secret_titles_and_metadata_are_rejected(self):
        path = self.write_jsonl("export.jsonl", [
            self.generic("innocent body", title="服务器账号密码"),
            self.generic("another body", api_key="fictional-sensitive-value"),
            self.generic("# API credentials\njust a heading"),
            self.generic("keep this"),
        ])
        self.assertEqual([r["text"] for r in self.run_collect("json", path)["records"]], ["keep this"])

    def test_shared_secret_check_handles_json_serialized_multiline_values(self):
        for text in ("A harmless opening\nAPI_KEY=fictional-value",
                     "A harmless opening\nAppSecret\nfictional-value",
                     "A harmless opening\n密码：\n虚构测试内容"):
            with self.subTest(text=text.splitlines()[1]):
                self.assertTrue(collector.contains_secret(json.dumps({"text": text}, ensure_ascii=False)))

    def test_public_record_secret_check_handles_nested_titles_and_text_blocks(self):
        for record in ({"metadata": {"title": "Private keys"}},
                       {"title": "key", "text": "synthetic"},
                       {"content": [{"type": "text", "text": "API Key"},
                                    {"type": "text", "text": "synthetic-value"}]}):
            with self.subTest(record=record):
                self.assertTrue(collector.record_contains_secret(record))

    def test_space_separated_appsecret_resend_and_bare_credential_titles(self):
        examples = ["AppSecret " + "SYNTHETIC_" * 4,
                    "api_key " + "SYNTHETIC_" * 4,
                    "Here is a fixture: re_" + "synthetic0123456789" * 2,
                    "sk_test_" + "synthetic0123456789" * 2]
        path = self.write_jsonl("notes-export.jsonl", [self.generic(text) for text in examples] + [
            self.generic("fictional body", title="Key"),
            self.generic("fictional body", title="Secrets"),
            self.generic("An ordinary creative seed"),
        ])
        self.assertEqual([r["text"] for r in self.run_collect("json", path)["records"]],
                         ["An ordinary creative seed"])

    def test_secret_in_removed_context_still_rejects_whole_record(self):
        path = self.write_jsonl("mixed-secret.jsonl", [self.claude(
            "Actual idea\n<system-reminder>password:\nsynthetic-secret</system-reminder>"
        )])
        self.assertEqual(self.run_collect("claude", path)["records"], [])

    def test_sensitive_paths_are_not_opened_but_topic_names_are_allowed(self):
        for folder in (".git", ".jj", "node_modules", ".secrets", "auth", "config", "subagents"):
            self.write_jsonl(folder + "/chat.jsonl", [self.generic("excluded folder")])
        for name in (".env", ".env.local", "auth.json", "config.json", "credentials.json"):
            self.write_text(name, json.dumps(self.generic("excluded file")))
        self.write_jsonl("configuration-ideas.jsonl", [self.generic("configuration idea")])
        self.write_jsonl("authoring.jsonl", [self.generic("authoring idea")])
        records = self.run_collect("json", self.root)["records"]
        self.assertEqual({r["text"] for r in records}, {"configuration idea", "authoring idea"})

    def test_explicit_sensitive_file_is_skipped(self):
        path = self.write_text("auth.json", json.dumps(self.generic("excluded")))
        self.assertEqual(self.run_collect("json", path)["records"], [])

    def test_symlinks_cannot_escape_selected_root(self):
        selected = self.root / "selected"
        selected.mkdir()
        outside = self.write_jsonl("outside/chat.jsonl", [self.generic("outside scope")])
        (selected / "linked.jsonl").symlink_to(outside)
        (selected / "linked-directory").symlink_to(outside.parent, target_is_directory=True)
        path = self.write_jsonl("selected/real.jsonl", [self.generic("inside scope")])
        self.assertEqual([r["text"] for r in self.run_collect("json", selected)["records"]], ["inside scope"])
        self.assertEqual(self.run_collect("json", selected / "linked-directory")["records"], [])
        self.assertTrue(path.exists())

    def test_json_arrays_and_wrapped_records_have_real_line_locators(self):
        array = self.write_text("array.json", '[\n  {"text":"one","timestamp":"' + RECENT + '"},\n'
                               '  {"text":"two","timestamp":"' + RECENT + '"}\n]')
        wrapped = self.write_text("wrapper.json", '{\n "label": "synthetic",\n "records": [\n'
                                 '  {"text":"three","timestamp":"' + RECENT + '"}\n ]\n}')
        records = self.run_collect("json", array)["records"]
        self.assertEqual({r["locator"].rsplit(":", 1)[1] for r in records}, {"2", "3"})
        self.assertTrue(self.run_collect("json", wrapped)["records"][0]["locator"].endswith(":4"))

    def test_invalid_json_errors_do_not_echo_content(self):
        path = self.write_text("broken.jsonl", '{"password": "synthetic-private-fragment"\n')
        report = self.run_collect("json", path)
        serialized = json.dumps(report)
        self.assertNotIn("synthetic-private-fragment", serialized)
        self.assertEqual(report["summary"]["errors"], [{"source": "json", "code": "invalid_json"}])

    def test_duplicate_selected_paths_and_no_source_mutation_or_network(self):
        path = self.write_jsonl("export.jsonl", [self.generic("local only")])
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file()}
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            report = collector.collect([("json", self.root), ("json", path)], now=NOW)
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(report["summary"]["counts"]["duplicate_files_skipped"], 1)

    def test_cli_requires_explicit_sources_and_has_json_only_errors(self):
        run = subprocess.run([sys.executable, "-B", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stderr, "")
        self.assertEqual(json.loads(run.stdout)["records"], [])
        run = subprocess.run([sys.executable, "-B", str(SCRIPT), "--unknown", "synthetic-private-argument"],
                             capture_output=True, text=True)
        self.assertNotIn("synthetic-private-argument", run.stdout + run.stderr)

    def test_cli_repeatable_sources_and_limits(self):
        first = self.write_jsonl("one.jsonl", [self.generic("earlier", timestamp="2030-06-20T00:00:00Z")])
        second = self.write_jsonl("two.jsonl", [self.generic("latest", timestamp="2030-06-29T00:00:00Z")])
        run = subprocess.run([sys.executable, "-B", str(SCRIPT), "--json", str(first), "--json", str(second),
                              "--days", "0", "--limit", "1", "--max-chars", "4"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        self.assertEqual([r["text"] for r in json.loads(run.stdout)["records"]], ["late"])


if __name__ == "__main__":
    unittest.main()
