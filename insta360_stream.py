"""
Independent Insta360 MJPEG stream server.
Reads from camera index 0 (Insta360 X4) and serves MJPEG at http://localhost:9100/stream
This is independent from Jarvis — Jarvis uses index 1 (Mac built-in camera).
"""

import cv2
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

CAMERA_INDEX = 0
PORT = 9100

cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    print(f"❌ Cannot open Insta360 at index {CAMERA_INDEX}")
    exit(1)

lock = threading.Lock()
print(f"✅ Insta360 stream server starting on http://0.0.0.0:{PORT}/stream")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            while True:
                with lock:
                    ret, frame = cap.read()
                if not ret:
                    continue
                _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                data = jpg.tobytes()
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n")
                    self.wfile.write(data)
                    self.wfile.write(b"\r\n")
                except BrokenPipeError:
                    break
        else:
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"Insta360 stream at /stream")
            except BrokenPipeError:
                pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


server = HTTPServer(("0.0.0.0", PORT), Handler)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    cap.release()
    server.server_close()
    print("\n👋 Insta360 stream stopped")
