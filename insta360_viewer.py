"""
Simple Insta360 camera viewer — opens Chrome to show the live feed.
Uses a local HTTP server that streams MJPEG from device index 1.
"""

import cv2
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

CAMERA_INDEX = 0  # Insta360 X4 (UVC Camera VendorID_11802 ProductID_3)
PORT = 9100

cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    print(f"❌ Cannot open camera at index {CAMERA_INDEX}")
    exit(1)

print(f"✅ Insta360 camera opened (index {CAMERA_INDEX})")


class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""<!DOCTYPE html>
<html><head><title>Insta360 Live</title>
<style>
  body { margin:0; background:#000; display:flex; justify-content:center; align-items:center; height:100vh; }
  img  { max-width:100vw; max-height:100vh; }
</style>
</head><body>
<img src="/stream">
</body></html>""")
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                _, jpg = cv2.imencode(".jpg", frame)
                data = jpg.tobytes()
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(data)
                    self.wfile.write(b"\r\n")
                except BrokenPipeError:
                    break

    def log_message(self, fmt, *args):
        pass  # silence request logs


server = HTTPServer(("0.0.0.0", PORT), MJPEGHandler)
url = f"http://localhost:{PORT}"
print(f"🎥 Streaming at {url}")
threading.Timer(0.5, lambda: webbrowser.open(url)).start()

try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    cap.release()
    server.server_close()
    print("\n👋 Stopped")
