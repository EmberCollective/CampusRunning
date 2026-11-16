"""Opt-in B5 exporter; inject it into GenerationEngine from the experiment UI."""

import math
import os
import tempfile
from datetime import datetime
from pathlib import Path

from src.core.models import ExportData
from src.exporters.base import BaseExporter

from .files import WorkoutFiles
from .history import encode_workout


class B5Exporter(BaseExporter):
    def get_file_extension(self) -> str:
        return ".sport44"

    def export(self, data: ExportData, output_path: str) -> str:
        if len(data.trackpoints) < 2:
            raise ValueError("B5 requires a GPS track with at least two points")
        if not math.isclose(data.trackpoints[-1].distance_meters, data.distance_km * 1000,
                            rel_tol=0, abs_tol=0.01):
            raise ValueError("GPS endpoint does not match the workout distance")
        elapsed = (datetime.fromisoformat(data.trackpoints[-1].time)
                   - datetime.fromisoformat(data.trackpoints[0].time)).total_seconds()
        if elapsed != data.duration_seconds:
            raise ValueError("GPS duration does not match the workout summary")
        encoded = encode_workout(data)
        target = Path(output_path)
        self.ensure_output_dir(output_path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".b5-", suffix=".tmp",
                                             delete=False) as output:
                temporary = Path(output.name)
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            WorkoutFiles(temporary)
            # A hard link publishes complete bytes atomically and never replaces a file.
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return str(target)
