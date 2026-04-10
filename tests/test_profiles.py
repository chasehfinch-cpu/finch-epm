"""Tests for the ProfileManager (non-secret config only).

Secret storage tests are skipped in CI since they require a real keyring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finch_epm.profiles.manager import ProfileManager


@pytest.fixture
def profile_manager(tmp_path: Path) -> ProfileManager:
    return ProfileManager(config_path=tmp_path / "profiles.json")


class TestProfileConfig:
    def test_no_profiles_initially(self, profile_manager: ProfileManager) -> None:
        assert profile_manager.list_profiles() == []

    def test_set_and_get_config(self, profile_manager: ProfileManager) -> None:
        profile_manager.set_config("netsuite", "prod", {"account_id": "12345"})
        config = profile_manager.get_config("netsuite", "prod")
        assert config["account_id"] == "12345"

    def test_list_profiles(self, profile_manager: ProfileManager) -> None:
        profile_manager.set_config("netsuite", "prod", {})
        profile_manager.set_config("netsuite", "sandbox", {})
        profile_manager.set_config("fake", "test", {})

        all_profiles = profile_manager.list_profiles()
        assert len(all_profiles) == 3

        ns_profiles = profile_manager.list_profiles("netsuite")
        assert len(ns_profiles) == 2

    def test_delete_profile(self, profile_manager: ProfileManager) -> None:
        profile_manager.set_config("netsuite", "prod", {"account_id": "12345"})
        assert profile_manager.profile_exists("netsuite", "prod")
        profile_manager.delete_profile("netsuite", "prod")
        assert not profile_manager.profile_exists("netsuite", "prod")

    def test_get_nonexistent_raises(self, profile_manager: ProfileManager) -> None:
        with pytest.raises(KeyError):
            profile_manager.get_config("netsuite", "nonexistent")

    def test_persistence(self, tmp_path: Path) -> None:
        config_path = tmp_path / "profiles.json"
        pm1 = ProfileManager(config_path=config_path)
        pm1.set_config("netsuite", "prod", {"account_id": "123"})

        pm2 = ProfileManager(config_path=config_path)
        assert pm2.get_config("netsuite", "prod")["account_id"] == "123"

    def test_profile_exists(self, profile_manager: ProfileManager) -> None:
        assert not profile_manager.profile_exists("netsuite", "prod")
        profile_manager.set_config("netsuite", "prod", {})
        assert profile_manager.profile_exists("netsuite", "prod")
