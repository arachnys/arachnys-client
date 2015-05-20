from urlparse import urljoin
import datetime
import json
import os
import time
import urllib

import requests


API_BASE = 'https://api.arachnys.com/api/v1/'


class ArachnysClient(object):
    def __init__(self, app_id=None, api_key=None, host=None, debug=False):
        """
        Expects to either get passed `app_id` and `api_key`, or to find them in the
        environment.
        """
        if not host:
            self.API_BASE = API_BASE
        else:
            self.API_BASE = host
        if app_id is None:
            app_id = os.environ.get('ARACHNYS_APP_ID')
            if not app_id:
                raise ConfigException('You need an app id')
        if api_key is None:
            api_key = os.environ.get('ARACHNYS_API_KEY')
            if not api_key:
                raise ConfigException('You need an api key')
        self.debug = debug
        self.session = requests.session()
        self.session.auth = (app_id, api_key)
        self.session.headers['Accept'] = 'application/json'

    def make_request(self, endpoint, method='get', resource_id=None, params=None):
        """
        Takes an endpoint and makes the request, returning a Response object Params
        will be urlencoded if making a GET request, and otherwise will be sent as a
        JSON object.
        """
        url = urljoin(self.API_BASE, endpoint)
        if not url.endswith('/'):
            url += '/'
        if resource_id is not None:
            url += str(resource_id) + '/'
        method = method.upper()
        data = None
        headers = None
        if method in ('POST', 'PUT', 'DELETE'):
            if params:
                data = json.dumps(params)
            params = None
            headers = {'Content-Type': 'application/json'}
        if self.debug:
            debug_url = url
            if params:
                debug_url = '%s?%s' % (url, urllib.urlencode(params))
            print 'Sending %s request to %s' % (method, debug_url)
            print 'Body: %s' % data
        resp = self.session.request(
            method,
            url,
            params=params,
            data=data,
            headers=headers,
        )
        if self.debug:
            print "Got response from API: %s" % resp.content
        if not resp.ok:
            try:
                error = resp.json()['error_message']
            except (ValueError, KeyError):
                error = resp.content
            raise ResponseException('Got error from Arachnys API: [%s] %s' %
                                    (resp.status_code, error))
        return resp.json()

    # Translation

    def _make_translate_payload(self, text, language_from, language_to):
        return {
            'to': language_to,
            'from': language_from,
            'text': text,
        }

    def translate_text(self, text, language_from='', language_to='en'):
        params = self._make_translate_payload(text, language_from, language_to)
        return self.make_request('translate', 'post', params=params)

    def translate_query(self, text, language_from='', language_to='en'):
        params = self._make_translate_payload(text, language_from, language_to)
        params['is_query'] = True
        return self.make_request('translate', 'post', params=params)

    # Collections

    def get_collections(self, filter=None, params=None):
        if params is None:
            params = {}
        if filter is not None:
            params['filter'] = filter
        return self.make_request('collections', 'get', params=params)

    def get_collection(self, id):
        return self.make_request('collection', 'get', id)

    def create_collection(self, name=None, description=None, sources=()):
        return self.make_request('collection', 'post', params={
            'name': name,
            'description': description,
            'sources': sources,
        })

    def modify_collection(self, id, name=None, description=None, sources=()):
        params = {}
        if name is not None:
            params['name'] = name
        if description is not None:
            params['description'] = description
        if sources:
            params['sources'] = sources
        if not params:
            raise Exception('No data supplied to modify resource')
        return self.make_request('collection', 'put', id, params=params)

    def delete_collection(self, id):
        return self.make_request('collection', 'delete', id)

    # Countries

    def get_countries(self, filter=None, params=None):
        if params is None:
            params = {}
        if filter is not None:
            params['name_filter'] = filter
        return self.make_request('countries', 'get', params=params)

    def get_country(self, iso_code):
        return self.make_request('country', 'get', iso_code)

    # Search

    def do_search(self, query, country_iso_code=None, category=None,
                  index_type=None, source_ids=(), collection_id=None):
        payload = {
            'query': query,
            'country_iso_code': country_iso_code,
            'category': category,
            'index_type': index_type,
            'source_ids': source_ids,
            'collection_id': collection_id
        }
        return self.make_request('search', 'post', params=payload)

    def get_search(self, uid):
        return self.make_request('search', 'get', uid)

    # News Search

    def do_news_search(self, query,
                       countries=None, exclude_countries=None,
                       sources=None, exclude_sources=None,
                       categories=None, exclude_categories=None,
                       from_date=None, to_date=None):
        payload = {
            'query': query,
            'countries': countries,
            'exclude_countries': exclude_countries,
            'sources': sources,
            'exclude_sources': exclude_sources,
            'categories': categories,
            'exclude_categories': exclude_categories,
            'from_date': from_date,
            'to_date': to_date,
        }
        return self.make_request('news', 'post', params=payload)

    def get_news_search(self, uid, start=None, params=None):
        if params is None:
            params = {}
        # Keeping for backwards compatibility
        if start:
            params['start'] = start
        return self.make_request('news/' + str(uid), 'get', params=params)

    # SearchWorker / results

    def get_searchworker(self, id, start=0, page_size=10):
        return self.make_request('searchworker', 'get', id, {
            'start': start,
            'page_size': page_size,
        })

    def poll_searchworkers(self, ids, timeout=120):
        """
        Polls a searchworker or a list of searchworkers for a result. Will time out
        after `timeout` seconds.

        This method will block until either
        a) all workers have completed, or
        b) timeout is reached

        Implementing a non-blocking version is left as an exercise to the reader.
        """
        started = time.time()
        if not isinstance(ids, list):
            ids = [ids]
        succeeded = []
        succeeded_ids = set([])
        failed = []
        failed_ids = set([])
        id_set = set(ids)
        # Don't even bother doing concurrent stuff
        while True:
            for id in id_set:
                worker = self.get_searchworker(id)
                status = worker['searchworker']['status']
                if status == 'failed':
                    failed.append(worker)
                    failed_ids.add(id)
                elif status == 'succeeded':
                    succeeded.append(worker)
                    succeeded_ids.add(id)
            id_set = id_set - (failed_ids | succeeded_ids)
            if not id_set:  # We're finished, none left
                break
            if time.time() - started > timeout:
                # Mark unfinished as failed
                for id in id_set:
                    failed.append(self.get_searchworker(id))
                    failed_ids.add(id)
                break
            time.sleep(2)
        return (succeeded, failed)

    # Sources

    def get_sources(self, country_iso_code=None, country_name=None,
                    category=None, country_region_name=None,
                    regional_coverage=None, query=None, params=None):
        if params is None:
            params = {}
        params['country_iso_code'] = country_iso_code
        params['country_name'] = country_name
        params['category'] = category
        params['country_region_name'] = country_region_name
        params['regional_coverage'] = regional_coverage
        params['query'] = query
        return self.make_request('sources', 'get', params=params)

    # Alerts

    def get_alerts(self):
        return self.make_request('alerts', 'get')

    def get_alert_updates(self, alert_id, updates_since=None, params=None):
        if params is None:
            params = {}
        if updates_since:
            if not isinstance(updates_since, datetime.date):
                raise ValueError("'updates_since' must be a datetime.date instance")
            params['updates_since'] = updates_since.isoformat()[:19]
        return self.make_request('alert', 'get', alert_id, params=params)

    def register_alert(self, query, country=None):
        return self.make_request('alert', 'post', params={
            'query': query,
            'country': country,
        })

    def update_alert(self, alert_id, **kwargs):
        if not kwargs:
            raise ValueError('Specify at least one parameter to update')
        return self.make_request('alert', 'put', alert_id, kwargs)

    def delete_alert(self, alert_id):
        return self.make_request('alert', 'delete', alert_id)


class ConfigException(Exception):
    pass


class ResponseException(Exception):
    pass
