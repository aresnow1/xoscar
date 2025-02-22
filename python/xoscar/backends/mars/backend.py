# Copyright 2022-2023 XProbe Inc.
# derived from copyright 1999-2021 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from typing import Dict

from ...backend import BaseActorBackend, register_backend
from ..context import MarsActorContext
from .driver import MarsActorDriver
from .pool import MainActorPool

__all__ = ["MarsActorBackend"]


def build_pool_kwargs(n_process: int, kwargs: Dict):
    n_io_process = kwargs.pop("n_io_process", 0)
    if n_io_process:
        n_process += n_io_process

        labels = kwargs["labels"]
        envs = kwargs["envs"]
        external_address_schemes = kwargs["external_address_schemes"]
        enable_internal_addresses = kwargs["enable_internal_addresses"]
        # sub-pools for IO(transfer and spill)
        for _ in range(n_io_process):
            if envs:  # pragma: no cover
                envs.append(dict())
            labels.append("io")
            if external_address_schemes:
                # just use main process' scheme for IO process
                external_address_schemes.append(external_address_schemes[0])
            if enable_internal_addresses:
                # just use main process' setting for IO process
                enable_internal_addresses.append(enable_internal_addresses[0])

    return n_process, kwargs


@register_backend
class MarsActorBackend(BaseActorBackend):
    @staticmethod
    def name():
        # None means Mars is default scheme
        # ucx can be recognized as Mars backend as well
        return [None, "ucx"]

    @staticmethod
    def get_context_cls():
        return MarsActorContext

    @staticmethod
    def get_driver_cls():
        return MarsActorDriver

    @classmethod
    async def create_actor_pool(
        cls, address: str, n_process: int | None = None, **kwargs
    ):
        from ..pool import create_actor_pool

        assert n_process is not None
        n_process, kwargs = build_pool_kwargs(n_process, kwargs)
        return await create_actor_pool(
            address, pool_cls=MainActorPool, n_process=n_process, **kwargs
        )
