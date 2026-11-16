import json
import csv
import hashlib

from app import graph_repository


class FakeSession:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        if "HAS_ENRICHED_GENE" in query:
            return iter([{
                "candidate_id": "CANDIDATE:BRD-TEST",
                "drug_id": "CHEMBL1",
                "target_gene_id": "ENSG000001",
                "pathway_id": "GO:0000001",
                "pathway_label": "test pathway",
                "disease_context_id": "DISEASE_CONTEXT:TEST",
                "candidate_evidence_ids": ["e-candidate"],
                "candidate_assertion": json.dumps({"mapping_method": "exact InChIKey"}),
                "target_evidence_ids": ["e-target"],
                "target_assertion": json.dumps({"sources": {"direct": ["DB"]}}),
                "pathway_gene_evidence_ids": ["e-gene"],
                "pathway_gene_assertion": json.dumps({"analysis_assertions": [{"gene_symbol": "TEST"}]}),
                "context_evidence_ids": ["e-context"],
                "context_assertion": json.dumps({"analysis_assertions": [{"analysis": "GO_UP"}]}),
            }])
        if "CONTAINS_GENE" in query:
            return iter([{
                "candidate_id": "CANDIDATE:BRD-TEST",
                "drug_id": "CHEMBL1",
                "target_gene_id": "ENSG000001",
                "pathway_id": "REACTOME:TEST",
                "pathway_label": "test Reactome pathway",
                "target_evidence_ids": ["e-target"],
                "target_assertion": json.dumps({"target": "direct"}),
                "pathway_evidence_ids": ["e-pathway"],
                "pathway_assertion": json.dumps({"source": "public KG"}),
            }])
        if "source_release AS source_release" in query:
            return FakeSingle({"source_release": "GSE test release", "assertion": json.dumps({"analysis": "GO_UP"})})
        raise AssertionError(f"Unexpected query: {query}")


class FakeSingle(dict):
    def single(self):
        return self


class FakeDriver:
    def __init__(self):
        self.session_instance = FakeSession()
        self.closed = False

    def session(self, **_):
        return self.session_instance

    def close(self):
        self.closed = True


