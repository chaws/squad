from django.utils.translation import ugettext as _
from squad.core.models import Metric, TestRun
from squad.core.utils import join_name, split_list


def get_metrics_list(project):
    import time
    start_time = time.time()
    print('starting at %s' % start_time)
    unique_names = set()

    testruns = TestRun.objects.filter(environment__project=project).values('id').order_by('id')
    test_runs_ids = [tr['id'] for tr in testruns]
    print('It took %s to query testruns' % (time.time() - start_time))
    start_time = time.time()

    for chunk in split_list(test_runs_ids, chunk_size=200):
        metrics = Metric.objects.filter(test_run_id__in=chunk).prefetch_related('suite')
        for m in metrics:
            unique_names.add(join_name(m.suite.slug, m.name))

    print('It took %s to query all metrics' % (time.time() - start_time))
    start_time = time.time()
    
    metric_names = [{"name": name} for name in sorted(unique_names
    )]
    print('It took %s to order all metrics' % (time.time() - start_time))

    metrics = [{"name": ":summary:", "label": _("Summary of all metrics per build")}]
    metrics += [{"name": ":dynamic_summary:", "label": _("Summary of selected metrics"), "dynamic": "yes"}]
    metrics += [{"name": ":tests:", "label": _("Test pass %"), "max": 100, "min": 0}]
    metrics += metric_names
    return metrics
