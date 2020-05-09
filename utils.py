#!/usr/bin/python
#
# Copyright (C) 2012 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import map
from builtins import object
import collections
from datetime import timedelta, datetime
import json
import logging
import os
import urllib.request, urllib.parse, urllib.error
import urllib.parse

__author__ = 'afshar@google.com (Ali Afshar)'
__author__ = 'arnaud@videonot.es Arnaud BRETON (UniShared)'

class FileUtils(object):
    LAST_FILE_VERSION = 2
    SNAPSHOT_KEY = 'snapshot'

    @staticmethod
    def get_empty_file():
        return {
            'version': FileUtils.LAST_FILE_VERSION,
            'content': '',
            'currentVideo': None,
            'videos': {},
            'syncNotesVideo': True
        }

    @staticmethod
    def get_content_from_data(data):
        content = json.dumps({
            'version': data.get('version', FileUtils.LAST_FILE_VERSION),
            'videos': data.get('videos', {}),
            'currentVideo': data.get('currentVideo', None),
            'content': data.get('content', ''),
            'syncNotesVideo': data.get('syncNotesVideo', True)
        })

        if 'content' in data:
            data.pop('content')

        return content

    @staticmethod
    def transformations(f):
        """
        Transform a file from a version to an another
        """
        return FileUtils.transformation_v1_to_v2(f)

    @staticmethod
    def transformation_v1_to_v2(f):
        """
        Transform a v1 file to v2
        V1: single video
        V2: multi videos support
        """

        # V1 has no version field
        if not 'version' in f:
            # Set version field to 2
            f['version'] = FileUtils.LAST_FILE_VERSION

            # Enabled field is now directly syncNotesVideo since this field does not contain timestamps anymore
            sync_status = f['syncNotesVideo']['enabled']
            del f['syncNotesVideo']['enabled']

            # We are now storing a dict of videos' URLs and for each, timestamps
            f['currentVideo'] = f['video']

            old_sync = f['syncNotesVideo']

            new_sync = {}
            for line_synced in old_sync:
                new_sync[line_synced] = {
                    'time' : old_sync[line_synced]
                }

            f['videos'] = {
                f['video']: new_sync
            }
            del f['video']

            f['syncNotesVideo'] = sync_status

        return f

    @staticmethod
    def flatten_sync(sync):
        """
        Flatten a nested sync

        Input format:
        {
            "http://video1": {
                0: {
                    time: ...,
                    snapshot: ...
                },
                2: {
                    time: ...,
                    snapshot: ...
                },
                ...
            },
            "http://video2": {
                1: {
                    time: ...,
                    snapshot: ...
                },
                3: {
                    time: ...,
                    snapshot: ...
                },
                ...
            }
        }
        Output format:
        {
            0: {
                url: "http://video1"
                time: ...,
                snapshot: ...
            },
            1: {
                url: "http://video2"
                time: ...,
                snapshot: ...
            },
            2: {
                url: "http://video1"
                time: ...,
                snapshot: ...
            },
            3: {
                url: "http://video2"
                time: ...,
                snapshot: ...
            },
            ...
        }
        """
        flat_sync = {}
        for url_video in sync:
            video = sync[url_video]
            for line_sync in video:
                video[line_sync]['url'] = url_video
                flat_sync[int(line_sync)] = video[line_sync]
        return collections.OrderedDict(sorted(flat_sync.items()))

    @staticmethod
    def to_ENML(file, base_url):
        """
        Formatting a VideoNot.es in ENML (Evernote markup)
        """
        flat_sync = FileUtils.flatten_sync(file['videos'])
        content_enml = []
        i = 0

        for line in file['content'].split('\n'):
            if line:
                if line == '<{0}>'.format(FileUtils.SNAPSHOT_KEY):
                    if flat_sync[i] and FileUtils.SNAPSHOT_KEY in flat_sync[i]:
                        video_url = flat_sync[i]['url']
                        sync_time = flat_sync[i]['time']

                        # Adding the Youtube time parameter
                        url_data = urllib.parse.urlparse(video_url)
                        if sync_time > 0.01 and any(match in url_data.hostname for match in ['youtube', 'youtu.be']):
                            query = urllib.parse.parse_qs(url_data.query)
                            video_id = query["v"][0]

                            sec = timedelta(seconds=sync_time)
                            d = datetime(1,1,1) + sec

                            minutes = seconds = ''
                            if d.second > 0:
                                seconds = '{0}s'.format(d.second)
                            if d.minute > 0:
                                minutes = '{0}m'.format(d.minute)

                            video_url = 'http://youtu.be/' + video_id
                            video_url = UrlUtils.add_query_parameter(video_url, {'t': minutes + seconds})

                        if i > 0:
                            content_enml.append('<br></br>')

                        content_enml.append('<img src="{0}"></img>'.format(flat_sync[i][FileUtils.SNAPSHOT_KEY]))
                        content_enml.append('<br></br>')
                        content_enml.append('<a href="{0}">{0}</a>'.format(video_url))
                        content_enml.append('<br></br><br></br>')
                else:
                    link = '<a href="{0}?l={1}">+</a>'.format(base_url, i+1)
                    content_enml.append(link + ' ' + line)
                    content_enml.append('<br></br>')
            else:
                content_enml.append(line)
            i += 1

        return content_enml

def SibPath(name):
    """Generate a path that is a sibling of this file.

    Args:
      name: Name of sibling file.
    Returns:
      Path to sibling file.
    """
    return os.path.join(os.path.dirname(__file__), name)

class DriveState(object):
    """Store state provided by Drive."""

    def __init__(self, state):
        """Create a new instance of drive state.

        Parse and load the JSON state parameter.

        Args:
          state: State query parameter as a string.
        """
        if state:
            state_data = json.loads(state)
            self.action = state_data['action']

            if 'folderId' in state_data:
                self.parent = state_data['folderId']
            else:
                self.parent = []
            self.ids = list(map(str, state_data.get('ids', [])))
        else:
            self.action = 'create'
            self.parent = []

        logging.debug('Create Drive state, parent %s, action %s', str(self.parent) if hasattr(self, 'parent') else None, self.action)

    @classmethod
    def FromRequest(cls, request):
        """Create a Drive State instance from an HTTP request.

        Args:
          cls: Type this class method is called against.
          request: HTTP request.
        """
        return DriveState(request.get('state'))

class UrlUtils(object):
    @staticmethod
    def add_query_parameter(url, params):
        """
        Add query parameters to an URL
        @return: URL with new parameters
        """
        url_parts = list(urllib.parse.urlparse(url))
        query = dict(urllib.parse.parse_qsl(url_parts[4]))
        query.update(params)

        url_parts[4] = urllib.parse.urlencode(query)

        return urllib.parse.urlunparse(url_parts)