import socketserver, threading
class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            self.wfile.write(raw.decode("utf-8").rstrip("\n").upper().encode("utf-8") + b"\n")
class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
class EchoServer:
    def __init__(self, host="127.0.0.1", port=0):
        self.addr = (host, port)
        self.srv = None
    def start(self):
        self.srv = _Srv(self.addr, _Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self.srv.server_address[1]
    def stop(self):
        if self.srv:
            self.srv.shutdown(); self.srv.server_close(); self.srv = None
