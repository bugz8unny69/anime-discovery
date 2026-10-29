"""Offline hash-addressed HTTP metainfo and worker handoff cases; unexecuted."""
import asyncio
import copy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

from src.nextgen.acquisition.metainfo_source import (Client, SourceOptions, make_reader, source_url,
    MetadataSourceConfigurationError, MetadataSourceUnavailable, MetadataSourceWaiting, MetadataSourceDenied)
from src.nextgen.acquisition.metadata import MetadataInvalid, MAX_METAINFO
from src.nextgen.configuration_schema import (CONVERSIONS, CONFIGURATION_VERSION, ConfigurationError,
    ConfigurationMigrationRequired, ConfigurationSnapshot, convert_document, load_current)
from src.nextgen.job_contracts import Registry
from src.nextgen.jobs.evaluate_trial_job import registration as evaluate
from src.nextgen.jobs.reserve_episode_job import registration as reserve
from src.nextgen.jobs.prepare_acquisition_job import registration as prepare
from src.nextgen.jobs.submit_torrent_job import registration as submit
from src.nextgen.tests.test_acquisition_metadata import metadata
from src.nextgen.tests import test_acquisition_preparation as fixture
from src.nextgen.worker import Worker


class Response(io.BytesIO):
    def __init__(self,raw,code=200,headers=None):
        super().__init__(raw)
        self.code=code;self.headers={} if headers is None else headers
    def getcode(self):return self.code


class MetainfoSourceTests(unittest.TestCase):
    def test_fixed_hash_path_bounded_read_and_no_credentials(self):
        raw,digest=metadata();calls=[]
        def transport(request,timeout):
            calls.append((request,timeout))
            return Response(raw,headers={'Content-Length':str(len(raw))})
        client=Client(SourceOptions('https://cache.example/torrents/',10),transport=transport)
        self.assertEqual(client.fetch(digest.upper(),asyncio.Event()),raw)
        request,timeout=calls[0]
        self.assertEqual(request.full_url,'https://cache.example/torrents/'+digest+'.torrent')
        self.assertEqual(request.method,'GET');self.assertEqual(timeout,10)
        self.assertIsNone(request.get_header('Authorization'));self.assertIsNone(request.get_header('Cookie'))
        self.assertEqual(request.get_header('Accept-encoding'),'identity')
        self.assertNotIn('private-secret',repr(client.options))

    def test_operator_base_validation_blocks_credentials_templates_and_path_injection(self):
        for value in ('', 'file:///tmp', 'https://user:secret@cache.example', 'https://cache.example/x?token=secret',
                      'https://cache.example/#frag', 'https://cache.example/%2fprivate', 'https://cache.example/../x',
                      'https://cache.example/{hash}', 'https://cache.example/a//b', 'https://cache.example\\other',
                      'http://host:0', 'https://cache.example/a.b'):
            with self.subTest(value=value),self.assertRaises(MetadataSourceConfigurationError):source_url(value)
        self.assertEqual(source_url('http://127.0.0.1:8080/cache/'),'http://127.0.0.1:8080/cache')
        with self.assertRaises(ConfigurationError):ConfigurationSnapshot(1,{'torrent_metadata':{'base_url':'https://cache.example?secret=1'}})

    def test_wrong_hash_invalid_inventory_compression_and_response_bounds_are_rejected(self):
        raw,digest=metadata()
        other,_=metadata(name=b'Wrong Anime - 10.mkv')
        cases=[(other,{}),(b'<html>error</html>',{}),(raw,{'Content-Encoding':'gzip'}),
               (raw,{'Content-Length':str(MAX_METAINFO+1)}),(raw,{'Content-Length':'-1'}),
               (raw,{'Content-Length':str(len(raw)+1)}),(b'x'*(MAX_METAINFO+1),{})]
        for body,headers in cases:
            with self.subTest(headers=headers),self.assertRaises(MetadataInvalid):
                Client(SourceOptions('https://cache.example',10),transport=lambda *args:Response(body,headers=headers)).fetch(digest,asyncio.Event())

    def test_http_outcomes_are_safe_and_never_retry_or_follow_redirects_in_transport(self):
        raw,digest=metadata()
        for code,kind in ((404,MetadataSourceWaiting),(429,MetadataSourceWaiting),(503,MetadataSourceWaiting),
                          (401,MetadataSourceDenied),(403,MetadataSourceDenied),(500,MetadataSourceUnavailable),
                          (302,MetadataInvalid),(410,MetadataInvalid)):
            calls=[]
            def transport(request,timeout):
                calls.append(request)
                raise urllib.error.HTTPError(request.full_url,code,'private-secret',{'Retry-After':'99999','Location':'https://other.example'},io.BytesIO())
            with self.subTest(code=code),self.assertRaises(kind) as error:
                Client(SourceOptions('https://cache.example',10),transport=transport).fetch(digest,asyncio.Event())
            self.assertEqual(len(calls),1)
            self.assertNotIn('private-secret',str(error.exception))
            if kind is MetadataSourceWaiting:self.assertEqual(error.exception.delay_ms,86400000)

    def test_cancellation_and_deadline_stop_work_without_leaving_a_response_open(self):
        raw,digest=metadata();cancelled=asyncio.Event();cancelled.set()
        client=Client(SourceOptions('https://cache.example',10),transport=lambda *args:(_ for _ in ()).throw(AssertionError('No request after cancellation')))
        with self.assertRaises(asyncio.CancelledError):client.fetch(digest,cancelled)
        response=Response(raw);ticks=iter((0,11))
        with self.assertRaises(MetadataSourceUnavailable):
            Client(SourceOptions('https://cache.example',10),transport=lambda *args:response,clock=lambda:next(ticks)).fetch(digest,asyncio.Event())
        self.assertTrue(response.closed)
        class CancelingResponse(Response):
            def read1(self,size):cancelled.set();return super().read1(size)
        cancelled.clear();response=CancelingResponse(raw)
        with self.assertRaises(asyncio.CancelledError):
            Client(SourceOptions('https://cache.example',10),transport=lambda *args:response).fetch(digest,cancelled)
        self.assertTrue(response.closed)

    def test_v6_upgrade_is_explicit_and_historical_shapes_remain_unchanged(self):
        doc={}
        for version in range(6):
            doc=CONVERSIONS[version](doc)
            self.assertNotIn('torrent_metadata',doc['settings'])
            with self.assertRaises(ConfigurationError):
                convert_document({**doc,'settings':{**doc['settings'],'torrent_metadata':{'base_url':'https://cache.example'}}})
        before=copy.deepcopy(doc)
        with self.assertRaises(ConfigurationMigrationRequired):load_current(json.dumps(doc).encode())
        upgraded=convert_document(doc)
        self.assertEqual(doc,before)
        self.assertEqual(upgraded.schema_version,CONFIGURATION_VERSION)
        self.assertEqual(upgraded.revision,doc['revision']+5)
        self.assertEqual(upgraded.value('torrent_metadata.base_url'),'')
        self.assertEqual(upgraded.value('torrent_metadata.timeout_seconds'),30)
        for section,values in before['settings'].items():self.assertEqual(upgraded.to_document()['settings'][section],values)


class MetainfoReaderWorkerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.AcquisitionPreparationTests.asyncSetUp
    rows=fixture.AcquisitionPreparationTests.rows
    source=fixture.AcquisitionPreparationTests.source

    def worker(self,transport):
        def client(options):return Client(options,transport=transport)
        reader=make_reader(client_factory=client)
        worker=Worker(self.store,self.startup,Registry((evaluate(reservation_kind='RESERVE_EPISODE'),
            reserve(preparation_kind='PREPARE_ACQUISITION'),prepare(reader,submission_kind='SUBMIT_TORRENT'),
            submit(reader,object()))))
        self.addAsyncCleanup(worker.close)
        return worker

    async def test_actual_reader_prepares_inventory_then_atomically_enqueues_submission(self):
        self.store.update({'torrent_metadata':{'base_url':'https://cache.example/torrents'}},expected_revision=1)
        self.source();requests=[]
        def transport(request,timeout):requests.append(request.full_url);return Response(self.raw)
        worker=self.worker(transport)
        for _ in range(3):await worker.attempt()
        self.assertEqual(requests,['https://cache.example/torrents/'+self.digest+'.torrent'])
        self.assertEqual(self.rows('SELECT state,info_hash FROM acquisition_plans'),[('PREPARED',self.digest)])
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='SUBMIT_TORRENT'"),[('PENDING',)])
        self.assertEqual(self.rows('SELECT count(*) FROM torrent_submissions'),[(0,)])
        self.assertNotIn('private-secret',str(self.rows('SELECT * FROM acquisition_plans')))

    async def test_missing_source_goes_to_readable_review_without_network_or_submission(self):
        self.source()
        worker=self.worker(lambda *args:(_ for _ in ()).throw(AssertionError('No request before configuration')))
        for _ in range(3):await worker.attempt()
        self.assertEqual(self.rows("SELECT state,last_reason_code FROM jobs WHERE kind='PREPARE_ACQUISITION'"),
                         [('NEEDS_REVIEW','TORRENT_METADATA_CONFIGURATION_INVALID')])
        self.assertEqual(self.rows('SELECT count(*) FROM acquisition_plans'),[(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM torrent_submissions'),[(0,)])

    async def test_missing_metadata_defers_with_its_own_reason_without_consuming_failure_retry(self):
        self.store.update({'torrent_metadata':{'base_url':'https://cache.example'}},expected_revision=1)
        self.source();worker=self.worker(lambda *args:Response(b'',404))
        for _ in range(3):await worker.attempt()
        self.assertEqual(self.rows("SELECT state,last_reason_code FROM jobs WHERE kind='PREPARE_ACQUISITION'"),
                         [('RETRY_WAIT','TORRENT_METADATA_WAITING')])
        self.assertEqual(self.rows("SELECT count(*) FROM job_history WHERE event_code='RETRY_SCHEDULED'"),[(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM acquisition_plans'),[(0,)])

    async def test_each_read_uses_its_operation_snapshot_and_does_not_keep_metainfo(self):
        requests=[]
        def transport(request,timeout):requests.append(request.full_url);return Response(self.raw)
        reader=make_reader(client_factory=lambda options:Client(options,transport=transport))
        first=ConfigurationSnapshot(1,{'torrent_metadata':{'base_url':'https://first.example'}})
        second=ConfigurationSnapshot(2,{'torrent_metadata':{'base_url':'https://second.example'}})
        source=SimpleNamespace(info_hash=self.digest)
        for configuration in (first,second):self.assertEqual(await reader(source,configuration,asyncio.Event()),self.raw)
        self.assertEqual(requests,['https://first.example/'+self.digest+'.torrent','https://second.example/'+self.digest+'.torrent'])
