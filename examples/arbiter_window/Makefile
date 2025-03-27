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

# Get this directory
THIS_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# Utilities
SPACE := $(SPACE) $(SPACE)

# Simulator options
SIM           ?= icarus
TOPLEVEL_LANG ?= verilog
DEFINES       += sim_$(SIM)
PLUSARGS      += +WAVE_FILE=dump.vcd
COMPILE_ARGS  += $(addprefix -D ,$(DEFINES))

# Design sources
VERILOG_SOURCES += $(abspath ../common/rtl/arbiter.sv)

# Design top-level and testbench module
TOPLEVEL = arbiter
MODULE   = testbench

# Setup the Python path
ACCUM_PY_PATH += $(PYTHONPATH)
ACCUM_PY_PATH += $(THIS_DIR)
ACCUM_PY_PATH += $(abspath $(THIS_DIR)/..)
ACCUM_PY_PATH += $(abspath $(THIS_DIR)/../..)
export PYTHONPATH := $(subst $(SPACE),:,$(ACCUM_PY_PATH))

# Parameters file
export TEST_PARAMS ?= $(THIS_DIR)/params.json

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
