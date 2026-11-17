# ott — Etapas 1 e 2 (overlay, rotas e ativação)

| Ficheiro | Função |
|---|---|
| `bootstrapper.py` | Responde a `REGISTER` com os vizinhos do nó (lidos do ficheiro de configuração) |
| `ott.py` | Nó do overlay: ligações aos vizinhos, `HELLO`, anúncios, ativação e reenvio de dados |
| `routing.py` | Tabela de rotas: escolha da Origem de cada fluxo e pedidos de ativação |
| `client.py` | Cliente: liga-se a um nó folha, pede fluxos e mostra os pacotes recebidos |
| `protocol.py` | Formato das mensagens (JSON, uma por linha) e constantes |
| `config.json` | Config ativo: nós do overlay, IP de cada um e vizinhos (sem clientes) |
| `config_cenario1.json`, `config_cenario2.json` | Config de cada cenário (fora do git) |

## Correr no CORE (Cenário 2)

Em cada nó, na pasta `ott/`:

```sh
# máquina do S1 (dois processos)
python3 bootstrapper.py config.json
python3 ott.py S1 10.0.0.20 --server F1 F2

# restantes nós overlay, por qualquer ordem (10.0.0.20 = IP do bootstrapper)
python3 ott.py S2 10.0.0.20 --server F1 F2
python3 ott.py O1 10.0.0.20
python3 ott.py O2 10.0.0.20
python3 ott.py O3 10.0.0.20

# clientes: só precisam do IP do nó folha
python3 client.py 10.0.12.20 F1      # C1, ligado ao O2
python3 client.py 10.0.5.20 F1       # C2, ligado ao O3
```

Portas: bootstrapper TCP 4000; cada nó overlay usa a 5000 para controlo (TCP) e para dados (UDP). O cliente recebe os dados numa porta UDP livre, que indica ao nó folha no `HELLO`.

Cada nó imprime a tabela de rotas sempre que ela muda. O cliente imprime cada pacote que recebe:

```
[O3] rotas:
F1: Servidor=S2 Origem=S2 Custo=15.20ms Hops=1 Alt={'O2/S1': 31.4} Destinos=['C2'] ativa
[C2] recebido F1 seq=38
```

Para a escolha das rotas pelo atraso ser visível, os links do CORE precisam de atraso configurado (por exemplo, 5 ms nos links de acesso e 10 ms entre routers).

## Mensagens

```
{"type": "REGISTER", "name": "O1"}                                        nó -> bootstrapper
{"type": "NEIGHBORS", "neighbors": [{"name": "S1", "ip": "...", "port": 5000}, ...]}
{"type": "ERROR", "reason": "..."}                                        bootstrapper -> nó

{"type": "HELLO", "from": "O1", "boot_id": "3f2a91c0", "port": 5000, "ts": 1234.5}   a cada 1 s
{"type": "HELLO", ..., "client": true}                                    HELLO de um cliente
{"type": "HELLO_ACK", "ts": 1234.5}                                       resposta; serve para medir o atraso
{"type": "ANNOUNCE", "server": "S1", "seq": 17, "cost": 15.2, "hops": 2, "flows": ["F1", "F2"]}
{"type": "ACTIVATE", "flow": "F1"}                                        para a Origem (ou do cliente para o nó folha)
{"type": "DEACTIVATE", "flow": "F1"}                                      para a Origem

{"flow": "F1", "seq": 38}                                                 dados de teste, por UDP
```

## Testar sem o CORE

No ficheiro de configuração, cada nó pode ter um campo `"port"`. Com todos os IPs a `127.0.0.1` e portas diferentes:

```sh
python3 bootstrapper.py config_local.json
python3 ott.py S1 127.0.0.1 --port 5001 --server F1 F2
python3 ott.py O1 127.0.0.1 --port 5003
python3 client.py 127.0.0.1 F1 --port 5003 --name C1
```

Em local os atrasos são quase zero, por isso a escolha entre caminhos é arbitrária. Serve para testar o protocolo, não a métrica.