def test_neo4j_mechanisms_return_both_route_types_and_source_evidence(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(graph_repository.settings, "graph_source", "neo4j")
    monkeypatch.setattr(graph_repository.GraphDatabase, "driver", lambda *args, **kwargs: driver)

    routes = graph_repository.mechanism_for_pert_id("BRD-TEST", "erpos-gse42568", "GRAPH_BUILD:test")

    assert {route["route_type"] for route in routes} == {"public_kg_pathway", "s1_enrichment_overlap"}
    enriched = next(route for route in routes if route["route_type"] == "s1_enrichment_overlap")
    assert enriched["evidence_ids"] == ["e-candidate", "e-target", "e-gene", "e-context"]
    assert enriched["analysis_assertions"] == [{"gene_symbol": "TEST"}]
    assert len(enriched["source_assertions"]) == 4
    assert all(params == {"project_slug": "erpos-gse42568", "pert_id": "BRD-TEST", "build_id": "GRAPH_BUILD:test"} for _, params in driver.session_instance.queries)
    assert all("graph_build_ids" in query for query, _ in driver.session_instance.queries)
    assert driver.closed


def test_neo4j_evidence_lookup_returns_source_release_and_assertion(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(graph_repository.settings, "graph_source", "neo4j")
    monkeypatch.setattr(graph_repository.GraphDatabase, "driver", lambda *args, **kwargs: driver)

    evidence = graph_repository.get_evidence("e-context")

    assert evidence == {
        "evidence_id": "e-context",
        "source_release": "GSE test release",
        "source_assertion": {"analysis": "GO_UP"},
        "source_url": None,
    }
    assert driver.session_instance.queries[0][1] == {"evidence_id": "e-context", "build_id": None}
    assert driver.closed


def test_neo4j_evidence_lookup_is_scoped_to_graph_build(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(graph_repository.settings, "graph_source", "neo4j")
    monkeypatch.setattr(graph_repository.GraphDatabase, "driver", lambda *args, **kwargs: driver)

    graph_repository.get_evidence("e-context", "GRAPH_BUILD:test")

    query, params = driver.session_instance.queries[0]
    assert "graph_build_ids" in query
    assert params == {"evidence_id": "e-context", "build_id": "GRAPH_BUILD:test"}


def test_graph_queries_require_context_relationship_in_selected_build(monkeypatch):
    class Result:
        def data(self):
            return []

        def single(self):
            return {"count": 0, "nodes": []}

    class QuerySession(FakeSession):
        def run(self, query, **params):
            self.queries.append((query, params))
            return Result()

    driver = FakeDriver()
    driver.session_instance = QuerySession()
    monkeypatch.setattr(graph_repository.settings, "graph_source", "neo4j")
    monkeypatch.setattr(graph_repository.GraphDatabase, "driver", lambda *args, **kwargs: driver)

    graph_repository.graph_counts("erpos-gse42568", "GRAPH_BUILD:test")
    graph_repository.search_nodes("erpos-gse42568", "TP53", graph_build_id="GRAPH_BUILD:test")
    graph_repository.get_subgraph("project-test", "erpos-gse42568", None, 2, 100, graph_build_id="GRAPH_BUILD:test")

    scoped_queries = [query for query, _ in driver.session_instance.queries if "MATCH (ctx:DiseaseContext" in query]
    assert len(scoped_queries) == 4  # node counts, edge count, search, subgraph
    assert all("EXISTS { MATCH (ctx)-[seed]-()" in query for query in scoped_queries)
    assert all("seed.graph_build_ids" in query for query in scoped_queries)


def test_csv_project_bundle_supports_summary_search_subgraph_mechanism_and_evidence(tmp_path, monkeypatch):
    from pathlib import Path

    bundle = Path(tmp_path)
    nodes = [
        {"id": "CTX:test", "type": "DiseaseContext", "label": "测试疾病上下文", "properties_json": json.dumps({"project_id": "project-test", "project_slug": "test-disease", "analysis_run_id": "RUN:KG:test", "s1_analysis_run_id": "RUN:S1:test"})},
        {"id": "CANDIDATE:project-test:BRD-TEST", "type": "Candidate", "label": "Drug A", "properties_json": json.dumps({"project_id": "project-test", "project_slug": "test-disease", "pert_id": "BRD-TEST", "analysis_run_id": "RUN:S2:test"})},
        {"id": "CHEMBL1", "type": "Drug", "label": "Drug A", "properties_json": json.dumps({"inchi_key": "TEST-INCHI"})},
        {"id": "ENSG000001", "type": "Gene", "label": "TP53", "properties_json": json.dumps({"symbol": "TP53"})},
        {"id": "GO:0000001", "type": "Pathway", "label": "Test pathway", "properties_json": json.dumps({"name": "Test pathway"})},
        {"id": "S2_CONDITION:project-test:1", "type": "S2Condition", "label": "Drug A · 1 uM · 24 h", "properties_json": json.dumps({"project_id": "project-test", "analysis_run_id": "RUN:S2:test", "dose": "1 uM", "time": "24 h", "WTCS_median": -0.4})},
    ]
    edges = [
        {"from": "CTX:test", "label": "PROJECT-HAS_CANDIDATE", "to": "CANDIDATE:project-test:BRD-TEST", "relation": "HAS_CANDIDATE", "source_release": "S2 test", "undirected": "false", "properties_json": json.dumps({"analysis_run_id": "RUN:S2:test"})},
        {"from": "CANDIDATE:project-test:BRD-TEST", "label": "PROJECT-REFERENCES_DRUG", "to": "CHEMBL1", "relation": "REFERENCES_DRUG", "source_release": "LINCS test", "undirected": "false", "properties_json": json.dumps({"analysis_run_id": "RUN:S2:test", "mapping_method": "exact InChIKey"})},
        {"from": "CHEMBL1", "label": "DRG-GEN", "to": "ENSG000001", "relation": "TARGETS", "source_release": "Public KG test", "undirected": "false", "properties_json": json.dumps({"relation_assertions": [{"source": "test"}]})},
        {"from": "GO:0000001", "label": "PWY-GEN", "to": "ENSG000001", "relation": "CONTAINS_GENE", "source_release": "Public KG test", "undirected": "false", "properties_json": json.dumps({"source": "test"})},
        {"from": "CTX:test", "label": "S1-ENRICHED-PATHWAY", "to": "GO:0000001", "relation": "HAS_ENRICHED_PATHWAY", "source_release": "S1 test", "undirected": "false", "properties_json": json.dumps({"analysis_assertions": [{"analysis_run_id": "RUN:ENRICH:test", "adjusted_p": 0.01}]})},
        {"from": "GO:0000001", "label": "S1-ENRICHED-GENE", "to": "ENSG000001", "relation": "HAS_ENRICHED_GENE", "source_release": "S1 test", "undirected": "false", "properties_json": json.dumps({"analysis_assertions": [{"analysis_run_id": "RUN:ENRICH:test", "gene_symbol": "TP53"}]})},
        {"from": "CANDIDATE:project-test:BRD-TEST", "label": "PROJECT-HAS_S2_CONDITION", "to": "S2_CONDITION:project-test:1", "relation": "HAS_S2_CONDITION", "source_release": "S2 test", "undirected": "false", "properties_json": json.dumps({"analysis_run_id": "RUN:S2:test"})},
    ]
    for filename, rows, fields in [
        ("subgraph_nodes.csv", nodes, ["id", "type", "label", "properties_json"]),
        ("subgraph_edges.csv", edges, ["from", "label", "to", "relation", "source_release", "undirected", "properties_json"]),
    ]:
        with (bundle / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    monkeypatch.setattr(graph_repository.settings, "graph_source", "csv")
    graph_dir = str(bundle)

    counts = graph_repository.graph_counts("test-disease", "GRAPH_BUILD:test", graph_dir)
    search = graph_repository.search_nodes("test-disease", "TP53", graph_dir=graph_dir)
    subgraph = graph_repository.get_subgraph("project-test", "test-disease", None, 2, 100, graph_build_id="GRAPH_BUILD:test", analysis_run_id="RUN:KG:test", graph_dir=graph_dir)
    routes = graph_repository.mechanism_for_pert_id("BRD-TEST", "test-disease", "GRAPH_BUILD:test", graph_dir)
    target_edge_id = hashlib.sha256("CHEMBL1|DRG-GEN|ENSG000001|Public KG test".encode()).hexdigest()
    evidence = graph_repository.get_evidence(target_edge_id, "GRAPH_BUILD:test", graph_dir)

    assert counts["node_count"] == 6 and counts["edge_count"] == 7
    assert search == [{"id": "ENSG000001", "type": "Gene", "label": "TP53"}]
    assert subgraph["analysis_run_id"] == "RUN:KG:test" and {node["id"] for node in subgraph["nodes"]} == {node["id"] for node in nodes}
    assert {route["route_type"] for route in routes} == {"public_kg_pathway", "s1_enrichment_overlap"}
    assert evidence["source_release"] == "Public KG test" and evidence["source_assertion"]["relation_assertions"][0]["source"] == "test"
