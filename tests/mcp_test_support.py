"""Temporary real MCP services and business dependencies for protocol/UI acceptance, with isolated SQLite storage."""
from pathlib import Path
from types import SimpleNamespace
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import create_database_engine_from_url
from tests.db_test_utils import initialize_test_database
from agent_service.services.settings.service import SettingsService
from agent_service.services.knowledge_library import KnowledgeLibraryService
from agent_service.services.knowledge_graph.service import KnowledgeGraphService
from agent_service.services.library.service import LibraryService
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.mcp_client.service import McpClientService
from agent_service.services.mcp_server.service import McpServerService
from agent_service.api.mcp.server import McpServerRuntime


def make_mcp_services(directory: Path):
    """Use actual Settings/Knowledge/Library/MCP services; omit unrelated model/Agent startup."""
    config = AgentConfig.load_config({"storage": {"base_data_dir": str(directory),
        "knowledge_dir": str(directory / "knowledge"), "sqlite_path": str(directory / "test.db")}},
        load_env=False, load_dotenv=False, ensure_directories=False, ensure_models=False)
    directory.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine_from_url(f"sqlite:///{directory / 'test.db'}")
    initialize_test_database(engine)
    memory = LongTermMemoryService(config=config, engine=engine, create_tables=False)
    settings = SettingsService(config=config, memory_service=memory)
    graph = KnowledgeGraphService(config=config, engine=engine, create_tables=False)
    knowledge = KnowledgeLibraryService(config=config, memory_service=memory, settings_service=settings, knowledge_graph_service=graph)
    library = LibraryService(config=config, settings_service=settings, knowledge_library_service=knowledge, knowledge_graph_service=graph)
    client = McpClientService(config=config, settings_service=settings, engine=engine)
    server = McpServerService(config=config, settings_service=settings, engine=engine)
    services = SimpleNamespace(config=config, database_engine=engine, settings_service=settings,
        knowledge_library_service=knowledge, library_service=library, memory_service=memory,
        mcp_client_service=client, mcp_server_service=server)
    server.services = services
    server.runtime = McpServerRuntime(server)
    return services
