P4C := p4c-bm2-ss
PYTHON := $(shell command -v python3)
MN := $(shell command -v mn)
P4SRC := straggler.p4
BUILD := build
JSONS := $(BUILD)/s1.json $(BUILD)/s2.json $(BUILD)/s3.json $(BUILD)/s4.json

all: $(JSONS)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/s1.json: $(P4SRC) | $(BUILD)
	$(P4C) --arch v1model -D SWITCH_ID=1 -o $@ $<

$(BUILD)/s2.json: $(P4SRC) | $(BUILD)
	$(P4C) --arch v1model -D SWITCH_ID=2 -o $@ $<

$(BUILD)/s3.json: $(P4SRC) | $(BUILD)
	$(P4C) --arch v1model -D SWITCH_ID=3 -o $@ $<

$(BUILD)/s4.json: $(P4SRC) | $(BUILD)
	$(P4C) --arch v1model -D SWITCH_ID=4 -o $@ $<

run: $(JSONS)
	sudo $(PYTHON) ../../../tutorials/utils/run_exercise.py \
		-t topology.json

stop:
	sudo $(MN) -c

clean:
	sudo $(MN) -c
	rm -rf build
	sudo rm -rf logs pcaps

.PHONY: all run stop clean
