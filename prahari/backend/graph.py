"""
PRAHARI — Identity Trust Graph.

Builds a graph of identities connected through shared attributes (device, IP,
beneficiary) from real rows in the DB, then detects synthetic-identity rings and
mule clusters: connected components where >= 3 identities share a device or a
payee. Returns a node/edge payload for visualisation plus a verdict.
"""
import networkx as nx
import db


def _build():
    g = nx.Graph()
    links = db.all_links()
    # attr_value -> users sharing it
    shared = {}
    for l in links:
        g.add_node(l["user_id"], kind="identity")
        shared.setdefault((l["attr_type"], l["attr_value"]), []).append(l["user_id"])
    # connect identities that share an attribute; remember the bridging attr
    for (atype, aval), users in shared.items():
        users = sorted(set(users))
        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                g.add_edge(users[i], users[j], via=atype, value=aval)
    return g, shared


def scan(user_id: str):
    g, shared = _build()
    if user_id not in g:
        return {"nodes": [{"id": user_id, "label": user_id, "kind": "self", "suspect": False}],
                "edges": [], "ring": False,
                "verdict": "Identity is isolated — no shared-attribute links found."}

    comp = nx.node_connected_subgraph = g.subgraph(nx.node_connected_component(g, user_id)).copy()
    members = sorted(comp.nodes())

    # ring signal: >=3 identities sharing the same device or beneficiary
    ring, ring_attr = False, None
    for (atype, aval), users in shared.items():
        members_sharing = [u for u in set(users) if u in members]
        if atype in ("device", "beneficiary") and len(members_sharing) >= 3:
            ring, ring_attr = True, (atype, aval)
            break

    names = db.identities_in(members)
    nodes = []
    for m in members:
        nodes.append({
            "id": m,
            "label": names.get(m, {}).get("name", m),
            "kind": "self" if m == user_id else "identity",
            "suspect": ring and m != user_id,
        })
    edges = [{"source": u, "target": v, "via": d.get("via")}
             for u, v, d in comp.edges(data=True)]

    if ring:
        atype, aval = ring_attr
        verdict = (f"Synthetic-identity ring flagged: {sum(1 for n in nodes if n['suspect'])+1} "
                   f"identities share {atype} '{aval}'. Linked accounts auto-escalated "
                   f"for onboarding + recovery.")
    else:
        verdict = "No collusion detected — identity graph is consistent (no shared-device rings or mule clustering)."

    return {"nodes": nodes, "edges": edges, "ring": ring, "verdict": verdict}
