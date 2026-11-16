import csv
import json

from kg.scripts.import_phase_b_to_neo4j import to_neo4j_properties
from kg.scripts.import_phase_b_to_neo4j import prepare_biocypher_import_rows


def test_nested_json_properties_are_encoded_for_neo4j():
    properties = to_neo4j_properties({
        "symbol": "TP53",
        "score_vector": [1, 2.5],
        "collections": ["GO_UP", "HALLMARK"],
        "analysis_assertions": [{"analysis": "GO_UP", "adjusted_p": 0.01}],
        "source_map": {"direct": ["PUBMED"]},
        "empty": None,
    })

    assert properties["symbol"] == "TP53"
    assert properties["score_vector"] == [1, 2.5]
    assert properties["collections"] == ["GO_UP", "HALLMARK"]
    assert properties["analysis_assertions"] == '[{"adjusted_p": 0.01, "analysis": "GO_UP"}]'
    assert properties["source_map"] == '{"direct": ["PUBMED"]}'
    assert "empty" not in properties


def test_importer_accepts_large_auditable_csv_assertions(tmp_path):
    value = "x" * (200 * 1024)
    path = tmp_path / "subgraph_edges.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["properties_json"])
        writer.writeheader(); writer.writerow({"properties_json": value})
    with path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert len(row["properties_json"]) == len(value)


def test_biocypher_normalized_import_preserves_source_release_identity_and_graph_build():
    nodes = [
        {"id": "DRUG:X", "type": "Drug", "label": "Drug X", "properties_json": "{}"},
        {"id": "ENSG000001", "type": "Gene", "label": "TP53", "properties_json": '{"symbol":"TP53"}'},
    ]
    edges = [
        {"from": "DRUG:X", "to": "ENSG000001", "label": "DRG-GEN", "relation": "TARGET", "undirected": "false", "source_release": "release-a", "properties_json": '{"source_assertions":[{"source":"db-a"}]}'},
        {"from": "DRUG:X", "to": "ENSG000001", "label": "DRG-GEN", "relation": "TARGET", "undirected": "false", "source_release": "release-b", "properties_json": '{"source_assertions":[{"source":"db-b"}]}'},
    ]

    nodes_by_type, edges_by_type, report = prepare_biocypher_import_rows(
        nodes, edges, "GRAPH_BUILD:test"
    )

    assert report["status"] == "PASS"
    assert nodes_by_type["Gene"][0]["symbol"] == "TP53"
    rows = edges_by_type[("TARGETS", "Drug", "Gene")]
    assert {row["id"] for row in rows} == {
        "DRUG:X|TARGETS|ENSG000001|release-a",
        "DRUG:X|TARGETS|ENSG000001|release-b",
    }
    assert all(row["graph_build_id"] == "GRAPH_BUILD:test" for row in rows)
    assert {row["source_release"] for row in rows} == {"release-a", "release-b"}
    assert {json.loads(row["source_assertion_json"])["source_assertions"][0]["source"] for row in rows} == {"db-a", "db-b"}
