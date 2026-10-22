import base64
import json
from pathlib import Path
from cryptography.exceptions import InvalidTag
import pytest
from server.vault import Vault
from server.cli import recover

@pytest.fixture
def vault(tmp_path):
    recovery = tmp_path / 'recovery'
    recovery.mkdir()
    (recovery / '.awanvault-target').write_text('test')
    return Vault(tmp_path / 'primary', recovery, b'k' * 32)


def test_roundtrip_and_no_plaintext(vault):
    file_id, duplicate = vault.store(b'secret contents', 'payroll.pdf', 'Android/Documents', 'application/pdf')
    assert not duplicate
    blob = (vault.recovery / (file_id + '.av')).read_bytes()
    assert b'secret contents' not in blob and b'payroll.pdf' not in blob
    meta, content = vault.unpack(blob, file_id)
    assert meta['name'] == 'payroll.pdf' and content == b'secret contents'
    with vault.db() as db:
        metadata = db.execute('SELECT metadata FROM files').fetchone()[0]
    assert b'payroll.pdf' not in metadata


def test_dedup_and_versions(vault):
    a, _ = vault.store(b'v1', 'report.txt', 'folder', 'text/plain')
    b, duplicate = vault.store(b'v1', 'report.txt', 'folder', 'text/plain')
    c, _ = vault.store(b'v2', 'report.txt', 'folder', 'text/plain')
    assert a == b and duplicate and c != a
    assert len(vault.list_files()) == 2


def test_separate_sources_preserved(vault):
    a, _ = vault.store(b'same', 'a.txt', 'one', 'text/plain')
    b, _ = vault.store(b'same', 'a.txt', 'two', 'text/plain')
    assert a != b


def test_tamper_and_wrong_key_rejected(vault):
    file_id, _ = vault.store(b'original', 'a.txt', 'f', 'text/plain')
    blob = vault.read_blob(file_id)
    with pytest.raises(InvalidTag):
        vault.unpack(blob[:-1] + bytes([blob[-1] ^ 1]), file_id)
    vault.key = b'x' * 32
    with pytest.raises(InvalidTag):
        vault.unpack(blob, file_id)


def test_primary_corruption_recovers_from_backup(vault):
    file_id, _ = vault.store(b'original', 'a.txt', 'f', 'text/plain')
    (vault.data / 'objects' / (file_id + '.av')).write_bytes(b'corrupt')
    assert vault.unpack(vault.read_blob(file_id), file_id)[1] == b'original'


def test_missing_target_blocks_new_acknowledgement(vault):
    (vault.recovery / '.awanvault-target').unlink()
    with pytest.raises(OSError):
        vault.store(b'data', 'a.txt', 'f', 'text/plain')
    assert vault.list_files() == []


def test_offline_disaster_recovery_needs_no_database_or_telegram(vault, tmp_path):
    file_id, _ = vault.store(b'important', 'report.pdf', 'f', 'application/pdf')
    keyfile = tmp_path / 'offline.key'
    keyfile.write_bytes(base64.urlsafe_b64encode(vault.key))
    import shutil
    shutil.rmtree(vault.data)
    recover(str(vault.recovery), str(tmp_path / 'restored'), str(keyfile))
    assert (tmp_path / 'restored' / file_id / 'report.pdf').read_bytes() == b'important'


def test_recovery_does_not_overwrite_existing_output(vault, tmp_path):
    file_id, _ = vault.store(b'important', 'report.pdf', 'f', 'application/pdf')
    keyfile = tmp_path / 'offline.key'; keyfile.write_bytes(base64.urlsafe_b64encode(vault.key))
    recover(str(vault.recovery), str(tmp_path / 'restored'), str(keyfile))
    with pytest.raises(SystemExit):
        recover(str(vault.recovery), str(tmp_path / 'restored'), str(keyfile))


@pytest.mark.parametrize('name', ['../x','a/b','a\\b','..','bad\nname',''])
def test_unsafe_names_rejected(vault, name):
    with pytest.raises(ValueError): vault.store(b'a',name,'f','text/plain')


def test_duplicate_repair(vault):
    file_id, _ = vault.store(b'original', 'a.txt', 'f', 'text/plain')
    (vault.recovery / (file_id + '.av')).unlink()
    other, duplicate = vault.store(b'original', 'a.txt', 'f', 'text/plain')
    assert duplicate and other == file_id
    assert vault.unpack((vault.recovery / (file_id + '.av')).read_bytes(), file_id)[1] == b'original'


def test_reupload_repairs_loss_of_both_files_with_database_intact(vault):
    file_id, _ = vault.store(b'original', 'a.txt', 'f', 'text/plain')
    (vault.data / 'objects' / (file_id + '.av')).unlink()
    (vault.recovery / (file_id + '.av')).unlink()
    same, duplicate = vault.store(b'original', 'a.txt', 'f', 'text/plain')
    assert duplicate and same == file_id
    assert vault.unpack(vault.read_blob(file_id), file_id)[1] == b'original'
