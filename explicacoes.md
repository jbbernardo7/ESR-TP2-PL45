# Explicações

## Underlay vs Overlay
- **Underlay:** a rede do CORE (routers, PCs, links). O OSPF leva pacotes de um IP a outro.
- **Overlay:** os PCs que correm `ott.py`, definidos no `config.json`. Routers não correm `ott.py`.
- O OSPF não replica nem escolhe nós overlay. Por isso são precisas rotas e métricas próprias.

## Etapa 1
- **Bootstrapper:** só devolve a lista de vizinhos do `config.json`.
- **Nó novo:** liga-se ele próprio aos vizinhos, que o aceitam.
- **HELLO:** o TCP não deteta um link caído ou um nó morto sem aviso. O HELLO deteta em 3 s e mede o atraso.

## Tabela de rotas (uma entrada por fluxo)
`{Fluxo, Servidor, Origem, Custo, Alternativas, Destinos, Estado}`
- **Origem:** o vizinho de quem recebo o fluxo (o mais barato até ao servidor). Só uma por fluxo.
- **Destinos:** os vizinhos que me pediram o fluxo.
- **Estado:** ativa (os dados passam) ou inativa (sei o caminho, ninguém pediu).

## Mensagens
1. **Anúncio** (servidor → todos): cada nó soma o custo da ligação por onde chegou e reenvia. Preenche Origem e Custo.
2. **Ativação** (cliente → servidor, pela Origem): para no primeiro nó que já recebe o fluxo. Preenche Destinos.
3. **Dados** (servidor → clientes, pelos Destinos).

## Árvore e replicação
- As rotas ativas formam uma árvore: raiz = servidor, folhas = clientes.
- Replica-se onde um nó tem mais de um Destino.
- Cada ligação leva no máximo uma cópia de cada fluxo.
- Ninguém conhece a árvore inteira, nem a lista de clientes.

## Perdas
- **Perdi a Origem:** passo para a Alternativa e envio-lhe ativação.
- **Perdi um Destino:** retiro-o; se ficar sem Destinos, envio desativação à Origem.
- Em ambos os casos, aviso os vizinhos se o meu custo mudou.

## Alternativas à inundação
- **Vetor de distâncias:** cada nó só envia a sua tabela aos vizinhos.
- **Atualizações por mudança:** só envia quando o custo muda.
- **Agregação:** um anúncio por servidor com todos os fluxos.

## Métricas
- **Atraso:** RTT do HELLO / 2, com média suavizada.
- **Largura de banda:** pares de pacotes (tamanho / intervalo entre chegadas).
- **Custo:** `soma dos atrasos + tamanho_frame / mínimo das larguras de banda`.
