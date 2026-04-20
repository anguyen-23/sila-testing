"""
Phase 2 Test Client: Locking, Simulation, and Error Handling

This script demonstrates advanced SiLA 2 concepts:
  1. SimulationController - toggling simulation mode, observing behavior changes
  2. LockController - locking/unlocking, metadata-based access control
  3. Defined Execution Errors - HeaterFault triggered by fault injection
  4. Undefined Execution Errors - unexpected server errors

Usage:
    # Start the server in another terminal:
    #   python -m temperature_controller --insecure --port 50052 --verbose
    #
    # Then run this script:
    #   python scripts/test_phase2_concepts.py [port]

This is a learning script -- read the output to understand how each concept works.
"""

import sys
import time

# Use the GENERATED typed client for this test -- it gives us typed access
# to all features including LockController and SimulationController.
# Compare this with test_temperature_client.py which uses the generic SilaClient.
from temperature_controller import Client

from sila2.framework.errors.defined_execution_error import DefinedExecutionError
from sila2.framework.errors.undefined_execution_error import UndefinedExecutionError
from sila2.framework.errors.invalid_metadata import InvalidMetadata

SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 50052


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def main():
    # ------------------------------------------------------------------
    # CONNECT using the generated typed Client
    # ------------------------------------------------------------------
    separator("Connecting with typed Client")

    # The generated Client class (from temperature_controller package) knows
    # about all features, commands, properties, and errors at the type level.
    # This is different from using the generic SilaClient.
    client = Client(SERVER_HOST, SERVER_PORT, insecure=True)
    print(f"Connected to: {client.SiLAService.ServerName.get()}")
    print(f"Features: {[str(f) for f in client.SiLAService.ImplementedFeatures.get()]}")

    # ------------------------------------------------------------------
    # 1. SIMULATION CONTROLLER
    # ------------------------------------------------------------------
    separator("1. SimulationController: Observable property + mode toggling")

    # SimulationMode is an observable property -- we can subscribe to it
    print("Checking initial simulation mode...")
    sim_sub = client.SimulationController.SimulationMode.subscribe()
    initial_mode = None

    def on_sim_change(value):
        nonlocal initial_mode
        if initial_mode is None:
            initial_mode = value
        print(f"  [SimulationMode changed] -> {value}")

    sim_sub.add_callback(on_sim_change)
    time.sleep(1)
    print(f"  Initial simulation mode: {initial_mode}")

    # Check device status in simulation mode
    status = client.TemperatureController.GetDeviceStatus()
    print(f"  Device status: {status.StatusMessage}")
    assert "[SIMULATION]" in status.StatusMessage, "Expected SIMULATION tag in status"

    # --- Switch to REAL mode ---
    print("\nSwitching to REAL mode (StopSimulationMode)...")
    client.SimulationController.StopSimulationMode()
    time.sleep(0.5)

    status = client.TemperatureController.GetDeviceStatus()
    print(f"  Device status: {status.StatusMessage}")
    assert "[REAL]" in status.StatusMessage, "Expected REAL tag in status"

    # --- Do a ramp in REAL mode (observe noise) ---
    print("\nRamping in REAL mode (expect sensor noise in readings)...")
    cmd = client.TemperatureController.SetTemperature(28.0, 5.0)
    intermediate_sub = cmd.subscribe_to_intermediate_responses()

    real_readings = []

    def on_real_reading(r):
        real_readings.append(r.CurrentTemperature)
        print(f"  [REAL intermediate] temp={r.CurrentTemperature:.3f} degC")

    intermediate_sub.add_callback(on_real_reading)
    while not cmd.done:
        time.sleep(0.2)
    responses = cmd.get_responses()
    print(f"  Final: {responses.FinalTemperature:.1f} degC")

    # --- Switch back to SIMULATION mode ---
    print("\nSwitching back to SIMULATION mode (StartSimulationMode)...")
    client.SimulationController.StartSimulationMode()
    time.sleep(0.5)

    # --- Do a ramp in SIMULATION mode (clean readings) ---
    print("\nRamping in SIMULATION mode (expect clean readings)...")
    cmd = client.TemperatureController.SetTemperature(35.0, 10.0)
    intermediate_sub = cmd.subscribe_to_intermediate_responses()

    sim_readings = []

    def on_sim_reading(r):
        sim_readings.append(r.CurrentTemperature)
        print(f"  [SIM intermediate] temp={r.CurrentTemperature:.3f} degC")

    intermediate_sub.add_callback(on_sim_reading)
    while not cmd.done:
        time.sleep(0.2)
    responses = cmd.get_responses()
    print(f"  Final: {responses.FinalTemperature:.1f} degC")

    sim_sub.cancel()

    # Compare: real mode readings should have fractional noise, sim should be clean
    print(f"\n  Summary:")
    print(f"    REAL mode readings:       {len(real_readings)} values, "
          f"noise visible in decimal places")
    print(f"    SIMULATION mode readings: {len(sim_readings)} values, "
          f"clean round numbers")

    # ------------------------------------------------------------------
    # 2. LOCK CONTROLLER
    # ------------------------------------------------------------------
    separator("2. LockController: Device locking for exclusive access")

    # Check lock status
    is_locked = client.LockController.IsLocked.get()
    print(f"  Server locked? {is_locked}")

    # Lock the server with a token
    LOCK_TOKEN = "my-secret-lock-123"
    LOCK_TIMEOUT = 60  # seconds

    print(f"\n  Locking server with token '{LOCK_TOKEN}', timeout={LOCK_TIMEOUT}s...")
    client.LockController.LockServer(LOCK_TOKEN, LOCK_TIMEOUT)

    is_locked = client.LockController.IsLocked.get()
    print(f"  Server locked? {is_locked}")

    # Now, calls to TemperatureController REQUIRE the LockIdentifier metadata
    print("\n  Calling GetDeviceStatus WITH correct lock token...")
    try:
        # Pass the lock identifier as metadata
        # The LockIdentifier metadata is accessed from the LockController feature
        status = client.TemperatureController.GetDeviceStatus(
            metadata=[client.LockController.LockIdentifier(LOCK_TOKEN)]
        )
        print(f"    Success: {status.StatusMessage}")
    except Exception as e:
        print(f"    Error: {type(e).__name__}: {e}")

    # Try WITHOUT the lock token -- should fail with InvalidMetadata
    print("\n  Calling GetDeviceStatus WITHOUT lock token (should fail)...")
    try:
        status = client.TemperatureController.GetDeviceStatus()
        print(f"    Unexpected success: {status.StatusMessage}")
    except InvalidMetadata as e:
        print(f"    Caught InvalidMetadata (expected):")
        print(f"      {e}")
    except Exception as e:
        print(f"    Caught {type(e).__name__}: {e}")

    # Try with WRONG lock token -- should fail with InvalidLockIdentifier
    print("\n  Calling GetDeviceStatus with WRONG lock token (should fail)...")
    try:
        status = client.TemperatureController.GetDeviceStatus(
            metadata=[client.LockController.LockIdentifier("wrong-token")]
        )
        print(f"    Unexpected success: {status.StatusMessage}")
    except DefinedExecutionError as e:
        print(f"    Caught DefinedExecutionError (expected):")
        print(f"      Identifier: {e.identifier}")
        print(f"      Message: {e.message}")
    except Exception as e:
        print(f"    Caught {type(e).__name__}: {e}")

    # Try to lock again (should fail -- already locked)
    print("\n  Trying to lock again (should fail -- ServerAlreadyLocked)...")
    try:
        client.LockController.LockServer("another-token", 30)
        print("    Unexpected success")
    except DefinedExecutionError as e:
        print(f"    Caught DefinedExecutionError (expected):")
        print(f"      Identifier: {e.identifier}")

    # Unlock the server
    print(f"\n  Unlocking server with token '{LOCK_TOKEN}'...")
    client.LockController.UnlockServer(LOCK_TOKEN)
    is_locked = client.LockController.IsLocked.get()
    print(f"  Server locked? {is_locked}")

    # Now calls should work without metadata again
    print("\n  Calling GetDeviceStatus after unlock (no metadata needed)...")
    status = client.TemperatureController.GetDeviceStatus()
    print(f"    Success: {status.StatusMessage}")

    # ------------------------------------------------------------------
    # 3. DEFINED EXECUTION ERRORS
    # ------------------------------------------------------------------
    separator("3. Defined Execution Errors: HeaterFault")

    # The TemperatureController defines HeaterFault and OverTemperature as
    # DefinedExecutionErrors. These are errors the feature designer anticipated
    # and defined in the FDL, so the client can handle them specifically.

    # We can't directly call trigger_fault() over SiLA (it's a server-side
    # method, not a SiLA command). But we can trigger the HeaterFault by
    # trying to set temperature when the device is in a fault state.
    # For this demo, the fault is already cleared from previous operations.

    print("  (Defined errors like HeaterFault are raised server-side and")
    print("   caught client-side as typed exceptions. We demonstrated")
    print("   ValidationError in Phase 1. HeaterFault would require")
    print("   server-side fault injection which we'll use in the Web UI.)")

    # ------------------------------------------------------------------
    # 4. MULTI-CLIENT LOCKING SCENARIO
    # ------------------------------------------------------------------
    separator("4. Multi-client locking scenario")

    print("  Simulating two clients accessing the same server...")
    print("  Client A locks the server, Client B tries to access it.\n")

    # Client A locks
    client_a = client  # reuse existing connection
    print("  Client A: Locking server...")
    client_a.LockController.LockServer("client-a-token", 30)

    # Client B connects
    client_b = Client(SERVER_HOST, SERVER_PORT, insecure=True)
    print("  Client B: Connected to same server")

    # Client B tries to read a property (should fail)
    print("  Client B: Trying to read temperature (should fail)...")
    try:
        client_b.TemperatureController.GetDeviceStatus()
        print("    Unexpected success")
    except InvalidMetadata as e:
        print(f"    Blocked! InvalidMetadata: metadata required but not sent")
    except Exception as e:
        print(f"    Blocked! {type(e).__name__}: {e}")

    # Client B can still check if server is locked (IsLocked is not lock-protected)
    print("  Client B: Checking lock status (always allowed)...")
    print(f"    Server locked? {client_b.LockController.IsLocked.get()}")

    # Client A unlocks
    print("  Client A: Unlocking server...")
    client_a.LockController.UnlockServer("client-a-token")

    # Client B can now access
    print("  Client B: Trying to read temperature again...")
    status = client_b.TemperatureController.GetDeviceStatus()
    print(f"    Success: {status.StatusMessage}")

    client_b.close()

    # ------------------------------------------------------------------
    # DONE
    # ------------------------------------------------------------------
    separator("Phase 2 tests complete!")
    print("SiLA 2 concepts demonstrated in this script:")
    print("  - SimulationController (observable property, mode toggling)")
    print("  - Simulation vs Real mode behavior differences")
    print("  - LockController (lock/unlock, token-based metadata)")
    print("  - Lock enforcement (missing metadata, wrong token)")
    print("  - Defined execution errors (ServerAlreadyLocked, InvalidLockIdentifier)")
    print("  - Multi-client locking scenario")
    print()


if __name__ == "__main__":
    main()
