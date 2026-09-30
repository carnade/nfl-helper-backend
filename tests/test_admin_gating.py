"""Nothing under /admin answers without an organiser's Sleeper login.

All sixteen were open. Two of them mattered a great deal: /admin/tinyurl/cleanup
runs clear_tinyurl_data() with no argument, so delete_finished defaults to True —
it scores the week, wipes every lineup and deletes finished tournaments. And
/admin/tinyurl/<name>/data is documented as returning "all data including
user_submissions without requiring any PINs", which is every entrant's lineup
and PIN to anyone holding the URL.

The gate is a before_request rather than a decorator per route, so these tests
walk the URL map: a route added later is covered without anyone remembering to
add it here.
"""

import sys
from unittest.mock import patch

import pytest

nfl_helper = sys.modules["nfl_helper"]


def admin_rules():
    """Every /admin rule, with a method that is not OPTIONS/HEAD."""
    out = []
    for rule in nfl_helper.app.url_map.iter_rules():
        if not str(rule).startswith("/admin/"):
            continue
        method = next(iter(rule.methods - {"OPTIONS", "HEAD"}), "GET")
        # Fill any <converters> with something harmless.
        path = str(rule)
        for part in rule.arguments:
            path = path.replace(f"<{part}>", "x").replace(f"<int:{part}>", "1")
            path = path.replace(f"<string:{part}>", "x")
        out.append((path, method))
    return out


def test_there_are_admin_routes_to_guard():
    """If this ever finds none, the tests below are vacuous."""
    assert len(admin_rules()) >= 10


@pytest.mark.parametrize("path,method", admin_rules())
def test_every_admin_route_refuses_an_anonymous_caller(client, path, method):
    with patch.object(nfl_helper, "verify_sleeper_token", return_value=None):
        resp = client.open(path, method=method)
    assert resp.status_code == 403, f"{method} {path} answered {resp.status_code}"


@pytest.mark.parametrize("path,method", admin_rules())
def test_every_admin_route_refuses_a_non_organiser(client, path, method):
    with patch.object(nfl_helper, "verify_sleeper_token",
                      return_value={"user_id": "2", "display_name": "bob"}):
        resp = client.open(path, method=method, headers={"Authorization": "tok"})
    assert resp.status_code == 403, f"{method} {path} answered {resp.status_code}"


class TestTheGateItself:
    def test_an_organiser_is_let_through(self, client):
        """Past the gate; what the route then does is its own business."""
        with patch.object(nfl_helper, "verify_sleeper_token",
                          return_value={"user_id": "1", "display_name": "carnade"}):
            resp = client.get("/admin/debug", headers={"Authorization": "tok"})
        assert resp.status_code != 403

    def test_the_preflight_is_not_refused(self, client):
        """It carries no Authorization header, so refusing it would stop the
        real request ever being sent."""
        with patch.object(nfl_helper, "verify_sleeper_token", return_value=None):
            resp = client.open("/admin/debug", method="OPTIONS")
        assert resp.status_code != 403

    def test_ordinary_routes_are_untouched(self, client):
        with patch.object(nfl_helper, "verify_sleeper_token", return_value=None):
            assert client.get("/statistics").status_code == 200

    def test_a_path_merely_containing_admin_is_not_gated(self, client):
        """The rule is a prefix, not a substring."""
        with patch.object(nfl_helper, "verify_sleeper_token", return_value=None):
            resp = client.get("/tinyurl/adminstuff/standings")
        assert resp.status_code != 403
