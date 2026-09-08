"""Regression tests for franchise-prefix hits impersonating the requested TV show."""
import asyncio
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import pytest

from app import torznab
from app.settings import settings
from app.webshare import SearchResult


SPINOFFS = [
    'Dexter.Resurrection.S01E01.1080p.mkv',
    'Dexter.New.Blood.S01E01.1080p.mkv',
    'Dexter.Original.Sin.S01E01.1080p.mkv',
    'Dexter Vzkříšení 01 1080p CZ En Bušící srdce.mkv',
    'Dexter Vzkriseni S01E01 CZ Dabing.mkv',
    'Dexter_Nova_krev_S01E01_Nahle_chladno.mkv',
    'Dexter Nová krev 1x01 Studeny start CZ.mkv',
    'Dexter Původní hřích S01E01.mkv',
    'Dexter Grzech pierworodny S01E01.mkv',
    'Dexter Resurrection 1080p 5.1.mkv',
]


@pytest.mark.parametrize('name', SPINOFFS)
def test_spinoff_never_acquires_original_identity(name):
    assert torznab.file_marker(['Dexter'], name) == (None, None)
    assert torznab.release_title('Dexter', '1', '1', name) == torznab._asciify(name[:-4])


@pytest.mark.parametrize('name,marker', [
    ('Dexter S01E01 1080p.mkv', (1, 1)),
    ('Dexter_S01E01_Dexter.mkv', (1, 1)),
    ('Dexter (2006) S01.E01.mkv', (1, 1)),
    ('Dexter 1x01.mkv', (1, 1)),
    ('Dexter 01 - Dexter.mkv', (None, 1)),
    ('Dexter 1. série 01 díl.mkv', (1, 1)),
    ('Dexter séria 1 epizóda 01.mkv', (1, 1)),
    ('Dexter S04 1080p.mkv', (4, None)),
])
def test_verified_local_numbering(name, marker):
    assert torznab.file_marker('Dexter', name) == marker


@pytest.mark.parametrize('title', ['The 100', '1923', '1899', '2 Socky'])
def test_numbers_belong_to_the_series_title(title):
    assert torznab.file_marker(title, title + ' S01E01.mkv') == (1, 1)
    assert torznab.file_marker(title, title + ' Resurrection S01E01.mkv') == (None, None)


def test_no_prefix_alias_leakage():
    aliases = [{'from': 'Dexter', 'to': 'Dexter CZ'},
               {'from': 'The Sleepers', 'to': 'Bez vědomí'}]
    assert torznab.alias_titles('Dexter Resurrection', aliases) == []
    assert torznab.alias_titles('Sleepers', aliases) == ['Bez vědomí']


def test_identity_ids_override_short_query(monkeypatch):
    monkeypatch.setattr(settings, 'tmdb_token', 'fake')
    monkeypatch.setattr(settings, 'aliases', [{'from': 'Dexter', 'to': 'Dexter CZ'}])

    async def lookup(*args):
        return ('Dexter: Resurrection', '', 'en', ('Dexter: Vzkříšení',), 2025)

    monkeypatch.setattr(torznab, 'tmdb_lookup_by_id', lookup)
    titles, display, *_ = asyncio.run(torznab.expand_titles(
        'tvsearch', 'Dexter', '5000', tvdbid='test-id'))
    assert titles == ['Dexter: Resurrection', 'Dexter: Vzkříšení']
    assert display == 'Dexter: Resurrection'


def test_season_search_preserves_file_episode():
    title = torznab.release_title('Dexter', '1', None, 'Dexter.S01E03.1080p.mkv')
    assert title.startswith('Dexter S01E03 - ')
    assert 'S01E01' not in title


@pytest.mark.parametrize('name', ['Dexter.S02E01.mkv', 'Dexter.S01E02.mkv',
                                 'Dexter.S01E01-E03.mkv'])
def test_conflicts_and_ranges_not_rewritten(name):
    assert torznab.release_title('Dexter', '1', '1', name) == name[:-4]


