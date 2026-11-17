"""Nó do overlay: obtém os vizinhos do bootstrapper, liga-se a eles, mede o atraso
de cada ligação com HELLOs, constrói as rotas a partir dos anúncios dos servidores
e reencaminha os dados dos fluxos ativos. Também aceita clientes (client.py),
que são tratados como Destinos e não recebem anúncios.

Uso: python3 ott.py <nome> <ip_bootstrapper> [--server F1 F2] [--port 5000] [--bport 4000]
"""

import argparse
import json
import logging
import signal
import socket
import sys
import threading
import time
import uuid

from protocol import (ANNOUNCE_INTERVAL, BOOTSTRAPPER_PORT, CONNECT_RETRY, CONNECT_TRIES, CONTROL_PORT,
                      DATA_INTERVAL, HELLO_INTERVAL, HELLO_TIMEOUT, RECONNECT_INTERVAL,
                      make_reader, read_msg, send_msg)
from routing import RouteTable

log = logging.getLogger("ott")


class Neighbor:
    """Uma ligação TCP ativa a um vizinho."""

    def __init__(self, name, sock, reader, initiator, boot_id, udp_addr, is_client):
        self.name = name
        self.sock = sock
        self.reader = reader
        self.initiator = initiator  # nome do nó que abriu a ligação
        self.boot_id = boot_id      # muda sempre que o vizinho reinicia
        self.udp_addr = udp_addr    # para onde enviar (e de onde aceitar) dados
        self.is_client = is_client  # cliente: só recebe dados, não recebe anúncios
        self.delay = None           # atraso suavizado da ligação, em segundos
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


def link_cost(nb):
    """Custo de uma ligação overlay: atraso em ms. None enquanto não houver medida.
    É o único sítio onde a métrica é calculada."""
    return None if nb.delay is None else max(nb.delay * 1000, 0.001)


