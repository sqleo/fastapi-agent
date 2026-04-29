from __future__ import annotations

import pytest

from skills.loader import SkillLoadError, load_skill_spec_from_dir
from skills.registry import SkillRegistry
from skills.resolver import merge_skill_params


def _write_skill_yaml(
    root,
    *,
    tool_name: str = "milvus_search",
    skill_default_top_k: int = 5,
) -> None:
    (root / "SKILL.yaml").write_text(
        (
            "id: kb_retrieval\n"
            "name: 知识库检索\n"
            "version: 1.0.0\n"
            "assistant_scope: [\"report\"]\n"
            "enabled: true\n"
            "tooling:\n"
            f"  enabled_tools: [\"{tool_name}\"]\n"
            "  max_tool_calls: 3\n"
            "  timeout_sec: 20\n"
            "params_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    top_k:\n"
            "      type: integer\n"
            "      minimum: 1\n"
            "      maximum: 20\n"
            "      default: 3\n"
            "  required: [\"top_k\"]\n"
            "  additionalProperties: false\n"
            "params:\n"
            f"  top_k: {skill_default_top_k}\n"
        ),
        encoding="utf-8",
    )


def test_load_skill_success(tmp_path) -> None:
    skill_dir = tmp_path / "kb_retrieval"
    skill_dir.mkdir(parents=True, exist_ok=True)
    _write_skill_yaml(skill_dir)

    spec = load_skill_spec_from_dir(
        skill_dir,
        allowed_tools={"milvus_search", "web_search"},
    )
    assert spec.id == "kb_retrieval"
    assert spec.tooling.enabled_tools == ["milvus_search"]
    assert spec.params["top_k"] == 5


def test_load_skill_tool_not_allowed(tmp_path) -> None:
    skill_dir = tmp_path / "kb_retrieval"
    skill_dir.mkdir(parents=True, exist_ok=True)
    _write_skill_yaml(skill_dir, tool_name="run_shell")

    with pytest.raises(SkillLoadError) as exc:
        load_skill_spec_from_dir(
            skill_dir,
            allowed_tools={"milvus_search"},
        )
    assert exc.value.code == "SKILL_TOOL_NOT_ALLOWED"


def test_merge_priority_request_over_user_over_skill_over_schema_default() -> None:
    merged = merge_skill_params(
        schema={
            "type": "object",
            "properties": {
                "top_k": {"type": "integer", "default": 3},
                "score_threshold": {"type": "number", "default": 0.6},
            },
            "additionalProperties": False,
        },
        skill_default_params={"top_k": 5},
        user_params={"top_k": 7},
        request_params={"top_k": 9},
    )
    assert merged["top_k"] == 9
    assert merged["score_threshold"] == 0.6


def test_registry_resolve_uses_priority(tmp_path) -> None:
    root = tmp_path / "skills_root"
    skill_dir = root / "kb_retrieval"
    skill_dir.mkdir(parents=True, exist_ok=True)
    _write_skill_yaml(skill_dir, skill_default_top_k=5)

    registry = SkillRegistry(allowed_tools={"milvus_search"})
    registry.load_all_from_root(root)

    resolved = registry.resolve(
        "kb_retrieval",
        user_params={"top_k": 7},
        request_params={"top_k": 9},
    )
    assert resolved.skill_id == "kb_retrieval"
    assert resolved.resolved_params["top_k"] == 9
