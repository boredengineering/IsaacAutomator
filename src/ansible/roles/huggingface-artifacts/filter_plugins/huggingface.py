"""Strict inventory validation before host mutation; shared with target runtime."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "files/huggingface_contract.py"
_spec = importlib.util.spec_from_file_location("isaac_hf_contract_filter", _path)
assert _spec is not None and _spec.loader is not None
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)


class FilterModule:
    def filters(self):
        return {"huggingface_settings": _contract.decode_settings}
