"""
Phase 3 Test: Multiple SiLA 2 Servers

This script demonstrates working with multiple SiLA 2 servers simultaneously:
  1. Connecting to three different device servers
  2. Server discovery via SiLAService introspection
  3. Exercising each device's unique features
  4. Cross-device coordination (simulate a lab workflow)

Usage:
    # Start all three servers in separate terminals:
    #   python -m temperature_controller --insecure --port 50052
    #   python -m pump_controller --insecure --port 50053
    #   python -m plate_reader --insecure --port 50054
    #
    # Then run:
    #   python scripts/test_phase3_multiserver.py

This is a learning script, not intended for production use.
"""

import sys
import time

from sila2.client import SilaClient

SERVER_PORTS = {
    "Temperature Controller": 50052,
    "Pump Controller": 50053,
    "Plate Reader": 50054,
}


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def connect_all():
    """Connect to all servers and return a dict of clients."""
    clients = {}
    for name, port in SERVER_PORTS.items():
        try:
            client = SilaClient("127.0.0.1", port, insecure=True)
            server_name = client.SiLAService.ServerName.get()
            server_type = client.SiLAService.ServerType.get()
            features = client.SiLAService.ImplementedFeatures.get()
            print(f"  {server_name} ({server_type}) on port {port}")
            print(f"    Features: {len(features)}")
            for fqi in features:
                print(f"      - {fqi}")
            clients[name] = client
        except Exception as e:
            print(f"  FAILED to connect to {name} on port {port}: {e}")
    return clients


