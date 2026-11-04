# ott — Etapa 1 (construção do overlay)

| Ficheiro | Função |
|---|---|
| `bootstrapper.py` | Responde a `REGISTER` com os vizinhos do nó (lidos do `config.json`) |
| `ott.py` | Nó do overlay: regista-se, liga-se aos vizinhos e troca `HELLO` |
| `protocol.py` | Formato das mensagens (JSON, uma por linha) e constantes |
| `config.json` | Nós do overlay, IP de cada um e vizinhos (Cenário 1) |

## Correr no CORE (Cenário 1)

Ajustar os IPs do `config.json` à topologia. Depois, em cada nó:

```sh
# máquina do S1 (dois processos)
python3 bootstrapper.py config.json
python3 ott.py S1 <ip_do_S1>

# restantes máquinas, por qualquer ordem
python3 ott.py O1 <ip_do_S1>
python3 ott.py C1 <ip_do_S1>
python3 ott.py C2 <ip_do_S1>
```

Portas: bootstrapper TCP 4000, controlo TCP 5000.

## Mensagens

```
{"type": "REGISTER", "name": "O1"}                                     nó -> bootstrapper
{"type": "NEIGHBORS", "neighbors": [{"name": "S1", "ip": "...", "port": 5000}, ...]}
{"type": "ERROR", "reason": "..."}                                     bootstrapper -> nó
{"type": "HELLO", "from": "O1", "boot_id": "3f2a91c0"}                 entre vizinhos, a cada 1 s
```

## Testar sem o CORE

No `config.json`, cada nó pode ter um campo `"port"`. Com todos os IPs a `127.0.0.1` e portas diferentes:

```sh
python3 bootstrapper.py config_local.json
python3 ott.py O1 127.0.0.1 --port 5002
```
