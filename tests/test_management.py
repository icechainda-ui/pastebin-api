import hashlib
import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models import Paste


def create_managed(client, **metadata):
    response = client.post('/pastes', json={'content': '  original\r\n\t🙂  ', **metadata})
    assert response.status_code == 201
    body = response.json()
    return response.headers['location'], {'Authorization': f"Bearer {body['management_key']}"}, body


def test_key_is_hashed_and_only_returned_once(client, caplog):
    caplog.set_level(logging.INFO)
    url, headers, created = create_managed(client, title='Example', language='python')
    key = created['management_key']
    assert len(bytes.fromhex(key)) == 32
    with SessionLocal() as session:
        stored = session.get(Paste, created['id'])
        assert stored.management_key_hash == hashlib.sha256(key.encode()).hexdigest()
        assert stored.management_key_hash != key
    fetched = client.get(url)
    assert fetched.json()['title'] == 'Example'
    assert fetched.json()['language'] == 'python'
    updated = client.patch(url, headers=headers, json={'title': 'Updated'})
    assert updated.status_code == 200
    for response in (fetched, updated, client.get(url)):
        assert set(response.json()) == {'id', 'content', 'created_at', 'title', 'language'}
        assert key not in response.text
    assert client.delete(url, headers=headers).status_code == 204
    assert key not in caplog.text


def test_keys_are_independent_and_cannot_manage_another_paste(client):
    url, _, first = create_managed(client)
    _, second_headers, second = create_managed(client)
    assert first['management_key'] != second['management_key']
    assert client.patch(url, headers=second_headers, json={'title': 'bad'}).status_code == 403
    assert client.delete(url, headers=second_headers).status_code == 403
    assert client.get(url).json()['title'] is None


@pytest.mark.parametrize('method', ['patch', 'delete'])
@pytest.mark.parametrize('authorization', [None, '', 'Basic abc', 'Bearer', 'Bearer ', 'Bearer a b', 'Bearer a,b', 'Bearer a:b'])
def test_missing_or_malformed_bearer(client, method, authorization, caplog):
    url, _, _ = create_managed(client)
    before = client.get(url).json()
    headers = {} if authorization is None else {'Authorization': authorization}
    kwargs = {'json': {'title': 'bad'}} if method == 'patch' else {}
    for target in (url, '/pastes/' + 'z' * 22):
        response = client.request(method, target, headers=headers, **kwargs)
        assert response.status_code == 401
        assert response.headers['www-authenticate'] == 'Bearer'
    assert client.get(url).json() == before
    assert 'Bearer a:b' not in caplog.text


@pytest.mark.parametrize('method', ['patch', 'delete'])
def test_wrong_key_unknown_id_and_legacy_paste(client, method, caplog):
    caplog.set_level(logging.INFO)
    url, _, created = create_managed(client)
    before = client.get(url).json()
    wrong_key = 'wrong-but-syntactically-valid-key'
    headers = {'Authorization': f'Bearer {wrong_key}'}
    kwargs = {'json': {'title': 'bad'}} if method == 'patch' else {}
    response = client.request(method, url, headers=headers, **kwargs)
    assert response.status_code == 403
    assert response.json() == {'detail': 'Invalid management key'}
    assert client.get(url).json() == before
    assert client.request(method, '/pastes/' + 'z' * 22, headers=headers, **kwargs).status_code == 404
    with SessionLocal() as session:
        session.add(Paste(id='l' * 22, content='legacy'))
        session.commit()
    legacy_url = '/pastes/' + 'l' * 22
    response = client.request(method, legacy_url, headers=headers, **kwargs)
    assert response.status_code == 403
    assert response.json() == {'detail': 'This legacy paste has no management key'}
    assert client.get(legacy_url).json()['content'] == 'legacy'
    assert wrong_key not in caplog.text
    assert created['management_key'] not in caplog.text