class Node:
    def __init__(self, name, port, bootstrapper, own=()):
        self.name = name
        self.port = port
        self.bootstrapper = bootstrapper
        self.boot_id = uuid.uuid4().hex[:8]
        self.neighbors = {}  # nome -> Neighbor (inclui clientes)
        self.connecting = set()  # vizinhos a que este nó está a tentar ligar-se
        self.routes = RouteTable(name, own)
        self.last_table = []
        self.lock = threading.RLock()  # protege os vizinhos e as rotas
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def hello(self):
        return {"type": "HELLO", "from": self.name, "boot_id": self.boot_id,
                "port": self.port, "ts": time.monotonic()}

    # ---------- arranque ----------

    def run(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen()
        self.udp.bind(("0.0.0.0", self.port))
        log.info("à escuta na porta %d (TCP controlo, UDP dados)", self.port)

        config_neighbors = self.register()
        loops = [(self.accept_loop, (listener,)), (self.data_loop, ()), (self.reconnect_loop, (config_neighbors,))]
        if self.routes.own:
            loops += [(self.announce_loop, ()), (self.send_loop, ())]
        loops += [(self.connect, (info, CONNECT_TRIES)) for info in config_neighbors]
        for target, args in loops:
            threading.Thread(target=target, args=args, daemon=True).start()

        try:
            self.heartbeat_loop()
        except KeyboardInterrupt:
            log.info("a terminar")
        finally:
            listener.close()
            self.udp.close()
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

    def connect(self, info, tries):
        """Tenta ligar a um vizinho. Se a ligação abrir, fica a tratá-la até cair."""
        name = info["name"]
        with self.lock:
            if name in self.neighbors or name in self.connecting:
                return
            self.connecting.add(name)
        try:
            for attempt in range(tries):
                if attempt:
                    time.sleep(CONNECT_RETRY)
                with self.lock:
                    if name in self.neighbors:
                        return  # o vizinho ligou-se entretanto
                try:
                    sock = socket.create_connection((info["ip"], info["port"]), timeout=2)
                except OSError:
                    continue
                self.handle_connection(sock, True)
                return
            if tries > 1:
                log.info("%s (%s) indisponível após %d tentativas; nova tentativa a cada %.0f s",
                         name, info["ip"], tries, RECONNECT_INTERVAL)
        finally:
            with self.lock:
                self.connecting.discard(name)

    def reconnect_loop(self, config_neighbors):
        """Volta a tentar os vizinhos do config a que não está ligado: recupera
        ligações perdidas por uma falha temporária (ex: um link que cai e volta)."""
        while True:
            time.sleep(RECONNECT_INTERVAL)
            with self.lock:
                missing = [i for i in config_neighbors
                           if i["name"] not in self.neighbors and i["name"] not in self.connecting]
            for info in missing:
                threading.Thread(target=self.connect, args=(info, 1), daemon=True).start()

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
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # para o atraso medido ser real
            sock.settimeout(HELLO_TIMEOUT)
            send_msg(sock, self.hello())
            first = read_msg(reader)
            sock.settimeout(None)
            peer, udp_addr = first["from"], (sock.getpeername()[0], int(first["port"]))
            if first["type"] != "HELLO":
                raise ValueError("esperava HELLO")
        except (OSError, ValueError, KeyError, TypeError):
            sock.close()
            return

        initiator = self.name if outgoing else peer
        nb = Neighbor(peer, sock, reader, initiator, first.get("boot_id"), udp_addr, bool(first.get("client")))
        if not self.add_neighbor(nb):
            return

        reason = "ligação TCP fechada"
        try:
            self.on_message(nb, first)
            while True:
                msg = read_msg(reader)
                if msg is None:
                    break
                self.on_message(nb, msg)
        except (OSError, ValueError, KeyError, TypeError) as e:
            reason = f"erro na ligação ({e!r})"
        self.remove_neighbor(nb, reason)

    def add_neighbor(self, new):
        """Junta o vizinho à tabela. Se já existir uma ligação a esse vizinho:
        - boot_id diferente: o vizinho reiniciou, fica a ligação nova;
        - boot_id igual: os dois nós ligaram-se ao mesmo tempo; fica a ligação
          aberta pelo nó de nome menor (os dois lados escolhem a mesma).
        Devolve True se a ligação nova ficou na tabela."""
        with self.lock:
            old = self.neighbors.get(new.name)
            restarted = old is not None and old.boot_id != new.boot_id
            if old is None or restarted:
                keep, drop = new, old
            elif new.initiator == min(self.name, new.name):
                keep, drop = new, old
            else:
                keep, drop = old, new
            self.neighbors[new.name] = keep
            if keep is new and old is not None:
                new.delay = old.delay
            if restarted:
                self.routes.on_neighbor_lost(new.name)  # o vizinho perdeu o estado que tinha
                self.update()
            names = sorted(self.neighbors)
        if drop is not None:
            drop.close()
        if old is None:
            log.info("novo %s %s -> vizinhos: %s", "cliente" if new.is_client else "vizinho", new.name, names)
        elif restarted:
            log.info("vizinho %s reiniciou; ligação substituída", new.name)
        return keep is new

    def remove_neighbor(self, nb, reason):
        with self.lock:
            removed = self.neighbors.get(nb.name) is nb
            if removed:
                del self.neighbors[nb.name]
                self.routes.on_neighbor_lost(nb.name)
                self.update()
            names = sorted(self.neighbors)
        nb.close()
        if removed:
            log.info("vizinho %s perdido (%s) -> vizinhos: %s", nb.name, reason, names)

    # ---------- mensagens de controlo ----------

    def on_message(self, nb, msg):
        kind = msg["type"]
        if kind == "HELLO":
            nb.last_seen = time.monotonic()
            nb.send({"type": "HELLO_ACK", "ts": msg["ts"]})
        elif kind == "HELLO_ACK":
            delay = (time.monotonic() - msg["ts"]) / 2
            if nb.delay is None:
                log.info("atraso até %s: %.2f ms", nb.name, delay * 1000)
            nb.delay = delay if nb.delay is None else 0.875 * nb.delay + 0.125 * delay
        elif kind in ("ANNOUNCE", "ACTIVATE", "DEACTIVATE"):
            with self.lock:
                if self.neighbors.get(nb.name) is not nb:
                    return
                if kind == "ANNOUNCE":
                    forward = self.routes.on_announce(msg, nb.name, link_cost(nb), time.monotonic())
                    if forward:
                        self.broadcast(forward, skip=nb.name)
                elif kind == "ACTIVATE":
                    self.routes.on_activate(msg["flow"], nb.name)
                else:
                    self.routes.on_deactivate(msg["flow"], nb.name)
                self.update()
        else:
            log.warning("mensagem desconhecida de %s: %s", nb.name, msg)

    def send_to(self, name, msg):
        """Envia uma mensagem de controlo. Chamar com o lock, para as mensagens nunca
        trocarem de ordem. Um erro é ignorado: a perda do vizinho é tratada por quem lê."""
        nb = self.neighbors.get(name)
        if nb:
            try:
                nb.send(msg)
            except OSError:
                pass

    def broadcast(self, msg, skip=None):
        """Envia a todos os vizinhos overlay. Os clientes não recebem anúncios."""
        for name, nb in list(self.neighbors.items()):
            if name != skip and not nb.is_client:
                self.send_to(name, msg)

    def update(self):
        """Chamar com o lock depois de qualquer evento: volta a escolher as Origens,
        envia os ACTIVATE/DEACTIVATE necessários e imprime a tabela se mudou."""
        costs = {name: link_cost(nb) for name, nb in self.neighbors.items()}
        for name, msg in self.routes.refresh(costs, time.monotonic()):
            self.send_to(name, msg)
        key, text = self.routes.describe(costs)
        if key != self.last_table:
            self.last_table = key
            log.info("rotas:\n%s", text or "(sem rotas)")

    # ---------- ciclos periódicos ----------

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
            with self.lock:
                self.update()  # rotas expiradas e prazo da Origem

    def announce_loop(self):
        """Servidor: anuncia os seus fluxos a todos os vizinhos. O seq começa na hora
        atual, para um servidor que reinicia não ser ignorado por ter um seq antigo."""
        seq = int(time.time())
        while True:
            time.sleep(ANNOUNCE_INTERVAL)
            seq += 1
            with self.lock:
                self.broadcast({"type": "ANNOUNCE", "server": self.name, "seq": seq,
                                "cost": 0, "hops": 0, "flows": sorted(self.routes.own)})

    # ---------- dados (UDP) ----------

    def send_loop(self):
        """Servidor: envia um pacote de teste por fluxo a cada Destino."""
        seq = 0
        while True:
            time.sleep(DATA_INTERVAL)
            seq += 1
            with self.lock:
                out = [(flow, self.neighbors[d].udp_addr) for flow in self.routes.own
                       for d in self.routes.dests.get(flow, ()) if d in self.neighbors]
            for flow, addr in out:
                self.send_data(json.dumps({"flow": flow, "seq": seq}).encode("utf-8"), addr)

    def data_loop(self):
        """Aceita pacotes de um fluxo só se vierem da Origem, e envia uma cópia a cada Destino."""
        while True:
            try:
                data, addr = self.udp.recvfrom(65535)
            except OSError:
                return
            try:
                flow = json.loads(data)["flow"]
            except (ValueError, KeyError, TypeError):
                continue
            with self.lock:
                origin = self.neighbors.get(self.routes.origin.get(flow, (None, None))[1])
                if origin is None or origin.udp_addr != addr:
                    continue
                dests = [self.neighbors[d].udp_addr for d in self.routes.dests.get(flow, ())
                         if d in self.neighbors]
            for dest in dests:
                self.send_data(data, dest)

    def send_data(self, data, addr):
        try:
            self.udp.sendto(data, addr)
        except OSError:
            pass


def _terminate(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="Nó do overlay OTT")
    parser.add_argument("name", help="nome lógico do nó (ex: O1)")
    parser.add_argument("bootstrapper", help="IP do bootstrapper")
    parser.add_argument("--server", nargs="+", default=[], metavar="FLUXO", help="fluxos que este nó serve")
    parser.add_argument("--port", type=int, default=CONTROL_PORT, help="porta deste nó (TCP controlo e UDP dados)")
    parser.add_argument("--bport", type=int, default=BOOTSTRAPPER_PORT, help="porta TCP do bootstrapper")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{args.name}] %(message)s", datefmt="%H:%M:%S")
    signal.signal(signal.SIGTERM, _terminate)  # kill <pid> também fecha as ligações
    Node(args.name, args.port, (args.bootstrapper, args.bport), args.server).run()


if __name__ == "__main__":
    main()
