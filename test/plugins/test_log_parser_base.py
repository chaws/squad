import os
import re
from collections import defaultdict

from django.test import TestCase

from squad.core.models import Group
from squad.plugins.lib.base_log_parser import BaseLogParser
from squad.plugins.linux_log_parser import Plugin


def read_sample_file(name):
    if not name.startswith('/'):
        name = os.path.join(os.path.dirname(__file__), 'log_parser_base', name)
    return open(name).read()


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
        self.plugin = Plugin()

    def new_testrun(self, logfile, job_id='999'):
        log = read_sample_file(logfile)
        testrun = self.build.test_runs.create(environment=self.env, job_id=job_id)
        testrun.save_log_file(log)
        return testrun

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

    def test_remove_numbers_and_time_with_pid(self):
        """
        Test removing numbers and time from a string containing timestamp,
        non-hex number and hex number
        """
        snippet1 = "<3>[    2.491276][    T1] BUG: KCSAN: data-race in console_emit_next_record / console_trylock_spinning"
        numbers_and_time_removed = self.log_parser.remove_numbers_and_time(snippet1)
        expected_numbers_and_time_removed = (
            " BUG: KCSAN: data-race in console_emit_next_record / console_trylock_spinning"
        )

        self.assertEqual(numbers_and_time_removed, expected_numbers_and_time_removed)

        snippet2 = "<3>[  157.430085][    C1] BUG: KCSAN: data-race in ktime_get / timekeeping_advance"
        numbers_and_time_removed = self.log_parser.remove_numbers_and_time(snippet2)
        expected_numbers_and_time_removed = (
            " BUG: KCSAN: data-race in ktime_get / timekeeping_advance"
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

    def test_create_name_log_dict_exclude_numbers(self):
        """
        Test creating the dict containing the "name" and "log lines" pairs -
        case where we want to exclude the numbers before doing the SHA
        """
        tests_without_shas_to_create, tests_with_shas_to_create = (
            self.log_parser.create_name_log_dict(
                "test_name", ["log lines 1", "log lines 2"]
            )
        )
        expected_tests_without_shas_to_create = defaultdict(
            set, {"test_name": {"log lines 1", "log lines 2"}}
        )
        expected_tests_with_shas_to_create = defaultdict(
            set,
            {
                "test_name-1677bef240c981a91c7f0c4321668491ff18f224ee5f4191feaa1940b09ccdaa": {
                    "log lines 1",
                    "log lines 2",
                }
            },
        )

        self.assertDictEqual(
            tests_without_shas_to_create, expected_tests_without_shas_to_create
        )
        self.assertDictEqual(
            tests_with_shas_to_create, expected_tests_with_shas_to_create
        )

    def test_create_name_log_dict_keep_numbers(self):
        """
        Test creating the dict containing the "name" and "log lines" pairs -
        case where we want to keep the numbers before doing the SHA
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
                "test_name-8166dde0dc110dc6d0064b55e0d09fb4589f6d68e4aa5580376858e290f4bc91": {
                    "log lines1",
                },
                "test_name-335a19ed20ff0d0b276e1120a5761802bb3c7ce416b24ef69b5ba4b247832f92": {
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

    def test_create_name_log_dict_no_shas(self):
        """
        Test creating the dict containing the "name" and "log lines" pairs
        """
        tests_without_shas_to_create, tests_with_shas_to_create = (
            self.log_parser.create_name_log_dict(
                "test_name", ["log lines1", "log lines2"], create_shas=False
            )
        )
        expected_tests_without_shas_to_create = defaultdict(
            set, {"test_name": {"log lines1", "log lines2"}}
        )
        expected_tests_with_shas_to_create = None

        self.assertDictEqual(
            tests_without_shas_to_create, expected_tests_without_shas_to_create
        )
        self.assertEqual(
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
            self.testrun, suite, "test_name", {"log lines 1", "log lines 2"}
        )

        test = self.testrun.tests.get(
            suite__slug="log-parser-test", metadata__name="test_name"
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)

        test_with_sha = self.testrun.tests.get(
            suite__slug="log-parser-test",
            metadata__name="test_name-1677bef240c981a91c7f0c4321668491ff18f224ee5f4191feaa1940b09ccdaa",
        )
        self.assertFalse(test_with_sha.result)
        self.assertIsNotNone(test_with_sha.log)
        self.assertIn("log lines 1", test_with_sha.log)
        self.assertIn("log lines 2", test_with_sha.log)

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

        snippets = self.log_parser.join_matches(matches, regex)

        self.assertIn(
            "Kernel panic - not syncing: Attempted to kill init 64! exitcode=0x00000009",
            snippets[0],
        )
        self.assertIn(
            "Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000008",
            snippets[0],
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

    def test_kfence_seconds(self):
        """
        Test removing numbers and time from a string containing timestamp,
        non-hex number and hex number
        """
        testrun = self.new_testrun('kfence-seconds.log')
        self.plugin.postprocess_testrun(testrun)

        tests = testrun.tests
        expected_output = read_sample_file('kfence-seconds-expected.log')

        test_kfence_seconds = tests.get(suite__slug='log-parser-test', metadata__name='kfence-bug-kfence-use-after-free-read-in-test_use_after_free_read-12cdfd85b20ffda2c398b1d6f97a7d5230cd4f2caf19ef0fb38bbc98469d3bde')
        numbers_and_time_removed = self.log_parser.remove_numbers_and_time(test_kfence_seconds.log)

        self.assertEqual(numbers_and_time_removed.strip(), expected_output.strip())
