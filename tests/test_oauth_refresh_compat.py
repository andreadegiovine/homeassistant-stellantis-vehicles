"""Exercise auth recovery combined with the companion per-account refresh lock."""
import asyncio
import os
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.stellantis_vehicles import stellantis
from custom_components.stellantis_vehicles.exceptions import CommunicationError, RateLimitException


@pytest.fixture
def client():
    if not hasattr(stellantis.StellantisVehicles, '_refresh_oauth_token_request_locked'):
        if os.environ.get('STELLANTIS_REQUIRE_REFRESH_LOCK') == '1':
            pytest.fail('The compatibility job must include the companion refresh lock')
        pytest.skip('Companion PR #672 is not present in the standalone variant')
    instance = stellantis.StellantisVehicles(Mock())
    instance.save_config({'oauth': {'refresh_token': 'synthetic-old'}})
    instance.apply_query_params = Mock(return_value='https://example.invalid/token')
    instance.apply_dict_params = Mock(return_value={})
    instance.update_stored_config = Mock()
    return instance


def token_response():
    return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-new',
            'expires_in': 3600}


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['success', 'auth_failure', 'shutdown'])
async def test_queued_refresh_observes_preceding_result(client, outcome):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def request(*args):
        entered.set()
        await release.wait()
        if outcome == 'auth_failure':
            raise ConfigEntryAuthFailed('invalid_grant')
        return token_response()

    client.make_http_request = AsyncMock(side_effect=request)
    first = asyncio.create_task(client.refresh_oauth_token_request())
    tasks = [first]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        tasks.append(asyncio.create_task(client.refresh_oauth_token_request()))
        await asyncio.sleep(0)  # Let the second caller queue behind the first.
        client.make_http_request.assert_awaited_once()
        assert not tasks[1].done()
        if outcome == 'shutdown':
            client._shutting_down = True
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        client.make_http_request.assert_awaited_once()
        if outcome == 'success':
            assert results == [None, None]
            assert client.get_config('oauth')['refresh_token'] == 'synthetic-new'
            client.update_stored_config.assert_called_once()
        elif outcome == 'auth_failure':
            assert all(isinstance(result, ConfigEntryAuthFailed) for result in results)
            assert client._oauth_auth_failed
            client.update_stored_config.assert_not_called()
        else:
            assert results[0] is None
            assert isinstance(results[1], CommunicationError)
            client.update_stored_config.assert_not_called()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_block_later_refresh(client):
    await client._oauth_refresh_lock.acquire()
    waiter = asyncio.create_task(client.refresh_oauth_token_request())
    try:
        await asyncio.sleep(0)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    finally:
        client._oauth_refresh_lock.release()
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
    client.make_http_request = AsyncMock(return_value=token_response())
    await asyncio.wait_for(client.refresh_oauth_token_request(), 2)
    client.make_http_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_attempts_are_bounded_without_blocking_another_account(client):
    client.make_http_request = AsyncMock(side_effect=CommunicationError('offline'))
    for _ in range(6):
        with pytest.raises(CommunicationError):
            await client.refresh_oauth_token_request()
    with pytest.raises(RateLimitException):
        await client.refresh_oauth_token_request()
    assert client.make_http_request.await_count == 6

    other = stellantis.StellantisVehicles(Mock())
    other.save_config({'oauth': {'refresh_token': 'synthetic-other'}})
    other.apply_query_params = client.apply_query_params
    other.apply_dict_params = client.apply_dict_params
    other.make_http_request = AsyncMock(side_effect=CommunicationError('offline'))
    with pytest.raises(CommunicationError):
        await other.refresh_oauth_token_request()
    other.make_http_request.assert_awaited_once()
