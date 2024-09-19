import logging
import re
from squad.plugins import Plugin as BasePlugin
from squad.plugins.lib.base_log_parser import BaseLogParser, REGEX_NAME, REGEX_EXTRACT_NAME, tstamp, pid, not_newline_or_plus

logger = logging.getLogger()

MULTILINERS = [
    ('exception', f'-+\[? cut here \]?-+.*?{tstamp}{pid}?\s+-+\[? end trace \w* \]?-+', f"\n{tstamp}{not_newline_or_plus}*"), # noqa
    ('kasan', f'{tstamp}{pid}?\s+=+\n{tstamp}{pid}?\s+BUG: KASAN:.*?\n*?{tstamp}{pid}?\s+=+', f"BUG: KASAN:{not_newline_or_plus}*"), # noqa
    ('kcsan', f'{tstamp}{pid}?\s+=+\n{tstamp}{pid}?\s+BUG: KCSAN:.*?=+', f"BUG: KCSAN:{not_newline_or_plus}*"), # noqa
    ('kfence', f'{tstamp}{pid}?\s+=+\n{tstamp}{pid}?\s+BUG: KFENCE:.*?{tstamp}{pid}?\s+=+', f"BUG: KFENCE:{not_newline_or_plus}*"), # noqa
    ('panic-multiline', f'{tstamp}{pid}?\s+Kernel panic - [^\n]+\n.*?-+\[? end Kernel panic - [^\n]+ \]?-*', f"Kernel {not_newline_or_plus}*"), # noqa
    ('internal-error-oops', f'{tstamp}{pid}?\s+Internal error: Oops.*?-+\[? end trace \w+ \]?-+', f"Oops{not_newline_or_plus}*"), # noqa
]

ONELINERS = [
    ('oops', r'^[^\n]+Oops(?: -|:).*?$', f"Oops{not_newline_or_plus}*"), # noqa
    ('fault', r'^[^\n]+Unhandled fault.*?$', f"Unhandled {not_newline_or_plus}*"), # noqa
    ('warning', r'^[^\n]+WARNING:.*?$', f"WARNING:{not_newline_or_plus}*"), # noqa
    ('bug', r'^[^\n]+(?: kernel BUG at|BUG:).*?$', f"BUG{not_newline_or_plus}*"), # noqa
    ('invalid-opcode', r'^[^\n]+invalid opcode:.*?$', f"invalid opcode:{not_newline_or_plus}*"), # noqa
    ('panic', r'Kernel panic - not syncing.*?$', f"Kernel {not_newline_or_plus}*"), # noqa
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
        kernel_msgs = re.findall(f'({tstamp}{pid}? .*?)$', log, re.S | re.M) # noqa
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
