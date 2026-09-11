"""
Debug 全局常量接口测试。

功能说明:
验证 debug 页面使用的配置快照由 AgentConfig dataclass 结构动态生成,并完整包含
每个配置组、字段说明、类型和值,避免前后端维护硬编码字段清单。
"""

from dataclasses import fields

from agent_service.api.rest.debug import _collect_agent_config_constants
from agent_service.core.agent_config import AgentConfig


def test_collect_agent_config_constants_covers_every_dataclass_field() -> None:
    """返回的配置组和常量必须与当前 AgentConfig dataclass 字段逐项一致。"""

    config = AgentConfig()

    payload = _collect_agent_config_constants(config)

    expected_groups = {field_info.name for field_info in fields(config)}
    actual_groups = {group["key"] for group in payload["configs"]}
    assert actual_groups == expected_groups

    expected_constant_count = 0
    for group in payload["configs"]:
        config_group = getattr(config, group["key"])
        expected_names = {field_info.name for field_info in fields(config_group)}
        actual_names = {constant["name"] for constant in group["constants"]}
        assert actual_names == expected_names
        assert all("description" in constant for constant in group["constants"])
        assert all("type" in constant for constant in group["constants"])
        assert all("value" in constant for constant in group["constants"])
        expected_constant_count += len(expected_names)

    assert payload["config_count"] == len(expected_groups)
    assert payload["constant_count"] == expected_constant_count


def test_collect_agent_config_constants_serializes_non_json_native_values() -> None:
    """Path、集合和嵌套容器等配置值必须转换为前端可直接消费的 JSON 值。"""

    payload = _collect_agent_config_constants(AgentConfig())
    storage = next(group for group in payload["configs"] if group["key"] == "storage")
    project_root = next(item for item in storage["constants"] if item["name"] == "project_root")

    assert project_root["type"] == "Path"
    assert isinstance(project_root["value"], str)


def test_collect_agent_config_constants_redacts_vlm_api_key() -> None:
    """Debug 配置快照不得泄露 MinerU 或其他服务级密钥。"""

    config = AgentConfig()
    config.vlm.api_key = "secret-token"
    payload = _collect_agent_config_constants(config)
    vlm = next(group for group in payload["configs"] if group["key"] == "vlm")
    api_key = next(item for item in vlm["constants"] if item["name"] == "api_key")

    assert api_key["value"] == "***"
