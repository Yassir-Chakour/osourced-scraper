import logging
from graph.state import GraphState

logger = logging.getLogger(__name__)

def filter_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping filter node due to existing errors.")
        return state
        
    logger.info("Starting filter node (pass-through)...")
    
    # All duplicate filtering is now handled dynamically on the live web page
    return state
