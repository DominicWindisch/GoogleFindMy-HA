"""Location request for Google Find My Device."""
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
    """Create a location request."""
    action_request = create_action_request(canonic_device_id, fcm_registration_id, request_uuid=request_uuid)
    action_request.action.locateTracker.lastHighTrafficEnablingTime.seconds = 1732120060
    action_request.action.locateTracker.contributorType = DeviceUpdate_pb2.SpotContributorType.FMDN_ALL_LOCATIONS
    return serialize_action_request(action_request)

async def get_location_data_for_device(canonic_device_id, name):
    """Get location data for a device."""
    _LOGGER.info(f"GoogleFindMyTools: Requesting location data for {name}...")

    try:
        request_uuid = generate_random_uuid()
        location_event = asyncio.Event()

        def location_callback(response_canonic_id, hex_response):
            """Handle the location callback."""
            try:
                _LOGGER.info(f"FCM callback triggered for {name}, processing response...")
                from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_update_protobuf
                from custom_components.googlefindmy.NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations

                device_update = parse_device_update_protobuf(hex_response)

                if response_canonic_id != canonic_device_id:
                    _LOGGER.warning(f"FCM callback received data for device {response_canonic_id}, but we requested {canonic_device_id}. Ignoring.")
                    return

                location_data = decrypt_location_response_locations(device_update)

                if location_data:
                    _LOGGER.info(f"Successfully decrypted {len(location_data)} location records for {name}")
                    location_data[0]["canonic_id"] = response_canonic_id
                    setattr(location_event, "location_data", location_data)
                    location_event.set()
                else:
                    _LOGGER.warning(f"No location data found after decryption for {name}")

            except Exception as callback_error:
                _LOGGER.error(f"Error processing FCM callback for {name}: {callback_error}")
                import traceback
                _LOGGER.debug(f"FCM callback traceback: {traceback.format_exc()}")

        fcm_receiver = FcmReceiverHA()
        fcm_token = await fcm_receiver.async_register_for_location_updates(canonic_device_id, location_callback)

        if not fcm_token:
            _LOGGER.error(f"Failed to get FCM token for {name}")
            return None

        hex_payload = create_location_request(canonic_device_id, fcm_token, request_uuid)
        nova_result = await async_nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

        if nova_result is None:
            _LOGGER.error(f"Failed to send location request for {name}")
            return None

        _LOGGER.info(f"Location request accepted by Google for {name} (response length: {len(nova_result)} chars)")
        return location_event

    except Exception as e:
        _LOGGER.error(f"Error requesting location for {name}: {e}")
        import traceback
        _LOGGER.error(f"Traceback: {traceback.format_exc()}")
        return None