def main():
    # ------------------------------------------------------------------
    # 1. CONNECT TO ALL SERVERS
    # ------------------------------------------------------------------
    separator("1. Connecting to all SiLA 2 servers")
    clients = connect_all()

    if len(clients) < 3:
        print(f"\nOnly {len(clients)}/3 servers connected. Start all servers and retry.")
        print("  python -m temperature_controller --insecure --port 50052")
        print("  python -m pump_controller --insecure --port 50053")
        print("  python -m plate_reader --insecure --port 50054")
        sys.exit(1)

    tc = clients["Temperature Controller"]
    pc = clients["Pump Controller"]
    pr = clients["Plate Reader"]

    # ------------------------------------------------------------------
    # 2. PUMP CONTROLLER: Prime and Dispense
    # ------------------------------------------------------------------
    separator("2. Pump Controller: Prime -> Dispense workflow")

    # Try dispensing without priming (should fail with PumpNotPrimed)
    print("  Dispensing without priming (should fail)...")
    try:
        cmd = pc.PumpController.Dispense(5.0, 2.0)
        while not cmd.done:
            time.sleep(0.1)
        cmd.get_responses()
    except Exception as e:
        print(f"    Caught: {type(e).__name__}")
        print(f"    Message: {e}")

    # Prime the pump
    print("\n  Priming pump...")
    result = pc.PumpController.Prime()
    print(f"    Prime successful: {result.PrimeSuccessful}")
    print(f"    Is primed: {pc.PumpController.IsPrimed.get()}")

    # Dispense 5 mL at 2 mL/s
    print("\n  Dispensing 5.0 mL at 2.0 mL/s...")
    cmd = pc.PumpController.Dispense(5.0, 2.0)
    intermediate_sub = cmd.subscribe_to_intermediate_responses()
    intermediate_sub.add_callback(
        lambda r: print(f"    [Pump] dispensed so far: {r.VolumeDispensedSoFar:.1f} mL")
    )
    while not cmd.done:
        time.sleep(0.2)
    result = cmd.get_responses()
    print(f"    Actual volume dispensed: {result.ActualVolumeDispensed:.2f} mL")

    # Check totals
    total = pc.PumpController.TotalVolumeDispensed.get()
    status = pc.PumpController.GetPumpStatus()
    print(f"    Total dispensed: {total:.1f} mL")
    print(f"    Status: {status.StatusMessage}")

    # ------------------------------------------------------------------
    # 3. PLATE READER: Insert plate and measure
    # ------------------------------------------------------------------
    separator("3. Plate Reader: Insert -> Measure workflow")

    # Check supported wavelengths (List property type)
    wavelengths = pr.PlateReader.SupportedWavelengths.get()
    print(f"  Supported wavelengths: {wavelengths}")

    # Try measuring without a plate (should fail)
    print("\n  Measuring without plate (should fail)...")
    try:
        cmd = pr.PlateReader.RunMeasurement(450, 24)
        while not cmd.done:
            time.sleep(0.1)
        cmd.get_responses()
    except Exception as e:
        print(f"    Caught: {type(e).__name__}: {e}")

    # Insert plate
    print("\n  Inserting plate...")
    pr.PlateReader.InsertPlate()
    print(f"    Plate inserted: {pr.PlateReader.IsPlateInserted.get()}")

    # Run a 24-well measurement at 450nm
    print("\n  Running 24-well measurement at 450 nm...")
    cmd = pr.PlateReader.RunMeasurement(450, 24)
    intermediate_sub = cmd.subscribe_to_intermediate_responses()

    well_count = 0

    def on_well(r):
        nonlocal well_count
        well_count += 1
        # Only print every 6th well to avoid spam
        if well_count % 6 == 0 or well_count <= 3:
            print(f"    [Well {well_count:>3}] {r.WellResult}")

    intermediate_sub.add_callback(on_well)
    while not cmd.done:
        time.sleep(0.1)
    result = cmd.get_responses()

    # Parse CSV results
    lines = result.ResultsCsv.strip().split("\n")
    print(f"\n    Total wells measured: {len(lines) - 1}")  # -1 for header
    print(f"    CSV header: {lines[0]}")
    print(f"    First row:  {lines[1]}")
    print(f"    Last row:   {lines[-1]}")

    timestamp = pr.PlateReader.LastMeasurementTimestamp.get()
    print(f"    Measurement timestamp: {timestamp}")

    # Eject plate
    pr.PlateReader.EjectPlate()
    print(f"    Plate ejected: {not pr.PlateReader.IsPlateInserted.get()}")

    # ------------------------------------------------------------------
    # 4. SIMULATED LAB WORKFLOW
    # ------------------------------------------------------------------
    separator("4. Simulated lab workflow (cross-device coordination)")

    print("  Scenario: Heat sample, dispense reagent, read plate")
    print()

    # Step 1: Heat to 37 degC
    print("  Step 1: Heating sample to 37 degC...")
    cmd = tc.TemperatureController.SetTemperature(37.0, 10.0)
    while not cmd.done:
        time.sleep(0.2)
    result = cmd.get_responses()
    print(f"    Temperature reached: {result.FinalTemperature:.1f} degC")

    # Step 2: Dispense reagent
    print("  Step 2: Dispensing 2.0 mL reagent...")
    cmd = pc.PumpController.Dispense(2.0, 5.0)
    while not cmd.done:
        time.sleep(0.2)
    result = cmd.get_responses()
    print(f"    Dispensed: {result.ActualVolumeDispensed:.1f} mL")

    # Step 3: Read plate
    print("  Step 3: Reading plate (24-well, 280 nm)...")
    pr.PlateReader.InsertPlate()
    cmd = pr.PlateReader.RunMeasurement(280, 24)
    while not cmd.done:
        time.sleep(0.2)
    result = cmd.get_responses()
    lines = result.ResultsCsv.strip().split("\n")
    print(f"    Measured {len(lines) - 1} wells")

    # Step 4: Cool down
    print("  Step 4: Stopping temperature control...")
    stop_result = tc.TemperatureController.StopTemperatureControl()
    print(f"    Temperature at stop: {stop_result.TemperatureAtStop:.1f} degC")

    print("\n  Workflow complete!")

    # ------------------------------------------------------------------
    # 5. FINAL STATUS CHECK
    # ------------------------------------------------------------------
    separator("5. Final status of all servers")

    tc_status = tc.TemperatureController.GetDeviceStatus()
    pc_status = pc.PumpController.GetPumpStatus()
    pr_status = pr.PlateReader.GetReaderStatus()

    print(f"  Temperature Controller: {tc_status.StatusMessage}")
    print(f"  Pump Controller:        {pc_status.StatusMessage}")
    print(f"  Plate Reader:           {pr_status.StatusMessage}")

    # ------------------------------------------------------------------
    # DONE
    # ------------------------------------------------------------------
    separator("Phase 3 tests complete!")
    print("SiLA 2 concepts demonstrated:")
    print("  - Multi-server connections")
    print("  - SiLAService introspection (feature discovery)")
    print("  - Prerequisite command pattern (Prime -> Dispense)")
    print("  - List property type (SupportedWavelengths)")
    print("  - Many intermediate responses (well-by-well plate reading)")
    print("  - CSV data as command response")
    print("  - Cross-device lab workflow coordination")
    print()


if __name__ == "__main__":
    main()
