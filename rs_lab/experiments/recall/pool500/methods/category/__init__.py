from rs_lab.experiments.recall.pool500.common.lightweight_source_builder import build_lightweight_governance_source

SOURCE_NAME = "category"


def build_category_method_source(**kwargs):
    return build_lightweight_governance_source(source=SOURCE_NAME, **kwargs)


__all__ = ["SOURCE_NAME", "build_category_method_source"]
