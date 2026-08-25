import logging
from state.schema import AgentState
from services.health_checker import (
    check_mongodb_health,
    check_mysql_health,
    check_service_health,
    check_all_health,
    sanitize_health_result,
)

logger = logging.getLogger(__name__)


async def health_agent(state: AgentState) -> dict:
    """
    Agen Independen untuk menjalankan pengujian kesehatan & keterhubungan database.
    Menerima target dari state ('mongodb', 'mysql', 'all', atau 'service:<name>').
    """
    health_target = state.get("health_target", "mongodb").lower().strip()
    logger.info(f"HealthAgent running connectivity check for target='{health_target}'")
    agents_visited = state.get("agents_visited", []) + ["health_agent"]

    try:
        if health_target == "mongodb":
            result = await check_mongodb_health()
        elif health_target == "mysql":
            result = await check_mysql_health()
        elif health_target == "all":
            result = await check_all_health()
        elif health_target.startswith("service:"):
            service_name = health_target.split("service:", 1)[1]
            result = await check_service_health(service_name, workspace_id=state.get("workspace_id"))
        else:
            # Check whether target is a known service name
            service_name = state.get("service_name") or health_target
            result = await check_service_health(service_name, workspace_id=state.get("workspace_id"))
    except Exception as e:
        logger.error(f"HealthAgent execution error: {e}", exc_info=True)
        result = {
            "status": "error",
            "error": str(e),
            "target": health_target,
        }

    logger.info(f"HealthAgent completed check for target='{health_target}'")

    return {
        "health_target": health_target,
        "health_result": sanitize_health_result(result),
        "next_agent": "telegram_agent",
        "agents_visited": agents_visited,
        "error": None,
    }
