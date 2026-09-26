"""Loopback-published TCP relays; SSH provides authentication and encryption.

Resolve upstream Docker service names for every connection, not at startup.
SFTP uses a forced SSH command into this container's bounded filesystem.
"""
import select
import socket
import threading
import os
import json


def proxy(client, destination):
    try:
        with client, socket.create_connection(destination, timeout=15) as upstream:
            client.settimeout(None)
            upstream.settimeout(None)
            while True:
                readable, _, _ = select.select([client, upstream], [], [], 300)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is client else client).sendall(data)
    except OSError as error:
        print(type(error).__name__, flush=True)


def serve(port, host, target_port):
    with socket.create_server(("0.0.0.0", port), backlog=128) as listener:
        while True:
            client, _ = listener.accept()
            threading.Thread(target=proxy, args=(client, (host, target_port)), daemon=True).start()


if __name__ == "__main__":
    for mapping in json.loads(os.environ.get("GATEWAY_TARGETS", '[[15432,"postgres",5432],[16379,"redis",6379],[16333,"qdrant",6333]]')):
        threading.Thread(target=serve, args=mapping, daemon=True).start()
    threading.Event().wait()