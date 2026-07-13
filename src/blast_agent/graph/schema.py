"""Neo4j schema declarations used by the graph writer."""

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT requirement_id IF NOT EXISTS FOR (n:Requirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT screen_id IF NOT EXISTS FOR (n:Screen) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ui_element_id IF NOT EXISTS FOR (n:UIElement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT interaction_id IF NOT EXISTS FOR (n:Interaction) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT user_flow_id IF NOT EXISTS FOR (n:UserFlow) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT code_file_path IF NOT EXISTS FOR (n:CodeFile) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT code_symbol_id IF NOT EXISTS FOR (n:CodeSymbol) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT pull_request_number IF NOT EXISTS FOR (n:PullRequest) REQUIRE n.number IS UNIQUE",
    "CREATE CONSTRAINT change_id IF NOT EXISTS FOR (n:Change) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT crawl_run_id IF NOT EXISTS FOR (n:CrawlRun) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT absence_observation_id IF NOT EXISTS FOR (n:AbsenceObservation) REQUIRE n.id IS UNIQUE",
]

__all__ = ["CONSTRAINTS"]
