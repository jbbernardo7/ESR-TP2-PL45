# Explicações

## Underlay vs Overlay
- **Underlay:** a rede do CORE (routers, PCs, links). O OSPF leva pacotes de um IP a outro.
- **Overlay:** os PCs que correm `ott.py` (servidores e nós intermédios), definidos no `config.json`. Routers não correm `ott.py`.
- **Clientes:** correm `client.py`, ficam fora do overlay e do `config.json`.
- O OSPF não replica nem escolhe nós overlay. Por isso são precisas rotas e métricas próprias.

### Uma ligação overlay não é um link do underlay
- Uma ligação overlay (ex: A–B) é uma ligação TCP entre dois IPs. O caminho dos pacotes é escolhido pelo OSPF.
- **Perdas a 100% num link do underlay não quebram a ligação overlay** se houver outro caminho: o OSPF deixa de receber HELLOs nesse link e desvia o tráfego. Para o overlay, o vizinho continua lá.
- Para quebrar só uma ligação overlay, bloqueia-se o tráfego entre os dois IPs (`iptables` no nó). Exemplo para a ligação O1–O2, num terminal do O2 (10.0.10.20 é o IP do O1):

```sh
# cortar a ligação O1–O2
iptables -A INPUT  -s 10.0.10.20 -j DROP
iptables -A OUTPUT -d 10.0.10.20 -j DROP

# repor
iptables -D INPUT  -s 10.0.10.20 -j DROP
iptables -D OUTPUT -d 10.0.10.20 -j DROP
```

### O OSPF não muda de caminho quando o atraso aumenta (ponto para o relatório)
- O OSPF escolhe caminhos pelo custo das interfaces, que é estático. Não mede o atraso.
- Se um link do underlay passar a ter um atraso elevado, o OSPF continua a usá-lo.
- O overlay mede o atraso de cada ligação com o HELLO. Se uma ligação overlay ficar lenta, o nó pode trocar de Origem e receber o fluxo por outro nó overlay, cujo caminho no underlay evita o link lento.
- Conclusão: o overlay pode encontrar um caminho melhor do que o do underlay, porque usa uma métrica medida e não um custo fixo.

## Programas
| Ficheiro | Papel |
|---|---|
| `bootstrapper.py` | Devolve a lista de vizinhos de cada nó, lida do `config.json` |
| `ott.py` | Nó overlay: servidor (`--server F1 F2`) ou nó intermédio |
| `routing.py` | Tabela de rotas: escolha da Origem e pedidos de ativação |
| `client.py` | Cliente: liga-se a um nó folha e pede fluxos |
| `protocol.py` | Formato das mensagens e constantes (portas, períodos) |

## Etapa 1: construção do overlay
- **Bootstrapper:** só devolve a lista de vizinhos do `config.json`. Não calcula rotas.
- **Arranque de um nó:** regista-se no bootstrapper e tenta ligar-se a cada vizinho (3 tentativas, 1 s de intervalo).
- **Nó que chega depois:** é ele que se liga; os vizinhos aceitam a ligação.
- **HELLO:** o TCP não deteta um link caído ou um nó morto sem aviso. O HELLO (a cada 1 s) deteta em 3 s e mede o atraso.
- **Recuperação:** a cada 5 s, cada nó volta a tentar os vizinhos do config a que não está ligado (ex: depois de um link cair e voltar).

## Tabela de rotas (uma entrada por fluxo)
`{Fluxo, Servidor, Origem, Custo, Hops, Alternativas, Destinos, Estado}`
- **Origem:** o vizinho de quem recebo o fluxo (o mais barato até ao servidor). Só uma por fluxo.
- **Alternativas:** outros vizinhos que chegam a um servidor com o fluxo.
- **Destinos:** os vizinhos e clientes que me pediram o fluxo.
- **Estado:** não é guardado. A rota está ativa se tiver Destinos.
- **Hops:** só para registo.

## Mensagens
| Mensagem | Sentido | Para que serve |
|---|---|---|
| `HELLO` / `HELLO_ACK` | Entre vizinhos, a cada 1 s | Deteta falhas e mede o atraso |
| `ANNOUNCE` | Servidor → todos, a cada 5 s | Preenche Origem, Custo e Alternativas |
| `ACTIVATE` | Cliente → nó folha → … pela Origem | Preenche Destinos; para no 1.º nó que já recebe o fluxo |
| `DEACTIVATE` | Para a Origem | Retira dos Destinos |
| Dados (UDP) | Servidor → … pelos Destinos | Pacote de teste `{flow, seq}` a cada 0,5 s |

## Anúncio
1. O servidor envia `ANNOUNCE {server, seq, cost: 0, hops: 0, flows}` aos vizinhos.
2. Cada nó soma o atraso da ligação por onde o anúncio chegou.
3. Só reenvia a 1.ª cópia de cada `(server, seq)`; as outras ficam guardadas como candidatas.
4. Se um servidor não anunciar durante 15 s, as suas rotas expiram.

## Escolha da Origem
- **Candidato seguro:** um vizinho só conta se o custo que anunciou for menor do que o meu. Assim, o caminho dele não passa por mim.
- **Melhor candidato:** custo anunciado + atraso da minha ligação a ele, entre todos os servidores com o fluxo.
- **Estabilidade:** só troco de Origem se outra for mais de 10% melhor, se a atual deixar de ser válida, ou se não entregar o anúncio de uma ronda nova em 1 s.
- **Troca:** `ACTIVATE` à nova e `DEACTIVATE` à antiga.

## Clientes
- Só conhecem o IP do nó folha e os nomes dos fluxos: `client.py <ip_nó_folha> F1`.
- Ligam-se por TCP com `HELLO {client: true}` e enviam `ACTIVATE` por fluxo. Recebem os dados por UDP.
- O nó folha trata o cliente como um Destino e não lhe envia anúncios.
- Se o nó folha cair, o cliente tenta religar-se a cada 1 s.

## Árvore e replicação
- As rotas ativas formam uma árvore: raiz = servidor, folhas = clientes.
- Replica-se onde um nó tem mais de um Destino.
- Cada ligação leva no máximo uma cópia de cada fluxo.
- Ninguém conhece a árvore inteira, nem a lista de clientes.
- Um nó só aceita dados de um fluxo vindos da sua Origem.

## Perdas
- **Perdi a Origem:** passo para a melhor Alternativa e envio-lhe `ACTIVATE`.
- **Perdi um Destino:** retiro-o; se ficar sem Destinos, envio `DEACTIVATE` à Origem.
- **Pedido sem rota:** fica nos Destinos e sobe assim que houver Origem.
- **Servidor caiu:** as rotas passam para o outro servidor (Alternativa) ou expiram em 15 s.
- Os custos novos só chegam aos vizinhos no anúncio seguinte (até 5 s).

## Métricas
- **Implementado:** atraso = RTT do HELLO / 2, com média suavizada (`0.875 × antigo + 0.125 × novo`). Calculado só em `link_cost`.
- **Futuro:** largura de banda, por exemplo com pares de pacotes (tamanho / intervalo entre chegadas).
- **No CORE:** é preciso configurar atrasos nos links; com atraso 0, a escolha entre caminhos é ruído.

## Melhorias possíveis (não implementadas)
- **Vetor de distâncias:** cada nó só envia a sua tabela aos vizinhos.
- **Atualizações por mudança:** enviar logo quando o custo muda, sem esperar pelo anúncio.
- **Mudança de Origem sem cortes:** ativar a nova e só desativar a antiga quando chegarem dados pela nova.
