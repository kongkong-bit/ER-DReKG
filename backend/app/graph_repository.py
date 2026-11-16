import csv
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from neo4j import GraphDatabase

from app.core.config import settings

CONTEXT_NODE_ID = "DISEASE_CONTEXT:GSE42568_ERPOS_TUMOR_VS_NORMAL"


@lru_cache(maxsize=8)
def load_csv_graph(graph_dir: str | None = None) -> tuple[dict[str, dict], list[dict]]:
    if graph_dir is not None:
        root = Path(graph_dir).resolve()
    else:
        root = Path(settings.graph_data_dir)
        if not root.is_absolute():
            root = (Path(__file__).resolve().parents[2] / root).resolve()
    nodes = {}
    with (root / "subgraph_nodes.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nodes[row["id"]] = {"id": row["id"], "type": row["type"], "label": row["label"], "properties": json.loads(row["properties_json"] or "{}")}
    edges = []
    with (root / "subgraph_edges.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            props = json.loads(row["properties_json"] or "{}")
            edge_id = hashlib.sha256(f"{row['from']}|{row['label']}|{row['to']}|{row['source_release']}".encode()).hexdigest()
            edges.append({"id": edge_id, "source": row["from"], "target": row["to"], "relation": row["relation"], "label": row["label"], "source_release": row["source_release"], "properties": props, "evidence_ids": [edge_id]})
    extension = root.parent / "platform_phase_b_pathways" if graph_dir is None else None
    if extension and extension.exists():
        for filename in ["pathway_nodes.csv", "gene_nodes.csv"]:
            path = extension / filename
            if not path.exists():
                continue
            with path.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    node_id = row["id"]
                    node = {"id": node_id, "type": row["type"], "label": row["label"], "properties": json.loads(row["properties_json"] or "{}")}
                    if node_id in nodes:
                        nodes[node_id]["properties"].update(node["properties"])
                        provenance = nodes[node_id]["properties"].setdefault("provenance_sources", [])
                        if isinstance(provenance, list) and "S1 pathway enrichment" not in provenance:
                            provenance.append("S1 pathway enrichment")
                    else:
                        nodes[node_id] = node
        path = extension / "pathway_edges.csv"
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    props = json.loads(row["properties_json"] or "{}")
                    edge_id = hashlib.sha256(f"{row['from']}|{row['label']}|{row['to']}|{row['source_release']}".encode()).hexdigest()
                    edges.append({"id": edge_id, "source": row["from"], "target": row["to"], "relation": row["relation"], "label": row["label"], "source_release": row["source_release"], "properties": props, "evidence_ids": [edge_id]})
    return nodes, edges


def graph_counts(project_slug: str, graph_build_id: str | None = None, graph_dir: str | None = None) -> dict:
    if settings.graph_source != "neo4j" and project_slug != "erpos-gse42568" and graph_dir is None:
        return {"node_count": 0, "edge_count": 0, "nodes_by_type": {}, "source": settings.graph_source}
    if settings.graph_source == "neo4j":
        driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        try:
            with driver.session(database=settings.neo4j_database) as session:
                node_rows = session.run(
                    "MATCH (ctx:DiseaseContext {project_slug: $slug}) "
                    "WITH ctx WHERE $build_id IS NULL OR EXISTS { MATCH (ctx)-[seed]-() WHERE $build_id IN coalesce(seed.graph_build_ids, []) } "
                    "MATCH p=(ctx)-[*0..2]-(n) "
                    "WHERE $build_id IS NULL OR all(r IN relationships(p) WHERE $build_id IN coalesce(r.graph_build_ids, [])) "
                    "RETURN labels(n) AS labels, count(DISTINCT n) AS count",
                    slug=project_slug, build_id=graph_build_id,
                ).data()
                edge_record = session.run(
                    "MATCH (ctx:DiseaseContext {project_slug: $slug}) "
                    "WITH ctx WHERE $build_id IS NULL OR EXISTS { MATCH (ctx)-[seed]-() WHERE $build_id IN coalesce(seed.graph_build_ids, []) } "
                    "MATCH p=(ctx)-[*0..2]-(n) "
                    "WHERE $build_id IS NULL OR all(r IN relationships(p) WHERE $build_id IN coalesce(r.graph_build_ids, [])) "
                    "WITH collect(DISTINCT n) AS nodes "
                    "UNWIND nodes AS n "
                    "MATCH (n)-[r]-(m) WHERE m IN nodes AND ($build_id IS NULL OR $build_id IN coalesce(r.graph_build_ids, [])) "
                    "RETURN count(DISTINCT r) AS count",
                    slug=project_slug, build_id=graph_build_id,
                ).single()
            by_type = {row["labels"][0] if row["labels"] else "Unknown": row["count"] for row in node_rows}
            return {"node_count": sum(by_type.values()), "edge_count": edge_record["count"] if edge_record else 0, "nodes_by_type": by_type, "source": settings.graph_source}
        finally:
            driver.close()
    nodes, edges = load_csv_graph(graph_dir)
    by_type = {}
    for node in nodes.values():
        by_type[node["type"]] = by_type.get(node["type"], 0) + 1
    return {"node_count": len(nodes), "edge_count": len(edges), "nodes_by_type": by_type, "source": settings.graph_source}


def search_nodes(project_slug: str, query_text: str, limit: int = 20, graph_build_id: str | None = None, graph_dir: str | None = None) -> list[dict]:
    query_text = query_text.strip().casefold()
    if len(query_text) < 2:
        return []
    if settings.graph_source == "neo4j":
        driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        query = """
        MATCH (ctx:DiseaseContext {project_slug: $project_slug})
        WITH ctx WHERE $build_id IS NULL OR EXISTS { MATCH (ctx)-[seed]-() WHERE $build_id IN coalesce(seed.graph_build_ids, []) }
        MATCH p=(ctx)-[*0..2]-(n)
        WHERE $build_id IS NULL OR all(r IN relationships(p) WHERE $build_id IN coalesce(r.graph_build_ids, []))
        WITH DISTINCT n
        WHERE toLower(coalesce(n.label, n.id, '')) CONTAINS $query_text
           OR toLower(coalesce(n.id, '')) CONTAINS $query_text
        RETURN n.id AS id,
               coalesce(head(labels(n)), 'Unknown') AS type,
               coalesce(n.label, n.id, '') AS label
        ORDER BY label LIMIT $limit
        """
        try:
            with driver.session(database=settings.neo4j_database) as session:
                return session.run(query, project_slug=project_slug, query_text=query_text, limit=limit, build_id=graph_build_id).data()
        finally:
            driver.close()
    if project_slug != "erpos-gse42568" and graph_dir is None:
        return []
    nodes, _ = load_csv_graph(graph_dir)
    hits = [n for n in nodes.values() if query_text in n["id"].casefold() or query_text in n["label"].casefold()]
    hits.sort(key=lambda n: (n["label"].casefold(), n["id"]))
    return [{"id": n["id"], "type": n["type"], "label": n["label"]} for n in hits[:limit]]


def get_subgraph(project_id: str, project_slug: str, node_id: str | None, max_depth: int, limit: int, cursor: int = 0, graph_build_id: str | None = None, analysis_run_id: str | None = None, graph_dir: str | None = None) -> dict:
    if settings.graph_source != "neo4j" and project_slug != "erpos-gse42568" and graph_dir is None:
        return {"project_id": project_id, "analysis_run_id": None, "nodes": [], "edges": [], "truncated": False, "next_cursor": None}
    if settings.graph_source == "neo4j":
        return _neo4j_subgraph(project_id, project_slug, node_id, max_depth, limit, cursor, graph_build_id, analysis_run_id)
    nodes, edges = load_csv_graph(graph_dir)
    return _csv_subgraph(project_id, node_id, max_depth, limit, cursor, nodes, edges, analysis_run_id)


def _csv_subgraph(project_id: str, node_id: str | None, max_depth: int, limit: int, cursor: int, nodes: dict[str, dict], edges: list[dict], analysis_run_id: str | None = None) -> dict:
    if node_id and node_id not in nodes:
        return {"project_id": project_id, "analysis_run_id": None, "nodes": [], "edges": [], "truncated": False, "next_cursor": None}
    selected = {node_id} if node_id else set(nodes)
    if node_id:
        frontier = {node_id}
        for _ in range(max_depth):
            next_frontier = set()
            for edge in edges:
                if edge["source"] in frontier:
                    next_frontier.add(edge["target"])
                if edge["target"] in frontier:
                    next_frontier.add(edge["source"])
            next_frontier -= selected
            selected |= next_frontier
            frontier = next_frontier
    selected_edges = [e for e in edges if e["source"] in selected and e["target"] in selected]
    ordered_ids = sorted(selected)
    page_ids = set(ordered_ids[cursor:cursor + limit])
    page_edges = [e for e in selected_edges if e["source"] in page_ids and e["target"] in page_ids]
    truncated = cursor + limit < len(ordered_ids)
    return {"project_id": project_id, "analysis_run_id": analysis_run_id or "PHASEB_OPTIMUSKG32_20261113", "nodes": [nodes[k] for k in ordered_ids[cursor:cursor + limit]], "edges": [{k: e[k] for k in ["id", "source", "target", "relation", "evidence_ids"]} for e in page_edges], "truncated": truncated, "next_cursor": str(cursor + limit) if truncated else None}


def _neo4j_subgraph(project_id: str, project_slug: str, node_id: str | None, max_depth: int, limit: int, cursor: int, graph_build_id: str | None = None, analysis_run_id: str | None = None) -> dict:
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    query = f"""
    MATCH (ctx:DiseaseContext {{project_slug: $project_slug}})
    WITH ctx WHERE $build_id IS NULL OR EXISTS {{ MATCH (ctx)-[seed]-() WHERE $build_id IN coalesce(seed.graph_build_ids, []) }}
    MATCH p=(ctx)-[*0..{max_depth}]-(m)
    WHERE ($build_id IS NULL OR all(r IN relationships(p) WHERE $build_id IN coalesce(r.graph_build_ids, [])))
      AND ($node_id IS NULL OR any(v IN nodes(p) WHERE v.id = $node_id))
    WITH p LIMIT $limit
    UNWIND nodes(p) AS v
    WITH collect(DISTINCT v) AS ns
    UNWIND ns AS v
    WITH v ORDER BY v.id SKIP $cursor LIMIT $limit
    RETURN collect({{node: v, type: coalesce(head(labels(v)), 'Unknown')}}) AS nodes
    """
    try:
        with driver.session(database=settings.neo4j_database) as session:
            record = session.run(query, project_slug=project_slug, node_id=node_id, limit=limit, cursor=cursor, build_id=graph_build_id).single()
            raw = list(record["nodes"]) if record else []
            result_nodes = [{"id": item["node"].get("id"), "type": item["type"], "label": item["node"].get("label", item["node"].get("id", "")), "properties": dict(item["node"])} for item in raw]
            ids = {n["id"] for n in result_nodes}
            relationships = session.run("MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids AND ($build_id IS NULL OR $build_id IN coalesce(r.graph_build_ids, [])) RETURN a.id AS source,b.id AS target,type(r) AS relation,coalesce(r.evidence_ids,[]) AS evidence_ids,coalesce(r.id,a.id+'|'+type(r)+'|'+b.id) AS id", ids=list(ids), build_id=graph_build_id).data()
            edge_rows = [{"id": e["id"], "source": e["source"], "target": e["target"], "relation": e["relation"], "evidence_ids": e["evidence_ids"]} for e in relationships]
            return {"project_id": project_id, "analysis_run_id": analysis_run_id, "nodes": result_nodes, "edges": edge_rows, "truncated": len(raw) == limit, "next_cursor": str(cursor + limit) if len(raw) == limit else None}
    finally:
        driver.close()


def mechanism_for_pert_id(pert_id: str, project_slug: str, graph_build_id: str | None = None, graph_dir: str | None = None) -> list[dict]:
    if settings.graph_source == "neo4j":
        return _neo4j_mechanism_for_pert_id(pert_id, project_slug, graph_build_id)
    if project_slug != "erpos-gse42568" and graph_dir is None:
        return []
    return _csv_mechanism_for_pert_id(pert_id, project_slug, graph_dir)


def _json_relationship_assertion(relationship: dict) -> dict:
    raw = relationship.get("source_assertion_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"raw": raw}


def _neo4j_mechanism_for_pert_id(pert_id: str, project_slug: str, graph_build_id: str | None = None) -> list[dict]:
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    public_query = """
    MATCH (c:Candidate {project_slug: $project_slug, pert_id: $pert_id})
          -[candidate_ref:REFERENCES_DRUG]->(d:Drug)-[target:TARGETS]->(g:Gene)
    MATCH (p)-[contains:CONTAINS_GENE]->(g)
    WHERE (p:Pathway OR p:GeneSet)
      AND ($build_id IS NULL OR ($build_id IN coalesce(candidate_ref.graph_build_ids, []) AND $build_id IN coalesce(target.graph_build_ids, []) AND $build_id IN coalesce(contains.graph_build_ids, [])))
    RETURN c.id AS candidate_id, d.id AS drug_id, g.id AS target_gene_id,
           p.id AS pathway_id, p.label AS pathway_label,
           target.evidence_ids AS target_evidence_ids,
           target.source_assertion_json AS target_assertion,
           contains.evidence_ids AS pathway_evidence_ids,
           contains.source_assertion_json AS pathway_assertion
    """
    enriched_query = """
    MATCH (c:Candidate {project_slug: $project_slug, pert_id: $pert_id})
          -[candidate_ref:REFERENCES_DRUG]->(d:Drug)-[target:TARGETS]->(g:Gene)
    MATCH (p)-[pathway_gene:HAS_ENRICHED_GENE]->(g)
    MATCH (ctx:DiseaseContext {project_slug: $project_slug})-[context_pathway:HAS_ENRICHED_PATHWAY]->(p)
    WHERE $build_id IS NULL OR ($build_id IN coalesce(candidate_ref.graph_build_ids, []) AND $build_id IN coalesce(target.graph_build_ids, []) AND $build_id IN coalesce(pathway_gene.graph_build_ids, []) AND $build_id IN coalesce(context_pathway.graph_build_ids, []))
    RETURN c.id AS candidate_id, d.id AS drug_id, g.id AS target_gene_id,
           p.id AS pathway_id, p.label AS pathway_label, ctx.id AS disease_context_id,
           candidate_ref.evidence_ids AS candidate_evidence_ids,
           candidate_ref.source_assertion_json AS candidate_assertion,
           target.evidence_ids AS target_evidence_ids,
           target.source_assertion_json AS target_assertion,
           pathway_gene.evidence_ids AS pathway_gene_evidence_ids,
           pathway_gene.source_assertion_json AS pathway_gene_assertion,
           context_pathway.evidence_ids AS context_evidence_ids,
           context_pathway.source_assertion_json AS context_assertion
    """
    routes = []
    try:
        with driver.session(database=settings.neo4j_database) as session:
            for row in session.run(public_query, project_slug=project_slug, pert_id=pert_id, build_id=graph_build_id):
                routes.append({
                    "route_type": "public_kg_pathway",
                    "drug_id": row["drug_id"],
                    "target_gene_id": row["target_gene_id"],
                    "pathway_id": row["pathway_id"],
                    "pathway_label": row["pathway_label"],
                    "evidence_ids": (row["target_evidence_ids"] or []) + (row["pathway_evidence_ids"] or []),
                    "source_assertions": [
                        _json_relationship_assertion({"source_assertion_json": row["target_assertion"]}),
                        _json_relationship_assertion({"source_assertion_json": row["pathway_assertion"]}),
                    ],
                })
            for row in session.run(enriched_query, project_slug=project_slug, pert_id=pert_id, build_id=graph_build_id):
                routes.append({
                    "route_type": "s1_enrichment_overlap",
                    "candidate_id": row["candidate_id"],
                    "drug_id": row["drug_id"],
                    "target_gene_id": row["target_gene_id"],
                    "pathway_id": row["pathway_id"],
                    "pathway_label": row["pathway_label"],
                    "disease_context_id": row["disease_context_id"],
                    "analysis_assertions": _json_relationship_assertion({"source_assertion_json": row["pathway_gene_assertion"]}).get("analysis_assertions", []),
                    "context_assertions": _json_relationship_assertion({"source_assertion_json": row["context_assertion"]}).get("analysis_assertions", []),
                    "evidence_ids": (
                        (row["candidate_evidence_ids"] or [])
                        + (row["target_evidence_ids"] or [])
                        + (row["pathway_gene_evidence_ids"] or [])
                        + (row["context_evidence_ids"] or [])
                    ),
                    "source_assertions": [
                        _json_relationship_assertion({"source_assertion_json": row["candidate_assertion"]}),
                        _json_relationship_assertion({"source_assertion_json": row["target_assertion"]}),
                        _json_relationship_assertion({"source_assertion_json": row["pathway_gene_assertion"]}),
                        _json_relationship_assertion({"source_assertion_json": row["context_assertion"]}),
                    ],
                })
        return routes
    finally:
        driver.close()


def _csv_mechanism_for_pert_id(pert_id: str, project_slug: str, graph_dir: str | None = None) -> list[dict]:
    nodes, edges = load_csv_graph(graph_dir)
    candidate_id = next((k for k, v in nodes.items() if v["type"] == "Candidate" and v["properties"].get("pert_id") == pert_id), None)
    if not candidate_id:
        return []
    reference_edges = [e for e in edges if e["source"] == candidate_id and e["relation"] == "REFERENCES_DRUG"]
    drug_ids = {e["target"] for e in reference_edges}
    target_edges = [e for e in edges if e["source"] in drug_ids and e["label"] == "DRG-GEN"]
    routes = []
    for target in target_edges:
        for pathway in edges:
            if pathway["label"] == "PWY-GEN" and pathway["target"] == target["target"]:
                routes.append({"route_type": "public_kg_pathway", "drug_id": target["source"], "target_gene_id": target["target"], "pathway_id": pathway["source"], "evidence_ids": target["evidence_ids"] + pathway["evidence_ids"], "source_assertions": [target["properties"], pathway["properties"]]})

    # Join the drug-side target edges to this project's independently sourced S1 enrichment.
    # This is an evidence intersection, not a causal or efficacy claim.
    enriched_gene_edges = [e for e in edges if e["label"] == "S1-ENRICHED-GENE"]
    enriched_context_ids = {node_id for node_id, node in nodes.items() if node["type"] == "DiseaseContext" and node["properties"].get("project_slug") == project_slug}
    enriched_context_edges = [e for e in edges if e["label"] == "S1-ENRICHED-PATHWAY" and e["source"] in enriched_context_ids]
    gene_to_pathway: dict[str, list[dict]] = {}
    for edge in enriched_gene_edges:
        gene_to_pathway.setdefault(edge["target"], []).append(edge)
    context_by_pathway = {edge["target"]: edge for edge in enriched_context_edges}
    reference_by_drug = {edge["target"]: edge for edge in reference_edges}
    for target in target_edges:
        candidate_reference = reference_by_drug.get(target["source"])
        if candidate_reference is None:
            continue
        for pathway_gene in gene_to_pathway.get(target["target"], []):
            context_edge = context_by_pathway.get(pathway_gene["source"])
            if context_edge is None:
                continue
            pathway_node = nodes.get(pathway_gene["source"], {})
            routes.append({
                "route_type": "s1_enrichment_overlap",
                "candidate_id": candidate_id,
                "drug_id": target["source"],
                "target_gene_id": target["target"],
                "pathway_id": pathway_gene["source"],
                "pathway_label": pathway_node.get("label", pathway_gene["source"]),
                "disease_context_id": context_edge["source"],
                "analysis_assertions": pathway_gene["properties"].get("analysis_assertions", []),
                "context_assertions": context_edge["properties"].get("analysis_assertions", []),
                "evidence_ids": candidate_reference["evidence_ids"] + target["evidence_ids"] + pathway_gene["evidence_ids"] + context_edge["evidence_ids"],
                "source_assertions": [candidate_reference["properties"], target["properties"], pathway_gene["properties"], context_edge["properties"]],
            })
    return routes


def get_evidence(evidence_id: str, graph_build_id: str | None = None, graph_dir: str | None = None) -> dict | None:
    if settings.graph_source == "neo4j":
        driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        try:
            with driver.session(database=settings.neo4j_database) as session:
                row = session.run(
                    "MATCH ()-[r]->() WHERE $evidence_id IN coalesce(r.evidence_ids, []) "
                    "AND ($build_id IS NULL OR $build_id IN coalesce(r.graph_build_ids, [])) "
                    "RETURN r.source_release AS source_release, r.source_assertion_json AS assertion LIMIT 1",
                    evidence_id=evidence_id, build_id=graph_build_id,
                ).single()
            if not row:
                return None
            try:
                assertion = json.loads(row["assertion"] or "{}")
            except json.JSONDecodeError:
                assertion = {"raw": row["assertion"]}
            return {"evidence_id": evidence_id, "source_release": row["source_release"], "source_assertion": assertion, "source_url": assertion.get("source_urls")}
        finally:
            driver.close()
    _, edges = load_csv_graph(graph_dir)
    edge = next((e for e in edges if e["id"] == evidence_id), None)
    if edge is None:
        return None
    return {"evidence_id": edge["id"], "source_release": edge.get("source_release", "OptimusKG 3.2"), "source_assertion": edge["properties"], "source_url": edge["properties"].get("source_urls")}
