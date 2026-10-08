"""Inbox discovery tests use temporary files and a mocked pipeline only."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from watchfiles import Change

from src.watcher import watch_inbox


@pytest.mark.parametrize("files", [[], ["old.pdf", "nested/UPPER.PDF"],
                                    ["notes.txt", "image.jpg", "fake.pdf/notes.txt",
                                     ".git/ignored.pdf", "flycheck_ignore.pdf"]])
async def test_startup_discovery(mock_settings, monkeypatch, files):
    for name in files:
        path = mock_settings.inbox_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    process = AsyncMock()
    monkeypatch.setattr("src.watcher.process_file", process)

    async def watch(path, **kwargs):
        assert path == mock_settings.inbox_dir
        assert kwargs["yield_on_timeout"] is True
        yield set()  # Watcher is installed; empty inboxes still trigger discovery.
        await asyncio.sleep(0)

    monkeypatch.setattr("src.watcher.awatch", watch)
    notifier, pending = object(), {}
    await watch_inbox(mock_settings, notifier, pending, asyncio.Event())
    expected = {mock_settings.inbox_dir / name for name in files
                if name in {"old.pdf", "nested/UPPER.PDF"}}
    assert {call.args[0] for call in process.call_args_list} == expected
    for call in process.call_args_list:
        assert call.args[1:] == (mock_settings, notifier, pending)


async def test_startup_overlap_and_arrivals(mock_settings, monkeypatch):
    old = mock_settings.inbox_dir / "old.pdf"
    old.write_bytes(b"test")
    arrival = mock_settings.inbox_dir / "arrival.pdf"
    later = mock_settings.inbox_dir / "later.pdf"
    release = asyncio.Event()
    started = asyncio.Event()
    finished = asyncio.Event()
    calls = []

    async def process(path, *_):
        calls.append(path)
        if path == old:
            started.set()
            await release.wait()
            finished.set()

    async def watch(*args, **kwargs):
        # Arrival during watcher initialization, before startup discovery.
        arrival.write_bytes(b"test")
        yield {(Change.added, str(old)), (Change.added, str(arrival))}
        await started.wait()
        # Events while startup processing is still running.
        yield {(Change.modified, str(old))}
        later.write_bytes(b"test")
        yield {(Change.added, str(later))}
        release.set()
        await finished.wait()
        await asyncio.sleep(0)
        # Delayed event after processing finishes, with source still present.
        yield {(Change.modified, str(old))}
        await asyncio.sleep(0)

    monkeypatch.setattr("src.watcher.awatch", watch)
    monkeypatch.setattr("src.watcher.process_file", process)
    await watch_inbox(mock_settings, object(), {}, asyncio.Event())
    assert sorted(calls) == sorted([old, arrival, later])


async def test_creates_directories(mock_settings, monkeypatch):
    directories = (mock_settings.inbox_dir, mock_settings.archive_dir,
                   mock_settings.pending_dir, mock_settings.error_dir)
    for directory in directories:
        directory.rmdir()

    async def watch(*args, **kwargs):
        assert all(directory.is_dir() for directory in directories)
        yield set()

    monkeypatch.setattr("src.watcher.awatch", watch)
    process = AsyncMock()
    monkeypatch.setattr("src.watcher.process_file", process)
    await watch_inbox(mock_settings, object(), {}, asyncio.Event())
    process.assert_not_called()


async def test_real_watcher_startup_and_new_file(mock_settings, monkeypatch):
    """Exercise awatch readiness using only a temporary local inbox."""
    old = mock_settings.inbox_dir / "nested" / "old.pdf"
    old.parent.mkdir()
    old.write_bytes(b"test")
    new = old.parent / "new.pdf"
    calls = []
    stop = asyncio.Event()

    async def process(path, *_):
        calls.append(path)
        path.unlink()
        if path == old:
            new.write_bytes(b"test")
        if path == new:
            stop.set()

    monkeypatch.delenv("WATCHFILES_FORCE_POLLING", raising=False)
    monkeypatch.setattr("src.watcher.process_file", process)
    await asyncio.wait_for(
        watch_inbox(mock_settings, object(), {}, stop), timeout=15
    )
    assert calls == [old, new]


@pytest.mark.parametrize("polling", [False, True])
async def test_changed_file_can_be_processed_again(mock_settings, monkeypatch, polling):
    path = mock_settings.inbox_dir / "document.pdf"
    path.write_bytes(b"first")
    process = AsyncMock()
    monkeypatch.setattr("src.watcher.process_file", process)
    monkeypatch.setenv("WATCHFILES_FORCE_POLLING", "true" if polling else "false")

    async def watch(*args, **kwargs):
        assert kwargs["force_polling"] is polling
        if polling:
            assert kwargs["step"] == 10000
            assert kwargs["poll_delay_ms"] == 10000
        yield set()
        await asyncio.sleep(0)
        path.write_bytes(b"changed contents")
        yield {(Change.modified, str(path))}
        await asyncio.sleep(0)
        path.unlink()
        yield {(Change.deleted, str(path))}
        path.write_bytes(b"replacement")
        yield {(Change.added, str(path))}
        await asyncio.sleep(0)

    monkeypatch.setattr("src.watcher.awatch", watch)
    await watch_inbox(mock_settings, object(), {}, asyncio.Event())
    assert process.await_count == 3


async def test_replacement_arriving_while_processing(mock_settings, monkeypatch):
    path = mock_settings.inbox_dir / "same.pdf"
    path.write_bytes(b"original")
    started, release, replacement_done = (asyncio.Event() for _ in range(3))
    calls = []

    async def process(pdf, *_):
        calls.append(pdf.read_bytes())
        if len(calls) == 1:
            pdf.rename(mock_settings.pending_dir / pdf.name)
            started.set()
            await release.wait()
        else:
            replacement_done.set()

    async def watch(*args, **kwargs):
        yield set()
        await started.wait()
        path.write_bytes(b"replacement")
        yield {(Change.added, str(path))}
        release.set()
        await replacement_done.wait()

    monkeypatch.setattr("src.watcher.awatch", watch)
    monkeypatch.setattr("src.watcher.process_file", process)
    await asyncio.wait_for(
        watch_inbox(mock_settings, object(), {}, asyncio.Event()), timeout=2
    )
    assert calls == [b"original", b"replacement"]
