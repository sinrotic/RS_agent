__all__ = [
    "FeedbackSessionFacade",
    "RecallFacade",
    "RecommendationFacade",
    "RecommendationService",
    "SessionNotFoundError",
]


def __getattr__(name: str):
    if name in {"FeedbackSessionFacade", "RecallFacade", "RecommendationFacade"}:
        from rs_core.serving import facades

        return getattr(facades, name)
    if name in {"RecommendationService", "SessionNotFoundError"}:
        from rs_core.serving.application import recommendation_service

        return getattr(recommendation_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
