import socket, threading
class ChatServer:
    def __init__(self, host="127.0.0.1", port=0):
        self.addr = (host, port)
        self.clients = {}
        self.lock = threading.Lock()
        self.sock = None
        self.running = False
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(self.addr); self.sock.listen()
        self.running = True
        threading.Thread(target=self._accept, daemon=True).start()
        return self.sock.getsockname()[1]
    def _accept(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
    def _broadcast(self, text, exclude):
        with self.lock:
            targets = [c for n, c in self.clients.items() if n != exclude]
        for c in targets:
            try:
                c.sendall((text + "\n").encode())
            except OSError:
                pass
    def _serve(self, conn):
        f = conn.makefile("r", encoding="utf-8", newline="\n")
        name = None
        try:
            first = f.readline()
            if not first.startswith("NAME "):
                return
            cand = first[5:].strip()
            with self.lock:
                if not cand or cand in self.clients:
                    conn.sendall(b"ERROR name taken\n")
                    return
                self.clients[cand] = conn
                name = cand
            conn.sendall(b"OK\n")
            self._broadcast(f"* {name} joined", name)
            for line in f:
                self._broadcast(f"{name}: {line.rstrip(chr(10))}", name)
        except OSError:
            pass
        finally:
            if name:
                with self.lock:
                    self.clients.pop(name, None)
                self._broadcast(f"* {name} left", name)
            try:
                f.close()
                conn.close()
            except OSError:
                pass
    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        with self.lock:
            conns = list(self.clients.values()); self.clients.clear()
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR); c.close()
            except OSError:
                pass
