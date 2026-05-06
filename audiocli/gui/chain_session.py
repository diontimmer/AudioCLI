"""GUI-neutral chain editing session state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from audiocli.capabilities import CapabilityNode
from audiocli.capabilities import get_capability as resolve_capability
from audiocli.chains import CapabilityChain, ChainNode


class ChainSession:
    """Mutable chain and selection state for a GUI workspace."""

    def __init__(
        self,
        capability_catalog: Mapping[str, CapabilityNode],
        *,
        chain: CapabilityChain | None = None,
        chain_name: str = "AudioCLI Workspace Chain",
    ) -> None:
        self._catalog = capability_catalog
        self._chain = CapabilityChain(name=chain_name, capability_catalog=self._catalog)
        self.selected_node_id: str | None = None
        if chain is not None:
            self.replace_chain(chain)

    @property
    def chain(self) -> CapabilityChain:
        return self._chain

    @chain.setter
    def chain(self, chain: CapabilityChain) -> None:
        self.replace_chain(chain)

    def replace_chain(
        self, chain: CapabilityChain, *, select_first: bool = True
    ) -> CapabilityChain:
        chain.capability_catalog = self._catalog
        self._chain = chain
        if select_first:
            self.selected_node_id = self._chain.nodes[0].id if self._chain.nodes else None
        else:
            self._sync_selection()
        return self._chain

    def get_capability(self, capability_id: str) -> CapabilityNode:
        capability = self._catalog.get(capability_id)
        if capability is not None:
            return capability
        try:
            capability = resolve_capability(capability_id)
        except KeyError as exc:
            raise ValueError(f"Unknown capability: {capability_id}") from exc
        if capability.id not in self._catalog:
            raise ValueError(f"Unknown capability: {capability_id}")
        return self._catalog[capability.id]

    def selected_node(self) -> ChainNode | None:
        if self.selected_node_id is None:
            return None
        try:
            return self._chain.get_node(self.selected_node_id)
        except (IndexError, ValueError, KeyError):
            self.selected_node_id = None
            return None

    def selected_capability(self) -> CapabilityNode | None:
        node = self.selected_node()
        if node is None:
            return None
        return self._catalog.get(node.capability_id)

    def select_node(self, node_id: str | None) -> ChainNode | None:
        if node_id is None:
            self.selected_node_id = None
            return None
        node = self._chain.get_node(node_id)
        self.selected_node_id = node.id
        return node

    def add_node(self, capability_id: str, *, index: int | None = None) -> ChainNode:
        capability = self.get_capability(capability_id)
        node = self._chain.add_node(capability.id, capability.defaults, index=index)
        self.selected_node_id = node.id
        return node

    def move_node(self, node_id: str, index: int) -> ChainNode:
        node = self._chain.move_node(node_id, index)
        self.selected_node_id = node.id
        return node

    def move_selected(self, delta: int) -> ChainNode | None:
        node = self.selected_node()
        if node is None:
            return None
        current_index = self._chain.nodes.index(node)
        new_index = max(0, min(len(self._chain.nodes) - 1, current_index + delta))
        if new_index == current_index:
            return node
        return self.move_node(node.id, new_index)

    def remove_node(self, node_id: str) -> ChainNode:
        current_index = self._chain.nodes.index(self._chain.get_node(node_id))
        node = self._chain.remove_node(node_id)
        if self.selected_node_id == node.id:
            if self._chain.nodes:
                self.selected_node_id = self._chain.nodes[
                    min(current_index, len(self._chain.nodes) - 1)
                ].id
            else:
                self.selected_node_id = None
        return node

    def remove_selected(self) -> ChainNode | None:
        node = self.selected_node()
        if node is None:
            return None
        return self.remove_node(node.id)

    def update_node_params(self, node_id: str, params: Mapping[str, Any]) -> ChainNode:
        node = self._chain.update_node_params(node_id, params)
        self.selected_node_id = node.id
        return node

    def update_selected_param(self, name: str, value: Any) -> ChainNode | None:
        node = self.selected_node()
        if node is None:
            return None
        params = dict(node.params)
        params[name] = value
        return self.update_node_params(node.id, params)

    def selected_node_view_model(self) -> dict[str, Any] | None:
        node = self.selected_node()
        if node is None:
            return None
        for node_view in self._chain.to_view_model()["nodes"]:
            if node_view["id"] == node.id:
                return node_view
        return None

    def _sync_selection(self) -> None:
        if self.selected_node_id is None:
            return
        if not any(node.id == self.selected_node_id for node in self._chain.nodes):
            self.selected_node_id = None
