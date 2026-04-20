"""
Re-stream a Basler camera as a virtual webcam.

Requirements:
    pip install pypylon pyvirtualcam opencv-python-headless

Virtual camera backend (install ONE):
    - OBS Virtual Camera: install OBS Studio (includes it)
    - Unity Capture: https://github.com/schellingb/UnityCapture

Usage:
    python basler_webcam.py
    python basler_webcam.py --width 1280 --height 720 --fps 30
    python basler_webcam.py --list          # list available Basler cameras
    python basler_webcam.py --serial <SN>   # use a specific camera by serial number
"""

import argparse
import sys
import signal

import cv2
import numpy as np
from pypylon import pylon
import pyvirtualcam


def list_cameras():
    tlf = pylon.TlFactory.GetInstance()
    devices = tlf.EnumerateDevices()
    if not devices:
        print("No Basler cameras found.")
        return
    print(f"Found {len(devices)} Basler camera(s):")
    for i, dev in enumerate(devices):
        print(f"  [{i}] {dev.GetModelName()}  SN: {dev.GetSerialNumber()}  ({dev.GetDeviceClass()})")


def open_camera(serial=None):
    tlf = pylon.TlFactory.GetInstance()
    if serial:
        info = pylon.DeviceInfo()
        info.SetSerialNumber(serial)
        return pylon.InstantCamera(tlf.CreateDevice(info))
    return pylon.InstantCamera(tlf.CreateFirstDevice())


def main():
    parser = argparse.ArgumentParser(description="Re-stream Basler camera as virtual webcam")
    parser.add_argument("--list", action="store_true", help="List available Basler cameras and exit")
    parser.add_argument("--serial", type=str, default=None, help="Camera serial number")
    parser.add_argument("--width", type=int, default=1280, help="Output width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Output height (default: 720)")
    parser.add_argument("--fps", type=int, default=30, help="Target FPS (default: 30)")
    parser.add_argument("--pixel-format", type=str, default=None,
                        help="Basler pixel format (e.g. Mono8, BayerRG8, RGB8). Auto-detected if omitted.")
    args = parser.parse_args()

    if args.list:
        list_cameras()
        return

    camera = open_camera(args.serial)
    camera.Open()

    model = camera.GetDeviceInfo().GetModelName()
    sn = camera.GetDeviceInfo().GetSerialNumber()
    print(f"Opened: {model} (SN: {sn})")

    # Set pixel format if requested
    if args.pixel_format:
        camera.PixelFormat.SetValue(args.pixel_format)

    # Configure acquisition
    camera.AcquisitionFrameRateEnable.SetValue(True)
    camera.AcquisitionFrameRate.SetValue(float(args.fps))

    # Set up format converter to always get BGR output for the virtual cam
    converter = pylon.ImageFormatConverter()
    converter.OutputPixelFormat = pylon.PixelType_BGR8packed
    converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    # Grab one frame to confirm actual resolution
    grab = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
    if not grab.GrabSucceeded():
        print("Failed to grab initial frame.")
        camera.Close()
        sys.exit(1)
    src_h, src_w = grab.Height, grab.Width
    print(f"Camera resolution: {src_w}x{src_h}")
    grab.Release()

    out_w, out_h = args.width, args.height
    need_resize = (src_w != out_w or src_h != out_h)

    print(f"Virtual webcam: {out_w}x{out_h} @ {args.fps} fps")
    print("Press Ctrl+C to stop.")

    running = True

    def on_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGBREAK, on_signal)

    with pyvirtualcam.Camera(width=out_w, height=out_h, fps=args.fps, print_fps=True) as vcam:
        print(f"Virtual camera device: {vcam.device}")

        while running and camera.IsGrabbing():
            grab = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            if not grab.GrabSucceeded():
                continue

            # Convert to BGR
            image = converter.Convert(grab)
            frame_bgr = image.GetArray()
            grab.Release()

            if need_resize:
                frame_bgr = cv2.resize(frame_bgr, (out_w, out_h))

            # pyvirtualcam expects RGB
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            vcam.send(frame_rgb)
            vcam.sleep_until_next_frame()

    camera.StopGrabbing()
    camera.Close()
    print("Stopped.")


if __name__ == "__main__":
    main()
