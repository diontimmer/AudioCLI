"""GUI-neutral chain editing primitives.

This module models the ordered capability-node chains that a future GUI editor
will manipulate.  It intentionally depends on the service-layer capability
projection only; it does not import the Typer CLI adapter or any PySide6 types.
"""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiocli.capabilities import (
    CapabilityNode,
    IOShape,
    ValidationResult,
    get_capability,
    list_macro_capabilities,
)

NATIVE_CHAIN_SCHEMA_VERSION = 1
NATIVE_CHAIN_KIND = "audiocli.saved_chain"
NATIVE_CHAIN_EXTENSIONS = (".aclichain", ".audiocli-chain.json")


class ChainFormatError(ValueError):
    """Raised when a native saved-chain file does not match the schema."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class ChainNode:
    """One editable node instance inside a chain.

    ``id`` is an editor/serialization identity for this occurrence.  Multiple
    chain nodes may point at the same ``capability_id``; duplicating a node
    copies the capability and params while assigning a new node id.
    """

    id: str
    capability_id: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    notes: str = ""
    output_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return stable serialization-ready state for this node."""

        state: dict[str, Any] = {
            "id": self.id,
            "capability_id": self.capability_id,
            "enabled": self.enabled,
            "params": _json_safe(self.params),
        }
        if self.notes:
            state["notes"] = self.notes
        if self.output_policy:
            state["output_policy"] = _json_safe(self.output_policy)
        return state

    def to_native_dict(self) -> dict[str, Any]:
        """Return this node in the native saved-chain schema."""

        return {
            "id": self.id,
            "node_type": "capability",
            "capability_id": self.capability_id,
            "enabled": self.enabled,
            "params": _json_safe(self.params),
            "notes": self.notes,
            "output_policy": _json_safe(self.output_policy),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChainNode:
        """Restore a chain node from ``to_dict``-compatible state."""

        return cls(
            id=str(data["id"]),
            capability_id=str(data["capability_id"]),
            enabled=bool(data.get("enabled", True)),
            params=dict(data.get("params") or {}),
            notes=str(data.get("notes") or ""),
            output_policy=dict(data.get("output_policy") or {}),
        )


@dataclass(frozen=True)
class ChainValidationError:
    """Structured pre-execution validation error for a chain or node."""

    code: str
    message: str
    node_id: str = ""
    capability_id: str = ""
    index: int | None = None
    parameter: str = ""
    expected_type: str = ""
    received: str = ""
    source_node_id: str = ""
    source_capability_id: str = ""

    def to_view_model(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "capability_id": self.capability_id,
            "index": self.index,
            "parameter": self.parameter,
            "expected_type": self.expected_type,
            "received": self.received,
            "source_node_id": self.source_node_id,
            "source_capability_id": self.source_capability_id,
        }


@dataclass(frozen=True)
class ChainCollectionMapping:
    """Validated edge where an upstream file collection is mapped downstream."""

    source_node_id: str
    source_capability_id: str
    node_id: str
    capability_id: str
    source_cardinality: str
    input_cardinality: str
    behavior: str = "map_each_file"

    def to_view_model(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "source_capability_id": self.source_capability_id,
            "node_id": self.node_id,
            "capability_id": self.capability_id,
            "source_cardinality": self.source_cardinality,
            "input_cardinality": self.input_cardinality,
            "behavior": self.behavior,
        }


@dataclass(frozen=True)
class ChainValidationResult:
    """Validation outcome for the enabled portion of a chain."""

    valid: bool
    errors: list[ChainValidationError] = field(default_factory=list)
    node_results: dict[str, ValidationResult] = field(default_factory=dict)
    collection_mappings: list[ChainCollectionMapping] = field(default_factory=list)

    def to_view_model(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [error.to_view_model() for error in self.errors],
            "node_results": {
                node_id: result.to_view_model() for node_id, result in self.node_results.items()
            },
            "collection_mappings": [
                mapping.to_view_model() for mapping in self.collection_mappings
            ],
        }


@dataclass(frozen=True)
class ChainExecutionStep:
    """One enabled, validated node ready for future execution wiring."""

    node_id: str
    position: int
    capability_id: str
    operation_name: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "position": self.position,
            "capability_id": self.capability_id,
            "operation_name": self.operation_name,
            "params": _json_safe(self.params),
        }

    def to_view_model(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True)
