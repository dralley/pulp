"""
This module contains custom filters that might be used by more than one ViewSet.
"""
from gettext import gettext as _
from urllib.parse import urlparse
from django.urls import resolve, Resolver404
from django_filters import Filter, DateTimeFilter
from django_filters.fields import IsoDateTimeField

from rest_framework import serializers

from pulpcore.app.models import RepositoryVersion, RepositoryContent
from pulpcore.app.viewsets import NamedModelViewSet


class HyperlinkRelatedFilter(Filter):
    """
    Enables a user to filter by a foreign key using that FK's href
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('help_text', _('Foreign Key referenced by HREF'))
        super().__init__(*args, **kwargs)

    def filter(self, qs, value):
        """
        Args:
            qs (django.db.models.query.QuerySet): The Queryset to filter
            value (string): href containing pk for the foreign key instance

        Returns:
            django.db.models.query.QuerySet: Queryset filtered by the foreign key pk
        """

        if value is None:
            # value was not supplied by the user
            return qs

        if not value:
            raise serializers.ValidationError(
                detail=_('No value supplied for {name} filter.').format(name=self.field_name))
        try:
            match = resolve(urlparse(value).path)
        except Resolver404:
            raise serializers.ValidationError(detail=_('URI not valid: {u}').format(u=value))

        pk = match.kwargs['pk']

        key = "{}__pk".format(self.field_name)
        return qs.filter(**{key: pk})


class IsoDateTimeFilter(DateTimeFilter):
    """
    Uses IsoDateTimeField to support filtering on ISO 8601 formated datetimes.
    For context see:
    * https://code.djangoproject.com/ticket/23448
    * https://github.com/tomchristie/django-rest-framework/issues/1338
    * https://github.com/alex/django-filter/pull/264
    """
    field_class = IsoDateTimeField

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('help_text', _('ISO 8601 formatted dates are supported'))
        super().__init__(*args, **kwargs)


class ContentRepositoryVersionFilter(Filter):
    """
    Filter used to get the content of this type found in a repository version.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('help_text', _('Repository Version referenced by HREF'))
        super().__init__(*args, **kwargs)

    def filter(self, qs, value):
        """
        Args:
            qs (django.db.models.query.QuerySet): The RepositoryVersion Queryset
            value (string): of content href to filter

        Returns:
            Queryset of the RepositoryVersions containing the specified content
        """

        if value is None:
            # user didn't supply a value
            return qs

        if not value:
            raise serializers.ValidationError(
                detail=_('No value supplied for repository version filter'))

        # Get the repo_version object from the repository_version href
        repo_version = NamedModelViewSet.get_resource(value, RepositoryVersion)
        content_id_list = RepositoryContent.objects.filter(
            repository=repo_version.repository, version_added__number__lte=repo_version.number
        ).exclude(
            version_removed__number__lte=repo_version.number
        ).values_list("object_id", flat=True)

        return qs.filter(id__in=content_id_list)
