import types

from nanochat.optim import DistMuonAdamW


def _bind(instance, function):
    return types.MethodType(function, instance)


def test_distributed_low_memory_step_finishes_each_group_before_next_reduce():
    optimizer = object.__new__(DistMuonAdamW)
    optimizer.param_groups = [
        {"kind": "adamw", "name": "embedding"},
        {"kind": "muon", "name": "matrix"},
    ]
    events = []

    def reduce_adamw(self, group, world_size):
        events.append(("reduce", group["name"], world_size))
        return {"name": group["name"]}

    def compute_adamw(self, group, info, gathers, rank, world_size):
        events.append(("compute", info["name"], rank, world_size))
        gathers.append({"name": info["name"]})

    def reduce_muon(self, group, world_size):
        events.append(("reduce", group["name"], world_size))
        return {"name": group["name"]}

    def compute_muon(self, group, info, gathers, rank):
        events.append(("compute", info["name"], rank))
        gathers.append({"name": info["name"]})

    def finish(self, gathers):
        events.append(("finish", gathers[0]["name"]))

    optimizer._reduce_adamw = _bind(optimizer, reduce_adamw)
    optimizer._compute_adamw = _bind(optimizer, compute_adamw)
    optimizer._reduce_muon = _bind(optimizer, reduce_muon)
    optimizer._compute_muon = _bind(optimizer, compute_muon)
    optimizer._finish_gathers = _bind(optimizer, finish)

    optimizer._step_low_memory(rank=1, world_size=2)

    assert events == [
        ("reduce", "embedding", 2),
        ("compute", "embedding", 1, 2),
        ("finish", "embedding"),
        ("reduce", "matrix", 2),
        ("compute", "matrix", 1),
        ("finish", "matrix"),
    ]
