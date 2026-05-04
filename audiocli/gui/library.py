"""Saved-chain library service for GUI and other app-shell callers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiocli.capabilities import CapabilityNode
from audiocli.chains import (
    CapabilityChain,
    ChainFormatError,
    iter_chain_files,
    load_chain,
    save_chain,
)


@dataclass(frozen=True)
class SavedChainEntry:
    """UI-ready saved-chain library row."""

    id: str
    path: str
    name: str
    description: str = ""
    notes: str = ""
    schema_version: int | None = None
    valid: bool = False
    error: str = ""
    error_code: str = ""
    node_count: int = 0
    enabled_node_count: int = 0

    def to_view_model(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "description": self.description,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "schema": self.schema_version,
            "valid": self.valid,
            "error": self.error,
            "error_code": self.error_code,
            "node_count": self.node_count,
            "enabled_node_count": self.enabled_node_count,
        }


class SavedChainLibraryService:
    """List and maintain saved chains under a configured library directory."""

    def __init__(
        self,
        library_dir: str | Path,
        *,
        capability_catalog: dict[str, CapabilityNode] | None = None,
    ) -> None:
        self.library_dir = Path(library_dir)
        self._resolved_library_dir = self.library_dir.resolve(strict=False)
        self.capability_catalog = capability_catalog

    def list_entries(self) -> list[SavedChainEntry]:
        entries: list[SavedChainEntry] = []
        for path in iter_chain_files(self.library_dir):
            try:
                entries.append(self.entry_for_path(path))
            except ChainFormatError as exc:
                entries.append(_invalid_entry_for_listing(path, str(exc), exc.code))
            except Exception as exc:
                entries.append(
                    _invalid_entry_for_listing(
                        path,
                        f"Could not inspect saved chain {path}: {exc}",
                        "listing_error",
                    )
                )
        return entries

    def entry_for_path(self, path: str | Path) -> SavedChainEntry:
        source = self._confined_path(path)
        try:
            chain = load_chain(
                source,
                capability_catalog=self.capability_catalog,
                chain_dir=self.library_dir,
            )
        except ChainFormatError as exc:
            return SavedChainEntry(
                id="",
                path=str(source),
                name=_display_name_from_path(source),
                valid=False,
                error=str(exc),
                error_code=exc.code,
            )
        except ValueError as exc:
            return SavedChainEntry(
                id="",
                path=str(source),
                name=_display_name_from_path(source),
                valid=False,
                error=str(exc),
                error_code="schema_error",
            )

        validation = chain.validate(chain_dir=self.library_dir)
        if validation.valid:
            return _valid_entry(source, chain)
        error = " | ".join(error.message for error in validation.errors[:3])
        if len(validation.errors) > 3:
            error += f" | +{len(validation.errors) - 3} more"
        return SavedChainEntry(
            id=chain.id,
            path=str(source),
            name=chain.name,
            description=chain.description,
            notes=chain.notes,
            schema_version=1,
            valid=False,
            error=error or "Saved chain failed validation.",
            error_code="validation_error",
            node_count=len(chain.nodes),
            enabled_node_count=sum(1 for node in chain.nodes if node.enabled),
        )

    def load_saved_chain(self, path: str | Path) -> CapabilityChain:
        chain = self._load_structured_chain(path)
        validation = chain.validate(chain_dir=self.library_dir)
        if not validation.valid:
            error = " | ".join(item.message for item in validation.errors[:3])
            raise ChainFormatError(
                "validation_error",
                f"Saved chain {Path(path)} is invalid and cannot be loaded: {error}",
            )
        return chain

    def rename_saved_chain(self, path: str | Path, new_name: str) -> SavedChainEntry:
        source = self._confined_path(path)
        chain = self._load_structured_chain(source)
        name = str(new_name).strip()
        if not name:
            raise ValueError("Saved chain name must not be empty.")
        chain.name = name
        save_chain(chain, source)
        return self.entry_for_path(source)

    def update_saved_chain_notes(
        self,
        path: str | Path,
        *,
        description: str | None = None,
        notes: str | None = None,
    ) -> SavedChainEntry:
        source = self._confined_path(path)
        chain = self._load_structured_chain(source)
        if description is not None:
            chain.description = str(description)
        if notes is not None:
            chain.notes = str(notes)
        save_chain(chain, source)
        return self.entry_for_path(source)

    def to_view_model(self) -> dict[str, Any]:
        entries = [entry.to_view_model() for entry in self.list_entries()]
        return {
            "chain_library_dir": str(self.library_dir),
            "entries": entries,
            "valid_count": sum(1 for entry in entries if entry["valid"]),
            "error_count": sum(1 for entry in entries if not entry["valid"]),
        }

    def _load_structured_chain(self, path: str | Path) -> CapabilityChain:
        source = self._confined_path(path)
        return load_chain(
            source,
            capability_catalog=self.capability_catalog,
            chain_dir=self.library_dir,
        )

    def _confined_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.library_dir / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self._resolved_library_dir)
        except ValueError as exc:
            raise ChainFormatError(
                "path_error",
                f"Saved chain path {candidate} is outside library directory {self.library_dir}.",
            ) from exc
        return resolved


def _valid_entry(path: Path, chain: CapabilityChain) -> SavedChainEntry:
    return SavedChainEntry(
        id=chain.id,
        path=str(path),
        name=chain.name,
        description=chain.description,
        notes=chain.notes,
        schema_version=1,
        valid=True,
        node_count=len(chain.nodes),
        enabled_node_count=sum(1 for node in chain.nodes if node.enabled),
    )


def _invalid_entry_for_listing(path: Path, error: str, error_code: str) -> SavedChainEntry:
    return SavedChainEntry(
        id="",
        path=str(path),
        name=_display_name_from_path(path),
        valid=False,
        error=error,
        error_code=error_code,
    )


def _display_name_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".audiocli-chain.json"):
        return name[: -len(".audiocli-chain.json")]
    if name.endswith(".aclichain"):
        return name[: -len(".aclichain")]
    return path.stem


__all__ = ["SavedChainEntry", "SavedChainLibraryService"]
