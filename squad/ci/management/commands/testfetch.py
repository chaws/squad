import time
from squad.core.models import Group
from squad.ci.models import Backend
from squad.ci.tasks import fetch
from squad.ci.utils import task_id
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = """Listens for "live" test results from CI backends"""

    def add_arguments(self, parser):
        parser.add_argument(
            '--background', '-b',
            action='store_true',
            dest="background",
            help="Fetch in the background (requires a running worker)",
        )
        parser.add_argument(
            'BACKEND',
            type=str,
            help='Backend name to use to fetch',
        )
        parser.add_argument(
            'JOBID',
            type=str,
            help='Job id to fetch',
        )
        parser.add_argument(
            'PROJECT',
            type=str,
            help='Project to fetch the data into (Format: foo/bar)',
        )
        parser.add_argument(
            'BUILD',
            type=str,
            nargs="?",
            help='Build to fetch the data into',
        )

    def handle(self, *args, **options):
        backend_name = options.get("BACKEND")
        job_id = options.get("JOBID")
        group_slug, project_slug = options.get("PROJECT").split('/')
        _build = options.get("BUILD") or str(time.time())

        backend = Backend.objects.get(name=backend_name)

        group, _ = Group.objects.get_or_create(slug=group_slug)
        project, _ = group.projects.get_or_create(slug=project_slug)
        build, _ = project.builds.get_or_create(version=_build)

        testjob = backend.test_jobs.create(target=project, job_id=job_id, target_build=build)

        if options.get("background"):
            fetch.apply_async(args=(testjob.id,), task_id=task_id(testjob))
        else:
            backend.fetch(testjob.id)
