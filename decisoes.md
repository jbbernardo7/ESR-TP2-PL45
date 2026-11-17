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
- A cada 5 s, cada nó volta a tentar os vizinhos do config a que não está ligado. Recupera as ligações depois de uma falha temporária (ex: um link que cai e volta).
- Um nó aceita ligações de qualquer nó overlay. Os vizinhos já ativos não precisam de saber do nó novo com antecedência: aceitam a ligação e acrescentam-no à tabela de vizinhos.

**Identificação dos nós:**
- Cada nó tem um nome lógico (`S1`, `O1`, `C1`...), associado ao seu IP no `config.json`.

**Deteção de falhas:**
- Cada nó envia `HELLO` aos vizinhos a cada 1 s. Um vizinho é dado como perdido se a ligação TCP fechar ou se não chegar nenhum `HELLO` durante 3 s.

**Abandono:**
- Sem mensagem `LEAVE`: a saída de um nó é detetada pelo fecho da ligação TCP ou pelo timeout do `HELLO`.

**Bootstrapper, formato e concorrência:**
- Bootstrapper em processo separado (TCP 4000). Cada nó usa a porta 5000 para controlo (TCP) e dados (UDP).
- Mensagens de controlo em JSON.
- Concorrência com threads.

**Questões em aberto:**
- Posso ter o servidor a partilhar rotas para os nós?
- Os clientes ficam fora do `config.json`? (Assumido que sim: o cliente só conhece os fluxos e o IP do nó folha; não fala com o bootstrapper nem recebe anúncios.)

**Decisões de implementação:**
- Cada mensagem JSON termina com `\n`.
- O `HELLO` leva um `boot_id` aleatório, criado a cada arranque, para distinguir um vizinho que reiniciou (fica a ligação nova).
- Ligação duplicada (dois nós ligam-se ao mesmo tempo): fica a aberta pelo nó de nome menor.

# Etapa 2
**Estratégia:**
- Árvore pelo caminho inverso: cada nó guarda, por fluxo, apenas a Origem e os Destinos.
- Descoberta da Origem por inundação de anúncios do servidor (com nº de sequência).
- Estado explícito: ativação e desativação enviadas uma vez; limpeza também quando se perde um vizinho.
- Mensagens de controlo só entre vizinhos, pela ligação TCP já aberta.

**Tabela de rotas (uma entrada por fluxo):**
- `{Fluxo, Servidor, Origem, Custo, Hops, Alternativas, Destinos, Estado}`
- O Estado não é guardado: a rota está ativa se tiver Destinos.

**Mensagens:**
- `ANNOUNCE {server, seq, cost, hops, flows}`: servidor → todos, periódico.
- `ACTIVATE {flow}` / `DEACTIVATE {flow}`: enviados à Origem.
- `HELLO_ACK {ts}`: resposta ao `HELLO`, para medir o atraso.

**Regras:**
- `ANNOUNCE`: cada nó reenvia só a 1.ª cópia de cada `(server, seq)` aos outros vizinhos, com o custo da ligação somado. As restantes cópias ficam guardadas como candidatas.
- Candidato seguro: um vizinho só pode ser Origem ou Alternativa se o custo que anunciou for menor do que o custo que eu reenviei nessa ronda (o caminho dele não passa por mim).
- Origem estável: só muda se outro candidato for mais de 10% melhor, se deixar de ser válida, ou se não entregar o anúncio de uma ronda nova em 1 s.
- `ACTIVATE`: junta aos Destinos; se a rota estava inativa, ativa-a e reenvia à Origem. Sem rota, o pedido fica nos Destinos e sobe quando houver Origem.
- `DEACTIVATE`: retira dos Destinos; se ficarem vazios, desativa a rota e reenvia à Origem.
- Perda de um Destino = `DEACTIVATE`. Perda da Origem: passa para a melhor Alternativa e envia-lhe `ACTIVATE`.
- Troca de Origem: `ACTIVATE` à nova e `DEACTIVATE` à antiga, de seguida.
- Dados (UDP) com ID do fluxo: só aceites da Origem; uma cópia para cada Destino.

**Métricas:**
- Inicialmente: atraso (RTT/2 medido com o `HELLO`) como custo. O número de hops fica só para registo.
- Largura de banda: implementação futura.
- Custo de uma ligação calculado numa só função (`link_cost`), para facilitar a troca de métrica.

**Períodos:**
- `ANNOUNCE` a cada 5 s. Rota expira após 15 s sem anúncios (3 períodos).

**Servidores:**
- Os dois servidores têm os mesmos fluxos (ex: S1 e S2 com F1 e F2, sendo F1 ≠ F2).
- Por fluxo, cada nó escolhe o servidor de menor custo; o outro serve de Alternativa.
- Repetidos detetados por `(server, seq)`.

**Clientes:**
- Programa separado (`client.py`), fora do `config.json`. Só conhece o IP do nó folha e os fluxos.
- Liga-se ao nó folha por TCP (porta 5000) com `HELLO {client: true}` e envia `ACTIVATE` por fluxo. Recebe os dados por UDP.
- O nó folha trata-o como um Destino e não lhe envia `ANNOUNCE`.
- Nome: hostname da máquina (ou `--name`). Se o nó folha cair, tenta religar-se a cada 1 s.

**Arranque dos papéis:**
- Servidor: `ott.py S1 <bootstrapper> --server F1 F2`
- Nó intermédio: `ott.py O1 <bootstrapper>`
- Cliente: `client.py <ip_nó_folha> F1`

**Testes (antes da Etapa 4):**
- Com a rota ativa, o servidor envia um pacote UDP de teste simples (`{flow, seq}`) a cada 0,5 s; o cliente imprime o que recebe.
- Cada nó imprime a tabela de rotas sempre que muda.

# Regras
Nenhum nó pode ter topologia completa, ou seja, algoritmos como dijkstra não podem ser utilizados.

Não é permitido fazer routeping[?] (pacotes que vão acumulando a assinatura de cada nó por onde passam).

# Extras que podem ser considerados no futuro:
Melhorar flood
Nós serem adicionados (e à rota mais eficiente)
Morte sem aviso
Mortes catastróficas (com self healing). Neste caso, os nós em risco (aqueles que perdem conexão com o Servidor) podem ter conhecimento dos vizinhos dos vizinhos  de forma a criar uma nova ligação