class ChainExecutionPlan:
    """Execution-ready projection of enabled chain nodes."""

    steps: list[ChainExecutionStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [step.to_dict() for step in self.steps]}

    def to_view_model(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class CapabilityChain:
    """Mutable GUI-neutral model for editing ordered capability chains."""

    id: str = field(default_factory=lambda: f"chain-{uuid.uuid4().hex}")
    name: str = "Untitled Chain"
    description: str = ""
    notes: str = ""
    nodes: list[ChainNode] = field(default_factory=list)
    output_policy: dict[str, Any] = field(default_factory=dict)
    include_plugins: bool = False
    capability_catalog: Mapping[str, CapabilityNode] | None = field(default=None, repr=False)
    source_path: Path | None = field(default=None, repr=False)
    chain_dir: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._ensure_unique_node_ids(self.nodes)

    def add_node(
        self,
        capability_id: str,
        params: Mapping[str, Any] | None = None,
        *,
        node_id: str | None = None,
        enabled: bool = True,
        index: int | None = None,
        notes: str = "",
        output_policy: Mapping[str, Any] | None = None,
    ) -> ChainNode:
        """Add a capability node at ``index`` or append it to the end."""

        insert_at = len(self.nodes) if index is None else index
        self._check_insert_index(insert_at)
        new_node_id = node_id or self._new_node_id()
        self._check_unique_node_id(new_node_id)
        node = ChainNode(
            id=new_node_id,
            capability_id=capability_id,
            params=_json_safe(dict(params or {})),
            enabled=enabled,
            notes=notes,
            output_policy=_json_safe(dict(output_policy or {})),
        )
        self.nodes.insert(insert_at, node)
        return node

    def move_node(self, node_id: str, index: int) -> ChainNode:
        """Move a node to a new stable list position."""

        current = self._node_index(node_id)
        node = self.nodes.pop(current)
        if index < 0 or index > len(self.nodes):
            self.nodes.insert(current, node)
            raise IndexError(f"Node index out of range: {index}")
        self.nodes.insert(index, node)
        return node

    def reorder_node(self, node_id: str, index: int) -> ChainNode:
        """Alias for ``move_node`` using editor terminology."""

        return self.move_node(node_id, index)

    def duplicate_node(
        self,
        source_node_id: str,
        *,
        node_id: str | None = None,
        new_node_id: str | None = None,
        index: int | None = None,
    ) -> ChainNode:
        """Duplicate a node's capability, params, and enabled state."""

        if node_id is not None and new_node_id is not None and node_id != new_node_id:
            raise ValueError("Specify either node_id or new_node_id for the duplicate, not both.")
        original_index = self._node_index(source_node_id)
        original = self.nodes[original_index]
        insert_at = original_index + 1 if index is None else index
        self._check_insert_index(insert_at)
        duplicate_node_id = node_id or new_node_id or self._new_node_id()
        self._check_unique_node_id(duplicate_node_id)
        duplicate = ChainNode(
            id=duplicate_node_id,
            capability_id=original.capability_id,
            params=copy.deepcopy(original.params),
            enabled=original.enabled,
            notes=original.notes,
            output_policy=copy.deepcopy(original.output_policy),
        )
        self.nodes.insert(insert_at, duplicate)
        return duplicate

    def delete_node(self, node_id: str) -> ChainNode:
        """Delete a node from the chain while leaving the remaining order stable."""

        return self.nodes.pop(self._node_index(node_id))

    def remove_node(self, node_id: str) -> ChainNode:
        """Alias for ``delete_node``."""

        return self.delete_node(node_id)

    def set_node_enabled(self, node_id: str, enabled: bool) -> ChainNode:
        """Enable or disable a node without removing it from the editor state."""

        node = self.get_node(node_id)
        node.enabled = enabled
        return node

    def enable_node(self, node_id: str) -> ChainNode:
        """Enable a node."""

        return self.set_node_enabled(node_id, True)

    def disable_node(self, node_id: str) -> ChainNode:
        """Disable a node while keeping it in the chain."""

        return self.set_node_enabled(node_id, False)

    def update_node_params(self, node_id: str, params: Mapping[str, Any]) -> ChainNode:
        """Replace a node's configurable parameters."""

        node = self.get_node(node_id)
        node.params = _json_safe(dict(params))
        return node

    def configure_node(self, node_id: str, params: Mapping[str, Any]) -> ChainNode:
        """Alias for ``update_node_params``."""

        return self.update_node_params(node_id, params)

    def update_node(
        self,
        node_id: str,
        params: Mapping[str, Any] | None = None,
        *,
        capability_id: str | None = None,
        enabled: bool | None = None,
    ) -> ChainNode:
        """Update one or more editable node fields."""

        node = self.get_node(node_id)
        if capability_id is not None:
            node.capability_id = capability_id
        if params is not None:
            node.params = _json_safe(dict(params))
        if enabled is not None:
            node.enabled = enabled
        return node

    def get_node(self, node_id: str) -> ChainNode:
        """Return one node by editor id."""

        return self.nodes[self._node_index(node_id)]

    def validate(self, *, chain_dir: str | Path | None = None) -> ChainValidationResult:
        """Validate enabled nodes, compatibility, and saved-chain macro recursion."""

        self._ensure_unique_node_ids(self.nodes)
        errors: list[ChainValidationError] = []
        collection_mappings: list[ChainCollectionMapping] = []
        node_results: dict[str, ValidationResult] = {}
        enabled_nodes = [(index, node) for index, node in enumerate(self.nodes) if node.enabled]
        library_dir = _effective_chain_dir(chain_dir, self.chain_dir, self.source_path)
        if not enabled_nodes:
            errors.append(
                ChainValidationError(
                    code="no_enabled_nodes",
                    message="Chain must contain at least one enabled runnable node.",
                )
            )
            return ChainValidationResult(valid=False, errors=errors, node_results=node_results)

        resolved_nodes: list[tuple[int, ChainNode, CapabilityNode, ValidationResult]] = []
        for index, node in enabled_nodes:
            capability = self._resolve_capability(node.capability_id, chain_dir=library_dir)
            if capability is None:
                errors.append(
                    ChainValidationError(
                        node_id=node.id,
                        capability_id=node.capability_id,
                        index=index,
                        code="unknown_capability",
                        message=f"Unknown capability '{node.capability_id}'.",
                    )
                )
                continue

            param_result = capability.validate_params(node.params)
            node_results[node.id] = param_result
            if _is_macro_capability(capability):
                errors.extend(
                    _validate_macro_recursion(
                        node=node,
                        index=index,
                        capability=capability,
                        params=param_result.values if param_result.valid else node.params,
                        root_chain=self,
                        chain_dir=library_dir,
                    )
                )
            if not param_result.valid:
                errors.extend(
                    ChainValidationError(
                        node_id=node.id,
                        capability_id=node.capability_id,
                        index=index,
                        code=error.code,
                        message=error.message,
                        parameter=error.parameter,
                        expected_type=error.expected_type,
                        received=error.received,
                    )
                    for error in param_result.errors
                )
            resolved_nodes.append((index, node, capability, param_result))

        for (_left_index, left_node, left_capability, left_result), (
            right_index,
            right_node,
            right_capability,
            _right_result,
        ) in zip(resolved_nodes, resolved_nodes[1:], strict=False):
            left_output_shape = _effective_output_shape(left_capability, left_node, left_result)
            if _is_collection_mapping(left_output_shape, right_capability.input_shape):
                collection_mappings.append(
                    ChainCollectionMapping(
                        source_node_id=left_node.id,
                        source_capability_id=left_node.capability_id,
                        node_id=right_node.id,
                        capability_id=right_node.capability_id,
                        source_cardinality=left_output_shape.cardinality,
                        input_cardinality=right_capability.input_shape.cardinality,
                    )
                )
            if not _shapes_compatible(left_output_shape, right_capability.input_shape):
                errors.append(
                    ChainValidationError(
                        node_id=right_node.id,
                        capability_id=right_node.capability_id,
                        source_node_id=left_node.id,
                        source_capability_id=left_node.capability_id,
                        index=right_index,
                        code="incompatible_shapes",
                        message=(
                            f"Node '{left_node.id}' outputs "
                            f"{_shape_label(left_output_shape)}, but node "
                            f"'{right_node.id}' expects {_shape_label(right_capability.input_shape)}."
                        ),
                    )
                )

        return ChainValidationResult(
            valid=not errors,
            errors=errors,
            node_results=node_results,
            collection_mappings=collection_mappings,
        )

    def to_execution_plan(self, *, validate: bool = True) -> ChainExecutionPlan:
        """Project enabled nodes into a future execution plan.

        Disabled nodes are omitted.  By default this refuses to plan invalid
        chains, ensuring validation failures are caught before execution.
        """

        self._ensure_unique_node_ids(self.nodes)
        validation = self.validate() if validate else None
        if validation is not None and not validation.valid:
            codes = ", ".join(error.code for error in validation.errors)
            raise ValueError(f"Cannot create execution plan for invalid chain: {codes}")

        steps: list[ChainExecutionStep] = []
        node_results = validation.node_results if validation is not None else {}
        for position, node in enumerate(self.nodes):
            if not node.enabled:
                continue
            capability = self._resolve_capability(node.capability_id)
            if capability is None:
                if validate:
                    raise ValueError(f"Unknown capability '{node.capability_id}'.")
                operation_name = ""
                params = _json_safe(node.params)
            else:
                operation_name = capability.operation_name
                result = node_results.get(node.id)
                params = (
                    result.values
                    if result is not None and result.valid
                    else _json_safe(node.params)
                )
            steps.append(
                ChainExecutionStep(
                    node_id=node.id,
                    position=position,
                    capability_id=node.capability_id,
                    operation_name=operation_name,
                    params=params,
                )
            )
        return ChainExecutionPlan(steps=steps)

    def execution_plan(self, *, validate: bool = True) -> ChainExecutionPlan:
        """Alias for ``to_execution_plan``."""

        return self.to_execution_plan(validate=validate)

    def to_view_model(self) -> dict[str, Any]:
        """Return UI-ready state for an ordered chain editor."""

        validation = self.validate()
        node_errors: dict[str, list[ChainValidationError]] = {}
        for error in validation.errors:
            if error.node_id:
                node_errors.setdefault(error.node_id, []).append(error)

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "notes": self.notes,
            "output_policy": _json_safe(self.output_policy),
            "node_count": len(self.nodes),
            "enabled_node_count": sum(1 for node in self.nodes if node.enabled),
            "nodes": [
                self._node_to_view_model(index, node, validation.node_results, node_errors)
                for index, node in enumerate(self.nodes)
            ],
            "validation_state": validation.to_view_model(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return stable serialization-ready state for the chain."""

        self._ensure_unique_node_ids(self.nodes)
        state: dict[str, Any] = {
            "version": 1,
            "id": self.id,
            "name": self.name,
            "nodes": [node.to_dict() for node in self.nodes],
        }
        if self.description:
            state["description"] = self.description
        if self.notes:
            state["notes"] = self.notes
        if self.output_policy:
            state["output_policy"] = _json_safe(self.output_policy)
        return state

    def to_native_dict(self) -> dict[str, Any]:
        """Return the versioned native saved-chain file schema."""

        self._ensure_unique_node_ids(self.nodes)
        return {
            "schema_version": NATIVE_CHAIN_SCHEMA_VERSION,
            "kind": NATIVE_CHAIN_KIND,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "notes": self.notes,
            "output_policy": _json_safe(self.output_policy),
            "nodes": [node.to_native_dict() for node in self.nodes],
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        include_plugins: bool = False,
        capability_catalog: Mapping[str, CapabilityNode] | None = None,
    ) -> CapabilityChain:
        """Restore a chain from ``to_dict``-compatible state."""

        version = int(data.get("version", 1))
        if version != 1:
            raise ValueError(f"Unsupported chain version: {version}")
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or "Untitled Chain"),
            description=str(data.get("description") or ""),
            notes=str(data.get("notes") or ""),
            nodes=[ChainNode.from_dict(node) for node in data.get("nodes", [])],
            output_policy=dict(data.get("output_policy") or {}),
            include_plugins=include_plugins,
            capability_catalog=capability_catalog,
        )

    @classmethod
    def from_native_dict(
        cls,
        data: Mapping[str, Any],
        *,
        include_plugins: bool = False,
        capability_catalog: Mapping[str, CapabilityNode] | None = None,
        source_path: str | Path | None = None,
        chain_dir: str | Path | None = None,
    ) -> CapabilityChain:
        """Restore a chain from the versioned native saved-chain schema."""

        _validate_native_chain_data(data)
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or "Untitled Chain"),
            description=str(data.get("description") or ""),
            notes=str(data.get("notes") or ""),
            nodes=[ChainNode.from_dict(node) for node in data["nodes"]],
            output_policy=dict(data.get("output_policy") or {}),
            include_plugins=include_plugins,
            capability_catalog=capability_catalog,
            source_path=Path(source_path) if source_path is not None else None,
            chain_dir=Path(chain_dir) if chain_dir is not None else None,
        )

    def _node_to_view_model(
        self,
        index: int,
        node: ChainNode,
        node_results: Mapping[str, ValidationResult],
        node_errors: Mapping[str, list[ChainValidationError]],
    ) -> dict[str, Any]:
        capability = self._resolve_capability(node.capability_id)
        if not node.enabled:
            validation_state = {"valid": True, "skipped": True, "errors": [], "values": {}}
        elif node.id in node_results:
            validation_state = node_results[node.id].to_view_model()
            validation_state["skipped"] = False
        else:
            validation_state = {
                "valid": False,
                "skipped": False,
                "errors": [error.to_view_model() for error in node_errors.get(node.id, [])],
                "values": {},
            }

        return {
            "id": node.id,
            "position": index,
            "capability_id": node.capability_id,
            "enabled": node.enabled,
            "params": _json_safe(node.params),
            "notes": node.notes,
            "output_policy": _json_safe(node.output_policy),
            "capability": capability.to_view_model() if capability is not None else None,
            "display_name": capability.display_name
            if capability is not None
            else node.capability_id,
            "validation_state": validation_state,
        }

    def _resolve_capability(
        self,
        capability_id: str,
        *,
        chain_dir: str | Path | None = None,
    ) -> CapabilityNode | None:
        if self.capability_catalog is not None:
            capability = self.capability_catalog.get(capability_id)
            if capability is not None:
                return capability
            for candidate in self.capability_catalog.values():
                if candidate.operation_name == capability_id:
                    return candidate
            return None

        try:
            return get_capability(capability_id, include_plugins=self.include_plugins)
        except KeyError:
            pass

        library_dir = _effective_chain_dir(chain_dir, self.chain_dir, self.source_path)
        if library_dir is not None:
            for capability in list_macro_capabilities(library_dir):
                if capability.id == capability_id or capability.operation_name == capability_id:
                    return capability
        return None

    def _new_node_id(self) -> str:
        while True:
            node_id = f"node-{uuid.uuid4().hex}"
            if all(node.id != node_id for node in self.nodes):
                return node_id

    def _check_unique_node_id(self, node_id: str) -> None:
        if any(node.id == node_id for node in self.nodes):
            self._raise_duplicate_node_id(node_id)

    @staticmethod
    def _ensure_unique_node_ids(nodes: list[ChainNode]) -> None:
        seen: set[str] = set()
        for node in nodes:
            if node.id in seen:
                CapabilityChain._raise_duplicate_node_id(node.id)
            seen.add(node.id)

    @staticmethod
    def _raise_duplicate_node_id(node_id: str) -> None:
        raise ValueError(
            f"Duplicate chain node id '{node_id}'. Node IDs must be unique within a chain."
        )

    def _node_index(self, node_id: str) -> int:
        for index, node in enumerate(self.nodes):
            if node.id == node_id:
                return index
        raise KeyError(node_id)

    def _check_insert_index(self, index: int) -> None:
        if index < 0 or index > len(self.nodes):
            raise IndexError(f"Node index out of range: {index}")


ChainModel = CapabilityChain


def _effective_output_shape(
    capability: CapabilityNode,
    node: ChainNode,
    result: ValidationResult | None = None,
) -> IOShape:
    if capability.type != "analysis":
        return capability.output_shape
    params = result.values if result is not None and result.valid else node.params
    if params.get("pass_through", capability.defaults.get("pass_through", True)) is False:
        metadata_shape = capability.metadata.get("metadata_shape")
        if isinstance(metadata_shape, Mapping):
            return IOShape(
                kind=str(metadata_shape.get("kind") or "metadata"),
                media_type=str(metadata_shape.get("media_type") or "application/json"),
                cardinality=str(metadata_shape.get("cardinality") or "single"),
                description=str(
                    metadata_shape.get("description") or "Structured analysis metadata."
                ),
            )
        return IOShape(
            kind="metadata",
            media_type="application/json",
            cardinality="single",
            description="Structured analysis metadata.",
        )
    return capability.output_shape


def _shapes_compatible(left_output: IOShape, right_input: IOShape) -> bool:
    if left_output.kind != right_input.kind:
        return False
    if not _media_types_compatible(left_output.media_type, right_input.media_type):
        return False
    if left_output.cardinality == right_input.cardinality:
        return True
    return _is_collection_mapping(left_output, right_input)


def _is_collection_mapping(left_output: IOShape, right_input: IOShape) -> bool:
    return (
        left_output.cardinality == "many"
        and right_input.cardinality in {"single", "any", "many"}
        and left_output.kind == right_input.kind
        and _media_types_compatible(left_output.media_type, right_input.media_type)
    )


def _media_types_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    if left.endswith("/*") and right.startswith(left[:-1]):
        return True
    return right.endswith("/*") and left.startswith(right[:-1])


def _shape_label(shape: IOShape) -> str:
    return f"{shape.kind} ({shape.media_type}, {shape.cardinality})"


def save_chain(chain: CapabilityChain, path: str | Path) -> Path:
    """Write ``chain`` to ``path`` using the native saved-chain schema."""

    destination = Path(path)
    _atomic_write_text(
        destination,
        json.dumps(chain.to_native_dict(), indent=2, sort_keys=True) + "\n",
    )
    chain.source_path = destination
    chain.chain_dir = destination.parent
    return destination


def _atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Atomically write text by replacing ``path`` with a same-directory temp file."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, destination)
    finally:
        if tmp_path is not None and tmp_path.exists():
            with suppress(OSError):
                tmp_path.unlink()
    return destination


def load_chain(
    path: str | Path,
    *,
    include_plugins: bool = False,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
    chain_dir: str | Path | None = None,
) -> CapabilityChain:
    """Load a native saved-chain file from disk."""

    source = Path(path)
    try:
        raw = json.loads(source.read_text())
    except json.JSONDecodeError as exc:
        raise ChainFormatError(
            "invalid_json", f"Invalid chain JSON in {source}: {exc.msg}."
        ) from exc
    except OSError as exc:
        raise ChainFormatError("read_error", f"Could not read chain file {source}: {exc}.") from exc
    if not isinstance(raw, Mapping):
        raise ChainFormatError("schema_error", "Saved chain file must contain a JSON object.")
    return CapabilityChain.from_native_dict(
        raw,
        include_plugins=include_plugins,
        capability_catalog=capability_catalog,
        source_path=source,
        chain_dir=Path(chain_dir) if chain_dir is not None else source.parent,
    )


def save_chain_file(chain: CapabilityChain, path: str | Path) -> Path:
    """Alias for :func:`save_chain`."""

    return save_chain(chain, path)


def load_chain_file(
    path: str | Path,
    *,
    include_plugins: bool = False,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
    chain_dir: str | Path | None = None,
) -> CapabilityChain:
    """Alias for :func:`load_chain`."""

    return load_chain(
        path,
        include_plugins=include_plugins,
        capability_catalog=capability_catalog,
        chain_dir=chain_dir,
    )


def is_native_chain_file(path: str | Path) -> bool:
    """Return true for paths with a supported native saved-chain extension."""

    name = Path(path).name
    return name.endswith(NATIVE_CHAIN_EXTENSIONS)


def iter_chain_files(chain_dir: str | Path) -> list[Path]:
    """List native saved-chain files in a chain library directory."""

    directory = Path(chain_dir)
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir() if path.is_file() and is_native_chain_file(path)
    )


def _validate_native_chain_data(data: Mapping[str, Any]) -> None:
    if "schema_version" not in data:
        raise ChainFormatError("missing_schema_version", "Saved chain is missing schema_version.")
    schema_version = data["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ChainFormatError(
            "schema_error", "Saved chain schema_version must be a JSON integer number."
        )
    if schema_version != NATIVE_CHAIN_SCHEMA_VERSION:
        raise ChainFormatError(
            "unsupported_schema_version",
            f"Unsupported saved chain schema_version {schema_version}; expected {NATIVE_CHAIN_SCHEMA_VERSION}.",
        )
    kind = data.get("kind", NATIVE_CHAIN_KIND)
    if kind != NATIVE_CHAIN_KIND:
        raise ChainFormatError("schema_error", f"Unsupported saved chain kind {kind!r}.")
    for field_name in ("id", "name", "nodes"):
        if field_name not in data:
            raise ChainFormatError(
                "schema_error", f"Saved chain is missing required field '{field_name}'."
            )
    for field_name in ("id", "name", "description", "notes"):
        if field_name in data and not isinstance(data[field_name], str):
            raise ChainFormatError(
                "schema_error", f"Saved chain field '{field_name}' must be a string."
            )
    if not isinstance(data["nodes"], list):
        raise ChainFormatError("schema_error", "Saved chain field 'nodes' must be a list.")
    if not isinstance(data.get("output_policy", {}), Mapping):
        raise ChainFormatError(
            "schema_error", "Saved chain field 'output_policy' must be an object."
        )
    for index, node in enumerate(data["nodes"]):
        if not isinstance(node, Mapping):
            raise ChainFormatError("schema_error", f"Saved chain node {index} must be an object.")
        node_type = node.get("node_type")
        if node_type != "capability":
            raise ChainFormatError(
                "schema_error",
                f"Saved chain node {index} has unsupported node_type {node_type!r}; expected 'capability'.",
            )
        for field_name in ("id", "capability_id"):
            if field_name not in node:
                raise ChainFormatError(
                    "schema_error", f"Saved chain node {index} is missing '{field_name}'."
                )
            if not isinstance(node[field_name], str):
                raise ChainFormatError(
                    "schema_error",
                    f"Saved chain node {index} field '{field_name}' must be a string.",
                )
        if "enabled" in node and not isinstance(node["enabled"], bool):
            raise ChainFormatError(
                "schema_error", f"Saved chain node {index} field 'enabled' must be a boolean."
            )
        if "params" not in node:
            raise ChainFormatError("schema_error", f"Saved chain node {index} is missing 'params'.")
        if not isinstance(node["params"], Mapping):
            raise ChainFormatError(
                "schema_error", f"Saved chain node {index} params must be an object."
            )
        if "output_policy" in node and not isinstance(node["output_policy"], Mapping):
            raise ChainFormatError(
                "schema_error", f"Saved chain node {index} output_policy must be an object."
            )
        if "notes" in node and not isinstance(node["notes"], str):
            raise ChainFormatError(
                "schema_error", f"Saved chain node {index} field 'notes' must be a string."
            )


def _effective_chain_dir(
    requested: str | Path | None,
    chain_dir: Path | None,
    source_path: Path | None,
) -> Path | None:
    if requested is not None:
        return Path(requested)
    if chain_dir is not None:
        return chain_dir
    if source_path is not None:
        return source_path.parent
    return None


def _is_macro_capability(capability: CapabilityNode) -> bool:
    return capability.type == "saved_chain_macro"


def _validate_macro_recursion(
    *,
    node: ChainNode,
    index: int,
    capability: CapabilityNode,
    params: Mapping[str, Any],
    root_chain: CapabilityChain,
    chain_dir: Path | None,
) -> list[ChainValidationError]:
    target_path = _resolve_macro_path(node, capability, params, chain_dir)
    target_id = str(params.get("chain_id") or capability.defaults.get("chain_id") or "")
    if target_path is None and target_id and chain_dir is not None:
        target_path = _find_chain_file_by_id(target_id, chain_dir)

    if target_id and target_id == root_chain.id:
        return [
            _recursive_chain_error(
                node=node,
                index=index,
                message=(
                    f"Recursive saved-chain reference rejected: node '{node.id}' references "
                    f"the containing chain id '{root_chain.id}'."
                ),
            )
        ]
    if target_path is None:
        return []

    root_path = root_chain.source_path.resolve() if root_chain.source_path is not None else None
    resolved_target = target_path.resolve()
    if root_path is not None and resolved_target == root_path:
        return [
            _recursive_chain_error(
                node=node,
                index=index,
                message=(
                    f"Recursive saved-chain reference rejected: node '{node.id}' directly "
                    f"references containing chain '{root_path}'."
                ),
            )
        ]

    if root_path is None and not root_chain.id:
        return []

    cycle = _find_macro_cycle(
        start_path=resolved_target,
        root_path=root_path,
        root_id=root_chain.id,
        chain_dir=chain_dir or resolved_target.parent,
        capability_catalog=root_chain.capability_catalog,
        visiting=(),
    )
    if cycle:
        return [
            _recursive_chain_error(
                node=node,
                index=index,
                message=f"Recursive saved-chain reference rejected: {' -> '.join(cycle)}.",
            )
        ]
    return []


def _recursive_chain_error(*, node: ChainNode, index: int, message: str) -> ChainValidationError:
    return ChainValidationError(
        node_id=node.id,
        capability_id=node.capability_id,
        index=index,
        code="recursive_chain",
        message=message,
    )


def _resolve_macro_path(
    node: ChainNode,
    capability: CapabilityNode | None,
    params: Mapping[str, Any],
    chain_dir: Path | None,
) -> Path | None:
    raw_path = params.get("path") or params.get("chain_path")
    if raw_path is None and capability is not None:
        raw_path = capability.defaults.get("path") or capability.defaults.get("chain_path")
    if raw_path is not None:
        path = Path(str(raw_path))
        return path if path.is_absolute() or chain_dir is None else chain_dir / path
    if chain_dir is not None:
        for candidate in list_macro_capabilities(chain_dir):
            if candidate.id == node.capability_id:
                candidate_path = candidate.defaults.get("path")
                if candidate_path:
                    path = Path(str(candidate_path))
                    return path if path.is_absolute() else chain_dir / path
                return None
    return None


def _find_macro_cycle(
    *,
    start_path: Path,
    root_path: Path | None,
    root_id: str,
    chain_dir: Path,
    capability_catalog: Mapping[str, CapabilityNode] | None,
    visiting: tuple[Path, ...],
) -> list[str]:
    current = start_path.resolve()
    current_dir = current.parent
    if root_path is not None and current == root_path:
        return [_path_label(path) for path in (*visiting, current)]
    if current in visiting:
        cycle_start = visiting.index(current)
        return [_path_label(path) for path in (*visiting[cycle_start:], current)]
    try:
        chain = load_chain(
            current,
            chain_dir=current_dir,
            capability_catalog=capability_catalog,
        )
    except ChainFormatError:
        return []
    if root_id and chain.id == root_id:
        return [_path_label(path) for path in (*visiting, current)]

    next_visiting = (*visiting, current)
    for nested in _iter_macro_references(
        chain,
        current_dir,
        library_dir=chain_dir,
        capability_catalog=capability_catalog,
    ):
        cycle = _find_macro_cycle(
            start_path=nested,
            root_path=root_path,
            root_id=root_id,
            chain_dir=chain_dir,
            capability_catalog=capability_catalog,
            visiting=next_visiting,
        )
        if cycle:
            return cycle
    return []


def _iter_macro_references(
    chain: CapabilityChain,
    chain_dir: Path,
    *,
    library_dir: Path | None = None,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
) -> list[Path]:
    refs: list[Path] = []
    for node in chain.nodes:
        if not node.enabled:
            continue
        capability = _resolve_macro_capability(
            node.capability_id,
            capability_catalog=capability_catalog
            if capability_catalog is not None
            else chain.capability_catalog,
            chain_dir=chain_dir,
            library_dir=library_dir,
        )
        params: Mapping[str, Any] = node.params
        if capability is not None:
            param_result = capability.validate_params(node.params)
            if param_result.valid:
                params = param_result.values
        path = _resolve_macro_path(node, capability, params, chain_dir)
        chain_id = str(
            params.get("chain_id")
            or (capability.defaults.get("chain_id") if capability is not None else "")
            or ""
        )
        if path is None and chain_id:
            path = _find_chain_file_by_id(chain_id, chain_dir)
        if path is None and chain_id and library_dir is not None:
            path = _find_chain_file_by_id(chain_id, library_dir)
        if path is not None:
            refs.append(path.resolve())
    return refs


def _resolve_macro_capability(
    capability_id: str,
    *,
    capability_catalog: Mapping[str, CapabilityNode] | None = None,
    chain_dir: Path | None = None,
    library_dir: Path | None = None,
) -> CapabilityNode | None:
    if capability_catalog is not None:
        capability = capability_catalog.get(capability_id)
        if capability is not None and _is_macro_capability(capability):
            return capability
        for candidate in capability_catalog.values():
            if (
                _is_macro_capability(candidate)
                and candidate.operation_name
                and candidate.operation_name == capability_id
            ):
                return candidate

    searched_dirs: set[Path] = set()
    for directory in (chain_dir, library_dir):
        if directory is None:
            continue
        resolved_dir = directory.resolve()
        if resolved_dir in searched_dirs:
            continue
        searched_dirs.add(resolved_dir)
        for candidate in list_macro_capabilities(directory):
            if candidate.id == capability_id or (
                candidate.operation_name and candidate.operation_name == capability_id
            ):
                return candidate
    return None


def _find_chain_file_by_id(chain_id: str, chain_dir: Path) -> Path | None:
    for path in iter_chain_files(chain_dir):
        try:
            chain = load_chain(path, chain_dir=chain_dir)
        except ChainFormatError:
            continue
        if chain.id == chain_id:
            return path
    return None


def _path_label(path: Path) -> str:
    return str(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if value is None or isinstance(value, str | int | bool):
        return value
    return repr(value)


__all__ = [
    "CapabilityChain",
    "ChainFormatError",
    "ChainExecutionPlan",
    "ChainExecutionStep",
    "ChainModel",
    "ChainNode",
    "ChainValidationError",
    "ChainValidationResult",
    "NATIVE_CHAIN_EXTENSIONS",
    "NATIVE_CHAIN_SCHEMA_VERSION",
    "is_native_chain_file",
    "iter_chain_files",
    "load_chain",
    "load_chain_file",
    "save_chain",
    "save_chain_file",
]
