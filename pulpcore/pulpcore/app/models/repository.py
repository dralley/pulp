"""
Repository related Django models.
"""
from collections import defaultdict
from contextlib import suppress
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from .base import Model, MasterModel
from .generic import Notes, GenericKeyValueRelation
from .task import CreatedResource

from pulpcore.app.models.storage import get_tls_path
from pulpcore.exceptions import ResourceImmutableError


class Repository(Model):
    """
    Collection of content.

    Fields:

        name (models.TextField): The repository name.
        description (models.TextField): An optional description.
        last_version (models.PositiveIntegerField): A record of the last created version number.
            Used when a repository version is deleted so as not to create a new vesrion with the
            same version number.

    Relations:

        notes (GenericKeyValueRelation): Arbitrary repository properties.
    """
    name = models.TextField(db_index=True, unique=True)
    description = models.TextField()
    last_version = models.PositiveIntegerField(default=0)

    notes = GenericKeyValueRelation(Notes)
    content = GenericRelation('RepositoryContent')

    class Meta:
        verbose_name_plural = 'repositories'

    def natural_key(self):
        """
        Get the model's natural key.

        :return: The model's natural key.
        :rtype: tuple
        """
        return (self.name,)


class Remote(MasterModel):
    """
    A content remote.

    Fields:

        url (models.TextField): The URL of an external content source.
        validate (models.BooleanField): If True, the plugin will validate imported files.
        ssl_ca_certificate (models.FileField): A PEM encoded CA certificate used to validate the
            server certificate presented by the external source.
        ssl_client_certificate (models.FileField): A PEM encoded client certificate used
            for authentication.
        ssl_client_key (models.FileField): A PEM encoded private key used for authentication.
        ssl_validation (models.BooleanField): If True, SSL peer validation must be performed.
        proxy_url (models.TextField): The optional proxy URL.
            Format: scheme://user:password@host:port
        username (models.TextField): The username to be used for authentication when syncing.
        password (models.TextField): The password to be used for authentication when syncing.
        last_synced (models.DatetimeField): Timestamp of the most recent successful sync.
        connection_limit (models.PositiveIntegerField): Total number of simultaneous connections.

    Relations:

        repository (models.ForeignKey): The repository that owns this Remote
    """
    TYPE = 'remote'

    def tls_storage_path(self, name):
        """
        Returns storage path for TLS file

        Args:
            name (str): Original name of the uploaded file.
        """
        return get_tls_path(self, name)

    name = models.TextField(db_index=True, unique=True)

    url = models.TextField()
    validate = models.BooleanField(default=True)

    ssl_ca_certificate = models.FileField(upload_to=tls_storage_path, max_length=255)
    ssl_client_certificate = models.FileField(upload_to=tls_storage_path,
                                              max_length=255)
    ssl_client_key = models.FileField(upload_to=tls_storage_path, max_length=255)
    ssl_validation = models.BooleanField(default=True)

    proxy_url = models.TextField()
    username = models.TextField()
    password = models.TextField()
    last_synced = models.DateTimeField(null=True)
    connection_limit = models.PositiveIntegerField(default=20)

    class Meta:
        default_related_name = 'remotes'


class Publisher(MasterModel):
    """
    A content publisher.

    Fields:

        last_published (models.DatetimeField): When the last successful publish occurred.

    Relations:

    """
    TYPE = 'publisher'

    name = models.TextField(db_index=True, unique=True)
    last_published = models.DateTimeField(null=True)

    class Meta:
        default_related_name = 'publishers'


class Exporter(MasterModel):
    """
    A publication exporter.

    Fields:

        name (models.TextField): The exporter unique name.
        last_export (models.DatetimeField): When the last successful export occurred.

    Relations:

    """
    TYPE = 'exporter'

    name = models.TextField(db_index=True, unique=True)
    last_export = models.DateTimeField(null=True)

    class Meta:
        default_related_name = 'exporters'


