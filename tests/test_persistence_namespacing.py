"""Dev and prod share one Supabase table; a key prefix keeps their rows apart."""

import sys

import pytest
from unittest.mock import patch

nfl_helper = sys.modules["nfl_helper"]

# conftest's autouse fixture stubs save_tinyurl_data so tests never write. Grab the
# real one at import, before that fixture runs, to exercise the dispatch itself.
REAL_SAVE_TINYURL = nfl_helper.save_tinyurl_data


class TestSupabaseKeyNamespacing:
    def test_production_owns_the_bare_keys(self):
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", ""):
            assert nfl_helper._supabase_key("tinyurl_data") == "tinyurl_data"

    def test_prefix_namespaces_every_key(self):
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", "dev_"):
            assert nfl_helper._supabase_key("tinyurl_data") == "dev_tinyurl_data"
            assert nfl_helper._supabase_key("odds_cache") == "dev_odds_cache"

    def test_dev_and_prod_keys_never_collide(self):
        keys = ("tinyurl_data", "tournament_data", "odds_cache",
                "odds_history", "props_history")
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", ""):
            prod = {nfl_helper._supabase_key(k) for k in keys}
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", "dev_"):
            dev = {nfl_helper._supabase_key(k) for k in keys}
        assert prod.isdisjoint(dev)


class TestReadOnlyWritesToFiles:
    def test_read_only_sends_tinyurl_writes_to_file(self, tmp_path):
        with patch.object(nfl_helper, "SUPABASE_READ_ONLY", True), \
             patch.object(nfl_helper, "DATA_DIR", tmp_path), \
             patch.object(nfl_helper, "supabase_client") as client:
            nfl_helper.tinyurl_data["probe"] = {"name": "probe"}
            REAL_SAVE_TINYURL()

        assert (tmp_path / "tinyurl_data.json").exists()
        client.table.assert_not_called(), "must not touch Supabase in read-only mode"

    def test_read_only_skips_the_shared_gist_too(self, tmp_path):
        """The gist is shared with production just as the Supabase rows are."""
        with patch.object(nfl_helper, "SUPABASE_READ_ONLY", True), \
             patch.object(nfl_helper, "USE_GIST", True), \
             patch.object(nfl_helper, "DATA_DIR", tmp_path), \
             patch.object(nfl_helper, "requests") as req:
            nfl_helper.save_odds_cache()

        req.patch.assert_not_called()
        assert (tmp_path / "odds_cache.json").exists()
