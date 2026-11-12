import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_nonroot_compose import CheckError, MEDIA, TEMP, WORK, validate_download_layout, validate_model, validate_reader_model


class ComposeContractTests(unittest.TestCase):
    def setUp(self):
        # Model tests do not provision a filesystem. Source readiness is a
        # separate check below and real permissions belong to the Linux runner.
        self.paths = [Path.cwd() / "synthetic-storage" / role for role in ("state", "temp", "media")]
        self.env = dict(BOTAPI_UID="1000", BOTAPI_GID="2000")
        self.model = {"services": {"botapi": {"user": "1000:2000", "environment": {
            "TELEGRAM_FILES_DIR": MEDIA, "BOTAPI_MEDIA_REQUIRE_NONROOT": "1",
            "BOTAPI_MEDIA_EXPECTED_UID": "1000", "BOTAPI_MEDIA_EXPECTED_GID": "2000"}, "volumes": [
                dict(type="bind", source=str(source), target=target, bind={"create_host_path": False})
                for source, target in zip(self.paths, (WORK, TEMP, MEDIA))]}, "gateway": {"volumes": []}}}

    def check(self, model=None, layers=("nonroot", "files")):
        return validate_model(model or self.model, layers, self.env, check_sources=False)

    def test_supported_model(self):
        self.assertTrue(self.check())

    def test_media_layer_requires_nonroot_even_when_ids_are_present(self):
        with self.assertRaisesRegex(CheckError, "media_requires_nonroot"):
            self.check(layers=("files",))

    def test_duplicate_mount_or_implicit_creation_fails(self):
        model = copy.deepcopy(self.model)
        mounts = model["services"]["botapi"]["volumes"]
        mounts.append(copy.deepcopy(mounts[0]))
        with self.assertRaisesRegex(CheckError, "duplicate"):
            self.check(model)
        mounts.pop()
        mounts[0]["bind"]["create_host_path"] = True
        with self.assertRaisesRegex(CheckError, "implicit_source_creation"):
            self.check(model)

    def test_alias_nested_missing_sources_and_wrong_identity_fail(self):
        for source in (str(self.paths[0]), str(self.paths[0] / "nested")):
            model = copy.deepcopy(self.model)
            model["services"]["botapi"]["volumes"][2]["source"] = source
            with self.subTest(source=source), self.assertRaises(CheckError):
                self.check(model)
        model = copy.deepcopy(self.model)
        model["services"]["botapi"]["user"] = "101:101"
        with self.assertRaisesRegex(CheckError, "identity_mismatch"):
            self.check(model)

    def test_missing_source_fails_without_provisioning_it(self):
        with patch.object(Path, "is_dir", return_value=False):
            with self.assertRaisesRegex(CheckError, "unprepared_source"):
                validate_model(self.model, ("nonroot", "files"), self.env)

    def test_gateway_cannot_mount_storage_by_destination_or_source(self):
        for mount in (dict(target=MEDIA + "/nested", source="unrelated"),
                      dict(target="/public", source=str(self.paths[0]))):
            model = copy.deepcopy(self.model)
            model["services"]["gateway"]["volumes"] = [mount]
            with self.assertRaises(CheckError):
                self.check(model)

    def test_reader_requires_scoped_readonly_subpath(self):
        model = {"services": {}}
        for role in ("reader", "posix", "stranger"):
            model["services"][role] = dict(user="2001:3000", network_mode="none",
                group_add=["2000"] if role != "stranger" else [], volumes=[dict(type="volume", source="media",
                target="/media/documents", read_only=role != 'posix', volume=dict(subpath="synthetic-bot/documents"))])
        validate_reader_model(model)
        for change in (dict(read_only=False), dict(volume=dict(subpath="synthetic-bot")), dict(target="/state")):
            bad = copy.deepcopy(model)
            bad["services"]["reader"]["volumes"][0].update(change)
            with self.assertRaises(CheckError):
                validate_reader_model(bad)

    def test_download_temp_must_share_the_media_mount(self):
        mounts = [dict(Destination=p) for p in (WORK, TEMP, MEDIA)]
        validate_download_layout(MEDIA + '/bot/temp/a', MEDIA + '/bot/documents/a', mounts)
        with self.assertRaisesRegex(CheckError, 'download_cross_mount_layout'):
            validate_download_layout(TEMP + '/a', MEDIA + '/bot/documents/a', mounts)


if __name__ == "__main__":
    unittest.main()
