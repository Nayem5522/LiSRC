import os
from http.server import SimpleHTTPRequestHandler, HTTPServer

def start_web():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"Web server running on port {port}")
    server.serve_forever()
