import asyncio
import time

# Import FcmReceiver lazily to avoid protobuf conflicts
from custom_components.googlefindmy.NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations
from custom_components.googlefindmy.NovaApi.ExecuteAction.nbe_execute_action import create_action_request, serialize_action_request
from custom_components.googlefindmy.NovaApi.nova_request import async_nova_request
from custom_components.googlefindmy.NovaApi.scopes import NOVA_ACTION_API_SCOPE
from custom_components.googlefindmy.NovaApi.util import generate_random_uuid
from custom_components.googlefindmy.ProtoDecoders import DeviceUpdate_pb2
from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_update_protobuf
from custom_components.googlefindmy.example_data_provider import get_example_data

def create_location_request(canonic_device_id, fcm_registration_id, request_uuid):

    action_request = create_action_request(canonic_device_id, fcm_registration_id, request_uuid=request_uuid)

    # Random values, can be arbitrary
    action_request.action.locateTracker.lastHighTrafficEnablingTime.seconds = 1732120060
    action_request.action.locateTracker.contributorType = DeviceUpdate_pb2.SpotContributorType.FMDN_ALL_LOCATIONS

    # Convert to hex string
    hex_payload = serialize_action_request(action_request)

    return hex_payload


async def get_location_data_for_device(canonic_device_id, name):
    """Get location data for device - HA-compatible async version."""

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"GoogleFindMyTools: Requesting location data for {name}...")

    try:
        # Generate request UUID
        request_uuid = generate_random_uuid()

        # Use an asyncio.Event to signal when data is received
        location_event = asyncio.Event()
        received_location_data = {}

        def location_callback(response_canonic_id, hex_response):
            try:
                logger.info(f"FCM callback triggered for {name}, processing response...")
                from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_update_protobuf
                from custom_components.googlefindmy.NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations

                device_update = parse_device_update_protobuf(hex_response)

                if response_canonic_id != canonic_device_id:
                    logger.warning(f"FCM callback received data for device {response_canonic_id}, but we requested {canonic_device_id}. Ignoring.")
                    return

                location_data = decrypt_location_response_locations(device_update)

                if location_data:
                    logger.info(f"Successfully decrypted {len(location_data)} location records for {name}")
                    nonlocal received_location_data
                    received_location_data = location_data[0] # Store the first record
                    location_event.set() # Signal that we have the data
                else:
                    logger.warning(f"No location data found after decryption for {name}")
                    location_event.set() # Signal to stop waiting even if no data

            except Exception as callback_error:
                logger.error(f"Error processing FCM callback for {name}: {callback_error}")
                import traceback
                logger.debug(f"FCM callback traceback: {traceback.format_exc()}")
                location_event.set()


        from custom_components.googlefindmy.Auth.fcm_receiver_ha import FcmReceiverHA
        fcm_receiver = FcmReceiverHA()

        if not await fcm_receiver.async_initialize():
            logger.error(f"Failed to initialize FCM receiver for {name}")
            return []

        fcm_token = await fcm_receiver.async_register_for_location_updates(canonic_device_id, location_callback)
        if not fcm_token:
            logger.error(f"Failed to get FCM token for {name}")
            return []

        hex_payload = create_location_request(canonic_device_id, fcm_token, request_uuid)
        await async_nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

        try:
            await asyncio.wait_for(location_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            logger.warning(f"No location response received for {name} within 60s timeout.")
            return {}
        finally:
            await fcm_receiver.async_unregister_for_location_updates(canonic_device_id)

        return received_location_data

    except Exception as e:
        logger.error(f"Error requesting location for {name}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {}