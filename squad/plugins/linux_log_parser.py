import logging
import re
from squad.plugins import Plugin as BasePlugin
from squad.plugins.lib.base_log_parser import BaseLogParser, REGEX_NAME, REGEX_EXTRACT_NAME, tstamp, pid, not_newline_or_plus

logger = logging.getLogger()

MULTILINERS = [
    ('exception', fr'-+\[? cut here \]?-+.*?{tstamp}{pid}?\s+-+\[? end trace \w* \]?-+', fr"\n{tstamp}{not_newline_or_plus}*"), # noqa
    ('kasan', fr'{tstamp}{pid}?\s+=+\n{tstamp}{pid}?\s+BUG: KASAN:.*?\n*?{tstamp}{pid}?\s+=+', fr"BUG: KASAN:{not_newline_or_plus}*"), # noqa
    ('kcsan', fr'{tstamp}{pid}?\s+=+\n{tstamp}{pid}?\s+BUG: KCSAN:.*?=+', fr"BUG: KCSAN:{not_newline_or_plus}*"), # noqa
    ('kfence', fr'{tstamp}{pid}?\s+=+\n{tstamp}{pid}?\s+BUG: KFENCE:.*?{tstamp}{pid}?\s+=+', fr"BUG: KFENCE:{not_newline_or_plus}*"), # noqa
    ('panic-multiline', fr'{tstamp}{pid}?\s+Kernel panic - [^\n]+\n.*?-+\[? end Kernel panic - [^\n]+ \]?-*', fr"Kernel {not_newline_or_plus}*"), # noqa
    ('internal-error-oops', fr'{tstamp}{pid}?\s+Internal error: Oops.*?-+\[? end trace \w+ \]?-+', fr"Oops{not_newline_or_plus}*"), # noqa
]

ONELINERS = [
    ('oops', r'^[^\n]+Oops(?: -|:).*?$', fr"Oops{not_newline_or_plus}*"), # noqa
    ('fault', r'^[^\n]+Unhandled fault.*?$', fr"Unhandled {not_newline_or_plus}*"), # noqa
    ('warning', r'^[^\n]+WARNING:.*?$', fr"WARNING:{not_newline_or_plus}*"), # noqa
    ('bug', r'^[^\n]+(?: kernel BUG at|BUG:).*?$', fr"BUG{not_newline_or_plus}*"), # noqa
    ('invalid-opcode', r'^[^\n]+invalid opcode:.*?$', fr"invalid opcode:{not_newline_or_plus}*"), # noqa
    ('panic', r'Kernel panic - not syncing.*?$', fr"Kernel {not_newline_or_plus}*"), # noqa
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

    def postprocess_testrun(self, testrun, squad=True, print=False):
        # If running as a SQUAD plugin, only run the boot/test log parser if this is not a build testrun
        if testrun.log_file is None or (squad and testrun.tests.filter(suite__slug="build").exists()):
            return

        boot_log, test_log = self.__cutoff_boot_log(testrun.log_file)
        logs = {
            'boot': boot_log,
            'test': test_log,
        }

        for log_type, log in logs.items():
            log = self.__kernel_msgs_only(log)
            suite_name = f'log-parser-{log_type}'

            regex = self.compile_regexes(REGEXES)
            matches = regex.findall(log)
            snippets = self.join_matches(matches, REGEXES)

            for regex_id in range(len(REGEXES)):
                test_name = REGEXES[regex_id][REGEX_NAME]
                regex_pattern = REGEXES[regex_id][REGEX_EXTRACT_NAME]
                test_name_regex = None
                if regex_pattern:
                    test_name_regex = re.compile(regex_pattern, re.S | re.M)
                self.create_squad_tests(testrun, suite_name, test_name, snippets[regex_id], test_name_regex, squad=squad, print=print)
