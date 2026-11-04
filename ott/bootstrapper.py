"""Bootstrapper: responde a REGISTER com a lista de vizinhos do nó.

Não calcula rotas nem avisa outros nós. Relê o ficheiro de configuração
a cada REGISTER, para ser possível acrescentar nós sem o reiniciar.

Uso: python3 bootstrapper.py [config.json] [--port 4000]
"""

import argparse
import json
import logging
import socket
import threading

from protocol import BOOTSTRAPPER_PORT, CONTROL_PORT, make_reader, read_msg, send_msg

log = logging.getLogger("bootstrapper")


def build_reply(config_path, name):
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    node = config.get(name)
    if node is None:
        return {"type": "ERROR", "reason": f"nó '{name}' não existe no config"}

    neighbors = []
    for n in node.get("neighbors", []):
        entry = config.get(n)
        if entry is None:
            log.warning("vizinho '%s' de '%s' não existe no config; ignorado", n, name)
            continue
        neighbors.append({"name": n, "ip": entry["ip"], "port": entry.get("port", CONTROL_PORT)})
    return {"type": "NEIGHBORS", "neighbors": neighbors}


def handle(conn, addr, config_path):
    with conn:
        try:
            msg = read_msg(make_reader(conn))
        except (OSError, ValueError) as e:
            log.warning("mensagem inválida de %s: %s", addr[0], e)
            return
        if not msg or msg.get("type") != "REGISTER":
            send_msg(conn, {"type": "ERROR", "reason": "esperava REGISTER"})
            return

        name = msg.get("name")
        try:
            reply = build_reply(config_path, name)
        except (OSError, ValueError, KeyError) as e:
            log.error("erro a ler %s: %s", config_path, e)
            reply = {"type": "ERROR", "reason": "config inválido no bootstrapper"}

        send_msg(conn, reply)
        if reply["type"] == "NEIGHBORS":
            log.info("REGISTER %s (%s) -> %s", name, addr[0], [n["name"] for n in reply["neighbors"]])
        else:
            log.info("REGISTER %s (%s) -> ERROR: %s", name, addr[0], reply["reason"])


def main():
    parser = argparse.ArgumentParser(description="Bootstrapper do overlay")
    parser.add_argument("config", nargs="?", default="config.json")
    parser.add_argument("--port", type=int, default=BOOTSTRAPPER_PORT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [bootstrapper] %(message)s", datefmt="%H:%M:%S")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", args.port))
    server.listen()
    log.info("à escuta na porta TCP %d (config: %s)", args.port, args.config)

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle, args=(conn, addr, args.config), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    main()