def test_patch_omitted_null_and_immutable_fields(client):
    url, headers, _ = create_managed(client, title='Original', language='python')
    before = client.get(url).json()
    response = client.patch(url, headers=headers, json={'title': 'New'})
    assert response.status_code == 200
    expected = {**before, 'title': 'New'}
    assert response.json() == expected
    assert client.get(url).json() == expected
    response = client.patch(url, headers=headers, json={'language': None})
    expected['language'] = None
    assert response.json() == expected
    response = client.patch(url, headers=headers, json={'title': None})
    expected['title'] = None
    assert response.json() == expected
    assert client.patch(url, headers=headers, json={}).json() == expected
    assert client.get(url).json() == expected
    response = client.patch(url, headers=headers, json={'title': 'Again', 'language': 'text'})
    assert response.json() == {**before, 'title': 'Again', 'language': 'text'}


@pytest.mark.parametrize('payload', [
    {'content': 'changed'}, {'id': 'x' * 22}, {'created_at': '2000-01-01T00:00:00Z'},
    {'management_key': 'replacement'}, {'management_key_hash': 'x' * 64}, {'unknown': 'x'},
])
def test_patch_forbids_immutable_and_unknown_fields(client, payload):
    url, headers, _ = create_managed(client)
    before = client.get(url).json()
    response = client.patch(url, headers=headers, json={'title': 'must not persist', **payload})
    assert response.status_code == 422
    assert client.get(url).json() == before


@pytest.mark.parametrize('payload', [
    {'id': 'x' * 22}, {'management_key': 'replacement'},
    {'management_key_hash': 'x' * 64}, {'unknown': 'x'},
])
def test_post_forbids_unknown_fields(client, payload):
    assert client.post('/pastes', json={'content': 'text', **payload}).status_code == 422


@pytest.mark.parametrize('metadata', [
    {'title': 'x' * 201}, {'language': 'x' * 51}, {'title': 123}, {'language': False},
    {'title': []}, {'language': {}}, {'title': 'a\x00b'}, {'language': 'a\x00b'},
])
def test_metadata_validation_for_post_and_patch(client, metadata):
    assert client.post('/pastes', json={'content': 'text', **metadata}).status_code == 422
    url, headers, _ = create_managed(client)
    before = client.get(url).json()
    assert client.patch(url, headers=headers, json=metadata).status_code == 422
    assert client.get(url).json() == before


@pytest.mark.parametrize('metadata', [
    {'title': None, 'language': None}, {'title': '', 'language': ''},
    {'title': '🙂' * 200, 'language': 'я' * 50},
])
def test_metadata_valid_boundaries(client, metadata):
    url, headers, created = create_managed(client, **metadata)
    assert {field: created[field] for field in metadata} == metadata
    assert client.patch(url, headers=headers, json=metadata).status_code == 200
    public = client.get(url).json()
    assert {field: public[field] for field in metadata} == metadata


def test_delete_and_repeated_delete(client):
    url, headers, created = create_managed(client)
    response = client.delete(url, headers=headers)
    assert response.status_code == 204
    assert response.content == b''
    with SessionLocal() as session:
        assert session.get(Paste, created['id']) is None
    assert client.get(url).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404
    assert client.patch(url, headers=headers, json={}).status_code == 404
    assert client.delete(url).status_code == 401


def test_migration_preserves_v01_paste(client):
    # conftest guarantees a dedicated *_test database and serial execution.
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.downgrade(config, '0001')
    try:
        with engine.begin() as connection:
            before = connection.execute(text(
                "INSERT INTO pastes (id, content) VALUES (:id, :content) "
                "RETURNING id, content, created_at"
            ), {'id': 'm' * 22, 'content': '  legacy\r\n\t🙂 '}).one()
    finally:
        command.upgrade(config, 'head')
    command.check(config)
    with SessionLocal() as session:
        stored = session.get(Paste, before.id)
        assert (stored.id, stored.content, stored.created_at) == tuple(before)
        assert stored.management_key_hash is None
        assert stored.title is None
        assert stored.language is None
    url = '/pastes/' + before.id
    assert client.get(url).json()['content'] == before.content
    assert client.delete(url, headers={'Authorization': 'Bearer any-key'}).status_code == 403
