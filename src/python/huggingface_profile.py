"""Normalize the independently optional Hugging Face artifact profile."""
import importlib.util
from pathlib import Path

from src.python.registry_profile import RegistryProfileError

# Use the same dependency-free validator on the controller and target. The
# deployment source tree already carries Ansible roles beside src/python.
_path = Path(__file__).resolve().parents[1] / "ansible/roles/huggingface-artifacts/files/huggingface_contract.py"
_spec = importlib.util.spec_from_file_location("isaac_huggingface_contract", _path)
assert _spec is not None and _spec.loader is not None
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)


def normalize_huggingface(profile: dict) -> dict:
    """Return the normalized mapping without consulting cloud/registry settings."""
    try:
        return {"huggingface": _contract.validate_settings(profile.get("huggingface", {}))}
    except ValueError as error:
        raise RegistryProfileError(str(error)) from None
