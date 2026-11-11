"""Stage 5: the Prometheus and Grafana setup files agree with the metrics the app really exposes."""

import json
import re
from pathlib import Path

import pytest
import yaml

from observability.metrics import ALLOWED_LABELS, PREFIX, Metrics
from observability.runs import SERVER_SIDE_ERRORS

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "observability" / "deploy"
DOC = ROOT / "docs" / "observability.md"

# Labels Prometheus itself adds or that rules use for grouping and routing.
PROMETHEUS_LABELS = {"le", "job", "instance", "severity", "alertname"}


def load(path):
    return yaml.safe_load((DEPLOY / path).read_text(encoding="utf-8"))


def exposed_names():
    """Every sample name the app can expose, including histogram parts, even before a label is first used."""
    names = set()
    for family in Metrics().registry.collect():
        if family.type == "counter":
            names.add(f"{family.name}_total")
        elif family.type == "histogram":
            names.update(f"{family.name}{suffix}" for suffix in ("_bucket", "_sum", "_count"))
        else:
            names.add(family.name)
    return {name for name in names if name.startswith(PREFIX)}


def rules_in(path):
    return [rule for group in load(path)["groups"] for rule in group["rules"]]


def expressions():
    return [(rule.get("record") or rule["alert"], rule["expr"]) for path in ("prometheus/rules.yml", "prometheus/alerts.yml") for rule in rules_in(path)]


def test_every_setup_file_is_valid_yaml():
    for path in (
        "docker-compose.yml",
        "prometheus/prometheus.yml",
        "prometheus/rules.yml",
        "prometheus/alerts.yml",
        "grafana/provisioning/datasources/prometheus.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
    ):
        assert isinstance(load(path), dict), path


def test_rules_and_alerts_only_use_metrics_the_app_exposes():
    known = exposed_names()
    for name, expr in expressions():
        used = set(re.findall(rf"{PREFIX}[a-z0-9_]+", expr))
        assert used <= known, f"{name} uses unknown metrics {sorted(used - known)}"


def test_rules_and_alerts_only_use_labels_the_app_can_produce():
    allowed = ALLOWED_LABELS | PROMETHEUS_LABELS
    for name, expr in expressions():
        grouped = {label.strip() for clause in re.findall(r"\b(?:by|on)\s*\(([^)]*)\)", expr) for label in clause.split(",") if label.strip()}
        matched = set(re.findall(r"(\w+)\s*(?:=~|!~|!=|=)\s*\"", expr))
        assert (grouped | matched) <= allowed, f"{name} uses unknown labels {sorted((grouped | matched) - allowed)}"


def test_alerts_only_use_recording_rules_that_exist():
    recorded = {rule["record"] for rule in rules_in("prometheus/rules.yml")}
    for name, expr in expressions():
        used = set(re.findall(r"scheme_saathi:[a-z0-9_:]+", expr))
        assert used <= recorded, f"{name} uses undefined rules {sorted(used - recorded)}"


def test_recording_rule_names_are_unique_and_follow_the_naming_convention():
    names = [rule["record"] for rule in rules_in("prometheus/rules.yml")]

    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"scheme_saathi:[a-z0-9_]+:[a-z0-9_]+", name) for name in names)


def test_the_run_error_rule_counts_exactly_the_server_side_outcomes():
    rule = next(r for r in rules_in("prometheus/rules.yml") if r["record"] == "scheme_saathi:runs:error_ratio_rate5m")
    outcomes = re.search(r'outcome=~"([^"]+)"', rule["expr"]).group(1).split("|")

    assert set(outcomes) == SERVER_SIDE_ERRORS


def test_every_alert_has_a_severity_and_a_summary():
    for rule in rules_in("prometheus/alerts.yml"):
        assert rule["labels"]["severity"] in {"critical", "warning", "info"}, rule["alert"]
        assert rule["annotations"]["summary"], rule["alert"]


def test_prometheus_reads_the_token_from_a_file_and_loads_both_rule_files():
    config = load("prometheus/prometheus.yml")
    job = next(j for j in config["scrape_configs"] if j["job_name"] == "scheme-saathi")
    authorization = job["authorization"]

    assert authorization["type"] == "Bearer"
    assert authorization["credentials_file"] == "/etc/prometheus/secrets/metrics_token"
    assert "credentials" not in authorization and job["metrics_path"] == "/metrics"
    assert set(config["rule_files"]) == {"/etc/prometheus/rules.yml", "/etc/prometheus/alerts.yml"}


