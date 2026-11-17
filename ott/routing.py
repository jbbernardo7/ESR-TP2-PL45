"""Tabela de rotas de um nó: escolha da Origem de cada fluxo e pedidos de ativação.

Só lógica: sem sockets, threads ou locks. É sempre chamada com o lock do nó.
`link_costs` é um dicionário vizinho -> custo da ligação (None se ainda não medido).
"""

from protocol import ORIGIN_GRACE, ROUTE_TIMEOUT, SWITCH_MARGIN


class RouteTable:
    def __init__(self, name, own=()):
        self.name = name
        self.own = set(own)  # fluxos que este nó serve (servidor)
        self.rounds = {}     # servidor -> {seq, cost, flows, started}; cost = custo que reenviei
        self.cands = {}      # servidor -> {vizinho -> {seq, cost, hops}}; cost = custo anunciado
        self.origin = {}     # fluxo -> (servidor, vizinho)
        self.dests = {}      # fluxo -> vizinhos que pediram o fluxo
        self.requested = {}  # fluxo -> vizinho a quem está enviado o ACTIVATE

    # ---------- eventos ----------

    def on_announce(self, msg, neighbor, link_cost, now):
        """Guarda o anúncio. Devolve a mensagem a reenviar se o seq for novo, senão None."""
        server, seq = msg["server"], msg["seq"]
        rnd = self.rounds.get(server)
        if server == self.name or link_cost is None or (rnd and seq < rnd["seq"]):
            return None
        self.cands.setdefault(server, {})[neighbor] = {"seq": seq, "cost": msg["cost"], "hops": msg["hops"]}
        if rnd and seq == rnd["seq"]:
            return None
        cost = msg["cost"] + link_cost
        self.rounds[server] = {"seq": seq, "cost": cost, "flows": msg["flows"], "started": now}
        return {"type": "ANNOUNCE", "server": server, "seq": seq, "cost": cost,
                "hops": msg["hops"] + 1, "flows": msg["flows"]}

    def on_activate(self, flow, neighbor):
        self.dests.setdefault(flow, set()).add(neighbor)

    def on_deactivate(self, flow, neighbor):
        self.dests.get(flow, set()).discard(neighbor)

    def on_neighbor_lost(self, neighbor):
        for dests in self.dests.values():
            dests.discard(neighbor)
        for cands in self.cands.values():
            cands.pop(neighbor, None)
        for flow in [f for f, n in self.requested.items() if n == neighbor]:
            del self.requested[flow]

    # ---------- escolha da Origem ----------

    def _flows(self):
        """Fluxos que não são deste nó: anunciados ou pedidos por vizinhos e clientes."""
        announced = {f for rnd in self.rounds.values() for f in rnd["flows"]}
        return sorted((announced | set(self.dests)) - self.own)

    def _candidates(self, flow, link_costs):
        """Candidatos válidos a Origem: (servidor, vizinho) -> custo total.

        Um vizinho só é seguro se o custo que anunciou for menor do que o custo
        que reenviei nessa ronda: assim, o caminho dele não pode passar por mim."""
        out = {}
        for server, rnd in self.rounds.items():
            if flow not in rnd["flows"]:
                continue
            for neighbor, cand in self.cands[server].items():
                if (link_costs.get(neighbor) is not None
                        and neighbor not in self.dests.get(flow, ())
                        and cand["seq"] == rnd["seq"] and cand["cost"] < rnd["cost"]):
                    out[server, neighbor] = cand["cost"] + link_costs[neighbor]
        return out

    def _in_grace(self, flow, origin, link_costs, now):
        """A Origem ainda não entregou o anúncio da ronda nova, mas está dentro do prazo."""
        server, neighbor = origin
        rnd = self.rounds.get(server)
        cand = self.cands.get(server, {}).get(neighbor)
        return bool(rnd and cand and link_costs.get(neighbor) is not None
                    and neighbor not in self.dests.get(flow, ())
                    and cand["seq"] < rnd["seq"] and now - rnd["started"] < ORIGIN_GRACE)

    def _choose(self, flow, link_costs, now):
        valid = self._candidates(flow, link_costs)
        best = min(valid, key=valid.get, default=None)
        current = self.origin.get(flow)
        if current in valid:
            if valid[best] >= valid[current] * (1 - SWITCH_MARGIN):
                return current
        elif current and self._in_grace(flow, current, link_costs, now):
            return current
        return best

    def refresh(self, link_costs, now):
        """Expira servidores calados, escolhe a Origem de cada fluxo e devolve a lista
        de (vizinho, mensagem) com os ACTIVATE/DEACTIVATE a enviar."""
        for server in [s for s, rnd in self.rounds.items() if now - rnd["started"] > ROUTE_TIMEOUT]:
            del self.rounds[server]
            del self.cands[server]

        out = []
        for flow in self._flows():
            origin = self._choose(flow, link_costs, now)
            if origin:
                self.origin[flow] = origin
            else:
                self.origin.pop(flow, None)

            target = origin[1] if origin and self.dests.get(flow) else None
            old = self.requested.get(flow)
            if target != old:
                if old:
                    out.append((old, {"type": "DEACTIVATE", "flow": flow}))
                if target:
                    out.append((target, {"type": "ACTIVATE", "flow": flow}))
                self.requested[flow] = target
        return out

    # ---------- registo ----------

    def describe(self, link_costs):
        """Devolve (chave, texto) da tabela. A chave só muda quando muda a estrutura
        das rotas (não com as oscilações do custo), para decidir quando imprimir."""
        key, lines = [], []
        for flow in sorted(self.own):
            dests = sorted(self.dests.get(flow, ()))
            state = "ativa" if dests else "inativa"
            key.append((flow, None, tuple(dests), state))
            lines.append(f"{flow}: raiz Destinos={dests} {state}")

        for flow in self._flows():
            dests = sorted(self.dests.get(flow, ()))
            origin = self.origin.get(flow)
            if not origin:
                if dests:
                    key.append((flow, None, tuple(dests), "sem rota"))
                    lines.append(f"{flow}: sem rota (pedido pendente) Destinos={dests}")
                continue
            server, neighbor = origin
            valid = self._candidates(flow, link_costs)
            cost = f"{valid[origin]:.2f}ms" if origin in valid else "?"
            alts = {f"{n}/{s}": round(c, 2) for (s, n), c in sorted(valid.items()) if (s, n) != origin}
            state = "ativa" if dests else "inativa"
            key.append((flow, origin, tuple(dests), state))
            lines.append(f"{flow}: Servidor={server} Origem={neighbor} Custo={cost} "
                         f"Hops={self.cands[server][neighbor]['hops'] + 1} Alt={alts} Destinos={dests} {state}")
        return key, "\n".join(lines)
