"""
Minimal test client for the Temperature Controller SiLA 2 server.

This script demonstrates the core SiLA 2 communication patterns:
  1. Connecting to a server (insecure, direct IP)
  2. Reading unobservable properties (poll once)
  3. Subscribing to observable properties (live stream)
  4. Executing unobservable commands (simple request/response)
  5. Executing observable commands (long-running with progress + intermediate responses)
  6. Error handling (defined execution errors, validation errors)

Usage:
    # First, start the server in another terminal:
    #   python -m temperature_controller --insecure --port 50052 --verbose
    #
    # Then run this script:
    #   python scripts/test_temperature_client.py

This is a learning script -- read the output and comments to understand
how each SiLA 2 concept works.
"""

import sys
import time

from sila2.client import SilaClient
from sila2.framework.errors.defined_execution_error import DefinedExecutionError
from sila2.framework.errors.validation_error import ValidationError

SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 50052


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def main():
    # ------------------------------------------------------------------
    # 1. CONNECT TO THE SERVER
    # ------------------------------------------------------------------
    separator("1. Connecting to Temperature Controller server")

    # The generated typed Client class gives us autocomplete and type safety,
    # but we use the generic SilaClient here to show the universal approach.
    # Both work identically over the wire.
    try:
        client = SilaClient(SERVER_HOST, SERVER_PORT, insecure=True)
    except Exception as e:
        print(f"ERROR: Could not connect to server at {SERVER_HOST}:{SERVER_PORT}")
        print(f"  {e}")
        print("\nMake sure the server is running:")
        print("  python -m temperature_controller --insecure --port 50052 --verbose")
        sys.exit(1)

    # Server info is accessed through the mandatory SiLAService feature.
    # Every SiLA 2 server MUST implement SiLAService -- it's the entry point
    # for discovering what a server is and what it can do.
    sila_service = client.SiLAService
    print(f"Connected to: {sila_service.ServerName.get()}")
    print(f"Server UUID:  {sila_service.ServerUUID.get()}")
    print(f"Server type:  {sila_service.ServerType.get()}")
    print(f"Description:  {sila_service.ServerDescription.get()}")

    # List all features the server implements
    implemented = sila_service.ImplementedFeatures.get()
    print(f"\nImplemented features ({len(implemented)}):")
    for fqi in implemented:
        print(f"  - {fqi}")

    # ------------------------------------------------------------------
    # 2. READ UNOBSERVABLE PROPERTIES (poll once)
    # ------------------------------------------------------------------
    separator("2. Reading unobservable properties")

    # Unobservable properties are simple request/response -- you call .get()
    # and immediately get the current value.
    temp_feature = client.TemperatureController

    target_temp = temp_feature.TargetTemperature.get()
    is_controlling = temp_feature.IsControlling.get()
    print(f"Target Temperature: {target_temp} degC")
    print(f"Is Controlling:     {is_controlling}")

    # ------------------------------------------------------------------
    # 3. EXECUTE UNOBSERVABLE COMMAND (simple request/response)
    # ------------------------------------------------------------------
    separator("3. Execute unobservable command: GetDeviceStatus")

    # Unobservable commands return immediately with the response.
    status = temp_feature.GetDeviceStatus()
    print(f"Device Status: {status.StatusMessage}")

    # ------------------------------------------------------------------
    # 4. SUBSCRIBE TO OBSERVABLE PROPERTY (live stream)
    # ------------------------------------------------------------------
    separator("4. Subscribe to observable property: CurrentTemperature")

    # Observable properties use server-side streaming (gRPC stream).
    # The server sends the current value immediately on subscription,
    # then pushes updates whenever the value changes.
    print("Subscribing to CurrentTemperature for 3 seconds...")

    subscription = temp_feature.CurrentTemperature.subscribe()

    received_values = []

    def on_temp_update(value):
        received_values.append(value)
        print(f"  [Observable] CurrentTemperature = {value:.2f} degC")

    subscription.add_callback(on_temp_update)
    time.sleep(3)
    subscription.cancel()
    print(f"Received {len(received_values)} updates in 3 seconds")

    # ------------------------------------------------------------------
    # 5. EXECUTE OBSERVABLE COMMAND (long-running with progress)
    # ------------------------------------------------------------------
    separator("5. Execute observable command: SetTemperature")

    # Observable commands are long-running. The server returns a command
    # execution UUID immediately, and you can:
    #   - Subscribe to intermediate responses (temperature readings during ramp)
    #   - Poll progress and estimated remaining time
    #   - Wait for the final response

    print("Starting ramp: target=35.0 degC, rate=5.0 degC/s")
    print("(This should take ~2-3 seconds)\n")

    cmd_instance = temp_feature.SetTemperature(35.0, 5.0)

    # Subscribe to intermediate responses (current temp during ramp)
    intermediate_sub = cmd_instance.subscribe_to_intermediate_responses()
    intermediate_sub.add_callback(
        lambda r: print(f"  [Intermediate] temp={r.CurrentTemperature:.1f} degC, "
                        f"progress={cmd_instance.progress * 100:.0f}%")
    )

    # Wait for the command to complete.
    # get_responses() does NOT block -- it immediately calls the Result RPC
    # and raises CommandExecutionNotFinished if not done yet.
    # So we poll cmd_instance.done (updated by the info subscription thread).
    print("  Waiting for ramp to complete...")
    while not cmd_instance.done:
        time.sleep(0.2)

    responses = cmd_instance.get_responses()
    print(f"\n  Final temperature: {responses.FinalTemperature:.1f} degC")

    # Verify with a property read
    status = temp_feature.GetDeviceStatus()
    print(f"  Device status: {status.StatusMessage}")

    # ------------------------------------------------------------------
    # 6. STOP COMMAND (unobservable)
    # ------------------------------------------------------------------
    separator("6. Execute StopTemperatureControl")

    stop_response = temp_feature.StopTemperatureControl()
    print(f"Temperature at stop: {stop_response.TemperatureAtStop:.1f} degC")

    # ------------------------------------------------------------------
    # 7. ERROR HANDLING: Validation Error
    # ------------------------------------------------------------------
    separator("7. Error handling: Validation Error")

    # The FDL defines constraints: temperature must be -20 to 200 degC.
    # Sending an out-of-range value should trigger a ValidationError.
    print("Attempting SetTemperature with target=999 degC (out of range)...")
    try:
        cmd_instance = temp_feature.SetTemperature(999.0, 5.0)
        cmd_instance.get_responses()
    except ValidationError as e:
        print(f"  Caught ValidationError (expected):")
        print(f"    {e}")
    except DefinedExecutionError as e:
        print(f"  Caught DefinedExecutionError: {e.identifier}")
        print(f"    {e.message}")
    except Exception as e:
        print(f"  Caught {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # 8. ERROR HANDLING: Negative ramp rate (validation)
    # ------------------------------------------------------------------
    separator("8. Error handling: Invalid ramp rate")

    print("Attempting SetTemperature with RampRate=-1 (violates MinimalExclusive=0)...")
    try:
        cmd_instance = temp_feature.SetTemperature(30.0, -1.0)
        cmd_instance.get_responses()
    except ValidationError as e:
        print(f"  Caught ValidationError (expected):")
        print(f"    {e}")
    except Exception as e:
        print(f"  Caught {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # DONE
    # ------------------------------------------------------------------
    separator("All tests complete!")
    print("Key SiLA 2 concepts demonstrated:")
    print("  - Server connection (insecure, direct IP)")
    print("  - Unobservable properties (.get())")
    print("  - Observable properties (.subscribe() with callbacks)")
    print("  - Unobservable commands (immediate response)")
    print("  - Observable commands (progress, intermediate responses, final response)")
    print("  - Validation errors (constraint violations)")
    print()


if __name__ == "__main__":
    main()
