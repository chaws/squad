import hashlib
import re
from collections import defaultdict

from django.template.defaultfilters import slugify

REGEX_NAME = 0
REGEX_BODY = 1
REGEX_EXTRACT_NAME = 2


class BaseLogParser:
    def compile_regexes(self, regexes):
        combined = [r"(%s)" % r[REGEX_BODY] for r in regexes]
        return re.compile(r"|".join(combined), re.S | re.M)

    def remove_numbers_and_time(self, snippet):
        without_numbers = re.sub(r"(0x[a-f0-9]+|[<\[][0-9a-f]+?[>\]]|\d+)", "", snippet)
        without_time = re.sub(r"^\[[^\]]+\]", "", without_numbers)

        return without_time

    def create_name(self, snippet, compiled_regex=None):
        matches = None
        if compiled_regex:
            matches = compiled_regex.findall(snippet)
        if not matches:
            # Only extract a name if we provide a regex to extract the name and
            # there is a match
            return None
        snippet = matches[0]
        without_numbers_and_time = self.remove_numbers_and_time(snippet)

        # Limit the name length to 191 characters, since the max name length
        # for SuiteMetadata in SQUAD is 256 characters. The SHA and "-" take 65
        # characters: 256-65=191
        return slugify(without_numbers_and_time)[:191]

    def create_shasum(self, snippet):
        sha = hashlib.sha256()
        without_numbers_and_time = self.remove_numbers_and_time(snippet)
        sha.update(without_numbers_and_time.encode())
        return sha.hexdigest()

    def create_name_log_dict(self, test_name, lines, test_regex=None):
        """
        Produce a dictionary with the test names as keys and the extracted logs
        for that test name as values. There will be at least one test name per
        regex. If there were any matches for a given regex, then a new test
        will be generated using test_name + shasum.
        """
        # Run the REGEX_EXTRACT_NAME regex over the log lines to sort them by
        # extracted name. If no name is extracted or the log parser did not
        # have any output for a particular regex, just use the default name
        # (for example "check-kernel-oops").
        tests_without_shas_to_create = defaultdict(set)
        tests_with_shas_to_create = defaultdict(set)

        # If there are no lines, use the default name and create a passing
        # test. For example "check-kernel-oops"
        if not lines:
            tests_without_shas_to_create[test_name] = []

        # If there are lines, then create the tests for these.
        for line in lines:
            extracted_name = self.create_name(line, test_regex)
            if extracted_name:
                extended_test_name = f"{test_name}-{extracted_name}"
            else:
                extended_test_name = test_name
            tests_without_shas_to_create[extended_test_name].add(line)

        for name, test_lines in tests_without_shas_to_create.items():
            # Some lines of the matched regex might be the same, and we don't want to create
            # multiple tests like test1-sha1, test1-sha1, etc, so we'll create a set of sha1sums
            # then create only new tests for unique sha's

            for line in test_lines:
                sha = self.create_shasum(line)
                name_with_sha = f"{name}-{sha}"
                tests_with_shas_to_create[name_with_sha].add(line)

        return tests_without_shas_to_create, tests_with_shas_to_create

    def create_squad_tests_from_name_log_dict(
        self, suite, testrun, tests_without_shas_to_create, tests_with_shas_to_create
    ):
        # Import SuiteMetadata from SQUAD only when required so BaseLogParser
        # does not require a SQUAD to work. This makes it easier to reuse this
        # class outside of SQUAD for testing and developing log parser
        # patterns.
        from squad.core.models import SuiteMetadata

        for name, lines in tests_without_shas_to_create.items():
            metadata, _ = SuiteMetadata.objects.get_or_create(
                suite=suite.slug, name=name, kind="test"
            )
            testrun.tests.create(
                suite=suite,
                result=(len(lines) == 0),
                log="\n".join(lines),
                metadata=metadata,
                build=testrun.build,
                environment=testrun.environment,
            )
        for name_with_sha, lines in tests_with_shas_to_create.items():
            metadata, _ = SuiteMetadata.objects.get_or_create(
                suite=suite.slug, name=name_with_sha, kind="test"
            )
            testrun.tests.create(
                suite=suite,
                result=False,
                log="\n---\n".join(lines),
                metadata=metadata,
                build=testrun.build,
                environment=testrun.environment,
            )

    def create_squad_tests(self, testrun, suite, test_name, lines, test_regex=None):
        """
        There will be at least one test per regex. If there were any match for
        a given regex, then a new test will be generated using test_name +
        shasum. This helps comparing kernel logs across different builds
        """
        tests_without_shas_to_create, tests_with_shas_to_create = (
            self.create_name_log_dict(test_name, lines, test_regex)
        )
        self.create_squad_tests_from_name_log_dict(
            suite,
            testrun,
            tests_without_shas_to_create,
            tests_with_shas_to_create,
        )

    def join_matches(self, matches, regexes):
        """
        group regex in python are returned as a list of tuples which each
        group match in one of the positions in the tuple. Example:
        regex = r'(a)|(b)|(c)'
        matches = [
            ('match a', '', ''),
            ('', 'match b', ''),
            ('match a', '', ''),
            ('', '', 'match c')
        ]
        """
        snippets = {regex_id: [] for regex_id in range(len(regexes))}
        for match in matches:
            for regex_id in range(len(regexes)):
                if len(match[regex_id]) > 0:
                    snippets[regex_id].append(match[regex_id])
        return snippets
