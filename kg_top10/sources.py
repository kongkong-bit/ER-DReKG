from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SourceFetchResult:
    source: str
    url: str
    status: str
    retrieved_at: str
    snapshot_path: str | None
    record_count: int
    error: str | None = None


class SourceAdapter:
    name = "source"

    def __init__(self, cache_dir: Path, timeout: int = 30, retries: int = 2, min_interval: float = 0.25) -> None:
        self.cache_dir = cache_dir / self.name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.retries = retries
        self.min_interval = min_interval
        self._last_request = 0.0

    def _snapshot_path(self, url: str, body: bytes | None = None) -> Path:
        key = hashlib.sha256(url.encode() + (body or b"")).hexdigest()
        return self.cache_dir / f"{key}.json"

    def fetch_json(self, url: str, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[dict[str, Any] | list[Any] | None, SourceFetchResult]:
        snapshot = self._snapshot_path(url, body)
        if snapshot.is_file():
            try:
                cached = json.loads(snapshot.read_text(encoding="utf-8"))
                payload = cached.get("payload")
                return payload, SourceFetchResult(self.name, url, "cached", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), str(snapshot), len(payload) if isinstance(payload, list) else 1)
            except (OSError, json.JSONDecodeError):
                pass
        error: str | None = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                request = Request(url, data=body, headers={"Accept": "application/json", "User-Agent": "ER-DReKG-top10/1.0", **(headers or {})}, method=method)
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                payload = json.loads(raw.decode("utf-8"))
                if not snapshot.exists():
                    snapshot.write_text(json.dumps({"url": url, "payload": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
                result = SourceFetchResult(self.name, url, "ok", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), str(snapshot), len(payload) if isinstance(payload, list) else 1)
                return payload, result
            except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                error = str(exc)
                if attempt < self.retries:
                    time.sleep(2**attempt)
        failure_log = self.cache_dir / "failures.jsonl"
        with failure_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"source": self.name, "url": url, "error": error, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, ensure_ascii=False) + "\n")
        return None, SourceFetchResult(self.name, url, "failed", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), None, 0, error)


class PubChemAdapter(SourceAdapter):
    name = "pubchem"

    def resolve(self, name: str):
        return self.fetch_json(f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/Title,CanonicalSMILES,InChIKey/JSON")


class ChEMBLAdapter(SourceAdapter):
    name = "chembl"

    def resolve(self, molecule_id: str):
        return self.fetch_json(f"https://www.ebi.ac.uk/chembl/api/data/molecule/{molecule_id}.json")

    def search(self, name: str):
        encoded = name.replace(" ", "%20")
        return self.fetch_json(f"https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?q={encoded}")


class DGIdbAdapter(SourceAdapter):
    name = "dgidb"

    def resolve(self, drug_name: str):
        return self.fetch_json(f"https://dgidb.org/api/v2/interactions.json?drug_name={drug_name}")


class ReactomeAdapter(SourceAdapter):
    name = "reactome"

    def pathways_for_gene(self, gene: str):
        search_payload, search_result = self.fetch_json(f"https://reactome.org/ContentService/search/query?query={gene}&species=Homo%20sapiens&cluster=true")
        if not isinstance(search_payload, dict):
            return search_payload, search_result
        entries = []
        for group in search_payload.get("results", []):
            entries.extend(group.get("entries", []))
        exact = next((entry for entry in entries if entry.get("exactType") == "ReferenceGeneProduct" and re.sub(r"<[^>]+>", "", str(entry.get("referenceName", ""))).casefold() == gene.casefold()), None)
        if exact is None:
            return search_payload, search_result
        return self.fetch_json(f"https://reactome.org/ContentService/data/pathways/low/entity/{exact['stId']}")


class OpenTargetsAdapter(SourceAdapter):
    name = "opentargets"

    def target_disease(self, target_id: str, disease_id: str):
        query = "query($target:String!,$disease:String!){disease(efoId:$disease){id name associatedTargets(page:{index:0,size:25},cursor:null){rows{target{id} score{overall}}}} target(ensemblId:$target){id approvedSymbol}}"
        body = json.dumps({"query": query, "variables": {"target": target_id, "disease": disease_id}}).encode()
        return self.fetch_json("https://api.platform.opentargets.org/api/v4/graphql", method="POST", body=body, headers={"Content-Type": "application/json"})


class PubMedAdapter(SourceAdapter):
    name = "pubmed"

    def search(self, term: str, retmax: int = 20):
        return self.fetch_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax={retmax}&term={term.replace(' ', '+')}")


ADAPTERS = {adapter.name: adapter for adapter in [PubChemAdapter, ChEMBLAdapter, DGIdbAdapter, ReactomeAdapter, OpenTargetsAdapter, PubMedAdapter]}
