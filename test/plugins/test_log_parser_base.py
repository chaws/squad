import re
from collections import defaultdict

from django.test import TestCase

from squad.core.models import Group
from squad.plugins.lib.base_log_parser import BaseLogParser


def compile_regex(regex):
    return re.compile(regex, re.S | re.M)


class TestBaseLogParser(TestCase):
    def setUp(self):
        self.log_parser = BaseLogParser()
        self.snippet = "[    0.123] Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009"
        group = Group.objects.create(slug="mygroup")
        self.project = group.projects.create(
            slug="myproject", enabled_plugins_list="example"
        )
        self.build = self.project.builds.create(version="1")
        self.env = self.project.environments.create(slug="myenv")
        self.testrun = self.build.test_runs.create(environment=self.env, job_id="123")

    def test_remove_numbers_and_time(self):
        """
        Test removing numbers and time from a string containing timestamp,
        non-hex number and hex number
        """
        numbers_and_time_removed = self.log_parser.remove_numbers_and_time(self.snippet)
        expected_numbers_and_time_removed = (
            " Kernel panic - not syncing: Attempted to kill init ! exitcode="
        )

        self.assertEqual(numbers_and_time_removed, expected_numbers_and_time_removed)

    def test_create_name_no_regex(self):
        """
        Test create_name when no regex is provided
        """
        name = self.log_parser.create_name(self.snippet)

        self.assertEqual(name, None)

    def test_create_name_with_regex_match(self):
        """
        Test create_name when a name regex is provided and there is a match
        """
        regex = r"panic.*"
        compiled_regex = compile_regex(regex)
        name = self.log_parser.create_name(self.snippet, compiled_regex)

        self.assertEqual(name, "panic-not-syncing-attempted-to-kill-init-exitcode")

    def test_create_name_with_regex_no_match(self):
        """
        Test create_name when a name regex is provided and there is not a match
        """
        regex = r"oops.*"
        compiled_regex = compile_regex(regex)
        name = self.log_parser.create_name(self.snippet, compiled_regex)

        self.assertEqual(name, None)

    def test_create_shasum(self):
        """
        Test the SHA sum behavior remains consistent
        """
        sha_sum = self.log_parser.create_shasum(self.snippet)

        self.assertEqual(
            sha_sum, "1e8e593de88f4856fc03d46c4156cf0772898309f8a796595f549bcabfc1cb9f"
        )

    def test_create_name_log_dict(self):
        """
        Test creating the dict containing the "name" and "log lines" pairs
        """
        tests_without_shas_to_create, tests_with_shas_to_create = (
            self.log_parser.create_name_log_dict(
                "test_name", ["log lines1", "log lines2"]
            )
        )
        expected_tests_without_shas_to_create = defaultdict(
            set, {"test_name": {"log lines1", "log lines2"}}
        )
        expected_tests_with_shas_to_create = defaultdict(
            set,
            {
                "test_name-2b06e6aa0f681d2b9d2de6b1e91d4b25cea58b5ce9c3dcd64b429766a8b0ecb1": {
                    "log lines1",
                    "log lines2",
                }
            },
        )

        self.assertDictEqual(
            tests_without_shas_to_create, expected_tests_without_shas_to_create
        )
        self.assertDictEqual(
            tests_with_shas_to_create, expected_tests_with_shas_to_create
        )

    def test_create_squad_tests_from_name_log_dict(self):
        """
        Test creating SQUAD tests from a dictionary of test names as keys and
        log lines as values.
        """
        tests_without_shas_to_create = {"test_name": ["log1a\nlog1b\nlog2a"]}
        tests_with_shas_to_create = {
            "test_name-sha1": ["log1a", "log1b"],
            "test_name-sha2": ["log2a"],
        }
        suite, _ = self.testrun.build.project.suites.get_or_create(
            slug="log-parser-test"
        )
        self.log_parser.create_squad_tests_from_name_log_dict(
            suite,
            self.testrun,
            tests_without_shas_to_create,
            tests_with_shas_to_create,
        )

        test = self.testrun.tests.get(
            suite__slug="log-parser-test", metadata__name="test_name"
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertEqual(test.log, "log1a\nlog1b\nlog2a")

        test_with_sha1 = self.testrun.tests.get(
            suite__slug="log-parser-test", metadata__name="test_name-sha1"
        )
        self.assertFalse(test_with_sha1.result)
        self.assertIsNotNone(test_with_sha1.log)
        self.assertEqual(test_with_sha1.log, "log1a\n---\nlog1b")

        test_with_sha2 = self.testrun.tests.get(
            suite__slug="log-parser-test", metadata__name="test_name-sha2"
        )
        self.assertFalse(test_with_sha2.result)
        self.assertIsNotNone(test_with_sha2.log)
        self.assertEqual(test_with_sha2.log, "log2a")

    def test_create_tests(self):
        """
        Test the wrapper for extracting the regexes then creating the SQUAD
        tests
        """
        suite, _ = self.testrun.build.project.suites.get_or_create(
            slug="log-parser-test"
        )
        self.log_parser.create_squad_tests(
            self.testrun, suite, "test_name", {"log lines1", "log lines2"}
        )

        test = self.testrun.tests.get(
            suite__slug="log-parser-test", metadata__name="test_name"
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)

        test_with_sha = self.testrun.tests.get(
            suite__slug="log-parser-test",
            metadata__name="test_name-2b06e6aa0f681d2b9d2de6b1e91d4b25cea58b5ce9c3dcd64b429766a8b0ecb1",
        )
        self.assertFalse(test_with_sha.result)
        self.assertIsNotNone(test_with_sha.log)
        self.assertIn("log lines1", test_with_sha.log)
        self.assertIn("log lines2", test_with_sha.log)

    def test_compile_regex_single(self):
        regex = [
            (
                "check-kernel-panic",
                r"Kernel panic - not syncing.*?$",
                r"Kernel [^\+\n]*",
            )
        ]

        compiled_regex = self.log_parser.compile_regexes(regex)
        log = """[    0.123] Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009\n[    0.999] Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008"""
        matches = compiled_regex.findall(log)

        self.assertIn(
            "Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009",
            matches,
        )
        self.assertIn(
            "Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008",
            matches,
        )

        self.assertEqual(len(matches), 2)

    def test_compile_regex_multiple(self):
        regex = [
            (
                "check-kernel-panic",
                r"Kernel panic - not syncing.*?$",
                r"Kernel [^\+\n]*",
            ),
            ("check-kernel-oops", r"^[^\n]+Oops(?: -|:).*?$", r"Oops[^\+\n]*"),
        ]
        compiled_regex = self.log_parser.compile_regexes(regex)

        log = """[    0.123] Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009\n[    0.999] Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008\n[   14.461360] Internal error: Oops - BUG: 0 [#0] PREEMPT SMP"""
        matches = compiled_regex.findall(log)

        snippets = self.log_parser.join_matches(matches, regex)

        self.assertIn(
            "Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009",
            snippets[0],
        )
        self.assertIn(
            "Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008",
            snippets[0],
        )
        self.assertIn(
            "[   14.461360] Internal error: Oops - BUG: 0 [#0] PREEMPT SMP", snippets[1]
        )

        self.assertEqual(
            len(snippets), 2
        )  # There are 2 regexes being tested so there is a dict entry for each regex
        self.assertEqual(len(snippets[0]), 2)  # Regex ID 0 has 2 matches
        self.assertEqual(len(snippets[1]), 1)  # Regex ID 1 has 1 match

    def test_join_matches(self):
        matches = [
            (
                "Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009",
                "",
            ),
            (
                "Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008",
                "",
            ),
            ("", "[   14.461360] Internal error: Oops - BUG: 0 [#0] PREEMPT SMP"),
        ]
        regexes = [
            (
                "check-kernel-panic",
                r"Kernel panic - not syncing.*?$",
                r"Kernel [^\+\n]*",
            ),
            ("check-kernel-oops", r"^[^\n]+Oops(?: -|:).*?$", r"Oops[^\+\n]*"),
        ]
        snippets = self.log_parser.join_matches(matches, regexes)
        expected_snippets = {
            0: [
                "Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009",
                "Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008",
            ],
            1: ["[   14.461360] Internal error: Oops - BUG: 0 [#0] PREEMPT SMP"],
        }

        self.assertDictEqual(snippets, expected_snippets)
