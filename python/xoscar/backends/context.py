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

import asyncio
from dataclasses import dataclass
from typing import Tuple, Type, Union

from .._utils import create_actor_ref, to_binary
from ..api import Actor
from ..context import BaseActorContext
from ..core import ActorRef, create_local_actor_ref
from ..debug import debug_async_timeout, detect_cycle_send
from ..errors import CannotCancelTask
from ..utils import dataslots
from .allocate_strategy import AddressSpecified, AllocateStrategy
from .core import ActorCaller
from .message import (
    DEFAULT_PROTOCOL,
    ActorRefMessage,
    CancelMessage,
    ControlMessage,
    ControlMessageType,
    CreateActorMessage,
    DestroyActorMessage,
    ErrorMessage,
    HasActorMessage,
    ResultMessage,
    SendMessage,
    _MessageBase,
    new_message_id,
)
from .router import Router


@dataslots
@dataclass
class ProfilingContext:
    task_id: str


class MarsActorContext(BaseActorContext):
    __slots__ = ("_caller",)

    support_allocate_strategy = True

    def __init__(self, address: str | None = None):
        BaseActorContext.__init__(self, address)
        self._caller = ActorCaller()

    def __del__(self):
        self._caller.cancel_tasks()

    async def _call(
        self, address: str, message: _MessageBase, wait: bool = True
    ) -> Union[ResultMessage, ErrorMessage, asyncio.Future]:
        return await self._caller.call(
            Router.get_instance_or_empty(), address, message, wait=wait
        )

    @staticmethod
    def _process_result_message(message: Union[ResultMessage, ErrorMessage]):
        if isinstance(message, ResultMessage):
            return message.result
        else:
            raise message.as_instanceof_cause()

    async def _wait(self, future: asyncio.Future, address: str, message: _MessageBase):
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            try:
                await self.cancel(address, message.message_id)
            except CannotCancelTask:
                # cancel failed, already finished
                raise asyncio.CancelledError
        except:  # noqa: E722  # nosec  # pylint: disable=bare-except
            pass
        return await future

    async def create_actor(
        self,
        actor_cls: Type[Actor],
        *args,
        uid=None,
        address: str | None = None,
        **kwargs,
    ) -> ActorRef:
        router = Router.get_instance_or_empty()
        address = address or self._address or router.external_address
        allocate_strategy = kwargs.get("allocate_strategy", None)
        if isinstance(allocate_strategy, AllocateStrategy):
            allocate_strategy = kwargs.pop("allocate_strategy")
        else:
            allocate_strategy = AddressSpecified(address)
        create_actor_message = CreateActorMessage(
            new_message_id(),
            actor_cls,
            to_binary(uid),
            args,
            kwargs,
            allocate_strategy,
            protocol=DEFAULT_PROTOCOL,
        )
        future = await self._call(address, create_actor_message, wait=False)
        result = await self._wait(future, address, create_actor_message)  # type: ignore
        return self._process_result_message(result)

    async def has_actor(self, actor_ref: ActorRef) -> bool:
        message = HasActorMessage(
            new_message_id(), actor_ref, protocol=DEFAULT_PROTOCOL
        )
        future = await self._call(actor_ref.address, message, wait=False)
        result = await self._wait(future, actor_ref.address, message)  # type: ignore
        return self._process_result_message(result)

    async def destroy_actor(self, actor_ref: ActorRef):
        message = DestroyActorMessage(
            new_message_id(), actor_ref, protocol=DEFAULT_PROTOCOL
        )
        future = await self._call(actor_ref.address, message, wait=False)
        result = await self._wait(future, actor_ref.address, message)  # type: ignore
        return self._process_result_message(result)

    async def kill_actor(self, actor_ref: ActorRef, force: bool = True):
        # get main_pool_address
        control_message = ControlMessage(
            new_message_id(),
            actor_ref.address,
            ControlMessageType.get_config,
            "main_pool_address",
            protocol=DEFAULT_PROTOCOL,
        )
        main_address = self._process_result_message(
            await self._call(actor_ref.address, control_message)  # type: ignore
        )
        real_actor_ref = await self.actor_ref(actor_ref)
        if real_actor_ref.address == main_address:
            raise ValueError("Cannot kill actor on main pool")
        stop_message = ControlMessage(
            new_message_id(),
            real_actor_ref.address,
            ControlMessageType.stop,
            # default timeout (3 secs) and force
            (3.0, force),
            protocol=DEFAULT_PROTOCOL,
        )
        # stop server
        result = await self._call(main_address, stop_message)
        return self._process_result_message(result)  # type: ignore

    async def actor_ref(self, *args, **kwargs):
        actor_ref = create_actor_ref(*args, **kwargs)
        local_actor_ref = create_local_actor_ref(actor_ref.address, actor_ref.uid)
        if local_actor_ref is not None:
            return local_actor_ref
        message = ActorRefMessage(
            new_message_id(), actor_ref, protocol=DEFAULT_PROTOCOL
        )
        future = await self._call(actor_ref.address, message, wait=False)
        result = await self._wait(future, actor_ref.address, message)
        return self._process_result_message(result)

    async def send(
        self,
        actor_ref: ActorRef,
        message: Tuple,
        wait_response: bool = True,
        profiling_context: ProfilingContext | None = None,
    ):
        send_message = SendMessage(
            new_message_id(),
            actor_ref,
            message,
            protocol=DEFAULT_PROTOCOL,
            profiling_context=profiling_context,
        )

        # use `%.500` to avoid print too long messages
        with debug_async_timeout(
            "actor_call_timeout",
            "Calling %.500r on %s at %s timed out",
            send_message.content,
            actor_ref.uid,
            actor_ref.address,
        ):
            detect_cycle_send(send_message, wait_response)
            future = await self._call(actor_ref.address, send_message, wait=False)
            if wait_response:
                result = await self._wait(future, actor_ref.address, send_message)  # type: ignore
                return self._process_result_message(result)
            else:
                return future

    async def cancel(self, address: str, cancel_message_id: bytes):
        message = CancelMessage(
            new_message_id(), address, cancel_message_id, protocol=DEFAULT_PROTOCOL
        )
        result = await self._call(address, message)
        return self._process_result_message(result)  # type: ignore

    async def wait_actor_pool_recovered(
        self, address: str, main_address: str | None = None
    ):
        if main_address is None:
            # get main_pool_address
            control_message = ControlMessage(
                new_message_id(),
                address,
                ControlMessageType.get_config,
                "main_pool_address",
                protocol=DEFAULT_PROTOCOL,
            )
            main_address = self._process_result_message(
                await self._call(address, control_message)  # type: ignore
            )

        # if address is main pool, it is never recovered
        if address == main_address:
            return

        control_message = ControlMessage(
            new_message_id(),
            address,
            ControlMessageType.wait_pool_recovered,
            None,
            protocol=DEFAULT_PROTOCOL,
        )
        self._process_result_message(await self._call(main_address, control_message))  # type: ignore

    async def get_pool_config(self, address: str):
        control_message = ControlMessage(
            new_message_id(),
            address,
            ControlMessageType.get_config,
            None,
            protocol=DEFAULT_PROTOCOL,
        )
        return self._process_result_message(await self._call(address, control_message))  # type: ignore
