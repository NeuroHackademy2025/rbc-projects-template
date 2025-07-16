# -*- coding: utf-8 -*-
###############################################################################
# rbclib/__init__.py

"""A minimal library that extends cloudpathlib.CloudPath to the RBC dataset.
"""

import os, urllib, mimetypes, json
from pathlib import Path, PosixPath, PurePosixPath

import cloudpathlib

class RBCFileException(Exception):
    """This exception is raised internally by the RBCClient object when one
    attempts to load a file that is not part of the S3 storage. This happens
    frequently because files like the `participants.tsv` equivalents are stored
    directly in git rather than as git-annex objects. The git-annex objects
    must be loaded from S3 while the non-annexed files are loaded directly from
    git.
    """
    __slots__ = ('url', 'contents')
    def __init__(self, url, contents=None):
        self.url = url
        self.contents = contents

@cloudpathlib.client.register_client_class("rbc")
class RBCClient(cloudpathlib.client.Client):
    @staticmethod
    def _url_slurp(url):
        with urllib.request.urlopen(url) as response:
            return response.read()
    @staticmethod
    def _path_split_repo(path):
        path = str(path)
        if path.startswith('rbc://') or path.startswith('RBC://'):
            path = path[6:]
        path = path.lstrip('/')
        parts = PurePosixPath(path).parts
        repo = parts[0]
        tail = '/'.join(parts[1:])
        return (repo, tail)
    @staticmethod
    def _get_github_path(path):
        (repo, tail) = RBCClient._path_split_repo(path)
        return (
            f"https://raw.githubusercontent.com/ReproBrainChart/"
            f"{repo}/refs/heads/main/{tail}")
    @staticmethod
    def _get_github_apipath(path):
        (repo, tail) = RBCClient._path_split_repo(path)
        return (
            f"https://api.github.com/repos/ReproBrainChart/"
            f"{repo}/contents/{tail}")
    @staticmethod
    def _get_github_json(path):
        url = RBCClient._get_github_apipath(path)
        dat = RBCClient._url_slurp(url)
        return json.loads(dat)
    @staticmethod
    def _get_s3_path(path):
        (repo, tail) = RBCClient._path_split_repo(path)
        ghpath = RBCClient._get_github_path(path)
        dat = RBCClient._url_slurp(ghpath)
        if b'/.git/annex/objects/' not in dat:
            raise RBCFileException(ghpath, dat)
        file = dat.decode('utf-8').split('/')[-1]
        return f"s3://fcp-indi/data/Projects/RBC/{repo}/{file}"
    def __init__(self,
                 file_cache_mode=None,
                 local_cache_dir=None,
                 content_type_method=mimetypes.guess_type):
        super().__init__(
            file_cache_mode=file_cache_mode,
            local_cache_dir=local_cache_dir,
            content_type_method=content_type_method)
        self._s3client = cloudpathlib.s3.S3Client(no_sign_request=True)
    # Several of the abstract methods are non-operational for OSF, because all
    # OSF operations are currently read-only
    def _move_file(self, src, dst, remove_src=True):
        raise RuntimeError(f"RBCPath operations are read-only")
    def _remove(self, path, missing_ok=True):
        raise RuntimeError(f"RBCPath operations are read-only")
    def _upload_file(self, local_path, cloud_path):
        raise RuntimeError(f"RBCPath operations are read-only")
    # Other abstract methods are valid, however.
    def to_s3(self, cloud_path):
        if not isinstance(cloud_path, (RBCPath, str)):
            raise TypeError("cannot download path that is not an RBCPath")
        s3path = RBCClient._get_s3_path(cloud_path)
        return cloudpathlib.s3.S3Path(s3path, client=self._s3client)
    def _download_file(self, cloud_path, local_path):
        if not isinstance(cloud_path, RBCPath):
            raise TypeError("cannot download path that is not an RBCPath")
        try:
            s3path = self.to_s3(cloud_path)
        except RBCFileException as e:
            local_path = Path(local_path)
            with local_path.open('wb') as f:
                f.write(e.contents)
        else:
            return self._s3client._download_file(s3path, local_path)
            
    def _exists(self, cloud_path):
        try:
            s3path = self.to_s3(cloud_path)
        except RBCFileException as e:
            return True
        else:
            return self._s3client._exists(s3path)
    def _list_dir(self, cloud_path, recursive=False):
        if recursive:
            raise NotImplementedError(
                "recursive listing of RBC projects is not supported")
        (repo, tail) = RBCClient._path_split_repo(cloud_path)
        json = RBCClient._get_github_json(cloud_path)
        if not isinstance(json, list):
            raise TypeError(f"cannot list non-directory: {str(cloud_path)}")
        return (RBCPath(f"rbc://{repo}/{filedict['path']}", client=self)
                for filedict in json)
    def _path_kind(self, cloud_path):
        json = RBCClient._get_github_json(cloud_path)
        if not isinstance(json, list):
            return "directory"
        else:
            return "file"
    def _get_public_url(self, cloud_path):
        try:
            s3path = self.to_s3(cloud_path)
        except RBCFileException as e:
            return e.url
        else:
            return self._s3client._get_public_url(s3path)
    def _generate_presigned_url(self, cloud_path, expire_seconds=60*60):
        try:
            s3path = self.to_s3(cloud_path)
        except RBCFileException as e:
            return e.url
        else:
            return self._s3client._generate_presigned_url(
                s3path,
                expire_seconds=expire_seconds)

@cloudpathlib.cloudpath.register_path_class('rbc')
class RBCPath(cloudpathlib.CloudPath):
    cloud_prefix = "rbc://"
    client = RBCClient
    init_default_options = dict(
        local_cache_dir=None,
        file_cache_mode=None)
    def __init__(self, cloud_path, client=None,
                 local_cache_dir=None,
                 file_cache_mode=None):
        self._handle = None
        self._stat = None
        self.client = RBCClient.get_default_client()
        if isinstance(cloud_path, RBCPath):
            if client is None:
                client = cloud_path.client
                self.client = client
        else:
            # Go ahead and validate the url.
            self.is_valid_cloudpath(cloud_path, raise_on_error=True)
        if client is None:
            client = RBCClient(
                file_cache_mode=file_cache_mode,
                local_cache_dir=local_cache_dir,
                content_type_method=mimetypes.guess_type)
            self.client = client
        super().__init__(cloud_path, client)
    @property
    def s3path(self):
        return self.client.to_s3(self)
    @property
    def drive(self):
        try:
            return self.s3path.drive
        except RBCFileException as e:
            return None
    def is_dir(self):
        json = self.client._get_github_json(self)
        return isinstance(json, list)
    def is_file(self):
        json = self.client._get_github_json(self)
        return isinstance(json, dict)
    def mkdir(self, parents=False, exist_ok=False):
        raise TypeError(f"RBCPath operations are read-only")
    def touch(self, exist_ok: bool = True):
        raise TypeError(f"RBCPath operations are read-only")
    def stat(self):
        if self._stat is None:
            try:
                self._stat = self.s3path.stat()
            except RBCFileException as e:
                import time
                self._stat = os.stat_result(
                    (None, None, 'github://',
                     None, None, None,
                     len(e.contents),
                     None, int(time.time()), None))
        return self._stat
    def iterdir(self):
        return self.client._list_dir(self)
    @property
    def key(self):
        try:
            return self.s3path.key
        except RBCFileException as e:
            return None

__all__ = ("RBCPath",)
