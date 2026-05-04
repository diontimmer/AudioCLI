"""Pure-Python workspace service tests for the optional GUI shell."""

from __future__ import annotations

from audiocli.capabilities import CapabilityNode, CapabilityParameter, IOShape, SafetySemantics
from audiocli.gui.service import InMemoryWorkspaceService


def _fake_capability(capability_id: str, display_name: str) -> CapabilityNode:
    shape = IOShape("audio_buffer", "audio/*", "single")
    return CapabilityNode(
        id=capability_id,
        type="filter",
        display_name=display_name,
        description=f"Fake {display_name} capability.",
        input_shape=shape,
        output_shape=shape,
        safety=SafetySemantics("pure_transform"),
        operation_name=display_name.lower().replace(" ", "_"),
        defaults={"amount": 1.0, "enabled": True},
        parameters=[
            CapabilityParameter(
                name="amount",
                type="float",
                display_name="Amount",
                required=True,
                default=1.0,
                control_hint="number",
            ),
            CapabilityParameter(
                name="enabled",
                type="bool",
                display_name="Enabled",
                default=True,
                control_hint="toggle",
            ),
        ],
    )


def test_in_memory_workspace_service_edits_chain_through_model_boundary() -> None:
    gain = _fake_capability("fake.gain", "Gain")
    trim = _fake_capability("fake.trim", "Trim")
    service = InMemoryWorkspaceService([gain, trim])

    assert [capability.id for capability in service.capabilities()] == ["fake.gain", "fake.trim"]

    gain_node = service.add_node("fake.gain")
    trim_node = service.add_node("fake.trim")
    assert service.selected_node_id == trim_node.id
    assert [node.capability_id for node in service.chain.nodes] == ["fake.gain", "fake.trim"]

    service.update_selected_param("amount", 2.5)
    assert service.chain.get_node(trim_node.id).params["amount"] == 2.5

    service.move_selected(-1)
    assert [node.id for node in service.chain.nodes] == [trim_node.id, gain_node.id]

    service.select_node(gain_node.id)
    service.remove_selected()
    assert [node.id for node in service.chain.nodes] == [trim_node.id]
    assert service.selected_node_id == trim_node.id

    view_model = service.to_view_model()
    assert view_model["capabilities"][0]["id"] == "fake.gain"
    assert view_model["chain"]["nodes"][0]["capability_id"] == "fake.trim"


def test_in_memory_workspace_fake_run_reports_results_without_processing_files() -> None:
    service = InMemoryWorkspaceService([_fake_capability("fake.gain", "Gain")])
    service.add_node("fake.gain")
    service.set_targets(["input.wav"])
    service.set_output_path("out")

    results = service.run_fake_job()

    assert results == [
        {
            "status": "ok",
            "target": "input.wav",
            "output": "out",
            "steps": ["gain"],
        }
    ]
    assert service.job.logs[-1] == "Fake run completed for 1 target(s)."
