"""Cliente: liga-se a um nó folha do overlay, pede fluxos e mostra os pacotes recebidos.

Só conhece o IP do nó folha e os nomes dos fluxos: não fala com o bootstrapper,
não está no ficheiro de configuração e não recebe anúncios.

Uso: python3 client.py <ip_nó_folha> F1 [F2 ...] [--port 5000] [--name C1]
"""

import argparse
import json
import logging
import signal
import socket
import threading
import time
import uuid

from protocol import CONNECT_RETRY, CONTROL_PORT, HELLO_INTERVAL, HELLO_TIMEOUT, make_reader, read_msg, send_msg

log = logging.getLogger("client")


def receive_loop(udp):
    while True:
        data, _ = udp.recvfrom(65535)
        try:
            packet = json.loads(data)
            log.info("recebido %s seq=%s", packet["flow"], packet["seq"])
        except (ValueError, KeyError, TypeError):
            continue


def session(leaf, name, flows, udp_port):
    """Uma ligação ao nó folha: pede os fluxos e mantém a ligação com HELLOs.
    Termina quando o nó folha fecha a ligação ou deixa de enviar HELLO."""
    sock = socket.create_connection(leaf, timeout=2)
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    boot_id = uuid.uuid4().hex[:8]  # novo a cada ligação: o nó folha substitui uma ligação antiga
    last_seen = time.monotonic()
    closed = threading.Event()

    def reader():
        nonlocal last_seen
        r = make_reader(sock)
        try:
            while read_msg(r) is not None:
                last_seen = time.monotonic()
        except (OSError, ValueError):
            pass
        closed.set()

    def hello():
        return {"type": "HELLO", "from": name, "boot_id": boot_id, "port": udp_port,
                "ts": time.monotonic(), "client": True}

    threading.Thread(target=reader, daemon=True).start()
    try:
        send_msg(sock, hello())
        for flow in flows:
            send_msg(sock, {"type": "ACTIVATE", "flow": flow})
        log.info("ligado ao nó folha %s:%d; pedidos: %s", leaf[0], leaf[1], flows)
        while not closed.wait(HELLO_INTERVAL) and time.monotonic() - last_seen <= HELLO_TIMEOUT:
            send_msg(sock, hello())
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


def _terminate(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="Cliente do serviço OTT")
    parser.add_argument("leaf", help="IP do nó folha do overlay")
    parser.add_argument("flows", nargs="+", metavar="FLUXO", help="fluxos a receber")
    parser.add_argument("--port", type=int, default=CONTROL_PORT, help="porta TCP do nó folha")
    parser.add_argument("--name", default=socket.gethostname(), help="nome do cliente (por omissão, o hostname)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{args.name}] %(message)s", datefmt="%H:%M:%S")
    signal.signal(signal.SIGTERM, _terminate)

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("0.0.0.0", 0))  # porta livre qualquer; vai no HELLO para o nó folha
    threading.Thread(target=receive_loop, args=(udp,), daemon=True).start()

    try:
        while True:
            try:
                session((args.leaf, args.port), args.name, args.flows, udp.getsockname()[1])
                log.info("ligação ao nó folha perdida; nova tentativa em %.0f s", CONNECT_RETRY)
            except OSError as e:
                log.info("nó folha indisponível (%s); nova tentativa em %.0f s", e, CONNECT_RETRY)
            time.sleep(CONNECT_RETRY)
    except KeyboardInterrupt:
        log.info("a terminar")


if __name__ == "__main__":
    main()
