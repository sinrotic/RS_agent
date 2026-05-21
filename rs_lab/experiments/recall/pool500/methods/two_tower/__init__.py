SOURCE_NAME = "two_tower"

__all__ = ["SOURCE_NAME", "build_two_tower_method_source"]


def build_two_tower_method_source(*args, **kwargs):
    from rs_lab.experiments.recall.pool500.methods.two_tower.builder import build_two_tower_method_source as _build_two_tower_method_source

    return _build_two_tower_method_source(*args, **kwargs)
