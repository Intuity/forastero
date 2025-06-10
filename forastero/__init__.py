# Copyright 2023, Peter Birch, mailto:peter@lightlogic.co.uk
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .bench import BaseBench
from .driver import BaseDriver, DriverEvent
from .io import BaseIO, IORole, io_plain_style, io_prefix_style, io_suffix_style
from .monitor import BaseMonitor, MonitorEvent
from .scoreboard import DrainPolicy, Scoreboard
from .sequence import SeqContext, SeqLock, SeqProxy, randarg, requires, sequence
from .transaction import BaseTransaction

assert all(
    (
        BaseBench,
        BaseDriver,
        IORole,
        BaseIO,
        BaseMonitor,
        BaseTransaction,
        DrainPolicy,
        DriverEvent,
        MonitorEvent,
        Scoreboard,
        SeqContext,
        SeqLock,
        SeqProxy,
        io_prefix_style,
        io_plain_style,
        io_suffix_style,
        randarg,
        requires,
        sequence,
    )
)