class RepositoryContent(Model):
    """
    Association between a repository and its contained content.

    Fields:

        created (models.DatetimeField): When the association was created.

    Relations:

        content (models.ForeignKey): The associated content.
        repository (models.ForeignKey): The associated repository.
        version_added (models.ForeignKey): The RepositoryVersion which added the referenced
            Content.
        version_removed (models.ForeignKey): The RepositoryVersion which removed the referenced
            Content.
    """
    object_id = models.PositiveIntegerField()
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    content = GenericForeignKey('content_type', 'object_id')
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
    version_added = models.ForeignKey('RepositoryVersion', related_name='added_memberships',
                                      on_delete=models.CASCADE)
    version_removed = models.ForeignKey('RepositoryVersion', null=True,
                                        related_name='removed_memberships',
                                        on_delete=models.CASCADE)

    class Meta:
        unique_together = (('repository', 'content_type', 'object_id', 'version_added'),
                           ('repository', 'content_type', 'object_id', 'version_removed'))


class RepositoryVersion(Model):
    """
    A version of a repository's content set.

    Plugin Writers are strongly encouraged to use RepositoryVersion as a context manager to provide
    transactional safety, working directory set up, and cleaning up the database on failures.

    Examples:
        >>>
        >>> with RepositoryVersion.create(repository) as new_version:
        >>>     new_version.add_content(content_q)
        >>>     new_version.remove_content(content_q)
        >>>

    Fields:

        number (models.PositiveIntegerField): A positive integer that uniquely identifies a version
            of a specific repository. Each new version for a repo should have this field set to
            1 + the most recent version.
        action  (models.TextField): The action that produced the version.
        complete (models.BooleanField): If true, the RepositoryVersion is visible. This field is set
            to true when the task that creates the RepositoryVersion is complete.

    Relations:

        repository (models.ForeignKey): The associated repository.
    """
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
    number = models.PositiveIntegerField(db_index=True)
    complete = models.BooleanField(db_index=True, default=False)
    base_version = models.ForeignKey('RepositoryVersion', null=True,
                                     on_delete=models.SET_NULL)

    class Meta:
        default_related_name = 'versions'
        unique_together = ('repository', 'number')
        get_latest_by = 'number'
        ordering = ('number',)

    def content(self):
        """
        Returns a dictionary of QuerySet objects, each one matching all units for a single content type.

        Returns:
            A dictionary of ContentTypes and the associated Content querysets.
            {:class:`django.contrib.contenttypes.models`:: :class:`django.db.models.QuerySet`:}

        Examples:
            >>> repository_version = ...
            >>>
            >>> for content_qs in repository_version.content():
            >>>     for content in content_qs:  # this loops over one type of content only
            >>>         ...
        """
        relationships = RepositoryContent.objects.filter(
            repository=self.repository, version_added__number__lte=self.number
        ).exclude(
            version_removed__number__lte=self.number
        ).values("content_type_id", "object_id")

        repo_content_by_type = defaultdict(set)
        for relationship in relationships:
            content_type_id = relationship['content_type_id']
            repo_content_by_type[content_type_id].add(relationship['object_id'])

        querysets_to_return = {}
        for content_type_id, id_list in repo_content_by_type.items():
            content_type = ContentType.objects.get(id=content_type_id)
            # content_type_name = "{model}".format(model=content_type.model)
            qs = content_type.model_class().objects.filter(id__in=id_list)
            querysets_to_return[content_type] = qs

        return querysets_to_return

    def contains(self, content):
        """
        Check whether a content exists in this repository version's set of content

        Returns:
            bool: True if the repository version contains the content, False otherwise
        """
        for ctype, content_qs in self.content().items():
            if isinstance(content, ctype.model_class()):
                if content_qs.filter(pk=content.pk).exists():
                    return True

        return False

    @property
    def content_summary(self):
        """
        The summary of content in the repository version.

        Returns the types of content present and the counts of those types.

        Returns:
            dict: of {<type>: <count>}
        """
        content_summary = {}
        for content_type, queryset in self.content().items():
            content_summary[content_type.model] = queryset.count()
        return content_summary

    @classmethod
    def create(cls, repository, base_version=None):
        """
        Create a new RepositoryVersion.

        Creation of a RepositoryVersion should be done in a RQ Job.

        Args:
            repository (pulpcore.app.models.Repository): to create a new version of
            base_version (pulpcore.app.models.RepositoryVersion): an optional repository version
                whose content will be used as the set of content for the new version

        Returns:
            pulpcore.app.models.RepositoryVersion: The Created RepositoryVersion
        """

        with transaction.atomic():
            version = cls(
                repository=repository,
                number=int(repository.last_version) + 1,
                base_version=base_version)
            repository.last_version = version.number
            repository.save()
            version.save()

            if base_version:
                # first remove the content that isn't in the base version
                for ctype, typed_content in version.content().items():
                    base_content = base_version.content()
                    if ctype in base_content:
                        base_typed_content = base_content[ctype]
                        version.remove_content(typed_content.exclude(base_typed_content))
                    else:
                        version.remove_content(typed_content)

                # now add any content that's in the base_version but not in version
                for ctype, typed_content in base_version.content().items():
                    version_content = version.content()
                    if ctype in version_content:
                        version_typed_content = version_content[ctype]
                        version.add_content(typed_content.exclude(version_typed_content))
                    else:
                        version.add_content(typed_content)

            resource = CreatedResource(content_object=version)
            resource.save()
            return version

    @staticmethod
    def latest(repository):
        """
        Get the latest RepositoryVersion on a repository

        Args:
            repository (pulpcore.app.models.Repository): to get the latest version of

        Returns:
            pulpcore.app.models.RepositoryVersion: The latest RepositoryVersion

        """
        with suppress(RepositoryVersion.DoesNotExist):
            model = repository.versions.exclude(complete=False).latest()
            return model

    def added(self):
        """
        Returns:
            QuerySet: The Content objects that were added by this version.

        TODO: deduplicate code with content()?

        """
        relationships = RepositoryContent.objects.filter(
            version_added=self
        ).values("content_type_id", "object_id")

        repo_content_by_type = defaultdict(set)
        for relationship in relationships:
            content_type_id = relationship['content_type_id']
            repo_content_by_type[content_type_id].add(relationship['object_id'])

        querysets_to_return = {}
        for content_type_id, id_list in repo_content_by_type.items():
            content_type = ContentType.objects.get(id=content_type_id)
            qs = content_type.model_class().objects.filter(id__in=id_list)
            querysets_to_return[content_type] = qs

        return querysets_to_return

    def removed(self):
        """
        Returns:
            QuerySet: The Content objects that were removed by this version.

        TODO: deduplicate code with content()?

        """
        relationships = RepositoryContent.objects.filter(
            version_removed=self
        ).values("content_type_id", "object_id")

        repo_content_by_type = defaultdict(set)
        for relationship in relationships:
            content_type_id = relationship['content_type_id']
            repo_content_by_type[content_type_id].add(relationship['object_id'])

        querysets_to_return = {}
        for content_type_id, id_list in repo_content_by_type.items():
            content_type = ContentType.objects.get(id=content_type_id)
            qs = content_type.model_class().objects.filter(id__in=id_list)
            querysets_to_return[content_type] = qs

        return querysets_to_return

    def next(self):
        """
        Returns:
            pulpcore.app.models.RepositoryVersion: The next RepositoryVersion with the same
                repository.

        Raises:
            RepositoryVersion.DoesNotExist: if there is not a RepositoryVersion for the same
                repository and with a higher "number".
        """
        try:
            return self.repository.versions.exclude(complete=False).filter(
                number__gt=self.number).order_by('number')[0]
        except IndexError:
            raise self.DoesNotExist

    def add_content(self, content):
        """
        Add content to this version.

        One or more :class:`django.db.models.QuerySet` can be passed in to `content`. All units
        matched by all :class:`~django.db.models.QuerySet` objects are associated.

        Args:
            content (:class:`django.db.models.QuerySet` or an iterable of
                :class:`django.db.models.QuerySet`): All units matched by all QuerySet objects are
                associated.

        Raise:
            pulpcore.exception.ResourceImmutableError: if add_content is called on a
                complete RepositoryVersion
        """
        if self.complete:
            raise ResourceImmutableError(self)

        if isinstance(content, models.query.QuerySet):
            content = (content,)

        repo_content = []
        existing_content = {}
        for existing_content_qs in self.content().values():
            existing_content[existing_content_qs.model] = existing_content_qs.\
                values_list('pk', flat=True)

        for content_type_qs in content:
            try:
                existing_content_one_type = existing_content[content_type_qs.model]
            except KeyError:
                pass
            else:
                content_type_qs = content_type_qs.exclude(pk__in=existing_content_one_type)

            for content in content_type_qs:
                repo_content.append(
                    RepositoryContent(
                        repository=self.repository,
                        content=content,
                        version_added=self
                    )
                )

        RepositoryContent.objects.bulk_create(repo_content)

    def remove_content(self, content):
        """
        Remove content from this version.

        One or more :class:`django.db.models.QuerySet` can be passed in to `content`. All units
        matched by all :class:`~django.db.models.QuerySet` objects are unassociated.

        Args:
            content (:class:`django.db.models.QuerySet` or an iterable of
                :class:`django.db.models.QuerySet`): All units matched by all QuerySet objects are
                unassociated.

        Raise:
            pulpcore.exception.ResourceImmutableError: if remove_content is called on a
                complete RepositoryVersion
        """
        if self.complete:
            raise ResourceImmutableError(self)

        if isinstance(content, models.query.QuerySet):
            content = (content,)

        for content_type_qs in content:
            pks = content_type_qs.values_list('pk', flat=True)
            content_type_id = ContentType.objects.get_for_model(content_type_qs.model).pk
            q_set = RepositoryContent.objects.filter(
                repository=self.repository,
                object_id__in=pks,
                content_type_id=content_type_id,
                version_removed=None)
            q_set.update(version_removed=self)

    def _squash(self, repo_relations, next_version):
        """
        Squash a complete repo version into the next version
        """
        # delete any relationships added in the version being deleted and removed in the next one.
        repo_relations.filter(version_added=self, version_removed=next_version).delete()

        # If the same content is deleted in version, but added back in next_version
        # set version_removed field in relation to None, and remove relation adding the content
        # in next_version
        content_added = repo_relations.filter(version_added=next_version).values_list('content_id')

        # use list() to force the evaluation of the queryset, otherwise queryset is affected
        # by the update() operation before delete() is ran
        content_removed_and_readded = list(repo_relations.filter(version_removed=self,
                                                                 content_id__in=content_added)
                                           .values_list('content_id'))

        repo_relations.filter(version_removed=self,
                              content_id__in=content_removed_and_readded)\
            .update(version_removed=None)

        repo_relations.filter(version_added=next_version,
                              content_id__in=content_removed_and_readded).delete()

        # "squash" by moving other additions and removals forward to the next version
        repo_relations.filter(version_added=self).update(version_added=next_version)
        repo_relations.filter(version_removed=self).update(version_removed=next_version)

    def delete(self, **kwargs):
        """
        Deletes a RepositoryVersion

        If RepositoryVersion is complete and has a successor, squash RepositoryContent changes into
        the successor. If version is incomplete, delete and and clean up RepositoryContent,
        CreatedResource, and Repository objects.

        Deletion of a complete RepositoryVersion should be done in a RQ Job.
        """
        if self.complete:
            repo_relations = RepositoryContent.objects.filter(repository=self.repository)
            try:
                next_version = self.next()
                self._squash(repo_relations, next_version)

            except RepositoryVersion.DoesNotExist:
                # version is the latest version so simply update repo contents
                # and delete the version
                repo_relations.filter(version_added=self).delete()
                repo_relations.filter(version_removed=self).update(version_removed=None)
            super().delete(**kwargs)

        else:
            with transaction.atomic():
                RepositoryContent.objects.filter(version_added=self).delete()
                RepositoryContent.objects.filter(version_removed=self) \
                    .update(version_removed=None)
                CreatedResource.objects.filter(object_id=self.pk).delete()
                self.repository.last_version = self.number - 1
                self.repository.save()
                super().delete(**kwargs)

    def __enter__(self):
        """
        Create the repository version

        Returns:
            RepositoryVersion: self
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Save the RepositoryVersion if no errors are raised, delete it if not
        """
        if exc_value:
            self.delete()
        else:
            self.complete = True
            self.save()
