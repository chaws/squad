import hashlib
import re
from collections import defaultdict

from django.template.defaultfilters import slugify

REGEX_NAME = 0
REGEX_BODY = 1
REGEX_EXTRACT_NAME = 2

tstamp = r"\[[ \d]+\.[ \d]+\]"
pid = r"(?:\s*?\[\s*?[CT]\d+\s*?\])"
not_newline_or_plus = r"[^\+\n]"
square_brackets_and_contents = r"\[[^\]]+\]"


class BaseLogParser:
    def compile_regexes(self, regexes):
        with_brackets = [r"(%s)" % r[REGEX_BODY] for r in regexes]
        combined = r"|".join(with_brackets)

        # In the case where there is only one regex, we need to add extra
        # bracket around it for it to behave the same as the multiple regex
        # case
        if len(regexes) == 1:
            combined = f"({combined})"

        return re.compile(combined, re.S | re.M)

    def remove_numbers_and_time(self, snippet):
        # allocated by task 285 on cpu 0 at 38.982743s (0.007174s ago):
        # Removes [digit(s)].[digit(s)]s
        cleaned_seconds = re.sub(r"\b\d+\.\d+s\b", "", snippet)
        # [   92.236941] CPU: 1 PID: 191 Comm: kunit_try_catch Tainted: G        W         5.15.75-rc1 #1
        # <4>[   87.925462] CPU: 0 PID: 135 Comm: (crub_all) Not tainted 6.7.0-next-20240111 #14
        # Remove '(Not t|T)ainted', to the end of the line.
        without_tainted = re.sub(r"(Not t|T)ainted.*", "", cleaned_seconds)

        # x23: ffff9b7275bc6f90 x22: ffff9b7275bcfb50 x21: fff00000cc80ef88
        # x20: 1ffff00010668fb8 x19: ffff8000800879f0 x18: 00000000805c0b5c
        # Remove words with hex numbers.
        # <3>[    2.491276][    T1] BUG: KCSAN: data-race in console_emit_next_record / console_trylock_spinning
        # -> <>[    .][    T1] BUG: KCSAN: data-race in console_emit_next_record / console_trylock_spinning
        without_hex = re.sub(r"\b(?:0x)?[a-fA-F0-9]+\b", "", without_tainted)

        # <>[ 1067.461794][  T132] BUG: KCSAN: data-race in do_page_fault spectre_v4_enable_task_mitigation
        # -> <>[ .][  T132] BUG: KCSAN: data-race in do_page_fault spectre_v_enable_task_mitigation
        # But should not remove numbers from functions.
        without_numbers = re.sub(
            r"(0x[a-f0-9]+|[<\[][0-9a-f]+?[>\]]|\b\d+\b(?!\s*\())", "", without_hex
        )

        # <>[ .][  T132] BUG: KCSAN: data-race in do_page_fault spectre_v_enable_task_mitigation
        # ->  BUG: KCSAN: data-race in do_page_fault spectre_v_enable_task_mitigation
        without_time = re.sub(
            f"^<?>?{square_brackets_and_contents}({square_brackets_and_contents})?",
            "",
            without_numbers,
        )  # noqa

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

        return slugify(without_numbers_and_time)

    def create_shasum(self, snippet):
        sha = hashlib.sha256()
        without_numbers_and_time = self.remove_numbers_and_time(snippet)
        sha.update(without_numbers_and_time.encode())
        return sha.hexdigest()

    def create_name_log_dict(self, test_name, lines, test_regex=None, create_shas=True):
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
        tests_with_shas_to_create = None

        # If there are lines, then create the tests for these.
        for line in lines:
            extracted_name = self.create_name(line, test_regex)
            if extracted_name:
                max_name_length = 256
                # If adding SHAs, limit the name length to 191 characters,
                # since the max name length for SuiteMetadata in SQUAD is 256
                # characters. The SHA and "-" take 65 characters: 256-65=191
                if create_shas:
                    max_name_length -= 65
                extended_test_name = f"{test_name}-{extracted_name}"[:max_name_length]
            else:
                extended_test_name = test_name
            tests_without_shas_to_create[extended_test_name].add(line)

        if create_shas:
            tests_with_shas_to_create = defaultdict(set)
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
        self,
        suite_name,
        testrun,
        tests_without_shas_to_create,
        tests_with_shas_to_create=None,
    ):
        # Import SuiteMetadata from SQUAD only when required so BaseLogParser
        # does not require a SQUAD to work. This makes it easier to reuse this
        # class outside of SQUAD for testing and developing log parser
        # patterns.
        from squad.core.models import SuiteMetadata

        suite, _ = testrun.build.project.suites.get_or_create(slug=suite_name)

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
        if tests_with_shas_to_create:
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

    def print_squad_tests_from_name_log_dict(
        self,
        suite_name,
        tests_without_shas_to_create,
        tests_with_shas_to_create=None,
    ):
        for name, lines in tests_without_shas_to_create.items():
            print(f"\nName: {suite_name}/{name}")
            log = "\n".join(lines)
            print(f"Log:\n{log}")

        if tests_with_shas_to_create:
            for name_with_sha, lines in tests_with_shas_to_create.items():
                print(f"\nName: {suite_name}/{name_with_sha}")
                log = "\n---\n".join(lines)
                print(f"Log:\n{log}")

    def create_squad_tests(
        self,
        testrun,
        suite_name,
        test_name,
        lines,
        test_regex=None,
        create_shas=True,
        print=False,
        squad=True,
    ):
        """
        There will be at least one test per regex. If there were any match for
        a given regex, then a new test will be generated using test_name +
        shasum. This helps comparing kernel logs across different builds
        """

        tests_without_shas_to_create, tests_with_shas_to_create = (
            self.create_name_log_dict(
                test_name, lines, test_regex, create_shas=create_shas
            )
        )
        if print:
            self.print_squad_tests_from_name_log_dict(
                suite_name,
                tests_without_shas_to_create,
                tests_with_shas_to_create,
            )
        if squad:
            self.create_squad_tests_from_name_log_dict(
                suite_name,
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