def test_the_compose_stack_is_local_only_pinned_and_has_no_hard_coded_secret():
    compose = load("docker-compose.yml")
    services = compose["services"]

    for service in services.values():
        assert not service["image"].endswith(":latest") and ":" in service["image"]
        assert all(port.startswith("127.0.0.1:") for port in service["ports"])
    password = services["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"]
    assert password.startswith("${GRAFANA_ADMIN_PASSWORD:?")
    assert services["grafana"]["environment"]["GF_AUTH_ANONYMOUS_ENABLED"] == "false"


def test_the_compose_files_mount_what_the_config_points_at():
    mounts = [v for service in load("docker-compose.yml")["services"].values() for v in service["volumes"]]
    sources = [m.split(":")[0] for m in mounts if m.startswith("./")]

    assert "./secrets/metrics_token" in sources
    for source in sources:
        if source != "./secrets/metrics_token":  # the token is made by the user and never committed
            assert (DEPLOY / source).exists(), source
    targets = {m.split(":")[1] for m in mounts}
    assert {"/etc/prometheus/rules.yml", "/etc/prometheus/alerts.yml", "/etc/prometheus/secrets/metrics_token"} <= targets


def test_the_data_source_has_no_secret_and_the_dashboard_uses_it():
    datasources = load("grafana/provisioning/datasources/prometheus.yml")["datasources"]
    assert [(d["type"], d["url"], d["isDefault"]) for d in datasources] == [("prometheus", "http://prometheus:9090", True)]
    assert not any(key in datasources[0] for key in ("basicAuth", "password", "secureJsonData"))

    provider = load("grafana/provisioning/dashboards/dashboards.yml")["providers"][0]
    assert provider["options"]["path"] == "/etc/grafana/provisioning/dashboards/json"  # inside the provisioning mount
    used = {json.dumps(p.get("datasource")) for p in dashboard_panels()}
    assert used == {json.dumps({"type": "prometheus", "uid": datasources[0]["uid"]})}


def dashboard_panels():
    path = DEPLOY / "grafana" / "provisioning" / "dashboards" / "json" / "scheme-saathi.json"
    return [p for p in json.loads(path.read_text(encoding="utf-8"))["panels"] if p["type"] != "row"]


def test_dashboard_queries_only_use_metrics_rules_and_labels_that_exist():
    known = exposed_names()
    recorded = {rule["record"] for rule in rules_in("prometheus/rules.yml")}
    allowed = ALLOWED_LABELS | PROMETHEUS_LABELS
    for panel in dashboard_panels():
        for target in panel["targets"]:
            expr = target["expr"]
            assert not set(re.findall(rf"{PREFIX}[a-z0-9_]+", expr)) - known, (panel["title"], expr)
            assert not set(re.findall(r"scheme_saathi:[a-z0-9_:]+", expr)) - recorded, (panel["title"], expr)
            grouped = {label.strip() for clause in re.findall(r"\b(?:by|on)\s*\(([^)]*)\)", expr) for label in clause.split(",") if label.strip()}
            assert grouped <= allowed, (panel["title"], expr)


def test_the_brief_operations_panels_are_on_the_dashboard():
    titles = {p["title"] for p in dashboard_panels()}
    assert {"Questions per conversation", "Can't-tell rate", "Waiting approvals", "Masked-ID hits", "Cost per conversation"} <= titles


def test_the_secrets_folder_holds_no_token_and_the_example_env_has_no_password():
    assert {p.name for p in (DEPLOY / "secrets").iterdir()} <= {"README.txt", "metrics_token"}
    assert (DEPLOY / ".env.example").read_text(encoding="utf-8").count("GRAFANA_ADMIN_PASSWORD=\n") == 1


def test_the_secrets_and_local_env_files_are_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "observability/deploy/secrets/*" in ignore and ".env" in ignore
    assert "observability/deploy/" in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def doc():
    return DOC.read_text(encoding="utf-8")


def test_the_documentation_lists_every_metric(doc):
    families = set()
    for family in Metrics().registry.collect():
        name = f"{family.name}_total" if family.type == "counter" else family.name
        if name.startswith(PREFIX):
            families.add(name)

    missing = sorted(name for name in families if f"`{name}`" not in doc)
    assert not missing, f"docs/observability.md does not mention {missing}"


def test_the_documentation_lists_every_recording_rule_and_every_kind(doc):
    for rule in rules_in("prometheus/rules.yml"):
        _, subject, _ = rule["record"].split(":")
        assert f"scheme_saathi:{subject}:" in doc, rule["record"]
    from observability.runs import RUN_KINDS

    for kind in RUN_KINDS:
        assert f"`{kind}`" in doc, kind


def test_the_documentation_does_not_contain_a_secret_looking_value(doc):
    assert not re.search(r"(?i)(password|token|api[_-]?key)\s*[:=]\s*[A-Za-z0-9_\-]{16,}", doc)
