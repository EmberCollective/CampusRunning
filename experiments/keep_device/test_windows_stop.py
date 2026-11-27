"""A launcher stop signal must leave the normal server cleanup reachable."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from experiments.keep_device.windows import _wait_for_stop, main


def test_stop_signal_and_duration_are_both_bounded():
    async def exercise():
        with TemporaryDirectory() as directory:
            path = Path(directory) / "stop"
            task = asyncio.create_task(_wait_for_stop(60, str(path)))
            await asyncio.sleep(0)
            assert not task.done()
            path.touch()
            await asyncio.wait_for(task, 1)
            path.unlink()
            await asyncio.wait_for(_wait_for_stop(0.01, str(path)), 1)
            assert not path.exists()
    asyncio.run(exercise())


def test_preexisting_stop_signal_rejected_before_radio_changes():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "stop"
        path.touch()
        with patch("sys.platform", "win32"), patch("sys.argv", ["windows", "--keep-name", "--stop-file", str(path)]), patch("experiments.keep_device.windows._run_with_keep_name") as start:
            with pytest.raises(SystemExit) as error:
                main()
            assert error.value.code == 2
            start.assert_not_called()


def test_launcher_signal_reaches_named_parent():
    with TemporaryDirectory() as directory:
        path = str(Path(directory) / "stop")
        with patch("sys.platform", "win32"), patch("sys.argv", ["windows", "--keep-name", "--model", "B5", "--stop-file", path]), patch("experiments.keep_device.windows._run_with_keep_name") as start:
            main()
            start.assert_called_once_with(300, None, "B5", None, stop_file=path)
