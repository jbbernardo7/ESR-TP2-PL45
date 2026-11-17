"""Formato das mensagens de controlo: um objeto JSON por linha, sobre TCP."""

import json

BOOTSTRAPPER_PORT = 4000
CONTROL_PORT = 5000   # TCP para controlo e, com o mesmo número, UDP para dados

HELLO_INTERVAL = 1.0  # segundos entre HELLOs
HELLO_TIMEOUT = 3.0   # sem HELLO durante este tempo -> vizinho perdido

CONNECT_TRIES = 3     # tentativas de ligação a um vizinho
CONNECT_RETRY = 1.0   # segundos entre tentativas
RECONNECT_INTERVAL = 5.0  # segundos entre novas tentativas aos vizinhos do config que não estão ligados

ANNOUNCE_INTERVAL = 5.0  # segundos entre anúncios de um servidor
ROUTE_TIMEOUT = 15.0     # sem anúncios de um servidor durante este tempo -> rotas expiram
ORIGIN_GRACE = 1.0       # tempo que a Origem tem para entregar o anúncio de uma ronda nova
SWITCH_MARGIN = 0.10     # só troca de Origem se a nova for mais de 10% melhor

DATA_INTERVAL = 0.5   # segundos entre pacotes de teste do servidor


def send_msg(sock, msg):
    sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))


def make_reader(sock):
    return sock.makefile("r", encoding="utf-8")


def read_msg(reader):
    """Lê a próxima mensagem. Devolve None se a ligação foi fechada."""
    line = reader.readline()
    if not line:
        return None
    return json.loads(line)
