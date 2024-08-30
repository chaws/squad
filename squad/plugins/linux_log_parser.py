import logging
import re
from squad.plugins import Plugin as BasePlugin
from squad.plugins.lib.base_log_parser import BaseLogParser, REGEX_NAME, REGEX_EXTRACT_NAME

logger = logging.getLogger()

MULTILINERS = [
    ('exception', r'-+\[? cut here \]?-+.*?\[[\s\.\d]+\]\s+-+\[? end trace \w* \]?-+', r"\n\[[\s\.\d][^\+\n]*"),
    ('kasan', r'\[[\s\.\d]+\]\s+=+\n\[[\s\.\d]+\]\s+BUG: KASAN:.*\n*?\[[\s\.\d]+\]\s+=+', r"BUG: KASAN:[^\+\n]*"),
    ('kcsan', r'=+\n\[[\s\.\d]+\].*?BUG: KCSAN:.*?=+', r"BUG: KCSAN:[^\+\n]*"),
    ('kfence', r'\[[\s\.\d]+\]\s+=+\n\[[\s\.\d]+\]\s+BUG: KFENCE:.*\[[\s\.\d]+\]\s+=+', r"BUG: KFENCE:[^\+\n]*"),
    ('panic-multiline', r'\[[\s\.\d]+\]\s+Kernel panic - [^\n]+\n.*?-+\[? end Kernel panic - [^\n]+ \]?-*', r"Kernel [^\+\n]*"),
    ('internal-error-oops', r'\[[\s\.\d]+\]\s+Internal error: Oops.*?-+\[? end trace \w+ \]?-+', r"Oops[^\+\n]*"),
]

ONELINERS = [
    ('oops', r'^[^\n]+Oops(?: -|:).*?$', r"Oops[^\+\n]*"),
    ('fault', r'^[^\n]+Unhandled fault.*?$', r"Unhandled [^\+\n]*"),
    ('warning', r'^[^\n]+WARNING:.*?$', r"WARNING:[^\+\n]*"),
    ('bug', r'^[^\n]+(?: kernel BUG at|BUG:).*?$', r"BUG[^\+\n]*"),
    ('invalid-opcode', r'^[^\n]+invalid opcode:.*?$', r"invalid opcode:[^\+\n]*"),
    ('panic', r'Kernel panic - not syncing.*?$', r"Kernel [^\+\n]*"),
]

# Tip: broader regexes should come first
REGEXES = MULTILINERS + ONELINERS


class Plugin(BasePlugin, BaseLogParser):
    def __cutoff_boot_log(self, log):
        # Attempt to split the log in " login:"
        logs = log.split(' login:', 1)

        # 1 string means no split was done, consider all logs as test log
        if len(logs) == 1:
            return '', log

        boot_log = logs[0]
        test_log = logs[1]
        return boot_log, test_log

    def __kernel_msgs_only(self, log):
        kernel_msgs = re.findall(r'(\[[ \d]+\.[ \d]+\] .*?)$', log, re.S | re.M)
        return '\n'.join(kernel_msgs)

    def postprocess_testrun(self, testrun):
        if testrun.log_file is None:
            return

        boot_log, test_log = self.__cutoff_boot_log(testrun.log_file)
        logs = {
            'boot': boot_log,
            'test': test_log,
        }

        for log_type, log in logs.items():
            log = self.__kernel_msgs_only(log)
            suite, _ = testrun.build.project.suites.get_or_create(slug=f'log-parser-{log_type}')

            regex = self.compile_regexes(REGEXES)
            matches = regex.findall(log)
            snippets = self.join_matches(matches, REGEXES)

            for regex_id in range(len(REGEXES)):
                test_name = REGEXES[regex_id][REGEX_NAME]
                regex_pattern = REGEXES[regex_id][REGEX_EXTRACT_NAME]
                test_name_regex = None
                if regex_pattern:
                    test_name_regex = re.compile(regex_pattern, re.S | re.M)
                self.create_squad_tests(testrun, suite, test_name, snippets[regex_id], test_name_regex)
