from __future__ import annotations

import hashlib
import json
import socket
import urllib.request
from dataclasses import dataclass

import pytest

from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus
from football_data_hub.providers.bdfutbol.match_details.acquisition import (
    MatchDiscoveryPilotBlocked,
    run_match_discovery_pilot,
    select_pilot_record,
)
from football_data_hub.providers.bdfutbol.match_details.discovery import (
    discover_html_structure,
)
from football_data_hub.providers.bdfutbol.match_details.store import (
    MatchDetailStoreError,
)
from football_data_hub.providers.bdfutbol.match_details.store import MatchDetailStore
from tests.match_detail_fixtures import make_inventory


def _pilot_inventory():
    inventory = make_inventory()
    record = inventory["matches"][1]
    inventory["source_generation"]["generation_id"] = "match-00-4ad1d610507e425d"
    inventory["source_generation"]["manifest_sha256"] = (
        "00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf"
    )
    record.update(
        {
            "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
            "source_match_id": "272582",
            "season": "2026-27",
            "competition": "Primera Federación",
            "group": "II",
            "matchday": 7,
            "home_team_id": 49,
            "away_team_id": 94,
            "reference_result": {"home_goals": 3, "away_goals": 3},
            "source_match_url": "https://www.bdfutbol.com/es/p/p.php?id=272582",
            "source_generation_id": "match-00-4ad1d610507e425d",
            "acquisition_status": "pending",
            "validation_status": "not_acquired",
        }
    )
    unsigned = {key: value for key, value in inventory.items() if key != "inventory_id"}
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    inventory["inventory_id"] = (
        "match-detail-inventory-" + hashlib.sha256(canonical).hexdigest()[:16]
    )
    record["source_generation_manifest_sha256"] = inventory["source_generation"][
        "manifest_sha256"
    ]
    # Recompute after the final field edit.
    unsigned = {key: value for key, value in inventory.items() if key != "inventory_id"}
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    inventory["inventory_id"] = (
        "match-detail-inventory-" + hashlib.sha256(canonical).hexdigest()[:16]
    )
    return inventory


@dataclass
class FakeDocument:
    source: str
    title_value: str = "Synthetic fixture, not BDFutbol evidence"

    def html(self):
        return self.source

    def title(self):
        return self.title_value


@dataclass
class FakeVisit:
    document: FakeDocument
    final_url: str
    response_status: int | None
    closed: bool = False

    def close(self):
        self.closed = True


@dataclass
class FakeOpened:
    assessment: AccessAssessment
    visit: FakeVisit | None = None
    closed: bool = False

    def close(self):
        self.closed = True
        if self.visit:
            self.visit.close()


