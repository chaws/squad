import os
from django.test import TestCase
from squad.plugins.linux_log_parser import Plugin
from squad.core.models import Group


def read_sample_file(name):
    if not name.startswith('/'):
        name = os.path.join(os.path.dirname(__file__), 'linux_log_parser', name)
    return open(name).read()


class TestLinuxLogParser(TestCase):

    def setUp(self):
        group = Group.objects.create(slug='mygroup')
        self.project = group.projects.create(slug='myproject', enabled_plugins_list='example')
        self.build = self.project.builds.create(version='1')
        self.env = self.project.environments.create(slug='myenv')
        self.plugin = Plugin()

    def new_testrun(self, logfile, job_id='999'):
        log = read_sample_file(logfile)
        testrun = self.build.test_runs.create(environment=self.env, job_id=job_id)
        testrun.save_log_file(log)
        return testrun

    def test_detects_oops(self):
        testrun = self.new_testrun('oops.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='oops-oops-bug-preempt-smp')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Linux version 4.4.89-01529-gb29bace', test.log)
        self.assertIn('Internal error: Oops - BUG: 0 [#1] PREEMPT SMP', test.log)
        self.assertNotIn('Kernel panic', test.log)

    def test_detects_kernel_panic(self):
        testrun = self.new_testrun('kernelpanic-single-and-multiline.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='panic-multiline-kernel-panic-not-syncing-attempted-to-kill-the-idle-task')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('Kernel panic - not syncing', test.log)
        self.assertNotIn('Attempted to kill init! exitcode=0x00000009', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_exception(self):
        testrun = self.new_testrun('kernelexceptiontrace.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='exception-warning-cpu-pid-at-kernelsmpc-smp_call_function_many_cond')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('WARNING: CPU: 0 PID: 1 at kernel/smp.c:912 smp_call_function_many_cond+0x3c4/0x3c8', test.log)
        self.assertIn('5fe0: 0000000b be963e80 b6f142d9 b6f0e648 60000030 ffffffff"}', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_exception_without_square_braces(self):
        testrun = self.new_testrun('kernelexceptiontrace_without_squarebraces.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='exception-warning-cpu-pid-at-kernelsmpc-smp_call_function_many_cond')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('WARNING: CPU: 0 PID: 1 at kernel/smp.c:912 smp_call_function_many_cond+0x3c4/0x3c8', test.log)
        self.assertIn('5fe0: 0000000b be963e80 b6f142d9 b6f0e648 60000030 ffffffff"}', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_kasan(self):
        testrun = self.new_testrun('kasan.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='kasan-bug-kasan-slab-out-of-bounds-in-kmalloc_oob_right')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('==================================================================', test.log)
        self.assertIn('BUG: KASAN: slab-out-of-bounds in kmalloc_oob_right+0x190/0x3b8', test.log)
        self.assertIn('Write of size 1 at addr c6aaf473 by task kunit_try_catch/191', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_kcsan_simple(self):
        testrun = self.new_testrun('kcsan_simple.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='kcsan-bug-kcsan-data-race-in-do_page_fault-spectre_v_enable_task_mitigation')

        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('==================================================================', test.log)
        self.assertIn('BUG: KCSAN: data-race in do_page_fault spectre_v4_enable_task_mitigation', test.log)
        self.assertIn('write to 0xffff80000f00bfb8 of 8 bytes by task 93 on cpu 0:', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_kcsan_full_log(self):
        testrun = self.new_testrun('kcsan_full_log.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-boot', metadata__name='kcsan-bug-kcsan-data-race-in-set_nlink-set_nlink')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('==================================================================', test.log)
        self.assertIn('BUG: KCSAN: data-race in set_nlink / set_nlink', test.log)
        self.assertIn('read to 0xffff54a501072a08 of 4 bytes by task 137 on cpu 1:', test.log)
        self.assertNotIn('BUG: KCSAN: data-race in __hrtimer_run_queues / hrtimer_active', test.log)

    def test_detects_kernel_panic_multiline(self):
        testrun = self.new_testrun('kernelpanic-multiline.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='panic-multiline-kernel-panic-not-syncing-attempted-to-kill-init-exitcode')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn(' Kernel panic - not syncing: Attempted to kill init! exitcode=0x0000000b', test.log)
        self.assertIn('SMP: stopping secondary CPUs', test.log)
        self.assertNotIn('note: swapper/0[1] exited with preempt_count 1', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_internel_error_oops(self):
        testrun = self.new_testrun('internal-error-oops.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='internal-error-oops-oops-bti-preempt-smp')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('Internal error: Oops - BTI: 0000000036000002 [#1] PREEMPT SMP', test.log)
        self.assertIn('Modules linked in: pl111_drm drm_dma_helper panel_simple arm_spe_pmu crct10dif_ce drm_kms_helper fuse drm backlight dm_mod ip_tables x_tables', test.log)
        self.assertNotIn('ok 1 - selftest-setup: selftest: setup: smp: number of CPUs matches expectation', test.log)

    def test_detects_kernel_kfence(self):
        testrun = self.new_testrun('kfence.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='kfence-bug-kfence-memory-corruption-in-kfree')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('==================================================================', test.log)
        self.assertIn('BUG: KFENCE: memory corruption in kfree+0x8c/0x174', test.log)
        self.assertIn('Corrupted memory at 0x00000000c5d55ff8 [ ! ! ! . . . . . . . . . . . . . ] (in kfence-#214):', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_bug(self):
        testrun = self.new_testrun('oops.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='bug-bug-spinlock-lockup-suspected-on-cpu-gdbus')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('] BUG:', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

        testrun = self.new_testrun('kernel_bug_and_invalid_opcode.log', job_id='1000')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='exception-kernel-bug-at-usrsrckernelarchxkvmmmummuc')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('] kernel BUG at', test.log)
        self.assertNotIn('] BUG:', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_kernel_invalid_opcode(self):
        testrun = self.new_testrun('kernel_bug_and_invalid_opcode.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='invalid-opcode-invalid-opcode-smp-pti')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Booting Linux', test.log)
        self.assertIn('] invalid opcode:', test.log)
        self.assertNotIn('] BUG:', test.log)
        self.assertNotIn('Internal error: Oops', test.log)

    def test_detects_multiple(self):
        testrun = self.new_testrun('multiple_issues_dmesg.log')
        self.plugin.postprocess_testrun(testrun)

        tests = testrun.tests
        test_panic = tests.get(suite__slug='log-parser-test', metadata__name='panic-multiline-kernel-panic-not-syncing-stack-protector-kernel-stack-is-corrupted-in-ffffffffcc')
        test_exception = tests.get(suite__slug='log-parser-test', metadata__name='exception-warning-cpu-pid-at-driversgpudrmradeonradeon_objectc-radeon_ttm_bo_destroy')
        test_warning = tests.get(suite__slug='log-parser-test', metadata__name='warning-warning-cpu-pid-at-driversregulatorcorec-_regulator_putpart')
        test_oops = tests.get(suite__slug='log-parser-test', metadata__name='oops-oops-preempt-smp')
        test_fault = tests.get(suite__slug='log-parser-test', metadata__name='fault-unhandled-fault-external-abort-on-non-linefetch-at')

        self.assertFalse(test_panic.result)
        self.assertNotIn('Boot CPU', test_panic.log)
        self.assertIn('Kernel panic - not syncing', test_panic.log)

        self.assertFalse(test_exception.result)
        self.assertNotIn('Boot CPU', test_exception.log)
        self.assertIn('------------[ cut here ]------------', test_exception.log)

        self.assertFalse(test_warning.result)
        self.assertNotIn('Boot CPU', test_warning.log)
        self.assertNotIn('Kernel panic - not syncing', test_warning.log)
        self.assertNotIn('------------[ cut here ]------------', test_warning.log)
        self.assertNotIn('Unhandled fault:', test_warning.log)
        self.assertNotIn('Oops', test_warning.log)
        self.assertIn('WARNING: CPU', test_warning.log)

        self.assertFalse(test_oops.result)
        self.assertNotIn('Boot CPU', test_oops.log)
        self.assertNotIn('Kernel panic - not syncing', test_oops.log)
        self.assertNotIn('------------[ cut here ]------------', test_oops.log)
        self.assertNotIn('WARNING: CPU', test_oops.log)
        self.assertNotIn('Unhandled fault:', test_oops.log)
        self.assertIn('Oops', test_oops.log)

        self.assertFalse(test_fault.result)
        self.assertNotIn('Boot CPU', test_fault.log)
        self.assertNotIn('Kernel panic - not syncing', test_fault.log)
        self.assertNotIn('------------[ cut here ]------------', test_fault.log)
        self.assertNotIn('WARNING: CPU', test_fault.log)
        self.assertNotIn('Oops', test_fault.log)
        self.assertIn('Unhandled fault:', test_fault.log)

    def test_two_testruns_distinct_test_names(self):
        testrun1 = self.new_testrun('/dev/null', 'job1')
        testrun2 = self.new_testrun('/dev/null', 'job2')

        self.plugin.postprocess_testrun(testrun1)
        self.plugin.postprocess_testrun(testrun2)

        self.assertNotEqual(testrun1.tests.all(), testrun2.tests.all())

    def test_rcu_warning(self):
        testrun = self.new_testrun('rcu_warning.log')
        self.plugin.postprocess_testrun(testrun)

        tests = testrun.tests
        test_warning = tests.get(suite__slug='log-parser-test', metadata__name='warning-warning-suspicious-rcu-usage')

        self.assertFalse(test_warning.result)

        self.assertIn('WARNING: suspicious RCU usage', test_warning.log)

    def test_no_string(self):
        testrun = self.build.test_runs.create(environment=self.env, job_id='1111')
        self.plugin.postprocess_testrun(testrun)

        tests = testrun.tests.filter(result=False)
        self.assertEqual(0, tests.count())

    def test_metadata_creation(self):
        log = '[ 0.0 ] Kernel panic - not syncing'
        testrun = self.build.test_runs.create(environment=self.env, job_id='999')
        testrun.save_log_file(log)
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-test', metadata__name='panic-kernel-panic-not-syncing')
        self.assertIsNotNone(test.metadata)

    def test_boot_log(self):
        testrun = self.new_testrun('oops.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-boot', metadata__name='internal-error-oops-oops-bug-preempt-smp')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Linux version 4.4.89-01529-gb29bace', test.log)
        self.assertIn('Internal error: Oops - BUG: 0 [#0] PREEMPT SMP', test.log)
        self.assertNotIn('Kernel panic', test.log)

    def test_sha_name(self):
        testrun = self.new_testrun('oops.log')
        self.plugin.postprocess_testrun(testrun)

        test = testrun.tests.get(suite__slug='log-parser-boot', metadata__name='internal-error-oops-oops-bug-preempt-smp')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertNotIn('Linux version 4.4.89-01529-gb29bace', test.log)
        self.assertIn('Internal error: Oops - BUG: 0 [#0] PREEMPT SMP', test.log)
        self.assertNotIn('Kernel panic', test.log)

        # Now check if a test with sha digest in the name
        test = testrun.tests.get(suite__slug='log-parser-boot', metadata__name='internal-error-oops-oops-bug-preempt-smp-112aca90e0eaf87ac104ae4e9aeea46f2757ac81faf013c77696d081c109aecc')
        self.assertFalse(test.result)
        self.assertIsNotNone(test.log)
        self.assertIn('Internal error: Oops - BUG: 0 [#0] PREEMPT SMP', test.log)
        self.assertNotIn('Internal error: Oops - BUG: 99 [#1] PREEMPT SMP', test.log)

    def test_sha_name_multiple(self):
        testrun = self.new_testrun('multiple_issues_dmesg.log')
        self.plugin.postprocess_testrun(testrun)

        tests = testrun.tests

        test_panic = tests.get(suite__slug='log-parser-test', metadata__name='panic-multiline-kernel-panic-not-syncing-stack-protector-kernel-stack-is-corrupted-in-ffffffffcc-18fbe2dd02a2df7ba9e8d2ef289ca7b76beb8f8f8253621ff47902378ee6df11')
        test_exception = tests.get(suite__slug='log-parser-test', metadata__name='exception-warning-cpu-pid-at-driversgpudrmradeonradeon_objectc-radeon_ttm_bo_destroy-77251099bfa081e5c942070a569fe31163336e61a80bda7304cd59f0f4b82080')
        test_warning = tests.get(suite__slug='log-parser-test', metadata__name='warning-warning-cpu-pid-at-driversregulatorcorec-_regulator_putpart-d44949024d5373185a7381cb9dd291b13c117d6b93feb576a431e5376025004f')
        test_oops = tests.get(suite__slug='log-parser-test', metadata__name='oops-oops-preempt-smp-4e1ddddb2c142178a8977e7d973c2a13db2bb978aa471c0049ee39fe3fe4d74c')
        test_fault = tests.get(suite__slug='log-parser-test', metadata__name='fault-unhandled-fault-external-abort-on-non-linefetch-at-6f9e3ab8f97e35c1e9167fed1e01c6149986819c54451064322b7d4208528e07')

        self.assertFalse(test_panic.result)
        self.assertNotIn('Boot CPU', test_panic.log)
        self.assertIn('Kernel panic - not syncing', test_panic.log)

        self.assertFalse(test_exception.result)
        self.assertNotIn('Boot CPU', test_exception.log)
        self.assertIn('------------[ cut here ]------------', test_exception.log)

        self.assertFalse(test_warning.result)
        self.assertNotIn('Boot CPU', test_warning.log)
        self.assertNotIn('Kernel panic - not syncing', test_warning.log)
        self.assertNotIn('------------[ cut here ]------------', test_warning.log)
        self.assertNotIn('Unhandled fault:', test_warning.log)
        self.assertNotIn('Oops', test_warning.log)
        self.assertIn('WARNING: CPU', test_warning.log)

        self.assertFalse(test_oops.result)
        self.assertNotIn('Boot CPU', test_oops.log)
        self.assertNotIn('Kernel panic - not syncing', test_oops.log)
        self.assertNotIn('------------[ cut here ]------------', test_oops.log)
        self.assertNotIn('WARNING: CPU', test_oops.log)
        self.assertNotIn('Unhandled fault:', test_oops.log)
        self.assertIn('Oops', test_oops.log)

        self.assertFalse(test_fault.result)
        self.assertNotIn('Boot CPU', test_fault.log)
        self.assertNotIn('Kernel panic - not syncing', test_fault.log)
        self.assertNotIn('------------[ cut here ]------------', test_fault.log)
        self.assertNotIn('WARNING: CPU', test_fault.log)
        self.assertNotIn('Oops', test_fault.log)
        self.assertIn('Unhandled fault:', test_fault.log)
