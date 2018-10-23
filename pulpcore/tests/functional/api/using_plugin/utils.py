# coding=utf-8
"""Utilities for pulpcore API tests that require the use of a plugin."""
from functools import partial
from unittest import SkipTest

from pulp_smash import api, selectors
from pulp_smash.pulp3.constants import REPO_PATH
from pulp_smash.pulp3.utils import (
    gen_publisher,
    gen_repo,
    gen_remote,
    get_content,
    get_added_content,
    get_removed_content,
    require_pulp_3,
    require_pulp_plugins,
    sync
)

from tests.functional.api.using_plugin.constants import (
    FILE_FIXTURE_MANIFEST_URL,
    FILE_CONTENT_NAME,
    FILE_CONTENT_PATH,
    FILE_REMOTE_PATH
)

skip_if = partial(selectors.skip_if, exc=SkipTest)


def set_up_module():
    """Conditions to skip tests.

    Skip tests if not testing Pulp 3, or if either pulpcore or pulp_file
    aren't installed.
    """
    require_pulp_3(SkipTest)
    require_pulp_plugins({'pulpcore', 'pulp_file'}, SkipTest)


def populate_pulp(cfg, url=None):
    """Add file contents to Pulp.

    :param pulp_smash.config.PulpSmashConfig: Information about a Pulp
        application.
    :param url: The URL to a file repository's ``PULP_MANIFEST`` file. Defaults
        to :data:`pulp_smash.constants.FILE_FIXTURE_URL` + ``PULP_MANIFEST``.
    :returns: A list of dicts, where each dict describes one file content in
        Pulp.
    """
    if url is None:
        url = FILE_FIXTURE_MANIFEST_URL

    client = api.Client(cfg, api.json_handler)
    remote = {}
    repo = {}
    try:
        remote.update(client.post(FILE_REMOTE_PATH, gen_remote(url)))
        repo.update(client.post(REPO_PATH, gen_repo()))
        sync(cfg, remote, repo)
    finally:
        if remote:
            client.delete(remote['_href'])
        if repo:
            client.delete(repo['_href'])
    return client.get(FILE_CONTENT_PATH)['results']


def gen_file_remote(url=None, **kwargs):
    """Return a semi-random dict for use in creating a file Remote.

    :param url: The URL of an external content source.
    """
    if url is None:
        url = FILE_FIXTURE_MANIFEST_URL

    return gen_remote(url, **kwargs)


def gen_file_publisher(**kwargs):
    """Return a semi-random dict for use in creating a file Remote.

    :param url: The URL of an external content source.
    """
    publisher = gen_publisher()
    file_extra_fields = {
        **kwargs
    }
    publisher.update(file_extra_fields)
    return publisher


def get_file_content(repo, version_href=None):
    """Return the content units present in a file repository.

    :param repo: A dict of information about the repository.
    :param version_href: Optional repository version.
    :returns: A list of filecontent units present in a given repository.
    """
    return get_content(repo, version_href)[FILE_CONTENT_NAME]


def get_file_added_content(repo, version_href=None):
    """Return the content units added in a file repository version.

    :param repo: A dict of information about the repository.
    :param version_href: Optional repository version.
    :returns: A list of filecontent units present in a given repository.
    """
    return get_added_content(repo, version_href)[FILE_CONTENT_NAME]


def get_file_removed_content(repo, version_href=None):
    """Return the content units removed in a file repository version.

    :param repo: A dict of information about the repository.
    :param version_href: Optional repository version.
    :returns: A list of filecontent units present in a given repository.
    """
    return get_removed_content(repo, version_href)[FILE_CONTENT_NAME]
