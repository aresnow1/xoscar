# Copyright 2022-2023 XProbe Inc.
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

from random import random

import pytest

from .. import api
from ..api import (
    Metrics,
    Percentile,
    _percentile_builder,
    init_metrics,
    record_time_cost_percentile,
    shutdown_metrics,
)


@pytest.fixture
def init():
    init_metrics()


def test_init_metrics():
    init_metrics()
    assert api._metric_backend == "console"
    shutdown_metrics()
    init_metrics("console")
    assert api._metric_backend == "console"
    shutdown_metrics()
    init_metrics(backend="console")
    assert api._metric_backend == "console"
    shutdown_metrics()
    init_metrics("prometheus")
    assert api._metric_backend == "prometheus"
    shutdown_metrics()
    init_metrics(backend="prometheus", config={"port": 0})
    assert api._metric_backend == "prometheus"
    shutdown_metrics()
    init_metrics("ray")
    assert api._metric_backend == "ray"
    shutdown_metrics()
    with pytest.raises(NotImplementedError):
        init_metrics("not_exist")


@pytest.mark.parametrize("init_firstly", [True, False])
def test_counter(init_firstly):
    if init_firstly:
        init_metrics()
    c = Metrics.counter("test_counter", "A test counter", ("service", "tenant"))
    assert c.name == "test_counter"
    assert c.description == "A test counter"
    assert c.tag_keys == ("service", "tenant")
    assert c.type == "Counter"
    if not init_firstly:
        init_metrics()
    c.record(1, {"service": "mars", "tenant": "test"})
    c.record(2, {"service": "mars", "tenant": "test"})
    assert c.value == 3


@pytest.mark.parametrize("init_firstly", [True, False])
def test_gauge(init_firstly):
    if init_firstly:
        init_metrics()
    g = Metrics.gauge("test_gauge", "A test gauge")
    assert g.name == "test_gauge"
    assert g.description == "A test gauge"
    assert g.tag_keys == ()
    assert g.type == "Gauge"
    if not init_firstly:
        init_metrics()
    g.record(1)
    assert g.value == 1
    g.record(2)
    assert g.value == 2


@pytest.mark.parametrize("init_firstly", [True, False])
def test_meter(init_firstly):
    if init_firstly:
        init_metrics()
    m = Metrics.meter("test_meter")
    assert m.name == "test_meter"
    assert m.description == ""
    assert m.tag_keys == ()
    assert m.type == "Meter"
    if not init_firstly:
        init_metrics()
    m.record(1)
    assert m.value == 0
    m.record(2001)
    assert m.value > 0


@pytest.mark.parametrize("init_firstly", [True, False])
def test_histogram(init_firstly):
    if init_firstly:
        init_metrics()
    h = Metrics.histogram("test_histogram")
    assert h.name == "test_histogram"
    assert h.description == ""
    assert h.tag_keys == ()
    assert h.type == "Histogram"
    if not init_firstly:
        init_metrics()
    h.record(1)
    assert h.value == 0
    for i in range(2002):
        h.record(1)
    assert h.value > 0


def test_percentile_report():
    def gen_callback(data):
        def callback(value):
            data.append(value)

        return callback

    data90 = []
    data95 = []
    data99 = []

    all_data = []
    percentile_args = [
        (Percentile.PercentileType.P90, gen_callback(data90), 100),
        (Percentile.PercentileType.P95, gen_callback(data95), 100),
        (Percentile.PercentileType.P99, gen_callback(data99), 100),
    ]
    percentile_list = [
        _percentile_builder[percentile_type](callback, window)
        for percentile_type, callback, window in percentile_args
    ]
    for _ in range(199):
        data = random()
        all_data.append(data)
        for percentile in percentile_list:
            percentile.record_data(data)
    sub_data = sorted(all_data[:100])
    print(sub_data[:10])
    assert len(data90) == 1 and sub_data[10 - 1] == data90[0]
    assert len(data95) == 1 and sub_data[5 - 1] == data95[0]
    assert len(data99) == 1 and sub_data[1 - 1] == data99[0]


def test_invaild_percentile_report():
    with pytest.raises(ValueError):
        Percentile(-1, 10, lambda x: ...)

    with pytest.raises(ValueError):
        Percentile(1, -1, lambda x: ...)

    with pytest.raises(ValueError):
        with record_time_cost_percentile([]):
            raise ValueError
