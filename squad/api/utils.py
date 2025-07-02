from base64 import b64decode
from squad.compat import RestFrameworkFilterBackend
from rest_framework.exceptions import NotFound
from rest_framework.pagination import Cursor, CursorPagination, _positive_int
from rest_framework.renderers import BrowsableAPIRenderer
from urllib import parse


class DisabledHTMLFilterBackend(RestFrameworkFilterBackend):

    def to_html(self, request, queryset, view):
        return ""


class CursorPaginationWithPageSize(CursorPagination):
    page_size_query_param = 'limit'
    ordering = '-id'

    def decode_cursor(self, request):
        """
        Given a request with a cursor, return a `Cursor` instance.

        This is an overwritten implementation of the parent function [1]. The parent function
        is vulnerable to cursor manipulation.

        Example: a cursor with value "cj0xJnA9Y29yZS5Lbm93bklzc3VlLk5vbmU=" is decoded to
        "r=1&p=core.KnownIssue.None". And that would make into one of the queries

        [1] https://github.com/encode/django-rest-framework/blob/30384947053b1f2b2c9e82cafd1da934d3442a61/rest_framework/pagination.py#L846
        """
        # Determine if we have a cursor, and if so then decode it.
        encoded = request.query_params.get(self.cursor_query_param)
        if encoded is None:
            return None

        try:
            querystring = b64decode(encoded.encode('ascii')).decode('ascii')
            tokens = parse.parse_qs(querystring, keep_blank_values=True)

            offset = tokens.get('o', ['0'])[0]
            offset = _positive_int(offset, cutoff=self.offset_cutoff)

            reverse = tokens.get('r', ['0'])[0]
            reverse = bool(int(reverse))

            # Make sure `position` is an integer
            position = int(tokens.get('p', [None])[0])
        except (TypeError, ValueError):
            raise NotFound(self.invalid_cursor_message)

        return Cursor(offset=offset, reverse=reverse, position=position)


# ref: https://bradmontgomery.net/blog/disabling-forms-django-rest-frameworks-browsable-api/
class BrowsableAPIRendererWithoutForms(BrowsableAPIRenderer):
    """Renders the browsable api, but excludes the forms."""

    def get_context(self, *args, **kwargs):
        ctx = super().get_context(*args, **kwargs)
        ctx['display_edit_forms'] = False
        return ctx

    def show_form_for_method(self, view, method, request, obj):
        """We never want to do this! So just return False."""
        return False

    def get_rendered_html_form(self, data, view, method, request):
        """Why render _any_ forms at all. This method should return
        rendered HTML, so let's simply return an empty string.
        """
        return ""