@pytest.mark.parametrize('endpoint', ['/torznab/api', '/ui/api/search'])
def test_endpoint_filters_franchise_and_unknown_markers(client, fake_webshare, endpoint):
    fake_webshare.fuzzy = True
    fake_webshare.results = [SearchResult(str(i), name, 1000) for i, name in enumerate(SPINOFFS)]
    fake_webshare.results += [SearchResult('good', 'Dexter_S01E01_Dexter.1080p.mkv', 1000),
                             SearchResult('unknown', 'Dexter FHD 1080p CZ.mkv', 1000)]
    response = client.get(endpoint, params={
        't': 'tvsearch', 'q': 'Dexter', 'season': '1', 'ep': '1', 'apikey': 'testkey'})
    if endpoint.startswith('/ui'):
        results = response.json()['results']
        assert len(results) == 1
        assert results[0]['release'].startswith('Dexter S01E01 - ')
        assert results[0]['name'] == 'Dexter_S01E01_Dexter.1080p.mkv'
        return
    items = ET.fromstring(response.content).findall('channel/item')
    assert [i.findtext('guid') for i in items] == ['websharr-good']
    assert items[0].findtext('title').startswith('Dexter S01E01 - ')
    params = parse_qs(urlparse(items[0].findtext('link')).query)
    assert params['name'] == ['Dexter_S01E01_Dexter.1080p.mkv']
    assert params['nzbname'] == [items[0].findtext('title')]


@pytest.mark.parametrize('endpoint', ['/torznab/api', '/ui/api/search'])
def test_endpoint_id_alias_and_later_season_year(client, fake_webshare, monkeypatch, endpoint):
    monkeypatch.setattr(settings, 'tmdb_token', 'fake')

    async def lookup(*args):
        return ('The Sleepers', 'Bez vědomí', 'cs', (), 2019)

    monkeypatch.setattr(torznab, 'tmdb_lookup_by_id', lookup)
    fake_webshare.fuzzy = True
    fake_webshare.results = [SearchResult('yes', 'Bez vedomi S02E01 (2022).mkv', 1000),
                             SearchResult('no', 'Bez vedomi Resurrection S02E01.mkv', 1000),
                             SearchResult('bare', 'Bez vedomi 01.mkv', 1000)]
    response = client.get(endpoint, params={
        't': 'tvsearch', 'tvdbid': 'test-id', 'season': '2', 'ep': '1', 'apikey': 'testkey'})
    if endpoint.startswith('/ui'):
        results = response.json()['results']
        assert len(results) == 1
        assert results[0]['release'].startswith('The Sleepers S02E01 - ')
        return
    items = ET.fromstring(response.content).findall('channel/item')
    assert [i.findtext('guid') for i in items] == ['websharr-yes']
    assert items[0].findtext('title').startswith('The Sleepers S02E01 - ')


def test_spinoff_can_be_requested_under_its_own_id(client, fake_webshare, monkeypatch):
    monkeypatch.setattr(settings, 'tmdb_token', 'fake')

    async def lookup(*args):
        return ('Dexter: Resurrection', '', 'en', ('Dexter: Vzkříšení',), 2025)

    monkeypatch.setattr(torznab, 'tmdb_lookup_by_id', lookup)
    fake_webshare.fuzzy = True
    fake_webshare.results = [SearchResult('en', SPINOFFS[0], 1000),
                             SearchResult('cz', SPINOFFS[3], 1000),
                             SearchResult('original', 'Dexter S01E01.mkv', 1000)]
    response = client.get('/torznab/api', params={
        't': 'tvsearch', 'q': 'Dexter', 'tvdbid': 'test-id', 'season': '1', 'ep': '1', 'apikey': 'testkey'})
    items = ET.fromstring(response.content).findall('channel/item')
    assert {i.findtext('guid') for i in items} == {'websharr-en', 'websharr-cz'}
    assert all(i.findtext('title').startswith('Dexter: Resurrection S01E01 - ') for i in items)
