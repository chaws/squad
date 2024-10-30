import re
import requests
import celery

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from squad.http import auth_user_from_request


@csrf_exempt
@require_http_methods(['GET'])
def metrics(request):
    user = auth_user_from_request(request, request.user)
    if not user.is_authenticated:
        return HttpResponseForbidden()

    output = ''
    available_queues = None

    active_queues = celery.current_app.control.inspect().active_queues()
    if active_queues is not None:
        active_workers = set()
        available_queues = set()
        for worker_name, queues in active_queues.items():
            active_workers.add(worker_name)
            available_queues |= set([q['name'] for q in queues])

        output += '# TYPE workers_count counter\n'
        output += f'workers_count {len(active_workers)}\n'

    # TODO: check how to get metrics for non-RabbitMQ brokers
    if settings.CELERY_BROKER_URL:
        rabbitmq_url = settings.CELERY_BROKER_URL.replace('amqps://', 'https://').replace('amqp://', 'http://')
        rabbitmq_url = re.sub(r':\d+$', '', rabbitmq_url)
        rabbitmq_url += '/api/queues'

        response = requests.get(rabbitmq_url)
        queues = response.json()
        available_queues = {r["queue"] for r in settings.CELERY_TASK_ROUTES.values()}

        for queue in queues:
            if queue['name'] in available_queues:
                metric_name = f'queue_{queue["name"]}_count'
                length = queue['messages_ready']

                output += f'\n# TYPE {metric_name} counter'
                output += f'\n{metric_name} {length}'

    return HttpResponse(output, status=200, content_type="text/plain;")
