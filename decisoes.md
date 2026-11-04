# Etapa 0
**Protocolos:**
- TCP para plano de controlo
- UDP para plano de dados (pacotes de media/streaming)

**Linguagem Programação:**
- Python

# Etapa 1
**Estratégia de construção do overlay:**
- Estratégia 2 (bootstrapper), com ficheiro de configuração estático (`config.json`).
- O `config.json` define todos os nós overlay e os vizinhos de cada um. Um nó que não esteja no config fica fora do âmbito.

**Bootstrapper:**
- Responde a `REGISTER` com a lista de vizinhos do nó.
- Relê o `config.json` a cada `REGISTER`, para ser possível acrescentar nós ao overlay sem o reiniciar.

**Ligações entre vizinhos:**
- O nó que chega por último inicia a ligação. Se o `connect()` a um vizinho falhar, tenta mais 2 vezes (3 no total), com 1 s de intervalo; se todas falharem, espera que seja o vizinho a ligar-se quando arrancar.
- As tentativas a cada vizinho correm em paralelo, para um vizinho offline não atrasar os outros.
- Um nó aceita ligações de qualquer nó overlay. Os vizinhos já ativos não precisam de saber do nó novo com antecedência: aceitam a ligação e acrescentam-no à tabela de vizinhos.

**Identificação dos nós:**
- Cada nó tem um nome lógico (`S1`, `O1`, `C1`...), associado ao seu IP no `config.json`.

**Deteção de falhas:**
- Cada nó envia `HELLO` aos vizinhos a cada 1 s. Um vizinho é dado como perdido se a ligação TCP fechar ou se não chegar nenhum `HELLO` durante 3 s.

**Questões em aberto:**
- Bootstrapper no mesmo processo do S1 (uma porta TCP) ou em processo separado (duas portas TCP [preferência atual])?
- Formato das mensagens de controlo: JSON (preferência atual) ou outro?
- Modelo de concorrência: threads (preferência atual)?
- Posso ter o servidor a partilhar rotas para os nós?

**Decisões de implementação:**
- Cada mensagem JSON termina com `\n`.
- O `HELLO` leva um `boot_id` aleatório, criado a cada arranque, para distinguir um vizinho que reiniciou (fica a ligação nova).
- Ligação duplicada (dois nós ligam-se ao mesmo tempo): fica a aberta pelo nó de nome menor.

# Etapa 2
**Métricas (ainda não 100% definido):**
- Largura de Banda + Atraso (peso a definir)

# Regras
Nenhum nó pode ter topologia completa, ou seja, algoritmos como dijkstra não podem ser utilizados.

Não é permitido fazer routeping[?] (pacotes que vão acumulando a assinatura de cada nó por onde passam).

# Extras que podem ser considerados no futuro:
Melhorar flood
Nós serem adicionados (e à rota mais eficiente)
Morte sem aviso
Mortes catastróficas (com self healing). Neste caso, os nós em risco (aqueles que perdem conexão com o Servidor) podem ter conhecimento dos vizinhos dos vizinhos  de forma a criar uma nova ligação