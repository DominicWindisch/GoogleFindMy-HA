# Path: custom_components/googlefindmy/NovaApi/ExecuteAction/LocateTracker/location_request.py
import asyncio
import logging
from custom_components.googlefindmy.NovaApi.ExecuteAction.nbe_execute_action import create_action_request, serialize_action_request
from custom_components.googlefindmy.NovaApi.nova_request import async_nova_request
from custom_components.googlefindmy.NovaApi.scopes import NOVA_ACTION_API_SCOPE
from custom_components.googlefindmy.NovaApi.util import generate_random_uuid
from custom_components.googlefindmy.ProtoDecoders import DeviceUpdate_pb2
from custom_components.googlefindmy.Auth.fcm_receiver_ha import FcmReceiverHA

_LOGGER = logging.getLogger(__name__)

def create_location_request(canonic_device_id, fcm_registration_id, request_uuid):
    action_request = create_action_request(canonic_device_id, fcm_registration_id, request_uuid=request_uuid)
    action_request.action.locateTracker.lastHighTrafficEnablingTime.seconds = 1732120060
    action_request.action.locateTracker.contributorType = DeviceUpdate_pb2.SpotContributorType.FMDN_ALL_LOCATIONS
    return serialize_action_request(action_request)

async def get_location_data_for_device(canonic_device_id, name):
    _LOGGER.debug(f"Requesting location data for {name}...")
    try:
        request_uuid = generate_random_uuid()
        location_event = asyncio.Event()
        received_location_data = {}

        fcm_receiver = FcmReceiverHA()

        def location_callback(response_canonic_id, hex_response):
            if location_event.is_set():
                return

            try:
                from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_update_protobuf
                from custom_components.googlefindmy.NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations
                
                device_update = parse_device_update_protobuf(hex_response)
                if response_canonic_id == canonic_device_id:
                    location_data = decrypt_location_response_locations(device_update)
                    if location_data:
                        nonlocal received_location_data
                        received_location_data = location_data[0]
            except Exception as e:
                _LOGGER.error(f"Error in location_callback for {name}: {e}")
            finally:
                location_event.set()

        fcm_token = await fcm_receiver.async_register_for_location_updates(canonic_device_id, location_callback)
        if not fcm_token:
            _LOGGER.error(f"Failed to get FCM token for {name}")
            return {}

        hex_payload = create_location_request(canonic_device_id, fcm_token, request_uuid)
        await async_nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

        try:
            await asyncio.wait_for(location_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Location request for {name} timed out after 60s.")
            return {}
        finally:
            await fcm_receiver.async_unregister_for_location_updates(canonic_device_id)

        return received_location_data
    except Exception as e:
        _LOGGER.error(f"Error requesting location for {name}: {e}")
        return {}