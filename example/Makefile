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

# Simulator options
SIM           ?= icarus
TOPLEVEL_LANG ?= verilog
DEFINES       += sim_$(SIM)
PLUSARGS      += +WAVE_FILE=dump.vcd
COMPILE_ARGS  += $(addprefix -D ,$(DEFINES))

# Design sources
VERILOG_SOURCES += $(abspath arbiter.sv)

# Design top-level
TOPLEVEL = arbiter

# Testbench module
export PYTHONPATH := $(PYTHONPATH):$(abspath ..)
MODULE = testbench

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
