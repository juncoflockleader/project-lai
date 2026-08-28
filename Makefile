# project-lai —— 葫来
#
# 三个动词：validate（校验分镜）、render（渲一个镜头）、all（渲全部）。
# 分工：系统 python3 管校验和编译，Blender 只管搭场景和渲帧。

BLENDER ?= /Applications/Blender.app/Contents/MacOS/Blender
PY      ?= python3
SHOT    ?= shots/ep01/sh010.yaml

EP  := $(notdir $(patsubst %/,%,$(dir $(SHOT))))
ID  := $(basename $(notdir $(SHOT)))
OUT := out/$(EP)/$(ID)

.PHONY: help validate test compile render preview all clean deps

help:
	@echo "make validate                       校验全部分镜和画质规格（不需要 Blender）"
	@echo "make test                           跑运镜校验的回归测试"
	@echo "make render SHOT=shots/ep01/sh020.yaml   渲一个镜头，出帧序列 + mp4"
	@echo "make preview SHOT=...               只搭场景不渲染，存一个 .blend 出来看"
	@echo "make all                            渲 shots/ 下全部镜头"
	@echo "make clean                          删掉 out/"
	@echo ""
	@echo "BLENDER = $(BLENDER)"

deps:
	$(PY) -m pip install -r requirements.txt

validate:
	$(PY) -m pipeline.validate

test:
	$(PY) tests/test_camera_rules.py

compile:
	$(PY) -m pipeline.compile $(SHOT)

render: compile
	$(BLENDER) -b -P pipeline/render.py -- --plan out/$(EP)/$(ID).plan.json
	$(PY) -m pipeline.assemble $(OUT) $(OUT).mp4

preview: compile
	$(BLENDER) -b -P pipeline/render.py -- \
		--plan out/$(EP)/$(ID).plan.json --dry-run --save-blend $(OUT).blend

all: validate test
	@for shot in $$(find shots -name 'sh*.yaml' | sort); do \
		echo "==> $$shot"; \
		$(MAKE) --no-print-directory render SHOT=$$shot || exit 1; \
	done

clean:
	rm -rf out
