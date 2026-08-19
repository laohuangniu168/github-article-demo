from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import publish_articles


class PublishArticlesGate64Tests(unittest.TestCase):
    def test_dry_run_has_no_generation_audits_or_file_writes(self) -> None:
        argv = [
            "publish_articles.py",
            "--input",
            "input/articles-gate6.txt",
            "--dry-run",
        ]

        with patch.object(sys, "argv", argv):
            with patch.object(publish_articles, "assert_clean_worktree"):
                with patch.object(
                    publish_articles,
                    "get_git_state",
                    return_value=("same", "same"),
                ):
                    with patch.object(
                        publish_articles,
                        "execute_gate6_4",
                    ) as execute:
                        with patch.object(Path, "write_text") as write_text:
                            with redirect_stdout(StringIO()) as output:
                                result = publish_articles.main()

        self.assertEqual(result, 0)
        self.assertIn("FINAL: DRY_RUN_PASS", output.getvalue())
        execute.assert_not_called()
        write_text.assert_not_called()

    def test_execute_runs_generation_then_all_audits(self) -> None:
        articles = [
            publish_articles.ArticleSpec("one", "标题一"),
            publish_articles.ArticleSpec("two", "标题二"),
        ]
        input_file = Path("input/articles-gate6.txt")
        generate = Mock(return_value=([], [], []))
        calls: list[str] = []

        fake_module = Mock(generate_articles=generate)
        with patch.dict(sys.modules, {"generate_articles": fake_module}):
            with patch.object(
                publish_articles,
                "run_audit",
                side_effect=lambda name, script, path: calls.append(name),
            ):
                publish_articles.execute_gate6_4(articles, input_file)

        generate.assert_called_once_with(articles=articles, use_ai=True)
        self.assertEqual(
            calls,
            [
                "Quality Audit",
                "Similarity Audit",
                "Jekyll Safety Audit",
            ],
        )

    def test_generation_failure_stops_before_audits(self) -> None:
        articles = [publish_articles.ArticleSpec("one", "标题一")]
        generate = Mock(return_value=([], [], [(articles[0], "boom")]))
        fake_module = Mock(generate_articles=generate)

        with patch.dict(sys.modules, {"generate_articles": fake_module}):
            with patch.object(publish_articles, "run_audit") as audit:
                with self.assertRaisesRegex(RuntimeError, "AI Generate"):
                    publish_articles.execute_gate6_4(
                        articles,
                        Path("input/articles-gate6.txt"),
                    )

        audit.assert_not_called()

    def test_audit_failure_stops_remaining_audits(self) -> None:
        articles = [publish_articles.ArticleSpec("one", "标题一")]
        generate = Mock(return_value=([], [], []))
        fake_module = Mock(generate_articles=generate)

        with patch.dict(sys.modules, {"generate_articles": fake_module}):
            with patch.object(
                publish_articles,
                "run_audit",
                side_effect=[None, RuntimeError("blocked")],
            ) as audit:
                with self.assertRaisesRegex(RuntimeError, "blocked"):
                    publish_articles.execute_gate6_4(
                        articles,
                        Path("input/articles-gate6.txt"),
                    )

        self.assertEqual(audit.call_count, 2)


if __name__ == "__main__":
    unittest.main()
