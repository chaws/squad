from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from enum import Enum
from rest_framework.authtoken.models import Token


from squad.core import models


class AuthMode(Enum):
    READ = 0
    WRITE = 1
    SUBMIT = 2


def auth_write(func):
    return auth(func, AuthMode.WRITE)


def auth_submit(func):
    return auth(func, AuthMode.SUBMIT)


def auth(func, mode=AuthMode.READ):
    def auth_wrapper(*args, **kwargs):
        request = args[0]
        group_slug = args[1]
        project_slug = args[2]

        group = get_object_or_404(models.Group, slug=group_slug)
        project = get_object_or_404(group.projects, slug=project_slug)

        request.group = group
        request.project = project

        tokenkey = request.META.get('HTTP_AUTH_TOKEN', None)
        user = request.user
        token = None
        if tokenkey:
            try:
                # truncate keys at 40 characters since djangorestframework's
                # Token keys are limited to 40 characters
                token = Token.objects.get(key=tokenkey[0:40])
                user = token.user
            except Token.DoesNotExist:
                pass

        if not (project.is_public or user.is_authenticated or token):
            raise PermissionDenied()

        if not project.accessible_to(user):
            # PermissionDenied = `401 Authentication needed` on purpose, and
            # not `403 Forbidden`.  If the project is not accessible to you,
            # you are not allowed to know whether that given team/project even
            # exists.
            raise PermissionDenied()

        if mode == AuthMode.SUBMIT and not project.can_submit(user):
            return HttpResponseForbidden()

        if mode == AuthMode.WRITE and not project.writable_by(user):
            return HttpResponseForbidden()

        # authentication OK, call the original view
        return func(*args, **kwargs)

    return auth_wrapper


def read_file_upload(stream):
    data = bytes()
    for chunk in stream.chunks():
        data = data + chunk
    return data
