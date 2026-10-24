import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from production import _arrival_destination_projection


def test_arrival_projection_includes_destination_type_and_storage_fields():
    projection = _arrival_destination_projection()

    assert projection["type"] == 1
    assert projection["category"] == 1
    assert projection["meta.storageCap"] == 1
    assert projection["meta.capacity"] == 1
