"""Nó do overlay (Etapa 1): obtém os vizinhos do bootstrapper, liga-se a eles
e mantém as ligações com HELLOs periódicos.

Uso: python3 ott.py <nome> <ip_bootstrapper> [--port 5000] [--bport 4000]
"""

import argparse
import logging
import signal
import socket
import sys
import threading
import time
import uuid

from protocol import (BOOTSTRAPPER_PORT, CONTROL_PORT, HELLO_INTERVAL, HELLO_TIMEOUT,
                      make_reader, read_msg, send_msg)

log = logging.getLogger("ott")


class Neighbor:
    """Uma ligação TCP ativa a um vizinho."""

    def __init__(self, name, sock, reader, initiator, boot_id):
        self.name = name
        self.sock = sock
        self.reader = reader
        self.initiator = initiator  # nome do nó que abriu a ligação
        self.boot_id = boot_id      # muda sempre que o vizinho reinicia
        self.last_seen = time.monotonic()
        self.send_lock = threading.Lock()

    def send(self, msg):
        with self.send_lock:
            send_msg(self.sock, msg)

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class Node:
    def __init__(self, name, port, bootstrapper):
        self.name = name
        self.port = port
        self.bootstrapper = bootstrapper
        self.boot_id = uuid.uuid4().hex[:8]
        self.neighbors = {}  # nome -> Neighbor
        self.lock = threading.Lock()

    def hello(self):
        return {"type": "HELLO", "from": self.name, "boot_id": self.boot_id}

    # ---------- arranque ----------

    def run(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen()
        threading.Thread(target=self.accept_loop, args=(listener,), daemon=True).start()
        log.info("à escuta na porta TCP %d", self.port)

        for info in self.register():
            self.connect(info)

        try:
            self.heartbeat_loop()
        except KeyboardInterrupt:
            log.info("a terminar")
        finally:
            listener.close()
            with self.lock:
                neighbors = list(self.neighbors.values())
            for nb in neighbors:
                nb.close()

    def register(self):
        try:
            with socket.create_connection(self.bootstrapper, timeout=5) as s:
                send_msg(s, {"type": "REGISTER", "name": self.name})
                reply = read_msg(make_reader(s))
        except (OSError, ValueError) as e:
            sys.exit(f"não foi possível contactar o bootstrapper {self.bootstrapper}: {e}")

        if not reply or reply.get("type") != "NEIGHBORS":
            sys.exit(f"registo recusado pelo bootstrapper: {reply}")
        log.info("vizinhos no config: %s", [n["name"] for n in reply["neighbors"]])
        return reply["neighbors"]

    def connect(self, info):
        """Liga a um vizinho. Se falhar, é o vizinho que se liga quando arrancar."""
        try:
            sock = socket.create_connection((info["ip"], info["port"]), timeout=2)
        except OSError:
            log.info("%s (%s) indisponível; liga-se quando arrancar", info["name"], info["ip"])
            return
        threading.Thread(target=self.handle_connection, args=(sock, True), daemon=True).start()

    def accept_loop(self, listener):
        while True:
            try:
                sock, _ = listener.accept()
            except OSError:
                return
            threading.Thread(target=self.handle_connection, args=(sock, False), daemon=True).start()

    # ---------- ligações ----------

    def handle_connection(self, sock, outgoing):
        """Os dois lados enviam HELLO logo ao abrir; o primeiro HELLO recebido
        identifica o vizinho. Depois fica a ler mensagens até a ligação cair."""
        reader = make_reader(sock)
        try:
            sock.settimeout(HELLO_TIMEOUT)
            send_msg(sock, self.hello())
            first = read_msg(reader)
            sock.settimeout(None)
        except (OSError, ValueError):
            sock.close()
            return
        if not first or first.get("type") != "HELLO" or "from" not in first:
            sock.close()
            return

        peer = first["from"]
        initiator = self.name if outgoing else peer
        nb = Neighbor(peer, sock, reader, initiator, first.get("boot_id"))
        if not self.add_neighbor(nb):
            return

        reason = "ligação TCP fechada"
        try:
            while True:
                msg = read_msg(reader)
                if msg is None:
                    break
                if msg.get("type") == "HELLO":
                    nb.last_seen = time.monotonic()
                else:
                    log.warning("mensagem desconhecida de %s: %s", peer, msg)
        except (OSError, ValueError) as e:
            reason = f"erro na ligação ({e})"
        self.remove_neighbor(nb, reason)

    def add_neighbor(self, new):
        """Junta o vizinho à tabela. Se já existir uma ligação a esse vizinho:
        - boot_id diferente: o vizinho reiniciou, fica a ligação nova;
        - boot_id igual: os dois nós ligaram-se ao mesmo tempo; fica a ligação
          aberta pelo nó de nome menor (os dois lados escolhem a mesma).
        Devolve True se a ligação nova ficou na tabela."""
        with self.lock:
            old = self.neighbors.get(new.name)
            if old is None or old.boot_id != new.boot_id:
                keep, drop = new, old
            elif new.initiator == min(self.name, new.name):
                keep, drop = new, old
            else:
                keep, drop = old, new
            self.neighbors[new.name] = keep
            names = sorted(self.neighbors)
        if drop is not None:
            drop.close()
        if keep is new and old is None:
            log.info("novo vizinho %s -> vizinhos: %s", new.name, names)
        elif keep is new and old.boot_id != new.boot_id:
            log.info("vizinho %s reiniciou; ligação substituída", new.name)
        return keep is new

    def remove_neighbor(self, nb, reason):
        with self.lock:
            removed = self.neighbors.get(nb.name) is nb
            if removed:
                del self.neighbors[nb.name]
            names = sorted(self.neighbors)
        nb.close()
        if removed:
            log.info("vizinho %s perdido (%s) -> vizinhos: %s", nb.name, reason, names)

    # ---------- heartbeat ----------

    def heartbeat_loop(self):
        while True:
            time.sleep(HELLO_INTERVAL)
            now = time.monotonic()
            with self.lock:
                neighbors = list(self.neighbors.values())
            for nb in neighbors:
                if now - nb.last_seen > HELLO_TIMEOUT:
                    self.remove_neighbor(nb, f"sem HELLO há {HELLO_TIMEOUT:.0f} s")
                    continue
                try:
                    nb.send(self.hello())
                except OSError as e:
                    self.remove_neighbor(nb, f"erro ao enviar ({e})")


def _terminate(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="Nó do overlay OTT")
    parser.add_argument("name", help="nome lógico do nó (ex: O1)")
    parser.add_argument("bootstrapper", help="IP do bootstrapper")
    parser.add_argument("--port", type=int, default=CONTROL_PORT, help="porta TCP de controlo deste nó")
    parser.add_argument("--bport", type=int, default=BOOTSTRAPPER_PORT, help="porta TCP do bootstrapper")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{args.name}] %(message)s", datefmt="%H:%M:%S")
    signal.signal(signal.SIGTERM, _terminate)  # kill <pid> também fecha as ligações
    Node(args.name, args.port, (args.bootstrapper, args.bport)).run()


if __name__ == "__main__":
    main()
