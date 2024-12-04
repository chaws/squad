from django.core.management.base import BaseCommand

from squad.plugins.linux_log_parser import Plugin as BootTestLogParser
from squad.plugins.linux_log_parser_build import Plugin as BuildLogParser


class FakeTestRun:
    log_file = None
    id = None


log_parsers = {
    'linux_log_parser_boot_test': BootTestLogParser(),
    "linux_log_parser_build": BuildLogParser(),
}


class Command(BaseCommand):

    help = """Run a log parser and print the outputs to the stdout."""

    def add_arguments(self, parser):

        parser.add_argument(
            "LOG_FILE",
            help="Log file to parser",
        )

        parser.add_argument(
            "LOG_PARSER",
            choices=log_parsers.keys(),
            help="Which log parser to run"
        )

    def handle(self, *args, **options):
        self.options = options

        with open(options["LOG_FILE"], "r") as f:
            log_file = f.read()

        testrun = FakeTestRun()
        testrun.log_file = log_file
        parser = log_parsers[options["LOG_PARSER"]]
        parser.postprocess_testrun(testrun, squad=False, print=True)
