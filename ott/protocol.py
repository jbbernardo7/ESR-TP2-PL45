"""Formato das mensagens de controlo: um objeto JSON por linha, sobre TCP."""

import json

BOOTSTRAPPER_PORT = 4000
CONTROL_PORT = 5000

HELLO_INTERVAL = 1.0  # segundos entre HELLOs
HELLO_TIMEOUT = 3.0   # sem HELLO durante este tempo -> vizinho perdido


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
