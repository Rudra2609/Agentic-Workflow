# Code summaries: tpl_tcp_server_client

The tpl_tcp_server_client repository implements a simple TCP chat system using only the standard library. The `client.py::main` function reads lines from stdin, sends them to the server, and prints any incoming messages, while MAX_LINE defines the maximum allowed line length for the UTF‑8, newline‑terminated wire format. The handle_client routine runs each connection in its own thread, broadcasting each received message to all other connected clients. Together, the protocol module defines the message format, the client module provides the user interface, and the server module manages multi‑client communication.

Public functions and classes: 17; described: 100 % (from docstrings or the model; the rest show their signature).

## `client.py`

“TCP chat client: lines typed on stdin are sent to the server; messages from the server are printed.”

- `client.py::ChatClient`: Defines a TCP chat client that connects to a server and manages sending and receiving messages.
- `client.py::ChatClient.__init__`: Initializes the client by creating a socket connection and setting up a line reader and pending message list.
- `client.py::ChatClient.send`: Sends a message string to the server over the socket.
- `client.py::ChatClient.receive`: “The next complete message from the server (blocks; raises ConnectionError when the server closed).”
- `client.py::ChatClient.close`: Closes the client's socket connection.
- `client.py::main`: Parses command-line arguments, starts a thread to print incoming messages, and sends user input to the server.

## `protocol.py`

“Wire format: UTF-8 text messages, one per line (``\n``-terminated).”

- `protocol.py::encode`: “One message as bytes on the wire (newlines inside a message become spaces).”
- `protocol.py::LineReader`: “Splits a byte stream into complete lines; keeps a partial line until the rest arrives.”
- `protocol.py::LineReader.__init__`: Initializes an empty byte buffer for accumulating incoming data.
- `protocol.py::LineReader.feed`: Appends data, extracts complete lines, decodes them, and raises error if a line exceeds MAX_LINE.

## `server.py`

“Multi-client TCP chat server: every client is served on its own thread at the same time, and each message a client sends is broadcast to every other connected client.”

- `server.py::ChatServer`: Defines a multi-client TCP chat server that handles connections, broadcasting, and client lifecycle.
- `server.py::ChatServer.__init__`: Initializes server with host, port, socket, client dict, lock, running event, and client ID counter.
- `server.py::ChatServer.start`: “Bind, listen and accept clients on a background thread; returns the port (useful with port=0).”
- `server.py::ChatServer.stop`: Stops server, closes listening socket, clears client list, and closes all client connections.
- `server.py::ChatServer.client_count`: Returns the current number of connected clients.
- `server.py::ChatServer.broadcast`: “Send ``message`` to every client except ``sender``; clients that fail are dropped.”
- `server.py::main`: Parses host/port arguments, starts server, prints listening address, and waits until interrupted to stop server.
