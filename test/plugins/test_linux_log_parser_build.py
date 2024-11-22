import os
import re

from django.test import TestCase

from squad.core.models import Group
from squad.plugins.linux_log_parser_build import Plugin, split_regex_gcc


def compile_regex(regex):
    return re.compile(regex, re.S | re.M)


def read_sample_file(name):
    if not name.startswith("/"):
        name = os.path.join(os.path.dirname(__file__), "linux_log_parser_build", name)
    return open(name).read()


class TestLinuxLogParserBuild(TestCase):

    def setUp(self):
        group = Group.objects.create(slug="mygroup")
        self.snippet = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'CC=sccache arm-linux-gnueabihf-gcc' 'HOSTCC=sccache gcc'
In file included from /builds/linux/mm/internal.h:22,
                 from /builds/linux/mm/filemap.c:52:
/builds/linux/mm/vma.h: In function 'init_vma_munmap':
/builds/linux/mm/vma.h:184:26: error: 'USER_PGTABLES_CEILING' undeclared (first use in this function)
  184 |         vms->unmap_end = USER_PGTABLES_CEILING;
      |                          ^~~~~~~~~~~~~~~~~~~~~
/builds/linux/mm/vma.h:184:26: note: each undeclared identifier is reported only once for each function it appears in"""
        self.project = group.projects.create(
            slug="myproject", enabled_plugins_list="example"
        )
        self.build = self.project.builds.create(version="1")
        self.env = self.project.environments.create(slug="myenv")
        self.plugin = Plugin()

    def new_testrun(self, logfile, job_id="999"):
        log = read_sample_file(logfile)
        testrun = self.build.test_runs.create(environment=self.env, job_id=job_id)
        testrun.save_log_file(log)

        # Create a test called "build" in the testrun so the build log parser will run
        suite_build = testrun.build.project.suites.create(slug="build")
        _ = testrun.tests.create(suite=suite_build)

        return testrun


class TestLinuxLogParserBuildCommonFunctionality(TestLinuxLogParserBuild):
    def test_only_run_on_build(self):
        log = read_sample_file("gcc_arm_24951924.log")
        testrun = self.build.test_runs.create(environment=self.env, job_id="999")
        testrun.save_log_file(log)

        self.plugin.postprocess_testrun(testrun)

        with self.assertRaises(Exception) as ctx:
            testrun.tests.get(suite__slug="log-parser-build-gcc")

        self.assertEqual("Test matching query does not exist.", str(ctx.exception))

    def test_create_name_no_regex(self):
        """
        Test create_name when no regex is provided
        """
        name = self.plugin.create_name(self.snippet)

        self.assertEqual(name, None)

    def test_create_name_with_everything_to_be_removed(self):
        """
        Test create_name when all of the thing we want to remove are in the
        string
        """
        regex = r"^.*$"
        compiled_regex = compile_regex(regex)
        snippet = "builds/linux/testa/testb///....c.. 23{test1}[test2]test.c"
        name = self.plugin.create_name(snippet, compiled_regex)

        self.assertEqual(name, "testa_testb_______c__-test_c")

    def test_create_name_with_regex_match(self):
        """
        Test create_name when a name regex is provided and there is a match
        """
        regex = r"^[^\n]*(?:error|warning)[^\n]*$"
        compiled_regex = compile_regex(regex)
        name = self.plugin.create_name(self.snippet, compiled_regex)

        self.assertEqual(
            name,
            "mm_vma_h-error-user_pgtables_ceiling-undeclared-first-use-in-this-function",
        )

    def test_create_name_with_regex_no_match(self):
        """
        Test create_name when a name regex is provided and there is not a match
        """
        regex = r"oops.*"
        compiled_regex = compile_regex(regex)
        name = self.plugin.create_name(self.snippet, compiled_regex)

        self.assertEqual(name, None)

    def test_post_process_test_name(self):
        """
        Test post_process_test_name when all of the thing we want to remove are
        in the string
        """
        text = "builds/linux/testa/testb///....c.. 23{test1}[test2]test.c"
        cleaned = self.plugin.post_process_test_name(text)

        self.assertEqual(cleaned, "_testa_testb_______c__ test_c")

    def test_process_blocks_reset_by_make(self):
        blocks_to_process = [
            "make",
            "Entering",
            "In file",
            "In function",
            "error",
            "make",
            "error",
        ]
        regexes = [("test", "error", None)]
        snippets = self.plugin.process_blocks(
            blocks_to_process,
            regexes,
            make_regex="make",
            entering_dir_regex="Entering",
            leaving_dir_regex="Leaving",
            in_file_regex="In file",
            in_function_regex="In function",
        )

        expected = {0: ["make\nEntering\nIn file\nIn function\nerror", "make\nerror"]}

        self.assertEqual(snippets, expected)

    def test_process_blocks_reset_by_entering(self):
        blocks_to_process = [
            "make",
            "Entering",
            "In file",
            "In function",
            "error",
            "Entering",
            "error",
        ]
        regexes = [("test", "error", None)]
        snippets = self.plugin.process_blocks(
            blocks_to_process,
            regexes,
            make_regex="make",
            entering_dir_regex="Entering",
            leaving_dir_regex="Leaving",
            in_file_regex="In file",
            in_function_regex="In function",
        )

        expected = {
            0: ["make\nEntering\nIn file\nIn function\nerror", "make\nEntering\nerror"]
        }

        self.assertEqual(snippets, expected)

    def test_process_blocks_reset_by_leaving(self):
        blocks_to_process = [
            "make",
            "Entering",
            "In file",
            "In function",
            "error",
            "Leaving",
            "error",
        ]
        regexes = [("test", "error", None)]

        snippets = self.plugin.process_blocks(
            blocks_to_process,
            regexes,
            make_regex="make",
            entering_dir_regex="Entering",
            leaving_dir_regex="Leaving",
            in_file_regex="In file",
            in_function_regex="In function",
        )

        expected = {0: ["make\nEntering\nIn file\nIn function\nerror", "make\nerror"]}

        self.assertEqual(snippets, expected)

    def test_process_blocks_reset_by_in_file(self):
        blocks_to_process = [
            "make",
            "Entering",
            "In file",
            "In function",
            "error",
            "In file",
            "error",
        ]
        regexes = [("test", "error", None)]

        snippets = self.plugin.process_blocks(
            blocks_to_process,
            regexes,
            make_regex="make",
            entering_dir_regex="Entering",
            leaving_dir_regex="Leaving",
            in_file_regex="In file",
            in_function_regex="In function",
        )

        expected = {
            0: [
                "make\nEntering\nIn file\nIn function\nerror",
                "make\nEntering\nIn file\nerror",
            ]
        }

        self.assertEqual(snippets, expected)

    def test_split_by_regex_basic(self):
        log = "ababaabccda"
        split_log = self.plugin.split_by_regex(log, "(.*?)(a)")
        joined_split_log = "".join(split_log)

        expected = ["a", "b", "a", "b", "a", "a", "bccd", "a"]
        self.assertEqual(split_log, expected)
        self.assertEqual(joined_split_log, log)

    def test_split_by_regex_arm_gcc(self):
        testrun = self.new_testrun("gcc_arm_24951924.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_arm64_gcc(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_i386_gcc(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_riscv_gcc(self):
        testrun = self.new_testrun("gcc_riscv_24715191.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_x86_64_gcc(self):
        testrun = self.new_testrun("gcc_x86_64_24932905.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_arm_clang(self):
        testrun = self.new_testrun("clang_arm_26001178.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_arm64_clang(self):
        testrun = self.new_testrun("clang_arm64_25103120.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_i386_clang(self):
        testrun = self.new_testrun("clang_i386_25043392.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_riscv_clang(self):
        testrun = self.new_testrun("clang_riscv_24688299.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_split_by_regex_x86_64_clang(self):
        testrun = self.new_testrun("clang_x86_64_25086964.log")
        split_log = self.plugin.split_by_regex(testrun.log_file, split_regex_gcc)
        joined_split_log = "".join(split_log)

        self.assertGreater(len(split_log), 1)
        self.assertEqual(joined_split_log, testrun.log_file)

    def test_captures_make_gcc(self):
        testrun = self.new_testrun("gcc_arm_24951924.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-mm_vma_h-error-user_pgtables_ceiling-undeclared-first-use-in-this-function",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'CC=sccache arm-linux-gnueabihf-gcc' 'HOSTCC=sccache gcc'"""
        self.assertIn(expected, test.log)
        self.assertNotIn("cc1: some warnings being treated as errors", test.log)

    def test_captures_make_clang(self):
        testrun = self.new_testrun("clang_arm_26001178.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-test_zswap_c-warning-format-specifies-type-long-but-the-argument-has-type-size_t-aka-unsigned-int",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- HOSTCC=clang CC=clang LLVM=1 LLVM_IAS=1 kselftest-install"""
        self.assertIn(expected, test.log)
        self.assertNotIn("  CC       test_zswap", test.log)

    def test_captures_entering_dir_gcc(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-sve-ptrace_c-warning-format-d-expects-argument-of-type-int-but-argument-has-type-size_t",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make[5]: Entering directory '/builds/linux/tools/testing/selftests/arm64/fp'"""
        self.assertIn(expected, test.log)

    def test_captures_entering_dir_clang(self):
        testrun = self.new_testrun("clang_arm_26001178.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-test_zswap_c-warning-format-specifies-type-long-but-the-argument-has-type-size_t-aka-unsigned-int",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make[4]: Entering directory '/builds/linux/tools/testing/selftests/cgroup'"""
        self.assertIn(expected, test.log)

    def test_captures_in_file_single_line_gcc(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-iommufd_utils_h-warning-cast-from-pointer-to-integer-of-different-size",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """In file included from iommufd_fail_nth.c:23:"""

        self.assertIn(expected, test.log)

    def test_captures_in_file_single_line_clang(self):
        testrun = self.new_testrun("clang_arm_24958120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-mm_vma_h-error-use-of-undeclared-identifier-user_pgtables_ceiling",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """In file included from /builds/linux/mm/early_ioremap.c:20:"""
        self.assertIn(expected, test.log)

    def test_captures_in_file_multiline_gcc(self):
        testrun = self.new_testrun("gcc_arm_24951924.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-mm_vma_h-error-user_pgtables_ceiling-undeclared-first-use-in-this-function",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """In file included from /builds/linux/mm/internal.h:22,
                 from /builds/linux/mm/filemap.c:52:"""
        self.assertIn(expected, test.log)

    def test_captures_in_file_multiline_clang(self):
        testrun = self.new_testrun("clang_arm_24958120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-mm_vma_h-error-use-of-undeclared-identifier-user_pgtables_ceiling",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """In file included from /builds/linux/mm/filemap.c:52:
In file included from /builds/linux/mm/internal.h:22:"""
        self.assertIn(expected, test.log)

    def test_captures_in_function_single_line_gcc(self):
        # NOTE: Only GCC prints "In function" messages.
        testrun = self.new_testrun("gcc_arm_24951924.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-mm_vma_h-error-user_pgtables_ceiling-undeclared-first-use-in-this-function",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """/builds/linux/mm/vma.h: In function 'init_vma_munmap':"""
        self.assertIn(expected, test.log)
        self.assertNotIn("cc1: some warnings being treated as errors", test.log)

    def test_captures_in_function_multiline_gcc(self):
        # NOTE: Only GCC prints "In function" messages.
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-kselftest_h-error-impossible-constraint-in-asm",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """In function 'arch_supports_noncont_cat',
    inlined from 'noncont_cat_run_test' at cat_test.c:323:6:"""
        self.assertIn(expected, test.log)
        self.assertNotIn("cc1: some warnings being treated as errors", test.log)


class TestLinuxLogParserBuildGccRegexes(TestLinuxLogParserBuild):
    def test_gcc_compiler_error_basic(self):
        """Just check the error is captured and ignore the extra information
        captured such as the "In function" and "make" lines"""
        testrun = self.new_testrun("gcc_x86_64_24932905.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-kernel_sched_ext_c-error-initialization-of-bool-struct-rq-struct-task_struct-int-from-incompatible-pointer-type-void-struct-rq-struct-task_struct-int",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """/builds/linux/kernel/sched/ext.c:3630:35: error: initialization of 'bool (*)(struct rq *, struct task_struct *, int)' {aka '_Bool (*)(struct rq *, struct task_struct *, int)'} from incompatible pointer type 'void (*)(struct rq *, struct task_struct *, int)' [-Werror=incompatible-pointer-types]
 3630 |         .dequeue_task           = dequeue_task_scx,
      |                                   ^~~~~~~~~~~~~~~~"""
        self.assertIn(expected, test.log)

    def test_gcc_compiler_warning_basic(self):
        """Just check the warning is captured and ignore the extra information
        captured such as the "In function" and "make" lines"""
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-test_zswap_c-warning-format-ld-expects-argument-of-type-long-int-but-argument-has-type-size_t",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """test_zswap.c:38:32: warning: format '%ld' expects argument of type 'long int', but argument 3 has type 'size_t' {aka 'unsigned int'} [-Wformat=]
   38 |         ret = fprintf(file, "%ld\\n", value);
      |                              ~~^     ~~~~~
      |                                |     |
      |                                |     size_t {aka unsigned int}
      |                                long int
      |                              %d"""
        self.assertIn(expected, test.log)

    def test_gcc_compiler_error_with_arrow_and_hint(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-sve-ptrace_c-warning-format-d-expects-argument-of-type-int-but-argument-has-type-size_t",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/2/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/2/build/kselftest_install ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabihf- 'CC=sccache aarch64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[5]: Entering directory '/builds/linux/tools/testing/selftests/arm64/fp'
sve-ptrace.c: In function 'ptrace_set_sve_get_sve_data':
sve-ptrace.c:343:58: warning: format '%d' expects argument of type 'int', but argument 2 has type 'size_t' {aka 'long unsigned int'} [-Wformat=]
  343 |                 ksft_test_result_fail("Error allocating %d byte buffer for %s VL %u\\n",
      |                                                         ~^
      |                                                          |
      |                                                          int
      |                                                         %ld
  344 |                                       data_size, type->name, vl);
      |                                       ~~~~~~~~~           
      |                                       |
      |                                       size_t {aka long unsigned int}"""  # noqa: W291
        self.assertIn(expected, test.log)

    def test_gcc_compiler_error_with_single_line_note(self):
        testrun = self.new_testrun("gcc_arm_24951924.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-mm_vma_h-error-user_pgtables_ceiling-undeclared-first-use-in-this-function",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'CC=sccache arm-linux-gnueabihf-gcc' 'HOSTCC=sccache gcc'
In file included from /builds/linux/mm/internal.h:22,
                 from /builds/linux/mm/filemap.c:52:
/builds/linux/mm/vma.h: In function 'init_vma_munmap':
/builds/linux/mm/vma.h:184:26: error: 'USER_PGTABLES_CEILING' undeclared (first use in this function)
  184 |         vms->unmap_end = USER_PGTABLES_CEILING;
      |                          ^~~~~~~~~~~~~~~~~~~~~
/builds/linux/mm/vma.h:184:26: note: each undeclared identifier is reported only once for each function it appears in"""
        self.assertIn(expected, test.log)
        self.assertNotIn("cc1: some warnings being treated as errors", test.log)

    def test_gcc_compiler_warning_with_arrow(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-iommufd_utils_h-warning-cast-from-pointer-to-integer-of-different-size",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/iommu'
In file included from iommufd.c:10:
iommufd_utils.h: In function '_test_cmd_get_hw_info':
iommufd_utils.h:648:30: warning: cast from pointer to integer of different size [-Wpointer-to-int-cast]
  648 |                 .data_uptr = (uint64_t)data,
      |                              ^"""
        self.assertIn(expected, test.log)

    def test_gcc_does_not_capture_cc(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-utils_idle_monitor_mperf_monitor_c-warning-left-shift-count-width-of-type",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build DESTDIR=/home/tuxbuild/.cache/tuxmake/builds/1/build/cpupower-install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' -C tools/power/cpupower
utils/idle_monitor/mperf_monitor.c: In function 'get_aperf_mperf':
utils/idle_monitor/mperf_monitor.c:119:45: warning: left shift count >= width of type [-Wshift-count-overflow]
  119 |                 *mval = ((low_m) | (high_m) << 32);
      |                                             ^~"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "  CC       /home/tuxbuild/.cache/tuxmake/builds/1/build/utils/cpupower-info.o",
            test.log,
        )

    def test_gcc_multiline_note(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-ipsec_c-warning-format-ld-expects-argument-of-type-long-int-but-argument-has-type-ssize_t",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)

        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/net'
ipsec.c: In function '__write_desc':
ipsec.c:40:24: warning: format '%ld' expects argument of type 'long int', but argument 4 has type 'ssize_t' {aka 'int'} [-Wformat=]
   40 |         ksft_print_msg("%d[%u] " fmt "\\n", getpid(), __LINE__, ##__VA_ARGS__)
      |                        ^~~~~~~~~
ipsec.c:42:33: note: in expansion of macro 'printk'
   42 | #define pr_err(fmt, ...)        printk(fmt ": %m", ##__VA_ARGS__)
      |                                 ^~~~~~
ipsec.c:2028:9: note: in expansion of macro 'pr_err'
 2028 |         pr_err("Writing test's desc failed %ld", ret);
      |         ^~~~~~"""
        self.assertIn(expected, test.log)
        self.assertNotIn("  CC       ioam6_parser", test.log)

    def test_gcc_compiler_warning_with_dots(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-syscall-abi_c-warning-format-llx-expects-argument-of-type-long-long-unsigned-int-but-argument-has-type-uint_t",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/2/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/2/build/kselftest_install ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabihf- 'CC=sccache aarch64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[5]: Entering directory '/builds/linux/tools/testing/selftests/arm64/abi'
syscall-abi.c: In function 'check_fpr':
syscall-abi.c:115:79: warning: format '%llx' expects argument of type 'long long unsigned int', but argument 6 has type 'uint64_t' {aka 'long unsigned int'} [-Wformat=]
  115 |                                 ksft_print_msg("%s Q%d/%d mismatch %llx != %llx\\n",
      |                                                                            ~~~^
      |                                                                               |
      |                                                                               long long unsigned int
      |                                                                            %lx
......
  118 |                                                fpr_in[i], fpr_out[i]);
      |                                                           ~~~~~~~~~~           
      |                                                                  |
      |                                                                  uint64_t {aka long unsigned int}"""  # noqa: W291
        self.assertIn(expected, test.log)

    def test_gcc_compiler_warning_single_line(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-stdin-warning-warning-syscall-setxattrat-not-implemented",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/2/build ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabihf- 'CC=sccache aarch64-linux-gnu-gcc' 'HOSTCC=sccache gcc'
<stdin>:1603:2: warning: #warning syscall setxattrat not implemented [-Wcpp]"""
        self.assertIn(expected, test.log)

    def test_gcc_compiler_warning_command_line(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-command-line-warning-_gnu_source-redefined",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/2/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/2/build/kselftest_install ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabihf- 'CC=sccache aarch64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[5]: Entering directory '/builds/linux/tools/testing/selftests/arm64/signal'
<command-line>: warning: "_GNU_SOURCE" redefined
<command-line>: note: this is the location of the previous definition"""
        self.assertIn(expected, test.log)

    def test_gcc_compiler_avoid_kernel_is_ready(self):
        testrun = self.new_testrun("gcc_sh_26103296.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="gcc-compiler-kernel_fork_c-warning-warning-clone-entry-point-is-missing-please-fix",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=sh CROSS_COMPILE=sh4-linux-gnu- 'CC=sccache sh4-linux-gnu-gcc' 'HOSTCC=sccache gcc'
/builds/linux/kernel/fork.c: In function '__do_sys_clone3':
/builds/linux/kernel/fork.c:3095:2: warning: #warning clone3() entry point is missing, please fix [-Wcpp]
 3095 | #warning clone3() entry point is missing, please fix
      |  ^~~~~~~"""
        self.assertIn(expected, test.log)
        self.assertNotIn("Kernel: arch/sh/boot/zImage is ready", test.log)


class TestLinuxLogParserBuildClangRegexes(TestLinuxLogParserBuild):
    def test_clang_compiler_error_basic(self):
        """Just check the error is captured and ignore the extra information
        captured such as the "In function" and "make" lines"""
        testrun = self.new_testrun("clang_arm_24958120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-mm_vma_h-error-use-of-undeclared-identifier-user_pgtables_ceiling",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """/builds/linux/mm/vma.h:184:19: error: use of undeclared identifier 'USER_PGTABLES_CEILING'
  184 |         vms->unmap_end = USER_PGTABLES_CEILING;
      |                          ^"""
        self.assertIn(expected, test.log)

    def test_clang_compiler_warning_basic(self):
        """Just check the warning is captured and ignore the extra information
        captured such as the "In function", "make" lines or notes"""
        testrun = self.new_testrun("clang_arm64_25103120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-drivers_soc_rockchip_pm_domains_c-warning-shift-count-is-negative",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """/builds/linux/drivers/soc/rockchip/pm_domains.c:800:22: warning: shift count is negative [-Wshift-count-negative]
  800 |         [RK3399_PD_TCPD0]       = DOMAIN_RK3399(8, 8, -1, false),
      |                                   ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"""
        self.assertIn(expected, test.log)

    def test_clang_compiler_error_with_arrow_and_hint(self):
        testrun = self.new_testrun("clang_i386_25043392.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-net_xfrm_xfrm_policy_c-error-variable-dir-is-uninitialized-when-used-here",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'HOSTCC=sccache clang' 'CC=sccache clang' LLVM=1 LLVM_IAS=1
/builds/linux/net/xfrm/xfrm_policy.c:1287:8: error: variable 'dir' is uninitialized when used here [-Werror,-Wuninitialized]
 1287 |                 if ((dir & XFRM_POLICY_MASK) == XFRM_POLICY_OUT) {
      |                      ^~~
/builds/linux/net/xfrm/xfrm_policy.c:1258:9: note: initialize the variable 'dir' to silence this warning
 1258 |         int dir;
      |                ^
      |                 = 0"""
        self.assertIn(expected, test.log)

    def test_gcc_compiler_multiline_note(self):
        testrun = self.new_testrun("clang_arm64_25103120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-drivers_soc_rockchip_pm_domains_c-warning-shift-count-is-negative",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """/builds/linux/drivers/soc/rockchip/pm_domains.c:800:22: warning: shift count is negative [-Wshift-count-negative]
  800 |         [RK3399_PD_TCPD0]       = DOMAIN_RK3399(8, 8, -1, false),
      |                                   ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"""
        self.assertIn(expected, test.log)

    def test_clang_error_with_in_file(self):
        testrun = self.new_testrun("clang_arm_24958120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-mm_vma_h-error-use-of-undeclared-identifier-user_pgtables_ceiling",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'HOSTCC=sccache clang' 'CC=sccache clang' LLVM=1 LLVM_IAS=1
In file included from /builds/linux/mm/memblock.c:23:
In file included from /builds/linux/mm/internal.h:22:
/builds/linux/mm/vma.h:184:19: error: use of undeclared identifier 'USER_PGTABLES_CEILING'
  184 |         vms->unmap_end = USER_PGTABLES_CEILING;
      |                          ^"""
        self.assertIn(expected, test.log)

    def test_clang_compiler_warning_with_cc(self):
        testrun = self.new_testrun("clang_arm64_25103120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-drivers_soc_rockchip_pm_domains_c-warning-shift-count-is-negative",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """/builds/linux/drivers/soc/rockchip/pm_domains.c:802:21: warning: shift count is negative [-Wshift-count-negative]
  802 |         [RK3399_PD_CCI]         = DOMAIN_RK3399(10, 10, -1, true),
      |                                   ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
/builds/linux/drivers/soc/rockchip/pm_domains.c:133:2: note: expanded from macro 'DOMAIN_RK3399'
  133 |         DOMAIN(pwr, status, req, req, req, wakeup)
      |         ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
/builds/linux/drivers/soc/rockchip/pm_domains.c:93:27: note: expanded from macro 'DOMAIN'
   93 |         .req_mask = (req >= 0) ? BIT(req) : 0,          \\
      |                                  ^~~~~~~~
/builds/linux/include/linux/bits.h:8:26: note: expanded from macro 'BIT'
    8 | #define BIT(nr)                 (UL(1) << (nr))
      |                                        ^  ~~~~"""
        self.assertIn(expected, test.log)

    def test_clang_compiler_single_line(self):
        testrun = self.new_testrun("clang_arm_26001178.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-single-line-clang-error-linker-command-failed-with-exit-code-use-v-to-see-invocation",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- HOSTCC=clang CC=clang LLVM=1 LLVM_IAS=1 kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/net/lib'
clang: error: linker command failed with exit code 1 (use -v to see invocation)"""
        self.assertIn(expected, test.log)

    def test_clang_compiler_fatal_error(self):
        testrun = self.new_testrun("clang_arm_26001178.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="clang-compiler-fatal-error-fatal-error-too-many-errors-emitted-stopping-now",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- HOSTCC=clang CC=clang LLVM=1 LLVM_IAS=1 kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/rseq'
In file included from param_test.c:266:
In file included from ./rseq.h:114:
In file included from ./rseq-arm.h:150:
fatal error: too many errors emitted, stopping now [-ferror-limit=]"""
        self.assertIn(expected, test.log)


class TestLinuxLogParserBuildGeneralRegexes(TestLinuxLogParserBuild):
    def test_general_not_a_git_repo(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-not-a-git-repo-fatal-not-a-git-repository-or-any-parent-up-to-mount-point-_builds",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make -C /builds/linux/tools/testing/selftests/../../../tools/arch/arm64/tools/ OUTPUT=/builds/linux/tools/testing/selftests/../../../tools/
make[4]: Entering directory '/builds/linux/tools/testing/selftests/powerpc'
fatal: not a git repository (or any parent up to mount point /builds)
Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set)."""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "Makefile:60: warning: overriding recipe for target 'emit_tests'", test.log
        )

    def test_general_unexpected_argument(self):
        testrun = self.new_testrun("gcc_x86_64_24932905.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-unexpected-argument-error-found-argument-e-which-wasnt-expected-or-isnt-valid-in-this-context",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=x86_64 SRCARCH=x86 CROSS_COMPILE=x86_64-linux-gnu- 'CC=sccache x86_64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/hid'
error: Found argument '-E' which wasn't expected, or isn't valid in this context

USAGE:
    sccache [FLAGS] [OPTIONS] [cmd]...

For more information try --help"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "error: Found argument '-d' which wasn't expected, or isn't valid in this context",
            test.log,
        )

    def test_general_broken_32_bit(self):
        testrun = self.new_testrun("gcc_x86_64_24932905.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-broken-32-bit-warning-you-seem-to-have-a-broken-bit-build",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=x86_64 SRCARCH=x86 CROSS_COMPILE=x86_64-linux-gnu- 'CC=sccache x86_64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/x86'
Warning: you seem to have a broken 32-bit build
environment.  This will reduce test coverage of 64-bit
kernels.  If you are using a Debian-like distribution,
try:

  apt-get install gcc-multilib libc6-i386 libc6-dev-i386

If you are using a Fedora-like distribution, try:

  yum install glibc-devel.*i686

If you are using a SUSE-like distribution, try:

  zypper install gcc-32bit glibc-devel-static-32bit"""
        self.assertIn(expected, test.log)

    def test_general_broken_32_bit_avoid_lines_after(self):
        testrun = self.new_testrun("gcc_x86_64_26103833.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-broken-32-bit-warning-you-seem-to-have-a-broken-bit-build",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=x86_64 SRCARCH=x86 CROSS_COMPILE=x86_64-linux-gnu- 'CC=sccache x86_64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/x86'
Warning: you seem to have a broken 32-bit build
environment.  This will reduce test coverage of 64-bit
kernels.  If you are using a Debian-like distribution,
try:

  apt-get install gcc-multilib libc6-i386 libc6-dev-i386

If you are using a Fedora-like distribution, try:

  yum install glibc-devel.*i686

If you are using a SUSE-like distribution, try:

  zypper install gcc-32bit glibc-devel-static-32bit"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "Warning: missing Module.symvers, please have the kernel built first. page_frag test will be skipped.",
            test.log,
        )

    def test_general_makefile_overriding(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-makefile-overriding-makefile-warning-overriding-recipe-for-target-emit_tests",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/powerpc'
Makefile:60: warning: overriding recipe for target 'emit_tests'"""
        self.assertIn(expected, test.log)
        self.assertNotIn("make[4]: Nothing to be done for 'all'.", test.log)
        self.assertNotIn(
            "Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).",
            test.log,
        )

    def test_general_warning_unmet_dependencies(self):
        testrun = self.new_testrun("gcc_arm_25078650.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-unmet-dependencies-warning-unmet-direct-dependencies-detected-for-get_free_region",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'CC=sccache arm-linux-gnueabihf-gcc' 'HOSTCC=sccache gcc'
WARNING: unmet direct dependencies detected for GET_FREE_REGION
  Depends on [n]: SPARSEMEM [=n]
  Selected by [y]:
  - RESOURCE_KUNIT_TEST [=y] && RUNTIME_TESTING_MENU [=y] && KUNIT [=y]"""
        self.assertIn(expected, test.log)

    def test_general_lld_error(self):
        testrun = self.new_testrun("clang_riscv_24688299.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="general-ldd-ld_lld-error-undefined-symbol-irq_work_queue",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=riscv CROSS_COMPILE=riscv64-linux-gnu- 'HOSTCC=sccache clang' 'CC=sccache clang' LLVM=1 LLVM_IAS=1
ld.lld: error: undefined symbol: irq_work_queue
>>> referenced by task_work.c
>>>               kernel/task_work.o:(task_work_add) in archive vmlinux.a"""
        self.assertIn(expected, test.log)

    def test_general_ld_warning(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-ld-usr_lib_gcc-cross_i-linux-gnu______________i-linux-gnu_bin_ld-warning-creating-dt_textrel-in-a-pie",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/rseq'
/usr/lib/gcc-cross/i686-linux-gnu/13/../../../../i686-linux-gnu/bin/ld: warning: creating DT_TEXTREL in a PIE"""
        self.assertIn(expected, test.log)

    def test_general_ld_warning_with_note(self):
        testrun = self.new_testrun("gcc_arm_25044425.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-ld-arm-linux-gnueabihf-ld-warning-_home_tuxbuild__cache_tuxmake_builds__build_arch_arm_tests_regs_load_o-missing-_note_gnu-stack-section-implies-executable-stack",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build DESTDIR=/home/tuxbuild/.cache/tuxmake/builds/1/build/perf-install/usr ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'CC=sccache arm-linux-gnueabihf-gcc' 'HOSTCC=sccache gcc' -C tools/perf
arm-linux-gnueabihf-ld: warning: /home/tuxbuild/.cache/tuxmake/builds/1/build/arch/arm/tests/regs_load.o: missing .note.GNU-stack section implies executable stack
arm-linux-gnueabihf-ld: NOTE: This behaviour is deprecated and will be removed in a future version of the linker"""
        self.assertIn(expected, test.log)

    def test_general_ld_undefined_reference(self):
        testrun = self.new_testrun("gcc_riscv_24715191.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-ld-undefined-reference-task_work_c_text-undefined-reference-to-irq_work_queue",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=riscv CROSS_COMPILE=riscv64-linux-gnu- 'CC=sccache riscv64-linux-gnu-gcc' 'HOSTCC=sccache gcc'
riscv64-linux-gnu-ld: kernel/task_work.o: in function `task_work_add':
task_work.c:(.text+0x9a): undefined reference to `irq_work_queue'"""
        self.assertIn(expected, test.log)

    def test_general_objcopy_warning(self):
        testrun = self.new_testrun("gcc_s390_26103313.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-objcopy-sx-linux-gnu-objcopy-sttiujx-warning-allocated-section-_got_plt-not-in-segment",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=s390 CROSS_COMPILE=s390x-linux-gnu- 'CC=sccache s390x-linux-gnu-gcc' 'HOSTCC=sccache gcc'
s390x-linux-gnu-objcopy: st1TiUjX: warning: allocated section `.got.plt' not in segment"""
        self.assertIn(expected, test.log)

    def test_general_modpost(self):
        testrun = self.new_testrun("clang_arm64_25103120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="general-modpost-warning-modpost-found-section-mismatches",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """WARNING: modpost: Found 1 section mismatch(es).
To see full details build your kernel with:
'make CONFIG_DEBUG_SECTION_MISMATCH=y'"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "arch/arm64/boot/dts/qcom/ipq8074-hk01.dtb: Warning (pci_device_bus_num): Failed prerequisite 'reg_format'",
            test.log,
        )

    def test_general_python_traceback(self):
        testrun = self.new_testrun("clang_x86_64_26103794.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="general-python-traceback-modulenotfounderror-no-module-named-jsonschema",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=x86_64 SRCARCH=x86 CROSS_COMPILE=x86_64-linux-gnu- 'HOSTCC=sccache clang' 'CC=sccache clang' LLVM=1 LLVM_IAS=1 kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/net'
Traceback (most recent call last):
  File "/builds/linux/tools/net/ynl/generated/../ynl-gen-c.py", line 2945, in <module>
    main()
  File "/builds/linux/tools/net/ynl/generated/../ynl-gen-c.py", line 2655, in main
    parsed = Family(args.spec, exclude_ops)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/builds/linux/tools/net/ynl/generated/../ynl-gen-c.py", line 926, in __init__
    super().__init__(file_name, exclude_ops=exclude_ops)
  File "/builds/linux/tools/net/ynl/lib/nlspec.py", line 457, in __init__
    jsonschema = importlib.import_module("jsonschema")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.11/importlib/__init__.py", line 126, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1206, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1178, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1142, in _find_and_load_unlocked
ModuleNotFoundError: No module named 'jsonschema'"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "make[6]: *** [Makefile:37: netdev-user.c] Error 1",
            test.log,
        )

    def test_general_no_such_file_or_directory(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-no-such-file-or-directory-rsync-link_stat-__tools_testing_selftests_livepatch_test_modules__ko-failed-no-such-file-or-directory",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/livepatch'
rsync: [sender] link_stat "/builds/linux/tools/testing/selftests/livepatch/test_modules/*.ko" failed: No such file or directory (2)"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "rsync -a --copy-unsafe-links test_modules/*.ko /home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install/livepatch/test_modules",
            test.log,
        )
        self.assertNotIn(
            "rsync error: some files/attrs were not transferred (see previous errors) (code 23) at main.c(1338) [sender=3.3.0]",
            test.log,
        )

    def test_general_no_targets(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-no-targets-make-no-targets_-stop",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make -C /builds/linux/tools/testing/selftests/../../../tools/arch/arm64/tools/ OUTPUT=/builds/linux/tools/testing/selftests/../../../tools/
make[4]: *** No targets.  Stop."""
        self.assertIn(expected, test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/2/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/2/build/kselftest_install ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabihf- 'CC=sccache aarch64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/kexec'
make[4]: *** No targets.  Stop."""
        self.assertIn(expected, test.log)
        expected = """make -C /builds/linux/tools/testing/selftests/../../../tools/arch/arm64/tools/ OUTPUT=/builds/linux/tools/testing/selftests/../../../tools/
make[4]: Entering directory '/builds/linux/tools/testing/selftests/thermal/intel/power_floor'
make[4]: *** No targets.  Stop."""
        self.assertIn(expected, test.log)
        expected = """make -C /builds/linux/tools/testing/selftests/../../../tools/arch/arm64/tools/ OUTPUT=/builds/linux/tools/testing/selftests/../../../tools/
make[4]: Entering directory '/builds/linux/tools/testing/selftests/thermal/intel/workload_hint'
make[4]: *** No targets.  Stop."""
        self.assertIn(expected, test.log)

    def test_general_no_rule_to_make_target(self):
        testrun = self.new_testrun("gcc_x86_64_24932905.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-no-rule-to-make-target-make-no-rule-to-make-target-gcc_-stop",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=x86_64 SRCARCH=x86 CROSS_COMPILE=x86_64-linux-gnu- 'CC=sccache x86_64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/hid'
make[5]: *** No rule to make target 'gcc'.  Stop."""
        self.assertIn(expected, test.log)

    def test_general_makefile_config(self):
        testrun = self.new_testrun("gcc_arm_25044425.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-makefile-config-makefile_config-no-libcapstone-found-disables-disasm-engine-support-for-perf-script-please-install-libcapstone-dev_capstone-devel",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build DESTDIR=/home/tuxbuild/.cache/tuxmake/builds/1/build/perf-install/usr ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- 'CC=sccache arm-linux-gnueabihf-gcc' 'HOSTCC=sccache gcc' -C tools/perf
Makefile.config:1113: No libcapstone found, disables disasm engine support for 'perf script', please install libcapstone-dev/capstone-devel"""
        self.assertIn(expected, test.log)

    def test_general_not_found(self):
        testrun = self.new_testrun("gcc_arm64_24934206.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-not-found-bin_sh-clang-not-found",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make -C /builds/linux/tools/testing/selftests/../../../tools/arch/arm64/tools/ OUTPUT=/builds/linux/tools/testing/selftests/../../../tools/
make[4]: Entering directory '/builds/linux/tools/testing/selftests/net'
/bin/sh: 1: clang: not found"""
        self.assertIn(expected, test.log)

    def test_general_kerenel_abi(self):
        testrun = self.new_testrun("gcc_i386_25044475.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-kernel-abi-warning-kernel-abi-header-at-tools_include_uapi_linux_if_xdp_h-differs-from-latest-version-at-include_uapi_linux_if_xdp_h",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=i386 SRCARCH=x86 CROSS_COMPILE=i686-linux-gnu- 'CC=sccache i686-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/net'
In file included from io_uring_zerocopy_tx.c:39:
../../../include/io_uring/mini_liburing.h: In function 'io_uring_prep_cmd':
Warning: Kernel ABI header at 'tools/include/uapi/linux/if_xdp.h' differs from latest version at 'include/uapi/linux/if_xdp.h'"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "Warning: Kernel ABI header at 'tools/include/uapi/linux/bpf.h' differs from latest version at 'include/uapi/linux/bpf.h'",
            test.log,
        )

    def test_general_missing(self):
        testrun = self.new_testrun("gcc_x86_64_26103833.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-gcc",
            metadata__name="general-missing-warning-missing-module_symvers-please-have-the-kernel-built-first_-page_frag-test-will-be-skipped",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build INSTALL_PATH=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest_install ARCH=x86_64 SRCARCH=x86 CROSS_COMPILE=x86_64-linux-gnu- 'CC=sccache x86_64-linux-gnu-gcc' 'HOSTCC=sccache gcc' kselftest-install
make[4]: Entering directory '/builds/linux/tools/testing/selftests/mm'
Warning: missing Module.symvers, please have the kernel built first. page_frag test will be skipped."""
        self.assertIn(expected, test.log)

    def test_general_dtc_warning(self):
        testrun = self.new_testrun("clang_arm64_25103120.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="general-dtc-arch_arm_boot_dts_qcom_ipq-hk_dtb-warning-reg_format-_soc_nandb_nandreg-property-has-invalid-length-bytes-address-cells-size-cells",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make --silent --keep-going --jobs=8 O=/home/tuxbuild/.cache/tuxmake/builds/1/build ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- 'HOSTCC=sccache clang' 'CC=sccache clang' LLVM=1 LLVM_IAS=0 dtbs
arch/arm64/boot/dts/qcom/ipq8074-hk01.dtb: Warning (reg_format): /soc/nand@79b0000/nand@0:reg: property has invalid length (4 bytes) (#address-cells == 2, #size-cells == 1)"""
        self.assertIn(expected, test.log)
        self.assertNotIn(
            "arch/arm64/boot/dts/qcom/ipq8074-hk01.dtb: Warning (pci_device_bus_num): Failed prerequisite 'reg_format'",
            test.log,
        )

    def test_general_register_allocation(self):
        testrun = self.new_testrun("clang_i386_25431539.log")
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(
            suite__slug="log-parser-build-clang",
            metadata__name="general-register-allocation-error-register-allocation-failed-maximum-depth-for-recoloring-reached_-use-fexhaustive-register-search-to-skip-cutoffs",
        )
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        expected = """make  -C /builds/linux/tools/lib/bpf OUTPUT=/home/tuxbuild/.cache/tuxmake/builds/1/build/kselftest/net/tools/build/libbpf/     \\
make[4]: Entering directory '/builds/linux/tools/testing/selftests/rseq'
error: register allocation failed: maximum depth for recoloring reached. Use -fexhaustive-register-search to skip cutoffs"""
        self.assertIn(expected, test.log)
