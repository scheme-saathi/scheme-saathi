from datetime import timedelta

import pytest

from app.document_storage import DocumentStorageError, LocalDocumentStore


def test_document_upload_works_without_an_encryption_key(tmp_path, monkeypatch):
    content = b"%PDF-1.4\nprivate applicant details\n%%EOF"
    monkeypatch.delenv("SCHEME_SAATHI_DOCUMENT_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv(LocalDocumentStore.DIRECTORY_ENV, str(tmp_path))
    store = LocalDocumentStore.from_environment()

    metadata = store.store(
        thread_id="opaque-thread",
        scheme_id="scheme-1",
        document_type="identity",
        filename="identity.pdf",
        content_type="application/pdf",
        content=content,
    )

    document_files = list(tmp_path.glob("*.bin"))
    assert len(document_files) == 1
    assert document_files[0].read_bytes() == content
    assert b"identity.pdf" in store.manifest_path.read_bytes()
    assert metadata["expires_at"]
    assert store.get_document("opaque-thread", "scheme-1", "identity") == (
        content,
        metadata,
    )
    store.close()
    restarted_store = LocalDocumentStore(tmp_path, start_maintenance=False)
    assert restarted_store.get_document(
        "opaque-thread", "scheme-1", "identity"
    ) == (content, metadata)
    restarted_store.close()


def test_expired_documents_are_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(LocalDocumentStore, "RETENTION", timedelta(seconds=-1))
    store = LocalDocumentStore(tmp_path, start_maintenance=False)
    store.store(
        thread_id="expired-thread",
        scheme_id="scheme-1",
        document_type="identity",
        filename="identity.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\n%%EOF",
    )

    assert store.purge_expired() == 1
    assert store.list_documents("expired-thread") == []
    assert list(tmp_path.glob("*.bin")) == []
    with pytest.raises(FileNotFoundError):
        store.get_document("expired-thread", "scheme-1", "identity")
    store.close()


def test_delete_removes_only_the_requested_thread(tmp_path):
    store = LocalDocumentStore(tmp_path, start_maintenance=False)
    for thread_id in ("thread-1", "thread-2"):
        store.store(
            thread_id=thread_id,
            scheme_id="scheme-1",
            document_type="identity",
            filename="identity.pdf",
            content_type="application/pdf",
            content=b"%PDF-1.4\n%%EOF",
        )

    assert store.delete_thread("thread-1") == 1
    assert store.list_documents("thread-1") == []
    assert len(store.list_documents("thread-2")) == 1
    store.close()


def test_invalid_manifest_is_reported(tmp_path):
    store = LocalDocumentStore(tmp_path, start_maintenance=False)
    store.manifest_path.write_text("invalid json", encoding="utf-8")

    with pytest.raises(DocumentStorageError, match="index could not be read"):
        store.list_documents("thread-1")

    store.close()