class FakeAccess:
    def __init__(self, opened=None, error=None):
        self.opened = opened
        self.error = error
        self.calls = []

    def open(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.opened


def _opened(
    status, *, http=200, final_url=None, body="", title="Fixture", challenge=False
):
    url = "https://www.bdfutbol.com/es/p/p.php?id=272582"
    assessment = AccessAssessment(
        status=status,
        requested_url=url,
        final_url=final_url or url,
        http_status=http,
        page_title=title,
        reason="fixture only",
    )
    visit = FakeVisit(FakeDocument(body, title), final_url or url, http)
    return FakeOpened(assessment, visit)


def test_discovery_report_separates_observed_dom_from_unverified_hypotheses():
    html = b"""<html><head><title>Synthetic match fixture</title>
      <script type="application/json">{"teams":[],"events":[]}</script></head>
      <body><h1>Fixture</h1><table id="synthetic-table"><tr><th>Local</th><th>Visitante</th></tr>
      <tr><td>Team A</td><td>Team B</td></tr></table>
      <a href="/es/p/p.php?id=272582">synthetic link</a></body></html>"""
    report = discover_html_structure(html)

    assert report["source_html_sha256"] == hashlib.sha256(html).hexdigest()
    assert report["semantic_mapping_confirmed"] is False
    assert report["observed_html"]["tables"][0]["rows_excerpt"][0] == [
        "Local",
        "Visitante",
    ]
    assert report["observed_html"]["scripts"][0]["json_object_keys_if_parseable"] == [
        "events",
        "teams",
    ]
    assert report["observed_html"]["scripts"][0]["json_shape_if_parseable"] == {
        "type": "object",
        "keys": ["events", "teams"],
        "children": {
            "events": {"type": "array", "length": 0},
            "teams": {"type": "array", "length": 0},
        },
    }
    assert report["observed_html"]["links"][0]["query_id_candidate"] == "272582"
    assert all(
        item["interpretation_status"] == "unverified_keyword_hypothesis"
        for item in report["hypotheses"]
    )
    assert "selector" not in json.dumps(report["observed_html"]).casefold()


def test_pilot_success_is_discovery_only_and_never_promotes_capture(
    tmp_path, monkeypatch
):
    inventory = _pilot_inventory()
    record = select_pilot_record(inventory)
    html = "<html><body><div>272582 arbitrary text only</div></body></html>"
    opened = _opened(AccessStatus.VALID, body=html)
    access = FakeAccess(opened)
    store = MatchDetailStore(tmp_path / "store")

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery must never promote a capture")

    monkeypatch.setattr(store, "store_valid_capture", forbidden)
    result = run_match_discovery_pilot(inventory=inventory, access=access, store=store)

    assert result.status == "DISCOVERY_REVIEW_REQUIRED"
    assert result.capture_promoted is False
    assert result.navigation_count == 1
    assert len(access.calls) == 1
    assert access.calls[0][0] == record["source_match_url"]
    assert access.calls[0][1]["required_markers"] == ("272582",)
    assert opened.closed and opened.visit.closed
    artifact = result.discovery_artifact
    assert artifact is not None
    report = json.loads(
        (
            tmp_path
            / "store/diagnostics"
            / inventory["inventory_id"]
            / artifact["discovery_id"]
            / "discovery.json"
        ).read_text()
    )
    assert report["semantic_mapping_confirmed"] is False
    assert not (tmp_path / "store/captures" / inventory["inventory_id"]).exists()
    resumed = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert resumed["active_stop"] is True
    assert resumed["verified_by_internal_id"] == {}
    assert resumed["diagnostics"][-1]["error_code"] == "DISCOVERY_REVIEW_REQUIRED"


def test_existing_discovery_artifact_blocks_second_navigation_and_corruption_is_detected(
    tmp_path,
):
    inventory = _pilot_inventory()
    access = FakeAccess(_opened(AccessStatus.VALID, body="<html>272582</html>"))
    store = MatchDetailStore(tmp_path / "store")
    first = run_match_discovery_pilot(inventory=inventory, access=access, store=store)
    assert first.discovery_artifact

    second_access = FakeAccess(_opened(AccessStatus.VALID, body="<html>272582</html>"))
    with pytest.raises(MatchDiscoveryPilotBlocked, match="parada activa"):
        run_match_discovery_pilot(
            inventory=inventory, access=second_access, store=store
        )
    assert second_access.calls == []

    raw_path = (
        tmp_path
        / "store/diagnostics"
        / inventory["inventory_id"]
        / first.discovery_artifact["discovery_id"]
        / "raw/source.html"
    )
    raw_path.write_text("tampered", encoding="utf-8")
    resumed = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert resumed["blocked"] is True
    assert resumed["integrity_blocked"] is True
    assert (
        resumed["invalid_discovery_artifacts"][0]["discovery_id"]
        == first.discovery_artifact["discovery_id"]
    )


def test_discovery_artifact_alone_is_a_stop_after_crash_before_diagnostic(tmp_path):
    inventory = _pilot_inventory()
    record = select_pilot_record(inventory)
    html = b"<html><body>synthetic page to review</body></html>"
    store = MatchDetailStore(tmp_path / "store")
    report = discover_html_structure(html)
    artifact = store.store_discovery_artifact(
        inventory,
        record,
        html,
        report,
        requested_url=record["source_match_url"],
        final_url=record["source_match_url"],
        http_status=200,
        access_status=AccessStatus.INVALID_CONTENT.value,
        page_title="Synthetic",
        duration_ms=100,
    )

    resumed = MatchDetailStore(tmp_path / "store").reconcile(inventory)
    assert resumed["active_stop"] is True
    assert resumed["diagnostics"] == []
    assert resumed["invalid_discovery_artifacts"] == []
    metadata = json.loads(
        (
            tmp_path
            / "store/diagnostics"
            / inventory["inventory_id"]
            / artifact["discovery_id"]
            / "metadata.json"
        ).read_text()
    )
    assert metadata["source_representation"].startswith(
        "BrowserDocument.html() DOM serialization"
    )
    access = FakeAccess(_opened(AccessStatus.VALID, body="272582"))
    with pytest.raises(MatchDiscoveryPilotBlocked):
        run_match_discovery_pilot(inventory=inventory, access=access, store=store)
    assert access.calls == []


def test_discovery_artifact_rejects_fake_semantic_confirmation(tmp_path):
    inventory = _pilot_inventory()
    record = select_pilot_record(inventory)
    html = b"<html><body>synthetic</body></html>"
    report = discover_html_structure(html)
    report["semantic_mapping_confirmed"] = True
    with pytest.raises(MatchDetailStoreError, match="informe de descubrimiento"):
        MatchDetailStore(tmp_path / "store").store_discovery_artifact(
            inventory,
            record,
            html,
            report,
            requested_url=record["source_match_url"],
            final_url=record["source_match_url"],
            http_status=200,
            access_status=AccessStatus.VALID.value,
            page_title="Synthetic",
            duration_ms=100,
        )


def test_store_rejects_challenge_html_even_if_access_flags_claim_valid(tmp_path):
    inventory = _pilot_inventory()
    record = select_pilot_record(inventory)
    html = b"<html><body>Just a moment... checking your browser</body></html>"
    report = discover_html_structure(html)
    with pytest.raises(MatchDetailStoreError, match="desafío de acceso"):
        MatchDetailStore(tmp_path / "store").store_discovery_artifact(
            inventory,
            record,
            html,
            report,
            requested_url=record["source_match_url"],
            final_url=record["source_match_url"],
            http_status=200,
            access_status=AccessStatus.VALID.value,
            page_title="Just a moment...",
            duration_ms=100,
        )
    assert not (tmp_path / "store/diagnostics" / inventory["inventory_id"]).exists()


@pytest.mark.parametrize(
    ("status", "http", "final_url", "challenge", "expected"),
    [
        (AccessStatus.HTTP_ERROR, 403, None, False, "HTTP_403"),
        (AccessStatus.HTTP_ERROR, 404, None, False, "HTTP_404"),
        (AccessStatus.HTTP_ERROR, 429, None, False, "HTTP_429"),
        (AccessStatus.HTTP_ERROR, 500, None, False, "HTTP_500"),
        (AccessStatus.HTTP_ERROR, 502, None, False, "HTTP_502"),
        (AccessStatus.HTTP_ERROR, 503, None, False, "HTTP_503"),
        (AccessStatus.HTTP_ERROR, 504, None, False, "HTTP_504"),
        (AccessStatus.HTTP_ERROR, None, None, False, "HTTP_UNKNOWN"),
        (AccessStatus.CHALLENGE_REQUIRED, 403, None, True, "CHALLENGE_REQUIRED"),
        (
            AccessStatus.INVALID_URL,
            200,
            "https://www.bdfutbol.com/other",
            False,
            "UNEXPECTED_URL",
        ),
    ],
)
def test_access_failures_stop_once_without_saving_challenge_or_redirect_html(
    tmp_path, status, http, final_url, challenge, expected
):
    inventory = _pilot_inventory()
    body = "Just a moment challenge 272582" if challenge else "redirect page 272582"
    access = FakeAccess(_opened(status, http=http, final_url=final_url, body=body))
    store = MatchDetailStore(tmp_path / "store")
    result = run_match_discovery_pilot(inventory=inventory, access=access, store=store)

    assert result.status == "STOPPED"
    assert result.capture_promoted is False
    assert result.discovery_artifact is None
    assert len(access.calls) == 1
    assert store.reconcile(inventory)["active_stop"] is True
    assert not (tmp_path / "store/diagnostics" / inventory["inventory_id"]).exists()
    assert store.reconcile(inventory)["diagnostics"][-1]["error_code"] == expected


def test_http_200_without_preliminary_marker_is_kept_only_for_review(tmp_path):
    inventory = _pilot_inventory()
    access = FakeAccess(
        _opened(
            AccessStatus.INVALID_CONTENT,
            http=200,
            body="<html><body>no id</body></html>",
        )
    )
    store = MatchDetailStore(tmp_path / "store")
    result = run_match_discovery_pilot(inventory=inventory, access=access, store=store)
    assert result.status == "DISCOVERY_REVIEW_REQUIRED"
    assert result.access_status == AccessStatus.INVALID_CONTENT.value
    assert result.discovery_artifact is not None
    assert (
        store.reconcile(inventory)["diagnostics"][-1]["error_code"]
        == "IDENTITY_OR_CONTENT_UNVERIFIED"
    )


def test_navigation_timeout_without_http_status_stops_and_is_not_retried(tmp_path):
    inventory = _pilot_inventory()
    access = FakeAccess(error=TimeoutError("synthetic transport timeout"))
    store = MatchDetailStore(tmp_path / "store")
    result = run_match_discovery_pilot(inventory=inventory, access=access, store=store)
    assert result.status == "STOPPED"
    assert result.http_status is None
    assert len(access.calls) == 1
    assert (
        store.reconcile(inventory)["diagnostics"][-1]["error_code"]
        == "PILOT_ADAPTER_ERROR"
    )
    diagnostic = store.reconcile(inventory)["diagnostics"][-1]
    assert diagnostic["access_status"] == "ADAPTER_ERROR"
    assert isinstance(diagnostic["duration_ms"], int) and diagnostic["duration_ms"] >= 0


def test_pilot_rejects_wrong_identity_inventory_before_access(tmp_path):
    inventory = _pilot_inventory()
    inventory["matches"][1]["away_team_id"] = 95
    unsigned = {key: value for key, value in inventory.items() if key != "inventory_id"}
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    inventory["inventory_id"] = (
        "match-detail-inventory-" + hashlib.sha256(canonical).hexdigest()[:16]
    )
    access = FakeAccess(_opened(AccessStatus.VALID, body="272582"))

    with pytest.raises(MatchDiscoveryPilotBlocked, match="identidad o procedencia"):
        run_match_discovery_pilot(
            inventory=inventory,
            access=access,
            store=MatchDetailStore(tmp_path / "store"),
        )
    assert access.calls == []


def test_offline_preflight_path_does_not_open_sockets_or_construct_browser(
    monkeypatch, capsys
):
    from football_data_hub.providers.bdfutbol.match_details import pilot_cli

    inventory = _pilot_inventory()
    report = {
        "status": "PREFLIGHT_READY_PROFILE_UNCHECKED",
        "http_enabled": False,
        "browser_started": False,
    }
    monkeypatch.setattr(
        pilot_cli, "build_pilot_preflight", lambda **kwargs: (report, inventory)
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run no debe iniciar navegador ni red")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(pilot_cli, "BrowserSessionManager", forbidden)
    assert pilot_cli.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["browser_started"] is False
    assert output["http_enabled"] is False


def test_offline_discovery_cli_writes_only_new_output_and_never_networks(
    tmp_path, monkeypatch, capsys
):
    from football_data_hub.providers.bdfutbol.match_details.discovery_cli import main

    source = tmp_path / "saved.html"
    source.write_text("<html><body>synthetic</body></html>", encoding="utf-8")
    output = tmp_path / "discovery.json"

    def forbidden(*args, **kwargs):
        raise AssertionError("offline HTML analysis must not use the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert main([str(source), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["semantic_mapping_confirmed"] is False
    assert source.read_text(encoding="utf-8") == "<html><body>synthetic</body></html>"
    output_before = output.read_bytes()
    with pytest.raises(FileExistsError):
        main([str(source), "--output", str(output)])
    assert output.read_bytes() == output_before
