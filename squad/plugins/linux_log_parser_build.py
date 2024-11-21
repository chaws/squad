import logging
import re

from django.template.defaultfilters import slugify

from squad.plugins import Plugin as BasePlugin
from squad.plugins.lib.base_log_parser import (
    REGEX_EXTRACT_NAME,
    REGEX_NAME,
    BaseLogParser,
)

logger = logging.getLogger()

file_path = r"^(?:[^\n]*?:(?:\d+:){2}|<[^\n]*?>:)"
gcc_clang_compiler_error_warning = rf"{file_path} (?:error|warning): [^\n]+?\n^(?:\.+\n|^(?!\s+(?:CC|Kernel[^\n]*?is ready))\s+?[^\n]+\n|{file_path} note:[^\n]+\n)*"

MULTILINERS_GCC = [
    (
        "gcc-compiler",
        gcc_clang_compiler_error_warning,
        r"^[^\n]*(?:error|warning)[^\n]*$",
    ),
]

ONELINERS_GCC = []

# Tip: broader regexes should come first
REGEXES_GCC = MULTILINERS_GCC + ONELINERS_GCC

supported_toolchains = {
    "gcc": REGEXES_GCC,
}

make_regex = r"^make .*?$"
in_file_regex = r"^[^\n]*?In file.*?:$"
in_function_regex = r"^[^\n]*?In function.*?:$"
entering_dir_regex = r"^make\[(?:\d+)\]: Entering directory.*?$"
leaving_dir_regex = r"^make\[(?:\d+)\]: Leaving directory.*?$"

split_regex_gcc = rf"(.*?)({make_regex}|{in_file_regex}|{in_function_regex}|{entering_dir_regex}|{leaving_dir_regex})"


class Plugin(BasePlugin, BaseLogParser):

    def post_process_test_name(self, text):
        # Remove "builds/linux" if there
        text = re.sub(r"builds/linux", "", text)

        # Change "/" and "." to "_" for readability
        text = re.sub(r"[/\.]", "_", text)

        # Remove numbers and hex
        text = re.sub(r"(0x[a-f0-9]+|[<\[][0-9a-f]+?[>\]]|\d+)", "", text)

        # Remove "{...}" and "[...]"
        text = re.sub(r"\{.+?\}", "", text)
        text = re.sub(r"\[.+?\]", "", text)

        return text

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

        name = slugify(self.post_process_test_name(without_numbers_and_time))

        return name

    def split_by_regex(self, log, regex):
        # Split up the log by the keywords we want to capture
        s_lines_compiled = re.compile(regex, re.DOTALL | re.MULTILINE)
        split_by_regex_list = s_lines_compiled.split(log)
        split_by_regex_list = [
            f for f in split_by_regex_list if f is not None and f != ""
        ]

        return split_by_regex_list

    def process_blocks(
        self,
        blocks_to_process,
        regexes,
        make_regex=make_regex,
        entering_dir_regex=entering_dir_regex,
        leaving_dir_regex=leaving_dir_regex,
        in_file_regex=in_file_regex,
        in_function_regex=in_function_regex,
    ):
        snippets = dict()
        regex_compiled = self.compile_regexes(regexes)
        make_regex_compiled = re.compile(make_regex, re.DOTALL | re.MULTILINE)
        entering_dir_regex_compiled = re.compile(
            entering_dir_regex, re.DOTALL | re.MULTILINE
        )
        leaving_dir_regex_compiled = re.compile(
            leaving_dir_regex, re.DOTALL | re.MULTILINE
        )
        in_file_regex_compiled = re.compile(in_file_regex, re.DOTALL | re.MULTILINE)
        in_function_regex_compiled = re.compile(
            in_function_regex, re.DOTALL | re.MULTILINE
        )

        # For tracking the last piece of information we saw
        make_command = None
        entering_dir = None
        in_file = None
        in_function = None

        for regex_id in range(len(regexes)):
            snippets[regex_id] = []
        for block in blocks_to_process:
            if make_regex_compiled.match(block):
                make_command = block
                entering_dir = None
                in_file = None
                in_function = None
            elif entering_dir_regex_compiled.match(block):
                entering_dir = block
                in_file = None
                in_function = None
            elif leaving_dir_regex_compiled.match(block):
                entering_dir = None
                in_file = None
                in_function = None
            elif in_file_regex_compiled.match(block):
                in_file = block
                in_function = None
            elif in_function_regex_compiled.match(block):
                in_function = block
            else:
                matches = regex_compiled.findall(block)
                sub_snippets = self.join_matches(matches, regexes)
                prepend = ""
                if make_command:
                    prepend += make_command + "\n"
                if entering_dir:
                    prepend += entering_dir + "\n"
                if in_file:
                    prepend += in_file + "\n"
                if in_function:
                    prepend += in_function + "\n"
                for regex_id in range(len(regexes)):
                    for s in sub_snippets[regex_id]:
                        snippets[regex_id].append(prepend + s)

        return snippets

    def postprocess_testrun(self, testrun, squad=True, print=False):
        """
        Check:
            - There is a log file
            - If running as SQUAD plugin, the testrun contains the "build"
              suite - this tells us that the testrun's log is a build log
        """
        if testrun.log_file is None or (
            squad and not testrun.tests.filter(suite__slug="build").exists()
        ):
            return

        regexes = None
        for toolchain, toolchain_regexes in supported_toolchains.items():
            if f"--toolchain={toolchain}" in testrun.log_file:
                toolchain_name = toolchain
                regexes = toolchain_regexes

        # If a supported toolchain was not found in the log
        if regexes is None:
            return

        # If running in SQUAD, create the suite
        suite_name = f"log-parser-build-{toolchain_name}"

        blocks_to_process = self.split_by_regex(testrun.log_file, split_regex_gcc)

        snippets = self.process_blocks(blocks_to_process, regexes)

        for regex_id in range(len(regexes)):
            test_name = regexes[regex_id][REGEX_NAME]
            regex_pattern = regexes[regex_id][REGEX_EXTRACT_NAME]
            test_name_regex = None
            if regex_pattern:
                test_name_regex = re.compile(regex_pattern, re.S | re.M)
            self.create_squad_tests(
                testrun,
                suite_name,
                test_name,
                snippets[regex_id],
                test_name_regex,
                create_shas=False,
                print=print,
                squad=squad,
            )
